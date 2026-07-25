"use strict";

const assetProductionState = { jobs: [], selectedJob: null };

function productionStatusLabel(value) {
  return {
    queued: "等待制作",
    processing: "制作中",
    needs_input: "等待补充资料",
    ready: "产物已校验，等待发布审核",
    failed: "制作失败，可重试",
    cancelled: "已撤回",
  }[value] || value;
}

function ensureAssetProductionWorkspace() {
  const section = $("asset-submissions-section");
  if (!section || $("asset-production-list")) return;

  const panel = node("article", "", "panel");
  const heading = node("div", "", "section-heading");
  const titleWrap = node("div");
  titleWrap.append(node("p", "PRODUCTION", "eyebrow"), node("h2", "素材制作进度"));
  const refresh = node("button", "刷新工单", "secondary");
  refresh.id = "refresh-asset-production";
  refresh.type = "button";
  heading.append(titleWrap, refresh);
  const hint = node(
    "p",
    "工单产物通过 13 种动作与安全校验后只进入待发布状态，不会自动替换宠物形象。",
    "hint",
  );
  const list = node("div", "", "card-list");
  list.id = "asset-production-list";
  panel.append(heading, hint, list);
  section.append(panel);

  const dialog = document.createElement("dialog");
  dialog.id = "asset-production-reference-dialog";
  dialog.innerHTML = `
    <form id="asset-production-reference-form" method="dialog">
      <h3>补充宠物参考图</h3>
      <p id="asset-production-reference-pet" class="hint"></p>
      <label>补充说明<textarea id="asset-production-reference-note" rows="3" maxlength="240" placeholder="例如：补充左侧花纹和尾巴颜色"></textarea></label>
      <label>参考图<input id="asset-production-reference-file" type="file" accept="image/jpeg,image/png,image/webp" required></label>
      <div class="dialog-actions">
        <button id="cancel-asset-production-reference" value="cancel" class="secondary">取消</button>
        <button value="default">上传参考图</button>
      </div>
    </form>`;
  document.body.append(dialog);

  refresh.addEventListener("click", async () => {
    try {
      await refreshAssetProductionJobs();
      setStatus(globalStatus, "素材制作工单已刷新。", "success");
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    }
  });
  $("cancel-asset-production-reference").addEventListener("click", (event) => {
    event.preventDefault();
    dialog.close();
  });
  $("asset-production-reference-form").addEventListener("submit", submitProductionReferenceImage);
}

async function refreshAssetProductionJobs() {
  assetProductionState.jobs = await api("/api/v1/pet-asset-production-jobs?limit=200");
  renderAssetProductionJobs();
}

function renderAssetProductionJobs() {
  const container = $("asset-production-list");
  if (!container) return;
  container.replaceChildren();
  if (!assetProductionState.jobs.length) {
    empty(container, "审核通过后会自动建立人工素材制作工单。");
    return;
  }

  assetProductionState.jobs.forEach((job) => {
    const meta = [
      `${productionStatusLabel(job.status)} · 进度 ${job.progress}%`,
      job.assignee_display_name
        ? `负责人：${job.assignee_display_name}（@${job.assignee_username}）`
        : "尚未分配负责人",
      job.status_note || "暂无进度说明",
      `更新时间：${new Date(job.updated_at).toLocaleString()}`,
    ];
    if (job.artifact) {
      meta.push(
        `目标版本：${job.artifact.identity_version} / ${job.artifact.asset_version}`,
        `产物 SHA-256：${job.artifact.package_sha256}`,
      );
    }
    const built = itemCard(job.pet_name, meta);
    const progress = document.createElement("progress");
    progress.max = 100;
    progress.value = job.progress;
    progress.setAttribute("aria-label", `${job.pet_name} 制作进度`);
    built.card.insertBefore(progress, built.actions);

    if (job.can_add_reference) {
      built.actions.append(actionButton("补充参考图", () => openProductionReferenceDialog(job), "secondary"));
    }
    if (job.can_cancel) {
      built.actions.append(actionButton("撤回工单", async () => {
        if (!window.confirm(`确认撤回 ${job.pet_name} 的尚未开始工单？`)) return;
        await api(`/api/v1/pet-asset-production-jobs/${encodeURIComponent(job.job_id)}/cancel`, {
          method: "POST",
          json: { note: "用户在制作开始前通过 Web 门户撤回工单。" },
        });
        await refreshAssetProductionJobs();
        setStatus(globalStatus, "工单已撤回。", "success");
      }, "danger"));
    }

    if (job.references.length) {
      const references = node("div", "", "item-meta");
      references.append(node("strong", `已补充 ${job.references.length} 张参考图`));
      job.references.forEach((reference, index) => {
        references.append(actionButton(`下载参考图 ${index + 1}`, () => downloadProductionReference(reference), "secondary"));
      });
      built.card.insertBefore(references, built.actions);
    }

    if (job.logs.length) {
      const history = node("div", "", "item-meta");
      history.append(node("strong", "最近进度"));
      job.logs.slice(-5).reverse().forEach((entry) => {
        const text = `${new Date(entry.created_at).toLocaleString()} · ${productionStatusLabel(entry.to_status)} · ${entry.progress}%${entry.message ? ` · ${entry.message}` : ""}`;
        history.append(node("div", text));
      });
      built.card.insertBefore(history, built.actions);
    }
    container.append(built.card);
  });
}

function openProductionReferenceDialog(job) {
  assetProductionState.selectedJob = job;
  $("asset-production-reference-pet").textContent = `${job.pet_name} · ${productionStatusLabel(job.status)}`;
  $("asset-production-reference-note").value = "";
  $("asset-production-reference-file").value = "";
  $("asset-production-reference-dialog").showModal();
}

async function submitProductionReferenceImage(event) {
  event.preventDefault();
  const job = assetProductionState.selectedJob;
  const file = $("asset-production-reference-file").files[0];
  if (!job || !file) return;
  const data = new FormData();
  data.append("note", $("asset-production-reference-note").value.trim());
  data.append("image", file);
  const key = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
  try {
    await api(`/api/v1/pet-asset-production-jobs/${encodeURIComponent(job.job_id)}/reference-images`, {
      method: "POST",
      headers: { "Idempotency-Key": `portal-production-reference-${key}` },
      body: data,
    });
    $("asset-production-reference-dialog").close();
    await refreshAssetProductionJobs();
    setStatus(globalStatus, "补充参考图已安全清理并提交。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
}

async function downloadProductionReference(reference) {
  const response = await fetch(reference.image_url, {
    headers: { Authorization: `Bearer ${accessToken}`, Accept: reference.image_media_type },
  });
  if (!response.ok) {
    let message = `下载失败（${response.status}）`;
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = reference.image_media_type === "image/png"
    ? `pet-production-reference-${reference.reference_id}.png`
    : `pet-production-reference-${reference.reference_id}.jpg`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

ensureAssetProductionWorkspace();

const refreshAssetSubmissionWorkspaceWithoutProduction = refreshAssetSubmissionWorkspace;
refreshAssetSubmissionWorkspace = async function refreshSubmissionAndProduction() {
  await refreshAssetSubmissionWorkspaceWithoutProduction();
  await refreshAssetProductionJobs();
};
