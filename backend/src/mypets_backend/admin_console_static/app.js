"use strict";

const state = {
  token: sessionStorage.getItem("mypetsAdminToken") || "",
  admin: null,
  permissions: new Set(),
  templates: [],
  versions: [],
  selectedTemplate: null,
  selectedVersion: null,
  preview: null,
  previewObjectUrl: "",
  previewRequestId: 0,
  animationTimer: null,
  releases: [],
  deployments: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const titles = {
  dashboard: "总览",
  templates: "宠物模板",
  reviews: "审核中心",
  releases: "发布与回滚",
  audit: "审计日志",
};
const statusNames = {
  draft: "草稿",
  in_review: "审核中",
  changes_required: "需修改",
  approved: "已批准",
  published: "已发布",
};
const roleNames = {
  superadmin: "超级管理员",
  editor: "宠物编辑",
  reviewer: "内容审核",
  publisher: "发布管理员",
  auditor: "审计员",
};
const actionNames = {
  idle: "待机",
  walk: "行走",
  sit: "坐下",
  sleep: "睡眠",
  wave: "挥手",
  happy: "开心",
  shy: "害羞",
  surprised: "惊讶",
  annoyed: "生气",
  sleepy: "困倦",
  curious: "好奇",
  selfie: "自拍",
  drag: "拖动",
};

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[char]);
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatBytes(value) {
  if (value === null || value === undefined) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1048576) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1048576).toFixed(1)} MB`;
}

function badge(status) {
  return `<span class="badge ${escapeHtml(status)}">${escapeHtml(statusNames[status] || status)}</span>`;
}

function badgeWithId(id, status) {
  return `<span id="${id}" class="badge ${escapeHtml(status)}">${escapeHtml(statusNames[status] || status)}</span>`;
}

function setStatus(message, isError = false) {
  const node = $("#globalStatus");
  node.textContent = message || "";
  node.classList.toggle("error", isError);
}

function errorMessage(error) {
  return error?.message || "请求失败";
}

function can(permission) {
  return state.permissions.has(permission);
}

function clearPreviewObjectUrl() {
  if (state.previewObjectUrl) {
    URL.revokeObjectURL(state.previewObjectUrl);
    state.previewObjectUrl = "";
  }
}

function stopAnimation() {
  if (state.animationTimer !== null) {
    window.clearInterval(state.animationTimer);
    state.animationTimer = null;
  }
  const button = $("#playPreview");
  if (button) button.textContent = "播放";
}

function clearCredentials() {
  state.token = "";
  state.admin = null;
  state.permissions = new Set();
  sessionStorage.removeItem("mypetsAdminToken");
}

function logout() {
  clearCredentials();
  clearPreviewObjectUrl();
  stopAnimation();
  state.templates = [];
  state.versions = [];
  state.selectedTemplate = null;
  state.selectedVersion = null;
  state.preview = null;
  state.releases = [];
  state.deployments = [];
  $("#appView").classList.add("hidden");
  $("#loginView").classList.remove("hidden");
  $("#password").value = "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) headers.set("Authorization", `Bearer ${state.token}`);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.json);
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    logout();
    throw new Error("登录已过期，请重新登录");
  }
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const data = await response.json();
      detail = typeof data.detail === "string" ? data.detail : detail;
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function login(username, password) {
  const body = new URLSearchParams({ username, password });
  const response = await fetch("/api/v1/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) {
    let detail = "用户名或密码错误";
    try {
      detail = (await response.json()).detail || detail;
    } catch {}
    throw new Error(detail);
  }
  const payload = await response.json();
  state.token = payload.access_token;
  sessionStorage.setItem("mypetsAdminToken", state.token);
  try {
    state.admin = await api("/api/v1/admin/me");
    state.permissions = new Set(state.admin.permissions);
  } catch (error) {
    clearCredentials();
    throw error;
  }
}

function applyPermissions() {
  $$('[data-requires]').forEach((node) => {
    node.classList.toggle("hidden", !can(node.dataset.requires));
  });
  $("#accountName").textContent = state.admin?.display_name || state.admin?.username || "";
  $("#roleBadges").innerHTML = (state.admin?.roles || [])
    .map((role) => `<span>${escapeHtml(roleNames[role] || role)}</span>`)
    .join("");
}

async function bootstrap() {
  if (!state.token) {
    logout();
    return;
  }
  try {
    state.admin = await api("/api/v1/admin/me");
    state.permissions = new Set(state.admin.permissions);
    applyPermissions();
    await loadTemplates();
    $("#loginView").classList.add("hidden");
    $("#appView").classList.remove("hidden");
    await showView("dashboard");
  } catch (error) {
    logout();
    $("#loginError").textContent = errorMessage(error);
  }
}

async function loadTemplates() {
  state.templates = await api("/api/v1/admin/pet-templates");
  renderTemplateList();
  return state.templates;
}

function renderTemplateList() {
  const query = $("#templateSearch").value.trim().toLowerCase();
  const rows = state.templates.filter((item) =>
    [item.template_code, item.display_name, item.species]
      .some((value) => String(value).toLowerCase().includes(query))
  );
  $("#templateList").innerHTML = rows.length
    ? rows.map((item) => `
      <button class="item-card ${state.selectedTemplate?.id === item.id ? "active" : ""}" data-template-id="${escapeHtml(item.id)}">
        <strong>${escapeHtml(item.display_name)}</strong>
        <small>${escapeHtml(item.template_code)} · ${escapeHtml(item.species)}</small>
      </button>`).join("")
    : '<div class="empty-row">没有匹配的模板</div>';
  $$('[data-template-id]').forEach((button) =>
    button.addEventListener("click", () => selectTemplate(button.dataset.templateId))
  );
}

async function selectTemplate(templateId) {
  state.selectedTemplate = state.templates.find((item) => item.id === templateId) || null;
  state.selectedVersion = null;
  state.preview = null;
  clearPreviewObjectUrl();
  stopAnimation();
  if (!state.selectedTemplate) return;
  setStatus("正在读取模板版本…");
  try {
    state.versions = await api(`/api/v1/admin/pet-templates/${templateId}/versions`);
    renderTemplateList();
    renderTemplateWorkspace();
    setStatus("");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

function renderTemplateWorkspace() {
  const item = state.selectedTemplate;
  $("#templateEmpty").classList.toggle("hidden", Boolean(item));
  $("#templateWorkspace").classList.toggle("hidden", !item);
  if (!item) return;
  $("#templateCode").textContent = `${item.template_code} · ${item.species}`;
  $("#templateName").textContent = item.display_name;
  $("#templateDescription").textContent = item.description || "暂无模板说明";
  $("#templateStatus").outerHTML = badgeWithId("templateStatus", item.status);
  $("#versionList").innerHTML = state.versions.length
    ? state.versions.map((version) => `
      <button class="version-card ${state.selectedVersion?.id === version.id ? "active" : ""}" data-version-id="${escapeHtml(version.id)}">
        <header><strong>${escapeHtml(version.template_version)}</strong>${badge(version.status)}</header>
        <p>身份 ${escapeHtml(version.identity_version)} · 素材 ${escapeHtml(version.asset_version)}</p>
      </button>`).join("")
    : '<div class="empty-row">尚未创建版本</div>';
  $$('[data-version-id]').forEach((button) =>
    button.addEventListener("click", () => selectVersion(button.dataset.versionId))
  );
  $("#versionDetail").classList.toggle("hidden", !state.selectedVersion);
  if (state.selectedVersion) renderVersionDetail();
}

async function selectVersion(versionId) {
  state.selectedVersion = state.versions.find((item) => item.id === versionId)
    || await api(`/api/v1/admin/pet-template-versions/${versionId}`);
  state.preview = null;
  clearPreviewObjectUrl();
  stopAnimation();
  renderTemplateWorkspace();
  if (state.selectedVersion.package_sha256) await loadPreview();
}

function actionButton(label, action, kind = "secondary") {
  return `<button class="${kind} compact" data-version-action="${action}">${label}</button>`;
}

function renderVersionDetail() {
  const version = state.selectedVersion;
  if (!version) return;
  $("#versionIdentity").textContent = `模板 ${version.template_version} · 身份 ${version.identity_version} · 素材 ${version.asset_version}`;
  $("#versionTitle").textContent = `版本 ${version.template_version}`;
  $("#versionStatus").outerHTML = badgeWithId("versionStatus", version.status);
  $("#packageSize").textContent = formatBytes(version.package_size);
  $("#packageHash").textContent = version.package_sha256 || "—";
  $("#reviewComment").textContent = version.review_comment || "—";

  const actions = [];
  if (["draft", "changes_required"].includes(version.status) && can("edit")) {
    actions.push(actionButton("提交审核", "submit", "primary"));
  }
  if (version.status === "in_review" && can("review")) {
    actions.push(actionButton("批准", "approve", "primary"));
    actions.push(actionButton("退回修改", "reject"));
  }
  if (version.status === "approved" && can("publish")) {
    actions.push(actionButton("正式发布", "publish", "primary"));
  }
  $("#versionActions").innerHTML = actions.join("");
  $$('[data-version-action]').forEach((button) =>
    button.addEventListener("click", () => runVersionAction(button.dataset.versionAction))
  );
  $("#uploadArea").classList.toggle(
    "hidden",
    !can("edit") || !["draft", "changes_required"].includes(version.status)
  );
  renderPreview();
}

async function loadPreview() {
  if (!state.selectedVersion) return;
  try {
    state.preview = await api(`/api/v1/admin/pet-template-versions/${state.selectedVersion.id}/preview`);
    renderPreview();
  } catch (error) {
    state.preview = null;
    setStatus(errorMessage(error), true);
  }
}

function currentActionInfo() {
  const name = $("#previewAction").value || "idle";
  return state.preview?.actions.find((item) => item.name === name) || null;
}

function renderPreview() {
  const preview = state.preview;
  $("#previewArea").classList.toggle("hidden", !preview);
  if (!preview) return;
  $("#previewAction").innerHTML = preview.actions.map((item) => `
    <option value="${escapeHtml(item.name)}">${escapeHtml(actionNames[item.name] || item.name)}${item.fallback_to ? `（降级到 ${escapeHtml(item.source_action)}）` : ""}</option>
  `).join("");
  $("#actionMatrix").innerHTML = preview.actions.map((item) => `
    <div class="matrix-item ${item.fallback_to ? "fallback" : "native"}">
      <strong>${escapeHtml(actionNames[item.name] || item.name)}</strong>
      <small>${item.fallback_to ? `降级 → ${escapeHtml(item.source_action)}` : `原生 · ${item.frame_count} 帧`}</small>
    </div>
  `).join("");
  $("#compareVersion").innerHTML = '<option value="">选择对比版本</option>'
    + state.versions
      .filter((item) => item.id !== state.selectedVersion.id && item.package_sha256)
      .map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.template_version)} · ${escapeHtml(item.asset_version)}</option>`)
      .join("");
  $("#comparisonResult").classList.add("hidden");
  $("#previewFrame").value = "0";
  updateFrameLimit();
  refreshPreviewImage();
}

function updateFrameLimit() {
  const count = Math.max(1, currentActionInfo()?.frame_count || 1);
  $("#previewFrame").max = String(count - 1);
  const current = Number.parseInt($("#previewFrame").value || "0", 10);
  if (current >= count) $("#previewFrame").value = "0";
}

function setPreviewFrame(value) {
  const count = Math.max(1, currentActionInfo()?.frame_count || 1);
  const normalized = ((value % count) + count) % count;
  $("#previewFrame").value = String(normalized);
  refreshPreviewImage();
}

async function refreshPreviewImage() {
  if (!state.selectedVersion || !state.preview) return;
  const requestId = ++state.previewRequestId;
  const action = $("#previewAction").value || "idle";
  const frame = Math.max(0, Number.parseInt($("#previewFrame").value || "0", 10));
  const url = `/api/v1/admin/pet-template-versions/${state.selectedVersion.id}/preview-image?action=${encodeURIComponent(action)}&frame_index=${frame}`;
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (response.status === 401) {
      logout();
      throw new Error("登录已过期，请重新登录");
    }
    if (!response.ok) {
      let detail = `预览失败（${response.status}）`;
      try {
        detail = (await response.json()).detail || detail;
      } catch {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    if (requestId !== state.previewRequestId) return;
    clearPreviewObjectUrl();
    state.previewObjectUrl = URL.createObjectURL(blob);
    $("#previewImage").src = state.previewObjectUrl;
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

function toggleAnimation() {
  if (state.animationTimer !== null) {
    stopAnimation();
    return;
  }
  const fps = Math.max(1, Number.parseInt($("#previewFps").value || "8", 10));
  $("#playPreview").textContent = "暂停";
  state.animationTimer = window.setInterval(() => {
    const current = Number.parseInt($("#previewFrame").value || "0", 10);
    setPreviewFrame(current + 1);
  }, Math.round(1000 / fps));
}

function applyDevicePreset() {
  const preset = $("#devicePreset").value || "desktop";
  $("#deviceSimulator").className = `device-simulator preset-${preset}`;
}

async function compareSelectedVersion() {
  if (!state.selectedVersion) return;
  const rightId = $("#compareVersion").value;
  if (!rightId) {
    setStatus("请选择一个对比版本", true);
    return;
  }
  try {
    const comparison = await api(`/api/v1/admin/pet-template-versions/compare?left_id=${encodeURIComponent(state.selectedVersion.id)}&right_id=${encodeURIComponent(rightId)}`);
    const flags = [
      ["模板", comparison.template_changed],
      ["渲染器", comparison.renderer_changed],
      ["视觉身份版本", comparison.identity_version_changed],
      ["素材版本", comparison.asset_version_changed],
      ["包哈希", comparison.package_hash_changed],
    ];
    const flagHtml = flags.map(([name, changed]) => `<span class="compare-flag ${changed ? "changed" : "same"}">${escapeHtml(name)}：${changed ? "有变化" : "一致"}</span>`).join("");
    const actionHtml = comparison.action_changes.length
      ? comparison.action_changes.map((item) => `<div class="comparison-row"><strong>${escapeHtml(actionNames[item.name] || item.name)}</strong><span>${escapeHtml(item.change)}</span><code>${escapeHtml(JSON.stringify(item.left))}</code><code>${escapeHtml(JSON.stringify(item.right))}</code></div>`).join("")
      : '<div class="empty-row">动作能力没有差异</div>';
    $("#comparisonResult").innerHTML = `<div class="compare-flags">${flagHtml}</div>${actionHtml}`;
    $("#comparisonResult").classList.remove("hidden");
    setStatus("版本对比完成");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function runVersionAction(action) {
  if (!state.selectedVersion) return;
  if (action === "approve" || action === "reject") {
    $("#reviewVersionId").value = state.selectedVersion.id;
    $("#reviewDecision").value = action;
    $("#reviewDialogTitle").textContent = action === "approve" ? "批准宠物版本" : "退回宠物版本";
    $("#reviewDecisionComment").value = "";
    $("#reviewDialog").showModal();
    return;
  }
  if (action === "publish" && !window.confirm("发布后素材包不可覆盖。确认正式发布该版本？")) return;
  const versionId = state.selectedVersion.id;
  setStatus("正在更新版本状态…");
  try {
    await api(`/api/v1/admin/pet-template-versions/${versionId}/${action === "submit" ? "submit-review" : "publish"}`, { method: "POST" });
    await selectTemplate(state.selectedTemplate.id);
    state.selectedVersion = state.versions.find((item) => item.id === versionId) || null;
    renderTemplateWorkspace();
    if (state.selectedVersion?.package_sha256) await loadPreview();
    setStatus(action === "publish" ? "发布完成" : "状态已更新");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

function uploadPackage() {
  const file = $("#packageFile").files[0];
  if (!file || !state.selectedVersion) {
    setStatus("请选择 ZIP 素材包", true);
    return;
  }
  const xhr = new XMLHttpRequest();
  const form = new FormData();
  form.append("package", file);
  xhr.open("POST", `/api/v1/admin/pet-template-versions/${state.selectedVersion.id}/package`);
  xhr.setRequestHeader("Authorization", `Bearer ${state.token}`);
  xhr.upload.onprogress = (event) => {
    if (event.lengthComputable) $("#uploadProgress").style.width = `${Math.round(event.loaded / event.total * 100)}%`;
  };
  xhr.onload = async () => {
    if (xhr.status === 401) {
      logout();
      return;
    }
    if (xhr.status >= 200 && xhr.status < 300) {
      state.selectedVersion = JSON.parse(xhr.responseText);
      state.versions = state.versions.map((item) => item.id === state.selectedVersion.id ? state.selectedVersion : item);
      $("#uploadProgress").style.width = "100%";
      renderTemplateWorkspace();
      await loadPreview();
      setStatus("素材包已上传并通过服务端校验");
      return;
    }
    let message = `上传失败（${xhr.status}）`;
    try {
      message = JSON.parse(xhr.responseText).detail || message;
    } catch {}
    setStatus(message, true);
  };
  xhr.onerror = () => setStatus("素材包上传失败", true);
  $("#uploadProgress").style.width = "0";
  setStatus("正在上传并校验素材包…");
  xhr.send(form);
}

async function loadAllVersions(status = "") {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return api(`/api/v1/admin/pet-template-versions${query}`);
}

async function loadReleaseData() {
  [state.releases, state.deployments] = await Promise.all([
    api("/api/v1/admin/pet-asset-releases"),
    api("/api/v1/admin/pet-asset-deployments"),
  ]);
  renderReleases();
  return state.releases;
}

function renderReleases() {
  const activeByTemplate = new Map(state.deployments.map((item) => [item.template_id, item.active_release.release_id]));
  $("#deploymentList").innerHTML = state.deployments.length
    ? state.deployments.map((item) => `<div class="deployment-card"><div><strong>${escapeHtml(item.template_id)}</strong><small>${escapeHtml(item.channel)} · ${formatDate(item.updated_at)}</small></div><div>${badge("published")}<code>${escapeHtml(item.active_release.asset_version)}</code></div><p>${escapeHtml(item.reason)}</p></div>`).join("")
    : '<div class="empty-row">暂无稳定发布通道</div>';

  $("#releaseList").innerHTML = state.releases.length
    ? `<table><thead><tr><th>模板</th><th>模板版本</th><th>身份 / 素材</th><th>大小</th><th>发布时间</th><th>状态</th><th>操作</th></tr></thead><tbody>${state.releases.map((item) => {
      const active = activeByTemplate.get(item.template_id) === item.release_id;
      const rollback = can("publish") && !active
        ? `<button class="secondary compact" data-rollback-release="${escapeHtml(item.release_id)}" data-rollback-template="${escapeHtml(item.template_id)}" data-rollback-label="${escapeHtml(item.asset_version)}">回滚到此版本</button>`
        : "";
      return `<tr><td>${escapeHtml(item.template_id)}</td><td>${escapeHtml(item.template_version)}</td><td>${escapeHtml(item.identity_version)} / ${escapeHtml(item.asset_version)}</td><td>${formatBytes(item.package_size)}</td><td>${formatDate(item.published_at)}</td><td>${active ? '<span class="badge active-release">当前稳定</span>' : "历史版本"}</td><td><a class="preview-link" href="${escapeHtml(item.download_url)}">下载</a>${rollback}</td></tr>`;
    }).join("")}</tbody></table>`
    : '<div class="empty-row">暂无发布记录</div>';

  $$('[data-rollback-release]').forEach((button) => button.addEventListener("click", () => {
    $("#rollbackTemplateId").value = button.dataset.rollbackTemplate;
    $("#rollbackReleaseId").value = button.dataset.rollbackRelease;
    $("#rollbackTarget").textContent = `将 ${button.dataset.rollbackTemplate} 的稳定通道切换到素材版本 ${button.dataset.rollbackLabel}`;
    $("#rollbackReason").value = "";
    $("#rollbackDialog").showModal();
  }));
}

async function renderReviews() {
  const reviews = await loadAllVersions("in_review");
  $("#reviewList").innerHTML = reviews.length
    ? reviews.map((item) => {
      const template = state.templates.find((entry) => entry.id === item.template_id);
      const decisions = can("review")
        ? `<button class="primary compact" data-review-approve="${escapeHtml(item.id)}">批准</button><button class="secondary compact" data-review-reject="${escapeHtml(item.id)}">退回</button>`
        : "";
      return `<div class="review-card"><div><div>${badge(item.status)}</div><h3>${escapeHtml(template?.display_name || item.template_id)} · ${escapeHtml(item.template_version)}</h3><p>身份 ${escapeHtml(item.identity_version)} · 素材 ${escapeHtml(item.asset_version)} · ${formatBytes(item.package_size)}</p></div><div class="button-row"><button class="secondary compact" data-review-open="${escapeHtml(item.id)}">查看</button>${decisions}</div></div>`;
    }).join("")
    : '<div class="empty-row">当前没有待审核版本</div>';

  $$('[data-review-open]').forEach((button) => button.addEventListener("click", async () => {
    const version = reviews.find((item) => item.id === button.dataset.reviewOpen);
    await selectTemplate(version.template_id);
    await selectVersion(version.id);
    await showView("templates");
  }));
  for (const decision of ["approve", "reject"]) {
    $$(`[data-review-${decision}]`).forEach((button) => button.addEventListener("click", () => {
      $("#reviewVersionId").value = button.dataset[`review${decision[0].toUpperCase()}${decision.slice(1)}`];
      $("#reviewDecision").value = decision;
      $("#reviewDialogTitle").textContent = decision === "approve" ? "批准宠物版本" : "退回宠物版本";
      $("#reviewDecisionComment").value = "";
      $("#reviewDialog").showModal();
    }));
  }
}

async function renderAudit() {
  const rows = await api("/api/v1/admin/audit-logs?limit=200");
  $("#auditList").innerHTML = rows.length
    ? `<table><thead><tr><th>时间</th><th>动作</th><th>资源</th><th>管理员</th><th>详情</th></tr></thead><tbody>${rows.map((item) => `<tr><td>${formatDate(item.created_at)}</td><td>${escapeHtml(item.action)}</td><td>${escapeHtml(item.resource_type)}<br><code>${escapeHtml(item.resource_id)}</code></td><td><code>${escapeHtml(item.admin_account_id)}</code></td><td><code>${escapeHtml(JSON.stringify(item.details))}</code></td></tr>`).join("")}</tbody></table>`
    : '<div class="empty-row">暂无审计记录</div>';
}

async function renderDashboard() {
  const [reviews, versions] = await Promise.all([loadAllVersions("in_review"), loadAllVersions()]);
  await loadReleaseData();
  const cards = [
    ["模板总数", state.templates.length],
    ["版本总数", versions.length],
    ["待审核", reviews.length],
    ["稳定通道", state.deployments.length],
  ];
  $("#summaryCards").innerHTML = cards.map(([name, value]) => `<div class="summary-card"><span>${name}</span><strong>${value}</strong></div>`).join("");
  $("#dashboardReviews").innerHTML = reviews.length
    ? reviews.slice(0, 5).map((item) => `<div class="item-card"><strong>${escapeHtml(item.template_version)}</strong><small>${escapeHtml(item.identity_version)} / ${escapeHtml(item.asset_version)}</small></div>`).join("")
    : '<div class="empty-row">没有待审核版本</div>';
  $("#dashboardReleases").innerHTML = state.deployments.length
    ? state.deployments.slice(0, 5).map((item) => `<div class="item-card"><strong>${escapeHtml(item.template_id)}</strong><small>稳定素材 ${escapeHtml(item.active_release.asset_version)} · ${formatDate(item.updated_at)}</small></div>`).join("")
    : '<div class="empty-row">暂无稳定发布</div>';
}

async function showView(name) {
  const button = $(`#navigation [data-view="${name}"]`);
  if (button?.dataset.requires && !can(button.dataset.requires)) {
    setStatus("当前角色无权访问该页面", true);
    return;
  }
  $$(".view-panel").forEach((panel) => panel.classList.add("hidden"));
  $(`#${name}View`).classList.remove("hidden");
  $$("#navigation button").forEach((entry) => entry.classList.toggle("active", entry.dataset.view === name));
  $("#viewTitle").textContent = titles[name] || name;
  setStatus("正在加载…");
  try {
    if (name === "dashboard") await renderDashboard();
    if (name === "templates") {
      await loadTemplates();
      renderTemplateWorkspace();
    }
    if (name === "reviews") {
      await loadTemplates();
      await renderReviews();
    }
    if (name === "releases") await loadReleaseData();
    if (name === "audit") await renderAudit();
    setStatus("");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#loginError").textContent = "";
  try {
    await login($("#username").value, $("#password").value);
    applyPermissions();
    $("#loginView").classList.add("hidden");
    $("#appView").classList.remove("hidden");
    await showView("dashboard");
  } catch (error) {
    $("#loginError").textContent = errorMessage(error);
  }
});

$("#logoutButton").addEventListener("click", logout);
$("#navigation").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) showView(button.dataset.view);
});
$$('[data-jump]').forEach((button) => button.addEventListener("click", () => showView(button.dataset.jump)));
$("#templateSearch").addEventListener("input", renderTemplateList);
$("#newTemplateButton").addEventListener("click", () => $("#templateDialog").showModal());
$("#newVersionButton").addEventListener("click", () => $("#versionDialog").showModal());

$("#templateForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const created = await api("/api/v1/admin/pet-templates", { method: "POST", json: data });
    event.currentTarget.reset();
    $("#templateDialog").close();
    await loadTemplates();
    await selectTemplate(created.id);
    setStatus("模板已创建");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
});

$("#versionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.selectedTemplate) return;
  const data = Object.fromEntries(new FormData(event.currentTarget));
  try {
    const created = await api(`/api/v1/admin/pet-templates/${state.selectedTemplate.id}/versions`, { method: "POST", json: data });
    $("#versionDialog").close();
    await selectTemplate(state.selectedTemplate.id);
    await selectVersion(created.id);
    setStatus("模板版本已创建");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
});

$("#uploadButton").addEventListener("click", uploadPackage);
$("#previewAction").addEventListener("change", () => {
  stopAnimation();
  $("#previewFrame").value = "0";
  updateFrameLimit();
  refreshPreviewImage();
});
$("#previewFrame").addEventListener("change", refreshPreviewImage);
$("#previousFrame").addEventListener("click", () => setPreviewFrame(Number.parseInt($("#previewFrame").value || "0", 10) - 1));
$("#nextFrame").addEventListener("click", () => setPreviewFrame(Number.parseInt($("#previewFrame").value || "0", 10) + 1));
$("#playPreview").addEventListener("click", toggleAnimation);
$("#previewFps").addEventListener("change", () => {
  if (state.animationTimer !== null) {
    stopAnimation();
    toggleAnimation();
  }
});
$("#devicePreset").addEventListener("change", applyDevicePreset);
$("#compareButton").addEventListener("click", compareSelectedVersion);

$("#reviewForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const id = $("#reviewVersionId").value;
  const decision = $("#reviewDecision").value;
  try {
    await api(`/api/v1/admin/pet-template-versions/${id}/${decision}`, { method: "POST", json: { comment: $("#reviewDecisionComment").value } });
    $("#reviewDialog").close();
    if (state.selectedTemplate) await selectTemplate(state.selectedTemplate.id);
    if (!$("#reviewsView").classList.contains("hidden")) await renderReviews();
    setStatus(decision === "approve" ? "版本已批准" : "版本已退回");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
});

$("#rollbackForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const templateId = $("#rollbackTemplateId").value;
  try {
    await api(`/api/v1/admin/pet-asset-deployments/${encodeURIComponent(templateId)}/rollback`, {
      method: "POST",
      json: { release_id: $("#rollbackReleaseId").value, reason: $("#rollbackReason").value },
    });
    $("#rollbackDialog").close();
    await loadReleaseData();
    setStatus("稳定版本已回滚");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
});

$("#refreshReviews").addEventListener("click", renderReviews);
$("#refreshReleases").addEventListener("click", loadReleaseData);
$("#refreshAudit").addEventListener("click", renderAudit);
$$('dialog button[value="cancel"]').forEach((button) => button.addEventListener("click", (event) => {
  event.preventDefault();
  button.closest("dialog").close();
}));
window.addEventListener("beforeunload", () => {
  clearPreviewObjectUrl();
  stopAnimation();
});

applyDevicePreset();
bootstrap();
