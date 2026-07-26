"use strict";

let selectedEvidenceRight = null;
let selectedEvidenceRows = [];
let selectedHistoryRows = [];

const rightValidityNames = {
  active: "授权有效",
  scheduled: "尚未生效",
  expired: "授权过期",
};

const rightHistoryNames = {
  declared: "登记存证",
  terms_updated: "调整有效期",
  evidence_added: "上传证据",
  verified: "独立复核通过",
  revoked: "撤销存证",
};

function localDateTimeValue(value) {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function isoOrNull(value) {
  return value ? new Date(value).toISOString() : null;
}

function ensureRightsEvidenceUi() {
  const declareForm = $("#rightDeclareForm");
  if (!declareForm || $("#rightDeclareEvidence")) return;
  const actions = declareForm.querySelector(".dialog-actions");
  actions.insertAdjacentHTML("beforebegin", `
    <div class="field-grid two-column">
      <label>授权开始时间<input id="rightDeclareValidFrom" type="datetime-local"></label>
      <label>授权结束时间<input id="rightDeclareValidUntil" type="datetime-local"></label>
    </div>
    <label>证据附件<input id="rightDeclareEvidence" type="file" accept="application/pdf,image/png,image/jpeg,text/plain" multiple required></label>
    <p class="muted">至少上传 1 个证据附件；单个文件不超过 8 MB，支持 PDF、PNG、JPEG 和纯文本。</p>`);

  declareForm.removeEventListener("submit", submitRightDeclaration);
  declareForm.addEventListener("submit", submitEnhancedRightDeclaration);

  const dialog = document.createElement("dialog");
  dialog.id = "rightEvidenceDialog";
  dialog.innerHTML = `<form id="rightEvidenceForm" method="dialog">
    <h3>版权证据与复核历史</h3>
    <p id="rightEvidenceTarget" class="muted"></p>
    <div id="rightEvidenceSummary" class="detail-grid"></div>
    <section class="evidence-section">
      <div class="panel-heading"><h4>授权有效期</h4></div>
      <div class="field-grid two-column">
        <label>开始时间<input id="rightTermsValidFrom" type="datetime-local"></label>
        <label>结束时间<input id="rightTermsValidUntil" type="datetime-local"></label>
      </div>
      <button id="saveRightTerms" type="button" class="secondary compact">保存有效期</button>
    </section>
    <section class="evidence-section">
      <div class="panel-heading"><h4>证据附件</h4></div>
      <div id="rightEvidenceList" class="evidence-list"></div>
      <div id="rightEvidenceUploadArea">
        <input id="rightEvidenceFiles" type="file" accept="application/pdf,image/png,image/jpeg,text/plain" multiple>
        <button id="uploadRightEvidence" type="button" class="secondary compact">补充上传</button>
      </div>
    </section>
    <section class="evidence-section">
      <div class="panel-heading"><h4>状态历史</h4></div>
      <div id="rightHistoryList" class="history-list"></div>
    </section>
    <div class="dialog-actions"><button id="closeRightEvidence" type="button" class="primary">关闭</button></div>
  </form>`;
  document.body.append(dialog);
  $("#closeRightEvidence").addEventListener("click", () => dialog.close());
  $("#saveRightTerms").addEventListener("click", saveRightTerms);
  $("#uploadRightEvidence").addEventListener("click", uploadAdditionalEvidence);
}

async function uploadEvidenceFiles(rightId, files) {
  for (const file of files) {
    const body = new FormData();
    body.append("evidence", file);
    await api(`/api/v1/admin/governance/rights/${encodeURIComponent(rightId)}/evidence`, {
      method: "POST",
      body,
    });
  }
}

async function submitEnhancedRightDeclaration(event) {
  event.preventDefault();
  const files = [...$("#rightDeclareEvidence").files];
  if (!files.length) {
    setStatus("登记版权存证时至少需要选择一个证据附件", true);
    return;
  }
  let right = null;
  try {
    right = await api("/api/v1/admin/governance/rights", {
      method: "POST",
      json: {
        artifact_id: $("#rightDeclareArtifactId").value,
        rights_type: $("#rightDeclareType").value,
        source_declaration: $("#rightDeclareSource").value.trim(),
        valid_from: isoOrNull($("#rightDeclareValidFrom").value),
        valid_until: isoOrNull($("#rightDeclareValidUntil").value),
      },
    });
    await uploadEvidenceFiles(right.right_id, files);
    $("#rightDeclareDialog").close();
    $("#rightDeclareEvidence").value = "";
    await refreshGovernance("版权存证和证据附件已登记，等待独立复核");
  } catch (error) {
    if (right) {
      $("#rightDeclareDialog").close();
      await loadGovernanceDeploymentData();
      setStatus(`版权存证已创建，但附件上传未全部完成：${errorMessage(error)}`, true);
    } else {
      setStatus(errorMessage(error), true);
    }
  }
}

const previousOpenRightDeclare = openRightDeclare;
openRightDeclare = function openRightDeclareWithEvidence(artifactId) {
  previousOpenRightDeclare(artifactId);
  $("#rightDeclareValidFrom").value = localDateTimeValue(new Date().toISOString());
  $("#rightDeclareValidUntil").value = "";
  $("#rightDeclareEvidence").value = "";
};

const previousRenderGovernanceArtifacts = renderGovernanceArtifacts;
renderGovernanceArtifacts = function renderGovernanceArtifactsWithEvidence() {
  previousRenderGovernanceArtifacts();
  const filter = $("#governanceRightFilter").value;
  const rights = latestRightsByArtifact();
  const jobs = state.governanceJobs.filter((job) => {
    const status = rights.get(job.artifact.artifact_id)?.status || "none";
    return !filter || status === filter;
  });
  const cards = [...$("#governanceArtifactList").querySelectorAll(".review-card")];
  cards.forEach((card, index) => {
    const job = jobs[index];
    if (!job) return;
    const right = rights.get(job.artifact.artifact_id);
    if (!right) return;
    const validity = rightValidityNames[right.validity_state] || right.validity_state;
    const info = document.createElement("p");
    info.className = "muted rights-validity-line";
    info.textContent = `有效期：${right.valid_from ? formatDate(right.valid_from) : "立即"} 至 ${right.valid_until ? formatDate(right.valid_until) : "长期"} · ${validity} · 证据 ${right.evidence_count || 0} 项${right.review_comment ? ` · 复核意见：${right.review_comment}` : ""}`;
    card.firstElementChild.append(info);
    const actions = card.querySelector(".button-row");
    const detailButton = document.createElement("button");
    detailButton.className = "secondary compact";
    detailButton.textContent = "证据与历史";
    detailButton.addEventListener("click", () => openRightEvidence(right.right_id));
    actions.append(detailButton);
  });
};

async function openRightEvidence(rightId) {
  selectedEvidenceRight = state.assetRights.find((item) => item.right_id === rightId) || null;
  if (!selectedEvidenceRight) return;
  $("#rightEvidenceTarget").textContent = `${selectedEvidenceRight.rights_type} · 产物 ${selectedEvidenceRight.artifact_id}`;
  $("#rightTermsValidFrom").value = localDateTimeValue(selectedEvidenceRight.valid_from);
  $("#rightTermsValidUntil").value = localDateTimeValue(selectedEvidenceRight.valid_until);
  const editable = selectedEvidenceRight.status === "pending" && can("edit");
  $("#rightTermsValidFrom").disabled = !editable;
  $("#rightTermsValidUntil").disabled = !editable;
  $("#saveRightTerms").classList.toggle("hidden", !editable);
  $("#rightEvidenceUploadArea").classList.toggle("hidden", !editable);
  $("#rightEvidenceSummary").innerHTML = `
    <div><span>状态</span><strong>${escapeHtml(governanceStatusLabel(selectedEvidenceRight.status))}</strong></div>
    <div><span>有效性</span><strong>${escapeHtml(rightValidityNames[selectedEvidenceRight.validity_state] || selectedEvidenceRight.validity_state)}</strong></div>
    <div><span>声明人</span><code>${escapeHtml(selectedEvidenceRight.declared_by_account_id)}</code></div>
    <div><span>复核人</span><code>${escapeHtml(selectedEvidenceRight.verified_by_account_id || "—")}</code></div>`;
  $("#rightEvidenceDialog").showModal();
  setStatus("正在读取版权证据和历史…");
  try {
    [selectedEvidenceRows, selectedHistoryRows] = await Promise.all([
      api(`/api/v1/admin/governance/rights/${encodeURIComponent(rightId)}/evidence`),
      api(`/api/v1/admin/governance/rights/${encodeURIComponent(rightId)}/history`),
    ]);
    renderRightEvidenceDetails();
    setStatus("");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

function renderRightEvidenceDetails() {
  $("#rightEvidenceList").innerHTML = selectedEvidenceRows.length
    ? selectedEvidenceRows.map((item) => `<div class="evidence-row"><div><strong>${escapeHtml(item.original_filename)}</strong><small>${escapeHtml(item.media_type)} · ${formatBytes(item.size_bytes)} · ${formatDate(item.created_at)}</small><code>${escapeHtml(item.sha256)}</code></div><button type="button" class="secondary compact" data-evidence-download="${escapeHtml(item.evidence_id)}">下载</button></div>`).join("")
    : '<div class="empty-row">尚未上传证据附件</div>';
  $("#rightHistoryList").innerHTML = selectedHistoryRows.length
    ? selectedHistoryRows.map((item) => `<div class="history-row"><div><strong>${escapeHtml(rightHistoryNames[item.event_type] || item.event_type)}</strong><small>${formatDate(item.created_at)} · 操作人 ${escapeHtml(item.actor_account_id)} · 状态 ${escapeHtml(governanceStatusLabel(item.status_snapshot))}</small>${item.comment ? `<p>${escapeHtml(item.comment)}</p>` : ""}</div></div>`).join("")
    : '<div class="empty-row">尚无状态历史</div>';
  $$('[data-evidence-download]').forEach((button) => button.addEventListener("click", () => downloadEvidence(button.dataset.evidenceDownload)));
}

async function saveRightTerms() {
  if (!selectedEvidenceRight) return;
  try {
    await api(`/api/v1/admin/governance/rights/${encodeURIComponent(selectedEvidenceRight.right_id)}/terms`, {
      method: "POST",
      json: {
        valid_from: isoOrNull($("#rightTermsValidFrom").value),
        valid_until: isoOrNull($("#rightTermsValidUntil").value),
      },
    });
    await loadGovernanceDeploymentData();
    await openRightEvidence(selectedEvidenceRight.right_id);
    setStatus("版权授权有效期已更新");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function uploadAdditionalEvidence() {
  if (!selectedEvidenceRight) return;
  const files = [...$("#rightEvidenceFiles").files];
  if (!files.length) {
    setStatus("请选择需要上传的证据附件", true);
    return;
  }
  try {
    await uploadEvidenceFiles(selectedEvidenceRight.right_id, files);
    $("#rightEvidenceFiles").value = "";
    await loadGovernanceDeploymentData();
    await openRightEvidence(selectedEvidenceRight.right_id);
    setStatus("证据附件已上传");
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

async function downloadEvidence(evidenceId) {
  if (!selectedEvidenceRight) return;
  const item = selectedEvidenceRows.find((row) => row.evidence_id === evidenceId);
  if (!item) return;
  try {
    const response = await fetch(item.download_url, {
      headers: { Authorization: `Bearer ${state.token}` },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`证据附件下载失败（${response.status}）`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = item.original_filename;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    setStatus(errorMessage(error), true);
  }
}

ensureRightsEvidenceUi();
