"use strict";

let productionReferencePreviewUrl = "";
let selectedProductionJob = null;

function productionAdminStatusLabel(value) {
  return {
    queued: "等待制作",
    processing: "制作中",
    needs_input: "等待补充资料",
    ready: "产物已校验",
    failed: "制作失败",
    cancelled: "已取消",
  }[value] || value;
}

function ensureAdminProductionWorkspace() {
  if (document.querySelector('[data-view="assetProduction"]')) return;
  titles.assetProduction = "素材制作";
  state.productionJobs = [];

  const navigation = $("#navigation");
  const button = document.createElement("button");
  button.dataset.view = "assetProduction";
  button.textContent = "素材制作";
  const releasesButton = navigation.querySelector('[data-view="releases"]');
  navigation.insertBefore(button, releasesButton || null);

  const view = document.createElement("section");
  view.id = "assetProductionView";
  view.className = "view-panel hidden";
  view.innerHTML = `
    <article class="panel">
      <div class="panel-heading">
        <div><p class="eyebrow">CONTROLLED PRODUCTION</p><h3>专属宠物素材制作工单</h3></div>
        <div class="button-row">
          <select id="productionStatusFilter" aria-label="制作状态">
            <option value="">全部状态</option>
            <option value="queued">等待制作</option>
            <option value="processing">制作中</option>
            <option value="needs_input">等待补充资料</option>
            <option value="ready">产物已校验</option>
            <option value="failed">制作失败</option>
            <option value="cancelled">已取消</option>
          </select>
          <button id="refreshProductionJobs" class="secondary compact">刷新</button>
        </div>
      </div>
      <p class="muted">产物上传只做声明式 ZIP 安全与 13 种动作校验。ready 工单仍需后续发布审核，不能直接改变宠物形象。</p>
      <div id="productionJobList" class="review-list"></div>
    </article>`;
  $(".main-content").append(view);

  const updateDialog = document.createElement("dialog");
  updateDialog.id = "productionUpdateDialog";
  updateDialog.innerHTML = `
    <form id="productionUpdateForm" method="dialog">
      <h3 id="productionUpdateTitle">更新制作工单</h3>
      <input id="productionUpdateJobId" type="hidden">
      <input id="productionUpdateStatus" type="hidden">
      <label>进度（0-99）<input id="productionUpdateProgress" type="number" min="0" max="99"></label>
      <label>说明<textarea id="productionUpdateNote" rows="4" maxlength="1000"></textarea></label>
      <div class="dialog-actions">
        <button id="cancelProductionUpdate" value="cancel" class="ghost">取消</button>
        <button value="default" class="primary">确认</button>
      </div>
    </form>`;
  document.body.append(updateDialog);

  const artifactDialog = document.createElement("dialog");
  artifactDialog.id = "productionArtifactDialog";
  artifactDialog.innerHTML = `
    <form id="productionArtifactForm" method="dialog">
      <h3>上传制作产物</h3>
      <input id="productionArtifactJobId" type="hidden">
      <label>目标模板版本<select id="productionArtifactVersion" required></select></label>
      <label>素材 ZIP<input id="productionArtifactFile" type="file" accept=".zip,application/zip" required></label>
      <p class="muted">上传成功后产物不可静默替换，工单进入 ready，但不会自动发布。</p>
      <div class="dialog-actions">
        <button id="cancelProductionArtifact" value="cancel" class="ghost">取消</button>
        <button value="default" class="primary">上传并校验</button>
      </div>
    </form>`;
  document.body.append(artifactDialog);

  const previewDialog = document.createElement("dialog");
  previewDialog.id = "productionReferencePreviewDialog";
  previewDialog.innerHTML = `
    <form method="dialog">
      <h3>用户补充参考图</h3>
      <div class="visual-acceptance"><div class="device-simulator preset-compact"><div class="desktop-canvas"><img id="productionReferencePreview" alt="用户补充参考图"></div></div></div>
      <p id="productionReferenceNote" class="muted"></p>
      <div class="dialog-actions"><button value="default" class="primary">关闭</button></div>
    </form>`;
  document.body.append(previewDialog);

  $("#refreshProductionJobs").addEventListener("click", loadProductionJobs);
  $("#productionStatusFilter").addEventListener("change", loadProductionJobs);
  $("#cancelProductionUpdate").addEventListener("click", (event) => {
    event.preventDefault();
    updateDialog.close();
  });
  $("#cancelProductionArtifact").addEventListener("click", (event) => {
    event.preventDefault();
    artifactDialog.close();
  });
  $("#productionUpdateForm").addEventListener("submit", submitProductionUpdate);
  $("#productionArtifactForm").addEventListener("submit", submitProductionArtifact);
  previewDialog.addEventListener("close", clearProductionReferencePreview);

  const previousShowView = showView;
  showView = async function showViewWithProduction(name) {
    if (name !== "assetProduction") return previousShowView(name);
    $$(".view-panel").forEach((panel) => panel.classList.add("hidden"));
    $("#assetProductionView").classList.remove("hidden");
    $$("#navigation button").forEach((entry) => entry.classList.toggle("active", entry.dataset.view === name));
    $("#viewTitle").textContent = titles[name];
    setStatus("正在加载…");
    try {
      await loadProductionJobs();
      setStatus("");
    } catch (error) {
      setStatus(errorMessage(error), true);
    }
  };
}

async function loadProductionJobs() {
  const status = $("#productionStatusFilter").value;
  const query = status ? `?status=${encodeURIComponent(status)}&limit=500` : "?limit=500";
  state.productionJobs = await api(`/api/v1/admin/pet-asset-production-jobs${query}`);
  renderProductionJobs();
}

function productionActionButton(label, action, jobId, kind = "secondary") {
  return `<button class="${kind} compact" data-production-action="${escapeHtml(action)}" data-production-job="${escapeHtml(jobId)}">${escapeHtml(label)}</button>`;
}

function renderProductionJobs() {
  const container = $("#productionJobList");
  if (!state.productionJobs.length) {
    container.innerHTML = '<div class="empty-row">当前没有匹配的制作工单</div>';
    return;
  }
  container.innerHTML = state.productionJobs.map((job) => {
    const actions = [];
    if (can("edit") && !["ready", "cancelled"].includes(job.status)) {
      actions.push(productionActionButton("分配给我", "assign", job.job_id, "primary"));
    }
    if (can("edit") && job.status === "queued") {
      actions.push(productionActionButton("开始制作", "processing", job.job_id, "primary"));
    }
    if (can("edit") && job.status === "processing") {
      actions.push(productionActionButton("更新进度", "progress", job.job_id));
      actions.push(productionActionButton("需要补图", "needs_input", job.job_id));
      actions.push(productionActionButton("标记失败", "failed", job.job_id));
      actions.push(productionActionButton("上传产物", "artifact", job.job_id, "primary"));
    }
    if (can("edit") && job.status === "needs_input") {
      actions.push(productionActionButton("继续制作", "processing", job.job_id, "primary"));
      actions.push(productionActionButton("标记失败", "failed", job.job_id));
      actions.push(productionActionButton("上传产物", "artifact", job.job_id, "primary"));
    }
    if (can("edit") && job.status === "failed") {
      actions.push(productionActionButton("重新排队", "queued", job.job_id, "primary"));
    }
    if (job.artifact?.package_url) {
      actions.push(productionActionButton("受控下载产物", "download", job.job_id));
    }
    const references = job.references.length
      ? `<div class="button-row">${job.references.map((reference, index) => `<button class="secondary compact" data-production-reference="${escapeHtml(reference.reference_id)}" data-production-job="${escapeHtml(job.job_id)}">查看补图 ${index + 1}</button>`).join("")}</div>`
      : '<p class="muted">没有补充参考图</p>';
    const logs = job.logs.slice(-5).reverse().map((entry) => `<li>${escapeHtml(formatDate(entry.created_at))} · ${escapeHtml(productionAdminStatusLabel(entry.to_status))} · ${entry.progress}%${entry.message ? ` · ${escapeHtml(entry.message)}` : ""}</li>`).join("");
    return `<div class="review-card">
      <div>
        <div><span class="badge ${escapeHtml(job.status)}">${escapeHtml(productionAdminStatusLabel(job.status))}</span></div>
        <h3>${escapeHtml(job.pet_name)} · @${escapeHtml(job.account_username)}</h3>
        <p>进度 ${job.progress}% · ${job.assignee_display_name ? `负责人 ${escapeHtml(job.assignee_display_name)}（@${escapeHtml(job.assignee_username)}）` : "尚未分配负责人"}</p>
        <p>${escapeHtml(job.status_note || "暂无说明")}</p>
        <progress max="100" value="${job.progress}" aria-label="${escapeHtml(job.pet_name)} 制作进度"></progress>
        ${job.artifact ? `<p>产物 ${escapeHtml(job.artifact.identity_version)} / ${escapeHtml(job.artifact.asset_version)} · <code>${escapeHtml(job.artifact.package_sha256)}</code></p>` : ""}
        ${references}
        ${logs ? `<details><summary>最近操作</summary><ul>${logs}</ul></details>` : ""}
      </div>
      <div class="button-row">${actions.join("")}</div>
    </div>`;
  }).join("");

  $$('[data-production-action]').forEach((button) => button.addEventListener("click", () => runProductionAction(button.dataset.productionAction, button.dataset.productionJob)));
  $$('[data-production-reference]').forEach((button) => button.addEventListener("click", () => openProductionReference(button.dataset.productionJob, button.dataset.productionReference)));
}

function findProductionJob(jobId) {
  return state.productionJobs.find((item) => item.job_id === jobId) || null;
}

async function runProductionAction(action, jobId) {
  const job = findProductionJob(jobId);
  if (!job) return;
  if (action === "assign") {
    try {
      await api(`/api/v1/admin/pet-asset-production-jobs/${encodeURIComponent(jobId)}/assign`, {
        method: "POST",
        json: { assignee_username: state.admin.username, note: "管理员从 Web 管理台领取制作工单。" },
      });
      await loadProductionJobs();
      setStatus("工单已分配给当前管理员");
    } catch (error) {
      setStatus(errorMessage(error), true);
    }
    return;
  }
  if (action === "artifact") {
    await openProductionArtifactDialog(job);
    return;
  }
  if (action === "download") {
    await downloadProductionArtifact(job);
    return;
  }
  const status = action === "progress" ? job.status : action;
  $("#productionUpdateJobId").value = jobId;
  $("#productionUpdateStatus").value = status;
  $("#productionUpdateProgress").value = String(action === "processing" && job.progress === 0 ? 10 : job.progress);
  $("#productionUpdateNote").value = action === "progress" ? job.status_note : "";
  $("#productionUpdateTitle").textContent = action === "progress" ? "更新制作进度" : `${productionAdminStatusLabel(status)}：${job.pet_name}`;
  $("#productionUpdateDialog").showModal();
}

async function submitProductionUpdate(event) {
  event.preventDefault();
  const jobId = $("#productionUpdateJobId").value;
  try {
    await api(`/api/v1/admin/pet-asset-production-jobs/${encodeURIComponent(jobId)}/update`, {
      method: "POST",
      json: {
        status: $("#productionUpdateStatus").value,
        progress: Number.parseInt($("#productionUpdateProgress").value || "0", 10),
        note: $("#productionUpdateNote").value.trim(),
      },
    });
    $("#productionUpdateDialog").close();
    await loadProductionJobs();
    setStatus("工单状态与进度已更新");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function openProductionArtifactDialog(job) {
  try {
    await loadTemplates();
    const versions = await loadAllVersions();
    const available = versions.filter((item) => ["draft", "changes_required"].includes(item.status));
    $("#productionArtifactVersion").innerHTML = available.length
      ? available.map((version) => {
        const template = state.templates.find((item) => item.id === version.template_id);
        return `<option value="${escapeHtml(version.id)}">${escapeHtml(template?.template_code || version.template_id)} · ${escapeHtml(version.template_version)} · ${escapeHtml(version.identity_version)} / ${escapeHtml(version.asset_version)}</option>`;
      }).join("")
      : '<option value="">没有可用的草稿模板版本</option>';
    $("#productionArtifactJobId").value = job.job_id;
    $("#productionArtifactFile").value = "";
    $("#productionArtifactForm button[value='default']").disabled = !available.length;
    $("#productionArtifactDialog").showModal();
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function submitProductionArtifact(event) {
  event.preventDefault();
  const jobId = $("#productionArtifactJobId").value;
  const file = $("#productionArtifactFile").files[0];
  if (!file) return;
  const data = new FormData();
  data.append("target_template_version_id", $("#productionArtifactVersion").value);
  data.append("package", file);
  try {
    await api(`/api/v1/admin/pet-asset-production-jobs/${encodeURIComponent(jobId)}/artifact`, {
      method: "POST",
      body: data,
    });
    $("#productionArtifactDialog").close();
    await loadProductionJobs();
    setStatus("制作产物已通过校验并进入 ready，尚未发布");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function downloadProductionArtifact(job) {
  const url = job.artifact?.package_url;
  if (!url) return;
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${state.token}`, Accept: "application/zip" },
    });
    if (response.status === 401) {
      logout();
      throw new Error("登录已过期，请重新登录");
    }
    if (!response.ok) {
      let message = `产物下载失败（${response.status}）`;
      try {
        message = (await response.json()).detail || message;
      } catch {}
      throw new Error(message);
    }
    const objectUrl = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = `pet-production-artifact-${job.artifact.artifact_id}.zip`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    setStatus("制作产物已通过鉴权下载");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function openProductionReference(jobId, referenceId) {
  const job = findProductionJob(jobId);
  const reference = job?.references.find((item) => item.reference_id === referenceId);
  if (!reference) return;
  try {
    const response = await fetch(reference.image_url, {
      headers: { Authorization: `Bearer ${state.token}`, Accept: reference.image_media_type },
    });
    if (!response.ok) throw new Error(`参考图读取失败（${response.status}）`);
    clearProductionReferencePreview();
    productionReferencePreviewUrl = URL.createObjectURL(await response.blob());
    $("#productionReferencePreview").src = productionReferencePreviewUrl;
    $("#productionReferenceNote").textContent = reference.note || reference.original_filename;
    $("#productionReferencePreviewDialog").showModal();
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

function clearProductionReferencePreview() {
  if (productionReferencePreviewUrl) URL.revokeObjectURL(productionReferencePreviewUrl);
  productionReferencePreviewUrl = "";
  const image = $("#productionReferencePreview");
  if (image) image.removeAttribute("src");
}

window.addEventListener("beforeunload", clearProductionReferencePreview);
ensureAdminProductionWorkspace();
