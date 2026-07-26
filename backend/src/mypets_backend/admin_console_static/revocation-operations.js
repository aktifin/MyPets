"use strict";

state.revocationOperations = {
  totals: {},
  groups: [],
  devices: [],
};
let selectedRevocationDevice = null;
let selectedRevocationHistory = [];

const revocationFollowUpNames = {
  unreviewed: "未跟进",
  investigating: "处理中",
  resolved: "已解决",
  waived: "已豁免",
};

function ensureRevocationOperationsWorkspace() {
  const view = $("#assetGovernanceView");
  if (!view || $("#revocationOperationsPanel")) return;
  const panel = document.createElement("article");
  panel.id = "revocationOperationsPanel";
  panel.className = "panel";
  panel.innerHTML = `
    <div class="panel-heading">
      <div><p class="eyebrow">DEVICE CLEANUP OPERATIONS</p><h3>设备撤销执行与人工跟进</h3></div>
      <div class="button-row inline-actions">
        <select id="revocationDeviceFilter" aria-label="设备撤销状态筛选">
          <option value="attention">仅需跟进</option>
          <option value="all">全部设备</option>
          <option value="pending">未回执</option>
          <option value="failed">清理失败</option>
          <option value="investigating">处理中</option>
          <option value="resolved">已解决</option>
          <option value="waived">已豁免</option>
        </select>
        <button id="refreshRevocationOperations" class="secondary compact">刷新</button>
      </div>
    </div>
    <p class="muted">统计所有仍有效设备对版权撤销的实际执行情况。客户端回执保持原始事实，人工跟进以不可变历史追加记录。</p>
    <div id="revocationOperationsSummary" class="summary-grid revocation-summary"></div>
    <div id="revocationGroupList" class="revocation-group-list"></div>
    <div class="panel-heading revocation-device-heading"><h4>设备明细</h4><span id="revocationDeviceCount" class="muted"></span></div>
    <div id="revocationDeviceList" class="revocation-device-list"></div>`;
  view.append(panel);

  const dialog = document.createElement("dialog");
  dialog.id = "revocationFollowUpDialog";
  dialog.innerHTML = `<form id="revocationFollowUpForm" method="dialog">
    <h3>记录设备撤销跟进</h3>
    <p id="revocationFollowUpTarget" class="muted"></p>
    <input id="revocationFollowUpRightId" type="hidden">
    <input id="revocationFollowUpReleaseId" type="hidden">
    <input id="revocationFollowUpDeviceId" type="hidden">
    <label>处理状态<select id="revocationFollowUpStatus">
      <option value="investigating">处理中</option>
      <option value="resolved">已解决</option>
      <option value="waived">已豁免</option>
    </select></label>
    <label>跟进记录<textarea id="revocationFollowUpNote" rows="5" minlength="3" maxlength="2000" required></textarea></label>
    <section class="evidence-section"><div class="panel-heading"><h4>跟进历史</h4></div><div id="revocationFollowUpHistory" class="history-list"></div></section>
    <div class="dialog-actions"><button id="cancelRevocationFollowUp" type="button" class="ghost">取消</button><button value="default" class="primary">保存记录</button></div>
  </form>`;
  document.body.append(dialog);

  $("#revocationDeviceFilter").addEventListener("change", renderRevocationOperations);
  $("#refreshRevocationOperations").addEventListener("click", async () => {
    try {
      await loadRevocationOperations();
      setStatus("设备撤销执行状态已刷新");
    } catch (error) {
      setStatus(errorMessage(error), true);
    }
  });
  $("#cancelRevocationFollowUp").addEventListener("click", () => dialog.close());
  $("#revocationFollowUpForm").addEventListener("submit", submitRevocationFollowUp);
}

function revocationStatusClass(value) {
  return String(value || "unknown").replace(/[^a-z0-9_-]/gi, "-");
}

function revocationBadge(value, label) {
  return `<span class="badge revocation-${revocationStatusClass(value)}">${escapeHtml(label)}</span>`;
}

function deviceAcknowledgementState(item) {
  if (!item.acknowledgement_id) return "pending";
  if (item.acknowledgement_status === "completed" && item.cache_cleared && item.fallback_applied) return "completed";
  return "failed";
}

function matchesRevocationFilter(item, filter) {
  if (filter === "all") return true;
  if (filter === "attention") return item.needs_attention;
  if (filter === "pending" || filter === "failed") return deviceAcknowledgementState(item) === filter;
  return item.follow_up_status === filter;
}

async function loadRevocationOperations() {
  state.revocationOperations = await api("/api/v1/admin/governance/revocation-operations?limit=500");
  renderRevocationOperations();
}

function renderRevocationOperations() {
  const data = state.revocationOperations || { totals: {}, groups: [], devices: [] };
  const totals = data.totals || {};
  const cards = [
    ["撤销批次", totals.revocation_count || 0],
    ["应执行设备", totals.expected_device_count || 0],
    ["已安全清理", totals.completed_device_count || 0],
    ["未回执", totals.pending_device_count || 0],
    ["清理失败", totals.failed_device_count || 0],
    ["需跟进", totals.attention_device_count || 0],
  ];
  $("#revocationOperationsSummary").innerHTML = cards
    .map(([name, value]) => `<div class="summary-card"><span>${escapeHtml(name)}</span><strong>${value}</strong></div>`)
    .join("");

  $("#revocationGroupList").innerHTML = data.groups.length
    ? data.groups.map((item) => {
      const rate = Math.max(0, Math.min(100, Number(item.completion_rate || 0)));
      return `<div class="revocation-group-card">
        <div class="revocation-group-main"><div><strong>${escapeHtml(item.pet_name)}</strong><small>撤销 ${formatDate(item.revoked_at)} · Release <code>${escapeHtml(item.release_id)}</code></small></div>${item.attention_device_count ? revocationBadge("attention", `${item.attention_device_count} 台需跟进`) : revocationBadge("resolved", "设备已闭环")}</div>
        <p>${escapeHtml(item.revoked_reason)}</p>
        <div class="revocation-progress"><span style="width:${rate}%"></span></div>
        <div class="revocation-group-metrics"><span>完成 ${item.completed_device_count}/${item.expected_device_count}</span><span>未回执 ${item.pending_device_count}</span><span>失败 ${item.failed_device_count}</span><span>处理中 ${item.investigating_device_count}</span><span>${rate.toFixed(1)}%</span></div>
      </div>`;
    }).join("")
    : '<div class="empty-row">当前没有需要统计的版权撤销批次</div>';

  const filter = $("#revocationDeviceFilter").value;
  const rows = data.devices.filter((item) => matchesRevocationFilter(item, filter));
  $("#revocationDeviceCount").textContent = `${rows.length} 台设备`;
  $("#revocationDeviceList").innerHTML = rows.length
    ? rows.map(renderRevocationDeviceRow).join("")
    : '<div class="empty-row">当前筛选条件下没有设备记录</div>';
  $$('[data-revocation-follow-up]').forEach((button) => button.addEventListener("click", () => openRevocationFollowUp(button.dataset.revocationFollowUp)));
}

function renderRevocationDeviceRow(item) {
  const stateValue = deviceAcknowledgementState(item);
  const stateLabel = stateValue === "completed" ? "已安全清理" : stateValue === "failed" ? "清理失败" : "未回执";
  const followLabel = revocationFollowUpNames[item.follow_up_status] || item.follow_up_status;
  const targetKey = `${item.right_id}|${item.release_id}|${item.device_id}`;
  const action = can("publish") ? `<button class="secondary compact" data-revocation-follow-up="${escapeHtml(targetKey)}">记录跟进</button>` : "";
  const checks = item.acknowledgement_id
    ? `<span>缓存清理：${item.cache_cleared ? "是" : "否"}</span><span>安全降级：${item.fallback_applied ? "是" : "否"}</span><span>尝试 ${item.attempt_count} 次</span>`
    : "<span>等待设备上线并提交回执</span>";
  return `<div class="revocation-device-row ${item.needs_attention ? "needs-attention" : "closed"}">
    <div class="revocation-device-title"><div>${revocationBadge(stateValue, stateLabel)} ${revocationBadge(item.follow_up_status, followLabel)}<h4>${escapeHtml(item.device_name)} · ${escapeHtml(item.platform)}</h4><small>${escapeHtml(item.account_display_name)}（@${escapeHtml(item.account_username)}） · 宠物 ${escapeHtml(item.pet_name)}</small></div><div class="button-row">${action}</div></div>
    <div class="revocation-device-meta"><span>最近在线：${formatDate(item.last_seen_at)}</span>${checks}</div>
    ${item.acknowledgement_message ? `<p>设备回执：${escapeHtml(item.acknowledgement_message)}</p>` : ""}
    ${item.follow_up_note ? `<p>最新跟进：${escapeHtml(item.follow_up_note)} · ${formatDate(item.follow_up_at)}</p>` : ""}
  </div>`;
}

function findRevocationDevice(targetKey) {
  const [rightId, releaseId, deviceId] = String(targetKey || "").split("|");
  return state.revocationOperations.devices.find((item) => item.right_id === rightId && item.release_id === releaseId && item.device_id === deviceId) || null;
}

async function openRevocationFollowUp(targetKey) {
  selectedRevocationDevice = findRevocationDevice(targetKey);
  if (!selectedRevocationDevice) return;
  $("#revocationFollowUpRightId").value = selectedRevocationDevice.right_id;
  $("#revocationFollowUpReleaseId").value = selectedRevocationDevice.release_id;
  $("#revocationFollowUpDeviceId").value = selectedRevocationDevice.device_id;
  $("#revocationFollowUpTarget").textContent = `${selectedRevocationDevice.pet_name} · ${selectedRevocationDevice.device_name} · @${selectedRevocationDevice.account_username}`;
  $("#revocationFollowUpStatus").value = selectedRevocationDevice.follow_up_status === "unreviewed" ? "investigating" : selectedRevocationDevice.follow_up_status;
  $("#revocationFollowUpNote").value = selectedRevocationDevice.follow_up_note || (selectedRevocationDevice.acknowledgement_id ? "核查设备清理失败原因并指导重新同步。" : "联系用户确认设备状态并促使设备上线执行撤销清理。");
  const dialog = $("#revocationFollowUpDialog");
  if (!dialog.open) dialog.showModal();
  await loadRevocationFollowUpHistory();
}

async function loadRevocationFollowUpHistory() {
  if (!selectedRevocationDevice) return;
  const params = new URLSearchParams({
    right_id: selectedRevocationDevice.right_id,
    release_id: selectedRevocationDevice.release_id,
    device_id: selectedRevocationDevice.device_id,
  });
  try {
    selectedRevocationHistory = await api(`/api/v1/admin/governance/revocation-follow-ups?${params}`);
    $("#revocationFollowUpHistory").innerHTML = selectedRevocationHistory.length
      ? selectedRevocationHistory.map((item) => `<div class="history-row"><div><strong>${escapeHtml(revocationFollowUpNames[item.status] || item.status)}</strong><small>${formatDate(item.created_at)} · 操作人 ${escapeHtml(item.actor_account_id)}</small><p>${escapeHtml(item.note)}</p></div></div>`).join("")
      : '<div class="empty-row">尚无人工跟进记录</div>';
  } catch (error) {
    $("#revocationFollowUpHistory").innerHTML = `<div class="empty-row error">${escapeHtml(errorMessage(error))}</div>`;
  }
}

async function submitRevocationFollowUp(event) {
  event.preventDefault();
  try {
    await api("/api/v1/admin/governance/revocation-follow-ups", {
      method: "POST",
      json: {
        right_id: $("#revocationFollowUpRightId").value,
        release_id: $("#revocationFollowUpReleaseId").value,
        device_id: $("#revocationFollowUpDeviceId").value,
        status: $("#revocationFollowUpStatus").value,
        note: $("#revocationFollowUpNote").value.trim(),
      },
    });
    $("#revocationFollowUpDialog").close();
    await loadRevocationOperations();
    setStatus("设备撤销跟进记录已保存");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

ensureRevocationOperationsWorkspace();
const previousLoadGovernanceDeploymentDataForRevocations = loadGovernanceDeploymentData;
loadGovernanceDeploymentData = async function loadGovernanceDeploymentDataWithRevocationOperations() {
  await previousLoadGovernanceDeploymentDataForRevocations();
  await loadRevocationOperations();
};
