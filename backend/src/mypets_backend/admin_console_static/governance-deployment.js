"use strict";

let selectedGovernanceArtifact = null;
let selectedGovernanceRight = null;
let selectedDeploymentReview = null;
let selectedPersonalDeployment = null;

const governanceStatusNames = {
  none: "未登记",
  pending: "待独立复核",
  verified: "已核验",
  revoked: "已撤销",
  approved: "已批准",
  rejected: "已退回",
  published: "已发布",
};

function governanceStatusLabel(value) {
  return governanceStatusNames[value] || statusNames[value] || value;
}

function governanceBadge(value) {
  return `<span class="badge ${escapeHtml(value)}">${escapeHtml(governanceStatusLabel(value))}</span>`;
}

function ensureGovernanceDeploymentWorkspace() {
  if (document.querySelector('[data-view="assetGovernance"]')) return;
  titles.assetGovernance = "版权与专属部署";
  Object.assign(statusNames, governanceStatusNames);
  state.assetRights = [];
  state.governanceJobs = [];
  state.deploymentReviews = [];
  state.personalDeployments = [];

  const navigation = $("#navigation");
  const button = document.createElement("button");
  button.dataset.view = "assetGovernance";
  button.textContent = "版权与专属部署";
  const releasesButton = navigation.querySelector('[data-view="releases"]');
  navigation.insertBefore(button, releasesButton || null);

  const view = document.createElement("section");
  view.id = "assetGovernanceView";
  view.className = "view-panel hidden";
  view.innerHTML = `
    <div id="governanceSummary" class="summary-grid"></div>
    <article class="panel">
      <div class="panel-heading">
        <div><p class="eyebrow">RIGHTS LEDGER</p><h3>制作产物与版权存证</h3></div>
        <div class="button-row inline-actions">
          <select id="governanceRightFilter" aria-label="版权状态">
            <option value="">全部状态</option>
            <option value="none">未登记</option>
            <option value="pending">待复核</option>
            <option value="verified">已核验</option>
            <option value="revoked">已撤销</option>
          </select>
          <button id="refreshGovernance" class="secondary compact">刷新</button>
        </div>
      </div>
      <p class="muted">编辑人员登记权利材料，复核人员独立核验，发布人员负责撤销。版权声明人不能复核自己的存证。</p>
      <div id="governanceArtifactList" class="review-list"></div>
    </article>
    <article class="panel">
      <div class="panel-heading">
        <div><p class="eyebrow">D3 INDEPENDENT REVIEW</p><h3>专属素材部署审核</h3></div>
        <select id="deploymentReviewFilter" aria-label="部署审核状态">
          <option value="">全部状态</option>
          <option value="pending">待审核</option>
          <option value="approved">已批准</option>
          <option value="rejected">已退回</option>
          <option value="published">已发布</option>
        </select>
      </div>
      <p class="muted">审核人必须同时确认版权状态、视觉身份和服务端兼容性；制作产物上传者不能审核自己的产物。</p>
      <div id="personalReviewList" class="review-list"></div>
    </article>
    <article class="panel">
      <div class="panel-heading"><div><p class="eyebrow">PER-PET DEPLOYMENT</p><h3>当前专属素材部署</h3></div></div>
      <p class="muted">发布只切换单只宠物的 active Release。回退会交换当前与上一版本，不删除不可变素材包。</p>
      <div id="personalDeploymentList" class="deployment-grid"></div>
    </article>`;
  $(".main-content").append(view);

  createGovernanceDialogs();
  $("#refreshGovernance").addEventListener("click", loadGovernanceDeploymentData);
  $("#governanceRightFilter").addEventListener("change", renderGovernanceArtifacts);
  $("#deploymentReviewFilter").addEventListener("change", renderDeploymentReviews);

  const previousShowView = showView;
  showView = async function showViewWithGovernance(name) {
    if (name !== "assetGovernance") return previousShowView(name);
    $$(".view-panel").forEach((panel) => panel.classList.add("hidden"));
    $("#assetGovernanceView").classList.remove("hidden");
    $$("#navigation button").forEach((entry) => entry.classList.toggle("active", entry.dataset.view === name));
    $("#viewTitle").textContent = titles[name];
    setStatus("正在加载…");
    try {
      await loadGovernanceDeploymentData();
      setStatus("");
    } catch (error) {
      setStatus(errorMessage(error), true);
    }
  };
}

function createGovernanceDialogs() {
  const container = document.createElement("div");
  container.innerHTML = `
    <dialog id="rightDeclareDialog"><form id="rightDeclareForm" method="dialog">
      <h3>登记版权存证</h3><input id="rightDeclareArtifactId" type="hidden">
      <p id="rightDeclareTarget" class="muted"></p>
      <label>权利类型<select id="rightDeclareType"><option value="owner_authorization">宠物主人授权</option><option value="original_work">原创制作</option><option value="licensed_asset">合法许可素材</option><option value="other">其他</option></select></label>
      <label>来源与授权声明<textarea id="rightDeclareSource" rows="6" minlength="3" maxlength="4000" required></textarea></label>
      <div class="dialog-actions"><button value="cancel" class="ghost">取消</button><button value="default" class="primary">登记并进入待复核</button></div>
    </form></dialog>
    <dialog id="rightVerifyDialog"><form id="rightVerifyForm" method="dialog">
      <h3>独立复核版权存证</h3><input id="rightVerifyId" type="hidden"><p id="rightVerifyTarget" class="muted"></p>
      <label>复核意见<textarea id="rightVerifyComment" rows="5" minlength="3" maxlength="1000" required></textarea></label>
      <div class="dialog-actions"><button value="cancel" class="ghost">取消</button><button value="default" class="primary">确认核验</button></div>
    </form></dialog>
    <dialog id="rightRevokeDialog"><form id="rightRevokeForm" method="dialog">
      <h3>撤销版权存证</h3><input id="rightRevokeId" type="hidden"><p id="rightRevokeTarget" class="muted"></p>
      <label>撤销原因<textarea id="rightRevokeReason" rows="5" minlength="3" maxlength="1000" required></textarea></label>
      <p class="muted">撤销后服务端停止分发关联专属素材，并向相关账户发布缓存清理事件。</p>
      <div class="dialog-actions"><button value="cancel" class="ghost">取消</button><button value="default" class="primary danger">确认撤销</button></div>
    </form></dialog>
    <dialog id="deploymentReviewDialog"><form id="deploymentReviewForm" method="dialog">
      <h3 id="deploymentReviewDialogTitle">审核专属素材</h3><input id="deploymentReviewId" type="hidden"><input id="deploymentReviewDecision" type="hidden">
      <p id="deploymentReviewTarget" class="muted"></p>
      <label class="check-row"><input id="deploymentRightsVerified" type="checkbox"> 已核对版权存证处于 verified 状态</label>
      <label class="check-row"><input id="deploymentIdentityVerified" type="checkbox"> 已核对宠物视觉身份与参考资料一致</label>
      <label>审核意见<textarea id="deploymentReviewComment" rows="5" minlength="3" maxlength="1000" required></textarea></label>
      <div class="dialog-actions"><button value="cancel" class="ghost">取消</button><button value="default" class="primary">提交审核决定</button></div>
    </form></dialog>
    <dialog id="personalPublishDialog"><form id="personalPublishForm" method="dialog">
      <h3>发布专属素材</h3><input id="personalPublishReviewId" type="hidden"><p id="personalPublishTarget" class="muted"></p>
      <label>发布原因<textarea id="personalPublishReason" rows="5" minlength="3" maxlength="1000" required></textarea></label>
      <div class="dialog-actions"><button value="cancel" class="ghost">取消</button><button value="default" class="primary">创建 Release 并部署</button></div>
    </form></dialog>
    <dialog id="personalRollbackDialog"><form id="personalRollbackForm" method="dialog">
      <h3>回退宠物专属素材</h3><input id="personalRollbackPetId" type="hidden"><p id="personalRollbackTarget" class="muted"></p>
      <label>回退原因<textarea id="personalRollbackReason" rows="5" minlength="3" maxlength="1000" required></textarea></label>
      <div class="dialog-actions"><button value="cancel" class="ghost">取消</button><button value="default" class="primary danger">确认回退</button></div>
    </form></dialog>`;
  while (container.firstElementChild) document.body.append(container.firstElementChild);

  $("#rightDeclareForm").addEventListener("submit", submitRightDeclaration);
  $("#rightVerifyForm").addEventListener("submit", submitRightVerification);
  $("#rightRevokeForm").addEventListener("submit", submitRightRevocation);
  $("#deploymentReviewForm").addEventListener("submit", submitDeploymentReviewDecision);
  $("#personalPublishForm").addEventListener("submit", submitPersonalPublish);
  $("#personalRollbackForm").addEventListener("submit", submitPersonalRollback);
  ["rightDeclareDialog", "rightVerifyDialog", "rightRevokeDialog", "deploymentReviewDialog", "personalPublishDialog", "personalRollbackDialog"].forEach((id) => {
    $(`#${id} button[value="cancel"]`).addEventListener("click", (event) => {
      event.preventDefault();
      $(`#${id}`).close();
    });
  });
}

function latestRightsByArtifact() {
  const map = new Map();
  for (const right of state.assetRights) {
    if (!map.has(right.artifact_id)) map.set(right.artifact_id, right);
  }
  return map;
}

function reviewsByArtifact() {
  return new Map(state.deploymentReviews.map((review) => [review.artifact_id, review]));
}

function jobsById() {
  return new Map(state.governanceJobs.map((job) => [job.job_id, job]));
}

async function loadGovernanceDeploymentData() {
  const [rights, jobs, reviews, deployments] = await Promise.all([
    api("/api/v1/admin/governance/rights?limit=500"),
    api("/api/v1/admin/pet-asset-production-jobs?limit=500"),
    api("/api/v1/admin/pet-asset-deployment-reviews?limit=500"),
    api("/api/v1/admin/pet-personal-asset-deployments?limit=500"),
  ]);
  state.assetRights = rights;
  state.governanceJobs = jobs.filter((job) => Boolean(job.artifact));
  state.deploymentReviews = reviews;
  state.personalDeployments = deployments;
  renderGovernanceSummary();
  renderGovernanceArtifacts();
  renderDeploymentReviews();
  renderPersonalDeployments();
}

function renderGovernanceSummary() {
  const latest = latestRightsByArtifact();
  const counts = { pending: 0, verified: 0, revoked: 0, none: 0 };
  for (const job of state.governanceJobs) {
    const status = latest.get(job.artifact.artifact_id)?.status || "none";
    counts[status] += 1;
  }
  const cards = [
    ["制作产物", state.governanceJobs.length],
    ["待版权复核", counts.pending],
    ["待 D3 审核", state.deploymentReviews.filter((item) => item.status === "pending").length],
    ["当前专属部署", state.personalDeployments.length],
  ];
  $("#governanceSummary").innerHTML = cards.map(([name, value]) => `<div class="summary-card"><span>${escapeHtml(name)}</span><strong>${value}</strong></div>`).join("");
}

function renderGovernanceArtifacts() {
  const container = $("#governanceArtifactList");
  const filter = $("#governanceRightFilter").value;
  const rights = latestRightsByArtifact();
  const reviews = reviewsByArtifact();
  const jobs = state.governanceJobs.filter((job) => {
    const status = rights.get(job.artifact.artifact_id)?.status || "none";
    return !filter || status === filter;
  });
  if (!jobs.length) {
    container.innerHTML = '<div class="empty-row">当前没有匹配的制作产物</div>';
    return;
  }
  container.innerHTML = jobs.map((job) => {
    const artifact = job.artifact;
    const right = rights.get(artifact.artifact_id) || null;
    const review = reviews.get(artifact.artifact_id) || null;
    const actions = [];
    if ((!right || right.status === "revoked") && can("edit")) actions.push(`<button class="primary compact" data-governance-declare="${escapeHtml(artifact.artifact_id)}">登记版权</button>`);
    if (right?.status === "pending" && can("review")) actions.push(`<button class="primary compact" data-governance-verify="${escapeHtml(right.right_id)}">独立复核</button>`);
    if (right?.status === "verified" && can("publish")) actions.push(`<button class="secondary compact" data-governance-revoke="${escapeHtml(right.right_id)}">撤销存证</button>`);
    if (right?.status === "verified" && !review && job.status === "ready" && can("edit")) actions.push(`<button class="primary compact" data-deployment-submit="${escapeHtml(job.job_id)}">提交 D3 审核</button>`);
    return `<div class="review-card"><div>
      <div>${governanceBadge(right?.status || "none")} ${review ? governanceBadge(review.status) : ""}</div>
      <h3>${escapeHtml(job.pet_name)} · @${escapeHtml(job.account_username)}</h3>
      <p>${escapeHtml(artifact.template_code)} · 模板 ${escapeHtml(artifact.template_version)} · 身份 ${escapeHtml(artifact.identity_version)} · 素材 ${escapeHtml(artifact.asset_version)}</p>
      <p>产物 <code>${escapeHtml(artifact.artifact_id)}</code> · ${formatBytes(artifact.package_size)}</p>
      <p>SHA-256 <code>${escapeHtml(artifact.package_sha256)}</code></p>
      ${right ? `<p>权利类型：${escapeHtml(right.rights_type)} · 声明人 <code>${escapeHtml(right.declared_by_account_id)}</code>${right.verified_by_account_id ? ` · 复核人 <code>${escapeHtml(right.verified_by_account_id)}</code>` : ""}</p><p>${escapeHtml(right.source_declaration)}</p>${right.revoked_reason ? `<p>撤销原因：${escapeHtml(right.revoked_reason)}</p>` : ""}` : '<p class="muted">尚未建立权利存证，不能通过部署审核或发布。</p>'}
    </div><div class="button-row">${actions.join("")}</div></div>`;
  }).join("");

  $$('[data-governance-declare]').forEach((button) => button.addEventListener("click", () => openRightDeclare(button.dataset.governanceDeclare)));
  $$('[data-governance-verify]').forEach((button) => button.addEventListener("click", () => openRightVerify(button.dataset.governanceVerify)));
  $$('[data-governance-revoke]').forEach((button) => button.addEventListener("click", () => openRightRevoke(button.dataset.governanceRevoke)));
  $$('[data-deployment-submit]').forEach((button) => button.addEventListener("click", () => submitDeploymentReview(button.dataset.deploymentSubmit)));
}

function compatibilityHtml(review) {
  const checks = review.compatibility?.checks || {};
  const entries = Object.entries(checks);
  if (!entries.length) return '<p class="muted">审核决定提交时执行服务端兼容性检查。</p>';
  return `<div class="check-grid">${entries.map(([name, passed]) => `<span class="check-pill ${passed ? "passed" : "failed"}">${passed ? "✓" : "✕"} ${escapeHtml(name)}</span>`).join("")}</div>`;
}

function renderDeploymentReviews() {
  const container = $("#personalReviewList");
  const filter = $("#deploymentReviewFilter").value;
  const rights = latestRightsByArtifact();
  const jobs = jobsById();
  const reviews = state.deploymentReviews.filter((item) => !filter || item.status === filter);
  if (!reviews.length) {
    container.innerHTML = '<div class="empty-row">当前没有匹配的专属素材审核</div>';
    return;
  }
  container.innerHTML = reviews.map((review) => {
    const job = jobs.get(review.job_id);
    const right = rights.get(review.artifact_id);
    const actions = [];
    if (review.status === "pending" && can("review")) {
      actions.push(`<button class="primary compact" data-deployment-approve="${escapeHtml(review.review_id)}">批准</button>`);
      actions.push(`<button class="secondary compact" data-deployment-reject="${escapeHtml(review.review_id)}">退回</button>`);
    }
    if (review.status === "approved" && can("publish")) actions.push(`<button class="primary compact" data-personal-publish="${escapeHtml(review.review_id)}">发布并部署</button>`);
    return `<div class="review-card"><div>
      <div>${governanceBadge(review.status)} ${governanceBadge(right?.status || "none")}</div>
      <h3>${escapeHtml(review.pet_name)}${job ? ` · @${escapeHtml(job.account_username)}` : ""}</h3>
      <p>审核 <code>${escapeHtml(review.review_id)}</code> · 产物 <code>${escapeHtml(review.artifact_id)}</code></p>
      <p>版权确认：${review.rights_verified ? "是" : "否"} · 视觉身份确认：${review.visual_identity_verified ? "是" : "否"}</p>
      ${review.review_comment ? `<p>审核意见：${escapeHtml(review.review_comment)}</p>` : ""}
      ${compatibilityHtml(review)}
      ${review.release ? `<p>Release：${escapeHtml(review.release.asset_version)} · ${formatDate(review.release.published_at)}</p>` : ""}
    </div><div class="button-row">${actions.join("")}</div></div>`;
  }).join("");
  for (const decision of ["approve", "reject"]) {
    $$(`[data-deployment-${decision}]`).forEach((button) => button.addEventListener("click", () => openDeploymentReview(button.dataset[`deployment${decision[0].toUpperCase()}${decision.slice(1)}`], decision)));
  }
  $$('[data-personal-publish]').forEach((button) => button.addEventListener("click", () => openPersonalPublish(button.dataset.personalPublish)));
}

function renderPersonalDeployments() {
  const container = $("#personalDeploymentList");
  if (!state.personalDeployments.length) {
    container.innerHTML = '<div class="empty-row">当前没有宠物部署专属素材</div>';
    return;
  }
  container.innerHTML = state.personalDeployments.map((deployment) => {
    const active = deployment.active_release;
    const previous = deployment.previous_release;
    const rollback = previous && can("publish") ? `<button class="secondary compact" data-personal-rollback="${escapeHtml(deployment.pet_id)}">回退上一版本</button>` : "";
    return `<div class="deployment-card"><div><div><strong>${escapeHtml(active.template_code)}</strong><small>宠物 <code>${escapeHtml(deployment.pet_id)}</code></small></div>${governanceBadge("published")}</div><p>当前：${escapeHtml(active.identity_version)} / ${escapeHtml(active.asset_version)}</p><p>上一版本：${previous ? `${escapeHtml(previous.identity_version)} / ${escapeHtml(previous.asset_version)}` : "无"}</p><p>${escapeHtml(deployment.reason)} · ${formatDate(deployment.updated_at)}</p><div class="button-row">${rollback}</div></div>`;
  }).join("");
  $$('[data-personal-rollback]').forEach((button) => button.addEventListener("click", () => openPersonalRollback(button.dataset.personalRollback)));
}

function findArtifact(artifactId) {
  for (const job of state.governanceJobs) if (job.artifact?.artifact_id === artifactId) return { job, artifact: job.artifact };
  return null;
}

function openRightDeclare(artifactId) {
  selectedGovernanceArtifact = findArtifact(artifactId);
  if (!selectedGovernanceArtifact) return;
  $("#rightDeclareArtifactId").value = artifactId;
  $("#rightDeclareTarget").textContent = `${selectedGovernanceArtifact.job.pet_name} · ${selectedGovernanceArtifact.artifact.template_code} · ${selectedGovernanceArtifact.artifact.asset_version}`;
  $("#rightDeclareType").value = "owner_authorization";
  $("#rightDeclareSource").value = "宠物主人已提交原图并授权制作该宠物的专属桌面素材，仅用于账户私有分发。";
  $("#rightDeclareDialog").showModal();
}

function openRightVerify(rightId) {
  selectedGovernanceRight = state.assetRights.find((item) => item.right_id === rightId) || null;
  if (!selectedGovernanceRight) return;
  $("#rightVerifyId").value = rightId;
  $("#rightVerifyTarget").textContent = `${selectedGovernanceRight.rights_type} · ${selectedGovernanceRight.source_declaration}`;
  $("#rightVerifyComment").value = "已核验权利来源、授权范围与私有分发用途。";
  $("#rightVerifyDialog").showModal();
}

function openRightRevoke(rightId) {
  selectedGovernanceRight = state.assetRights.find((item) => item.right_id === rightId) || null;
  if (!selectedGovernanceRight) return;
  $("#rightRevokeId").value = rightId;
  $("#rightRevokeTarget").textContent = `${selectedGovernanceRight.rights_type} · 产物 ${selectedGovernanceRight.artifact_id}`;
  $("#rightRevokeReason").value = "授权失效，停止服务端分发并要求客户端清理缓存。";
  $("#rightRevokeDialog").showModal();
}

function openDeploymentReview(reviewId, decision) {
  selectedDeploymentReview = state.deploymentReviews.find((item) => item.review_id === reviewId) || null;
  if (!selectedDeploymentReview) return;
  const right = latestRightsByArtifact().get(selectedDeploymentReview.artifact_id);
  $("#deploymentReviewId").value = reviewId;
  $("#deploymentReviewDecision").value = decision;
  $("#deploymentReviewDialogTitle").textContent = decision === "approve" ? "批准专属素材" : "退回专属素材";
  $("#deploymentReviewTarget").textContent = `${selectedDeploymentReview.pet_name} · 产物 ${selectedDeploymentReview.artifact_id}`;
  $("#deploymentRightsVerified").checked = right?.status === "verified";
  $("#deploymentIdentityVerified").checked = false;
  $("#deploymentReviewComment").value = decision === "approve" ? "版权、视觉身份与兼容性检查通过。" : "需要修正后重新制作并提交新的产物。";
  $("#deploymentReviewDialog").showModal();
}

function openPersonalPublish(reviewId) {
  selectedDeploymentReview = state.deploymentReviews.find((item) => item.review_id === reviewId) || null;
  if (!selectedDeploymentReview) return;
  $("#personalPublishReviewId").value = reviewId;
  $("#personalPublishTarget").textContent = `${selectedDeploymentReview.pet_name} · 审核 ${reviewId}`;
  $("#personalPublishReason").value = "专属素材完成独立审核，创建不可变 Release 并部署到目标宠物。";
  $("#personalPublishDialog").showModal();
}

function openPersonalRollback(petId) {
  selectedPersonalDeployment = state.personalDeployments.find((item) => item.pet_id === petId) || null;
  if (!selectedPersonalDeployment?.previous_release) return;
  $("#personalRollbackPetId").value = petId;
  $("#personalRollbackTarget").textContent = `从 ${selectedPersonalDeployment.active_release.asset_version} 回退到 ${selectedPersonalDeployment.previous_release.asset_version}`;
  $("#personalRollbackReason").value = "当前专属素材需要回退，恢复上一已发布版本。";
  $("#personalRollbackDialog").showModal();
}

async function refreshGovernance(message) {
  await loadGovernanceDeploymentData();
  setStatus(message);
}

async function submitRightDeclaration(event) {
  event.preventDefault();
  try {
    await api("/api/v1/admin/governance/rights", { method: "POST", json: { artifact_id: $("#rightDeclareArtifactId").value, rights_type: $("#rightDeclareType").value, source_declaration: $("#rightDeclareSource").value.trim() } });
    $("#rightDeclareDialog").close();
    await refreshGovernance("版权存证已登记，等待独立复核");
  } catch (error) { setStatus(errorMessage(error), true); }
}

async function submitRightVerification(event) {
  event.preventDefault();
  try {
    await api(`/api/v1/admin/governance/rights/${encodeURIComponent($("#rightVerifyId").value)}/verify`, { method: "POST", json: { comment: $("#rightVerifyComment").value.trim() } });
    $("#rightVerifyDialog").close();
    await refreshGovernance("版权存证已独立核验");
  } catch (error) { setStatus(errorMessage(error), true); }
}

async function submitRightRevocation(event) {
  event.preventDefault();
  try {
    await api(`/api/v1/admin/governance/rights/${encodeURIComponent($("#rightRevokeId").value)}/revoke`, { method: "POST", json: { reason: $("#rightRevokeReason").value.trim() } });
    $("#rightRevokeDialog").close();
    await refreshGovernance("版权存证已撤销，关联素材已停止分发");
  } catch (error) { setStatus(errorMessage(error), true); }
}

async function submitDeploymentReview(jobId) {
  try {
    await api(`/api/v1/admin/pet-asset-production-jobs/${encodeURIComponent(jobId)}/submit-deployment-review`, { method: "POST" });
    await refreshGovernance("制作产物已提交 D3 独立审核");
  } catch (error) { setStatus(errorMessage(error), true); }
}

async function submitDeploymentReviewDecision(event) {
  event.preventDefault();
  const reviewId = $("#deploymentReviewId").value;
  const decision = $("#deploymentReviewDecision").value;
  const rightsVerified = $("#deploymentRightsVerified").checked;
  const visualVerified = $("#deploymentIdentityVerified").checked;
  if (decision === "approve" && (!rightsVerified || !visualVerified)) {
    setStatus("批准前必须勾选版权和视觉身份两项核验", true);
    return;
  }
  try {
    await api(`/api/v1/admin/pet-asset-deployment-reviews/${encodeURIComponent(reviewId)}/${decision}`, { method: "POST", json: { comment: $("#deploymentReviewComment").value.trim(), rights_verified: rightsVerified, visual_identity_verified: visualVerified } });
    $("#deploymentReviewDialog").close();
    await refreshGovernance(decision === "approve" ? "专属素材审核已批准" : "专属素材审核已退回");
  } catch (error) { setStatus(errorMessage(error), true); }
}

async function submitPersonalPublish(event) {
  event.preventDefault();
  try {
    await api(`/api/v1/admin/pet-asset-deployment-reviews/${encodeURIComponent($("#personalPublishReviewId").value)}/publish`, { method: "POST", json: { reason: $("#personalPublishReason").value.trim() } });
    $("#personalPublishDialog").close();
    await refreshGovernance("专属素材 Release 已创建并部署");
  } catch (error) { setStatus(errorMessage(error), true); }
}

async function submitPersonalRollback(event) {
  event.preventDefault();
  try {
    await api(`/api/v1/admin/pet-personal-asset-deployments/${encodeURIComponent($("#personalRollbackPetId").value)}/rollback`, { method: "POST", json: { reason: $("#personalRollbackReason").value.trim() } });
    $("#personalRollbackDialog").close();
    await refreshGovernance("宠物专属素材已回退到上一版本");
  } catch (error) { setStatus(errorMessage(error), true); }
}

ensureGovernanceDeploymentWorkspace();
