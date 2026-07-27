"use strict";

const multiPetOverviewState = {
  currentPetId: null,
  nextPetId: null,
  totalCount: 0,
  needsAttentionCount: 0,
  urgentCount: 0,
  careReadyCount: 0,
  completedTodayCount: 0,
  items: [],
};

const multiPetPriorityLabels = {
  urgent: "优先关注",
  attention: "需要照料",
  routine: "今日陪伴",
  stable: "状态良好",
  unavailable: "暂不可照料",
};

function ensureMultiPetOverviewPanel() {
  let panel = $("multi-pet-overview-panel");
  if (panel) return panel;
  const dashboardSection = $("dashboard-section");
  if (!dashboardSection) return null;

  panel = node("article", "", "panel multi-pet-overview-panel");
  panel.id = "multi-pet-overview-panel";
  const heading = node("div", "", "section-heading multi-pet-heading");
  const copy = node("div");
  copy.append(
    node("p", "MULTI-PET CARE", "eyebrow"),
    node("h2", "多宠状态总览"),
    node("p", "真正需要关注的宠物排在前面，稳定宠物不会制造额外任务。", "hint"),
  );
  const controls = node("div", "", "multi-pet-controls");
  const summary = node("span", "0 只宠物", "badge");
  summary.id = "multi-pet-overview-summary";
  const nextButton = node("button", "下一只需要照料", "");
  nextButton.id = "multi-pet-next-button";
  nextButton.type = "button";
  nextButton.addEventListener("click", async () => {
    if (!multiPetOverviewState.nextPetId) return;
    nextButton.disabled = true;
    try {
      await switchPortalPetForRotation(multiPetOverviewState.nextPetId);
      const pet = multiPetOverviewState.items.find((item) => item.pet_id === multiPetOverviewState.nextPetId);
      setStatus(globalStatus, `已切换到 ${pet?.name || "下一只宠物"}。`, "success");
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      nextButton.disabled = false;
    }
  });
  controls.append(summary, nextButton);
  heading.append(copy, controls);

  const list = node("div", "", "multi-pet-overview-list");
  list.id = "multi-pet-overview-list";
  panel.append(heading, list);

  const pendingPanel = $("pending-items-panel");
  if (pendingPanel) pendingPanel.insertAdjacentElement("afterend", panel);
  else dashboardSection.append(panel);
  return panel;
}

async function switchPortalPetForRotation(petId) {
  if (!petId || dashboard?.selected_pet_id === petId) return;
  dashboard = await api("/api/v1/portal/preference", {
    method: "PATCH",
    json: { selected_pet_id: petId },
  });
  await refreshPhase1PetData();
  renderDashboard();
  renderPortalPhase1();
  await refreshMultiPetOverview();
}

async function careForOverviewPet(item, button) {
  if (!item.recommended_action || !item.action_available) return;
  if (dashboard?.selected_pet_id !== item.pet_id) {
    await switchPortalPetForRotation(item.pet_id);
  }
  await performPhase1Care(item.recommended_action, button);
  await refreshMultiPetOverview();
}

function renderMultiPetOverview() {
  ensureMultiPetOverviewPanel();
  const panel = $("multi-pet-overview-panel");
  if (panel) panel.hidden = !accessToken || multiPetOverviewState.totalCount < 2;

  const summary = $("multi-pet-overview-summary");
  if (summary) {
    summary.textContent = multiPetOverviewState.needsAttentionCount
      ? `${multiPetOverviewState.totalCount} 只 · ${multiPetOverviewState.needsAttentionCount} 只需关注`
      : `${multiPetOverviewState.totalCount} 只 · 当前都稳定`;
    summary.classList.toggle("urgent", multiPetOverviewState.urgentCount > 0);
  }
  const nextButton = $("multi-pet-next-button");
  if (nextButton) {
    nextButton.disabled = !multiPetOverviewState.nextPetId;
    nextButton.textContent = multiPetOverviewState.nextPetId
      ? "切换下一只需要照料"
      : "暂无其他待照料宠物";
  }

  const list = $("multi-pet-overview-list");
  if (!list) return;
  list.replaceChildren();
  if (!multiPetOverviewState.items.length) {
    empty(list, "还没有可显示的宠物。");
    return;
  }

  multiPetOverviewState.items.forEach((item) => {
    const card = node("article", "", `multi-pet-card priority-${item.priority}${item.current ? " current" : ""}`);
    const header = node("div", "", "multi-pet-card-header");
    const identity = node("div");
    identity.append(
      node("strong", item.name),
      node("span", `Lv.${item.growth_level} · 羁绊 Lv.${item.bond_level}`, "hint"),
    );
    const badge = node("span", multiPetPriorityLabels[item.priority] || item.priority, "multi-pet-priority");
    header.append(identity, badge);

    const status = node("p", item.status_summary, "multi-pet-status");
    const detail = node("p", item.recommendation_detail, "hint");
    const task = node(
      "div",
      `今日任务 ${item.daily_completed_tasks}/${item.daily_total_tasks}${item.daily_all_completed ? " · 已完成" : ""}`,
      "multi-pet-task",
    );
    const progress = node("div", "", "multi-pet-progress");
    const progressValue = node("span");
    progressValue.style.setProperty(
      "--multi-pet-progress",
      `${Math.min(100, Math.round((Number(item.daily_completed_tasks) / Math.max(1, Number(item.daily_total_tasks))) * 100))}%`,
    );
    progress.append(progressValue);

    const actions = node("div", "", "multi-pet-actions");
    if (!item.current) {
      actions.append(actionButton("切换到它", async () => {
        await switchPortalPetForRotation(item.pet_id);
        setStatus(globalStatus, `已切换到 ${item.name}。`, "success");
      }, "secondary"));
    } else {
      actions.append(node("span", "当前宠物", "current-pet-label"));
    }
    if (item.recommended_action && item.can_care) {
      const careButton = actionButton(item.recommended_action_label, async () => {
        await careForOverviewPet(item, careButton);
      });
      careButton.disabled = !item.action_available;
      careButton.title = item.action_reason || item.recommendation_detail;
      actions.append(careButton);
    } else if (item.priority === "unavailable") {
      actions.append(node("span", item.action_reason || "暂不可照料", "hint"));
    }

    card.append(header, status, detail, task, progress, actions);
    list.append(card);
  });
}

async function refreshMultiPetOverview() {
  if (!accessToken) {
    Object.assign(multiPetOverviewState, {
      currentPetId: null,
      nextPetId: null,
      totalCount: 0,
      needsAttentionCount: 0,
      urgentCount: 0,
      careReadyCount: 0,
      completedTodayCount: 0,
      items: [],
    });
    renderMultiPetOverview();
    return;
  }
  const offset = new Date().getTimezoneOffset();
  const payload = await api(`/api/v1/multi-pet-overview?timezone_offset_minutes=${encodeURIComponent(offset)}`);
  multiPetOverviewState.currentPetId = payload.current_pet_id || null;
  multiPetOverviewState.nextPetId = payload.next_pet_id || null;
  multiPetOverviewState.totalCount = Number(payload.total_count || 0);
  multiPetOverviewState.needsAttentionCount = Number(payload.needs_attention_count || 0);
  multiPetOverviewState.urgentCount = Number(payload.urgent_count || 0);
  multiPetOverviewState.careReadyCount = Number(payload.care_ready_count || 0);
  multiPetOverviewState.completedTodayCount = Number(payload.completed_today_count || 0);
  multiPetOverviewState.items = Array.isArray(payload.items) ? payload.items : [];
  renderMultiPetOverview();
}

const baseRefreshAllForMultiPetOverview = refreshAll;
refreshAll = async function refreshAllWithMultiPetOverview() {
  await baseRefreshAllForMultiPetOverview();
  await refreshMultiPetOverview();
};

ensureMultiPetOverviewPanel();
window.setInterval(() => {
  if (accessToken) refreshMultiPetOverview().catch(() => {});
}, 60000);
