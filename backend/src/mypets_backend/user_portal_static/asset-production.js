"use strict";

const assetProductionState = {
  jobs: [],
  selectedJob: null,
  loaded: false,
  loading: false,
  error: "",
};

const assetProductionUI = window.MyPetsPortalUI;
if (!assetProductionUI) throw new Error("MyPets 门户 UI 组件未加载");

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
  ensureAssetSubmissionWorkspace();
  const section = $("asset-submissions-section");
  if (!section || $("asset-production-list")) return;

  const panel = node("article", "", "panel");
  const heading = node("div", "", "section-heading");
  const titleWrap = node("div");
  titleWrap.append(
    node("p", "PRODUCTION", "eyebrow"),
    node("h2", "素材制作进度"),
  );
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
        <button id="submit-asset-production-reference" value="default">上传参考图</button>
      </div>
    </form>`;
  document.body.append(dialog);
}

function installAssetProductionActions() {
  ensureAssetProductionWorkspace();
  const refresh = $("refresh-asset-production");
  if (refresh && refresh.dataset.assetProductionBound !== "1") {
    refresh.dataset.assetProductionBound = "1";
    refresh.addEventListener("click", () => {
      assetProductionUI.runAction({
        control: refresh,
        statusNode: globalStatus,
        busyLabel: "正在刷新…",
        successMessage: "素材制作工单已刷新。",
        task: () => refreshAssetProductionJobs({ showLoading: true }),
      });
    });
  }
  const cancel = $("cancel-asset-production-reference");
  if (cancel && cancel.dataset.assetProductionBound !== "1") {
    cancel.dataset.assetProductionBound = "1";
    cancel.addEventListener("click", (event) => {
      event.preventDefault();
      $("asset-production-reference-dialog")?.close();
    });
  }
  const form = $("asset-production-reference-form");
  if (form && form.dataset.assetProductionBound !== "1") {
    form.dataset.assetProductionBound = "1";
    form.addEventListener("submit", submitProductionReferenceImage);
  }
}

function assetProductionRetryAction() {
  return {
    label: "重新读取",
    busyLabel: "正在读取…",
    onClick: () => refreshAssetProductionJobs({ showLoading: true }),
  };
}

function renderAssetProductionJobs() {
  ensureAssetProductionWorkspace();
  const container = $("asset-production-list");
  if (!container) return;
  assetProductionUI.setRegionBusy(container, assetProductionState.loading);

  if (assetProductionState.loading && !assetProductionState.loaded) {
    assetProductionUI.renderState(container, {
      kind: "loading",
      title: "正在读取素材制作工单",
      detail: "正在加载制作进度、补充资料和产物校验状态。",
    });
    return;
  }
  if (assetProductionState.error && !assetProductionState.loaded) {
    assetProductionUI.renderState(container, {
      kind: "error",
      title: "素材制作工单读取失败",
      detail: assetProductionState.error,
      action: assetProductionRetryAction(),
    });
    return;
  }
  if (!assetProductionState.loaded) {
    assetProductionUI.renderState(container, {
      kind: "idle",
      title: "素材制作工单尚未读取",
      detail: "进入专属形象页面后读取人工制作进度。",
    });
    return;
  }

  container.replaceChildren();
  assetProductionUI.clearState(container);
  if (!assetProductionState.jobs.length) {
    assetProductionUI.renderState(container, {
      kind: "empty",
      title: "当前没有素材制作工单",
      detail: "原图审核通过后，服务端会自动建立人工素材制作工单。",
    });
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
      built.actions.append(
        actionButton(
          "补充参考图",
          () => openProductionReferenceDialog(job),
          "secondary",
        ),
      );
    }
    if (job.can_cancel) {
      built.actions.append(
        actionButton(
          "撤回工单",
          async () => {
            if (!window.confirm(`确认撤回 ${job.pet_name} 的尚未开始工单？`)) return;
            await api(
              `/api/v1/pet-asset-production-jobs/${encodeURIComponent(job.job_id)}/cancel`,
              {
                method: "POST",
                json: { note: "用户在制作开始前通过 Web 门户撤回工单。" },
              },
            );
            await refreshAssetProductionJobs({ showLoading: false });
            setStatus(globalStatus, "工单已撤回。", "success");
          },
          "danger",
        ),
      );
    }

    if (job.references.length) {
      const references = node("div", "", "item-meta");
      references.append(node("strong", `已补充 ${job.references.length} 张参考图`));
      job.references.forEach((reference, index) => {
        references.append(
          actionButton(
            `下载参考图 ${index + 1}`,
            () => downloadProductionReference(reference),
            "secondary",
          ),
        );
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

  if (assetProductionState.error) {
    assetProductionUI.renderInlineNotice(container, {
      kind: "error",
      title: "最新工单状态暂未更新",
      detail: `${assetProductionState.error} 当前仍显示上次成功读取的工单。`,
      action: assetProductionRetryAction(),
    });
  }
}

async function refreshAssetProductionJobs(options = {}) {
  ensureAssetProductionWorkspace();
  if (!accessToken) {
    resetAssetProductionState();
    return [];
  }
  const showLoading = options.showLoading ?? !assetProductionState.loaded;
  assetProductionState.loading = true;
  assetProductionState.error = "";
  if (showLoading || !assetProductionState.loaded) renderAssetProductionJobs();
  else assetProductionUI.setRegionBusy($("asset-production-list"), true);

  try {
    const payload = await api("/api/v1/pet-asset-production-jobs?limit=200");
    assetProductionState.jobs = Array.isArray(payload) ? payload : [];
    assetProductionState.loaded = true;
    return assetProductionState.jobs;
  } catch (error) {
    assetProductionState.error = error.message || "素材制作工单读取失败";
    throw error;
  } finally {
    assetProductionState.loading = false;
    renderAssetProductionJobs();
  }
}

function openProductionReferenceDialog(job) {
  assetProductionState.selectedJob = job;
  $("asset-production-reference-pet").textContent =
    `${job.pet_name} · ${productionStatusLabel(job.status)}`;
  $("asset-production-reference-note").value = "";
  $("asset-production-reference-file").value = "";
  $("asset-production-reference-dialog").showModal();
}

async function submitProductionReferenceImage(event) {
  event.preventDefault();
  const job = assetProductionState.selectedJob;
  const file = $("asset-production-reference-file")?.files?.[0];
  if (!job || !file) {
    setStatus(globalStatus, "请选择需要补充的参考图。", "error");
    return;
  }
  const submit = $("submit-asset-production-reference");
  assetProductionUI.runAction({
    control: submit,
    statusNode: globalStatus,
    busyLabel: "正在上传…",
    task: async () => {
      const data = new FormData();
      data.append("note", $("asset-production-reference-note").value.trim());
      data.append("image", file);
      const key = typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
      await api(
        `/api/v1/pet-asset-production-jobs/${encodeURIComponent(job.job_id)}/reference-images`,
        {
          method: "POST",
          headers: { "Idempotency-Key": `portal-production-reference-${key}` },
          body: data,
        },
      );
      $("asset-production-reference-dialog").close();
      assetProductionState.selectedJob = null;
      await refreshAssetProductionJobs({ showLoading: false });
      setStatus(globalStatus, "补充参考图已安全清理并提交。", "success");
    },
  });
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

function resetAssetProductionState() {
  assetProductionState.jobs = [];
  assetProductionState.selectedJob = null;
  assetProductionState.loaded = false;
  assetProductionState.loading = false;
  assetProductionState.error = "";
  renderAssetProductionJobs();
  const dialog = $("asset-production-reference-dialog");
  if (dialog?.open) dialog.close();
}

portalRuntime.registerFeature({
  id: "asset-production",
  label: "素材制作进度",
  order: 340,
  mount: () => {
    ensureAssetProductionWorkspace();
    installAssetProductionActions();
    renderAssetProductionJobs();
  },
  onSectionEnter: async ({ sectionId, source }) => {
    if (
      sectionId === "asset-submissions-section"
      && accessToken
      && source !== "anonymous"
    ) {
      await refreshAssetProductionJobs({
        showLoading: !assetProductionState.loaded,
      });
    }
  },
  onRealtime: async () => {
    const section = $("asset-submissions-section");
    if (!accessToken || !section || section.hidden || !assetProductionState.loaded) return;
    await refreshAssetProductionJobs({ showLoading: false });
  },
  onLogout: resetAssetProductionState,
});
