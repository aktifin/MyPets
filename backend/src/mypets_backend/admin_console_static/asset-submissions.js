"use strict";

let assetSubmissionPreviewUrl = "";
let selectedAssetSubmission = null;

function ensureAdminAssetSubmissionWorkspace() {
  if (document.querySelector('[data-view="assetSubmissions"]')) return;
  titles.assetSubmissions = "用户原图";
  state.assetSubmissions = [];

  const navigation = $("#navigation");
  const button = document.createElement("button");
  button.dataset.view = "assetSubmissions";
  button.textContent = "用户原图";
  const auditButton = navigation.querySelector('[data-view="audit"]');
  navigation.insertBefore(button, auditButton || null);

  const view = document.createElement("section");
  view.id = "assetSubmissionsView";
  view.className = "view-panel hidden";
  view.innerHTML = `
    <article class="panel">
      <div class="panel-heading">
        <div><p class="eyebrow">USER SOURCE IMAGES</p><h3>宠物原图提交</h3></div>
        <div class="button-row">
          <select id="assetSubmissionStatusFilter" aria-label="提交状态">
            <option value="">全部状态</option>
            <option value="pending_processing">等待处理</option>
            <option value="in_review">审核中</option>
            <option value="approved">已通过</option>
            <option value="rejected">已驳回</option>
          </select>
          <button id="refreshAssetSubmissions" class="secondary compact">刷新</button>
        </div>
      </div>
      <p class="muted">通过仅表示进入人工动作帧制作队列，不会自动发布或修改宠物形象版本。</p>
      <div id="assetSubmissionList" class="review-list"></div>
    </article>`;
  $(".main-content").append(view);

  const dialog = document.createElement("dialog");
  dialog.id = "assetSubmissionDialog";
  dialog.innerHTML = `
    <form id="assetSubmissionReviewForm" method="dialog">
      <h3 id="assetSubmissionDialogTitle">审核宠物原图</h3>
      <div class="visual-acceptance">
        <div class="device-simulator preset-compact"><div class="desktop-canvas"><img id="assetSubmissionPreview" alt="用户提交的宠物原图"></div></div>
      </div>
      <div id="assetSubmissionFacts" class="detail-grid"></div>
      <label>审核意见<textarea id="assetSubmissionComment" rows="5" maxlength="2000"></textarea></label>
      <input id="assetSubmissionDecision" type="hidden">
      <div class="dialog-actions">
        <button id="cancelAssetSubmissionReview" value="cancel" class="ghost">取消</button>
        <button value="default" class="primary">确认</button>
      </div>
    </form>`;
  document.body.append(dialog);

  $("#refreshAssetSubmissions").addEventListener("click", loadAssetSubmissions);
  $("#assetSubmissionStatusFilter").addEventListener("change", loadAssetSubmissions);
  $("#cancelAssetSubmissionReview").addEventListener("click", (event) => {
    event.preventDefault();
    dialog.close();
    clearAssetSubmissionPreview();
  });
  $("#assetSubmissionReviewForm").addEventListener("submit", submitAssetSubmissionDecision);

  const originalShowView = showView;
  showView = async function patchedShowView(name) {
    if (name !== "assetSubmissions") return originalShowView(name);
    $$(".view-panel").forEach((panel) => panel.classList.add("hidden"));
    $("#assetSubmissionsView").classList.remove("hidden");
    $$("#navigation button").forEach((entry) => entry.classList.toggle("active", entry.dataset.view === name));
    $("#viewTitle").textContent = titles[name];
    setStatus("正在加载…");
    try {
      await loadAssetSubmissions();
      setStatus("");
    } catch (error) {
      setStatus(errorMessage(error), true);
    }
  };
}

function assetSubmissionStatusLabel(value) {
  return {
    pending_processing: "等待处理",
    in_review: "审核中",
    approved: "已通过",
    rejected: "已驳回",
  }[value] || value;
}

function assetSubmissionStyleLabel(value) {
  return {
    original: "保留原画风",
    light_chibi: "轻度 Q 版",
    full_chibi: "完整 Q 版",
  }[value] || value;
}

async function loadAssetSubmissions() {
  const status = $("#assetSubmissionStatusFilter").value;
  const query = status ? `?status=${encodeURIComponent(status)}&limit=500` : "?limit=500";
  state.assetSubmissions = await api(`/api/v1/admin/pet-asset-submissions${query}`);
  renderAssetSubmissions();
}

function renderAssetSubmissions() {
  const container = $("#assetSubmissionList");
  if (!state.assetSubmissions.length) {
    container.innerHTML = '<div class="empty-row">当前没有匹配的用户原图提交</div>';
    return;
  }
  container.innerHTML = state.assetSubmissions.map((item) => {
    const actions = [
      `<button class="secondary compact" data-asset-preview="${escapeHtml(item.submission_id)}">查看原图</button>`,
    ];
    if (item.status === "pending_processing" && can("edit")) {
      actions.push(`<button class="primary compact" data-asset-start="${escapeHtml(item.submission_id)}">领取审核</button>`);
    }
    if (item.status === "in_review" && can("review")) {
      actions.push(`<button class="primary compact" data-asset-approve="${escapeHtml(item.submission_id)}">通过</button>`);
      actions.push(`<button class="secondary compact" data-asset-reject="${escapeHtml(item.submission_id)}">驳回</button>`);
    }
    return `<div class="review-card">
      <div>
        <div><span class="badge ${escapeHtml(item.status)}">${escapeHtml(assetSubmissionStatusLabel(item.status))}</span></div>
        <h3>${escapeHtml(item.pet_name)} · ${escapeHtml(item.account_display_name)}</h3>
        <p>@${escapeHtml(item.account_username)} · ${escapeHtml(assetSubmissionStyleLabel(item.style_preference))}</p>
        <p>${escapeHtml(`${item.image_width}×${item.image_height}`)} · ${escapeHtml(formatBytes(item.image_size))} · ${escapeHtml(formatDate(item.created_at))}</p>
        ${item.personality_hint ? `<p>${escapeHtml(item.personality_hint)}</p>` : ""}
        ${item.review_comment ? `<p>审核意见：${escapeHtml(item.review_comment)}</p>` : ""}
      </div>
      <div class="button-row">${actions.join("")}</div>
    </div>`;
  }).join("");

  $$('[data-asset-preview]').forEach((button) => button.addEventListener("click", () => openAssetSubmissionDialog(button.dataset.assetPreview, "preview")));
  $$('[data-asset-start]').forEach((button) => button.addEventListener("click", () => startAssetSubmissionReview(button.dataset.assetStart)));
  for (const decision of ["approve", "reject"]) {
    $$(`[data-asset-${decision}]`).forEach((button) => button.addEventListener("click", () => {
      openAssetSubmissionDialog(button.dataset[`asset${decision[0].toUpperCase()}${decision.slice(1)}`], decision);
    }));
  }
}

async function fetchAssetSubmissionImage(item) {
  const response = await fetch(item.image_url, {
    headers: { Authorization: `Bearer ${state.token}`, Accept: item.image_media_type },
  });
  if (response.status === 401) {
    logout();
    throw new Error("登录已过期，请重新登录");
  }
  if (!response.ok) {
    let message = `原图读取失败（${response.status}）`;
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  clearAssetSubmissionPreview();
  assetSubmissionPreviewUrl = URL.createObjectURL(await response.blob());
  $("#assetSubmissionPreview").src = assetSubmissionPreviewUrl;
}

function clearAssetSubmissionPreview() {
  if (assetSubmissionPreviewUrl) URL.revokeObjectURL(assetSubmissionPreviewUrl);
  assetSubmissionPreviewUrl = "";
  const image = $("#assetSubmissionPreview");
  if (image) image.removeAttribute("src");
}

async function openAssetSubmissionDialog(submissionId, decision) {
  selectedAssetSubmission = state.assetSubmissions.find((item) => item.submission_id === submissionId) || null;
  if (!selectedAssetSubmission) return;
  try {
    await fetchAssetSubmissionImage(selectedAssetSubmission);
    $("#assetSubmissionDecision").value = decision;
    $("#assetSubmissionDialogTitle").textContent = {
      preview: "查看宠物原图",
      approve: "通过宠物原图",
      reject: "驳回宠物原图",
    }[decision];
    $("#assetSubmissionFacts").innerHTML = `
      <div><span>宠物</span><strong>${escapeHtml(selectedAssetSubmission.pet_name)}</strong></div>
      <div><span>提交账户</span><strong>@${escapeHtml(selectedAssetSubmission.account_username)}</strong></div>
      <div><span>权利依据</span><strong>${escapeHtml(selectedAssetSubmission.rights_basis)}</strong></div>
      <div><span>SHA-256</span><code>${escapeHtml(selectedAssetSubmission.image_sha256)}</code></div>`;
    $("#assetSubmissionComment").value = selectedAssetSubmission.review_comment || "";
    $("#assetSubmissionComment").disabled = decision === "preview";
    $("#assetSubmissionReviewForm button[value='default']").classList.toggle("hidden", decision === "preview");
    $("#assetSubmissionDialog").showModal();
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function startAssetSubmissionReview(submissionId) {
  try {
    await api(`/api/v1/admin/pet-asset-submissions/${encodeURIComponent(submissionId)}/start-review`, {
      method: "POST",
      json: { comment: "" },
    });
    await loadAssetSubmissions();
    setStatus("提交已领取并进入审核中");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function submitAssetSubmissionDecision(event) {
  event.preventDefault();
  if (!selectedAssetSubmission) return;
  const decision = $("#assetSubmissionDecision").value;
  if (decision === "preview") {
    $("#assetSubmissionDialog").close();
    clearAssetSubmissionPreview();
    return;
  }
  const comment = $("#assetSubmissionComment").value.trim();
  if (decision === "reject" && comment.length < 3) {
    setStatus("驳回时必须填写至少 3 个字符的原因", true);
    return;
  }
  try {
    await api(`/api/v1/admin/pet-asset-submissions/${encodeURIComponent(selectedAssetSubmission.submission_id)}/${decision}`, {
      method: "POST",
      json: { comment },
    });
    $("#assetSubmissionDialog").close();
    clearAssetSubmissionPreview();
    await loadAssetSubmissions();
    setStatus(decision === "approve" ? "原图已通过并进入人工制作队列" : "原图已驳回");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

window.addEventListener("beforeunload", clearAssetSubmissionPreview);
ensureAdminAssetSubmissionWorkspace();
