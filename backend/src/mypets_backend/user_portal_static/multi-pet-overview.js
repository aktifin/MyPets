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
  timerId: 0,
};

const multiPetPriorityLabels = {
  urgent: "优先关注",
  attention: "需要照料",
  routine: "今日陪伴",
  stable: "状态良好",
  unavailable: "暂不可照料",
};

function ensureMultiPetAfterCarePrompt() {
  let prompt = $("multi-pet-after-care-prompt");
  if (prompt) return prompt;
  const dashboardSection = $("dashboard-section");
  if (!dashboardSection) return null;
  prompt = node("article", "", "panel multi-pet-after-care-prompt");
  prompt.id = "multi-pet-after-care-prompt";
  prompt.hidden = true;
  const copy = node("div", "", "multi-pet-after-care-copy");
  copy.append(
    node("span", "照料完成", "recommendation-label"),
    node("strong", "还有宠物值得看看"),
    node("small", "", "hint"),
  );
  copy.querySelector("strong").id = "multi-pet-after-care-title";
  copy.querySelector("small").id = "multi-pet-after-care-detail";
  const actions = node("div", "", "multi-pet-after-care-actions");
  const later = node("button", "稍后", "secondary");
  later.type = "button";
  later.addEventListener("click", () => {
    prompt.hidden = true;
  });
  const switchButton = node("button", "切换", "");
  switchButton.id = "multi-pet-after-care-switch";
  switchButton.type = "button";
  switchButton.addEventListener("click", async () => {
    const targetPetId = switchButton.dataset.petId || "";
    if (!targetPetId) return;
    switchButton.disabled = true;
    try {
      const target = multiPetOverviewState.items.find(
        (item) => item.pet_id === targetPetId,
      );
      await switchPortalPetForRotation(targetPetId);
      prompt.hidden = true;
      setStatus(
        globalStatus,
        `已切换到 ${target?.name || "下一只宠物"}。`,
        "success",
      );
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      switchButton.disabled = false;
    }
  });
  actions.append(later, switchButton);
  prompt.append(copy, actions);
  const overview = $("multi-pet-overview-panel");
  if (overview) overview.insertAdjacentElement("beforebegin", prompt);
  else dashboardSection.append(prompt);
  return prompt;
}

function showMultiPetAfterCarePrompt() {
  const prompt = ensureMultiPetAfterCarePrompt();
  if (!prompt) return;
  const targetPetId = multiPetOverviewState.nextPetId;
  const target = multiPetOverviewState.items.find(
    (item) => item.pet_id === targetPetId,
  );
  if (!targetPetId || !target) {
    prompt.hidden = true;
    return;
  }
  $("multi-pet-after-care-title").textContent =
    `下一只可以看看 ${target.name}`;
  $("multi-pet-after-care-detail").textContent =
    target.recommendation_detail || "还有一只宠物需要关注。";
  const switchButton = $("multi-pet-after-care-switch");
  switchButton.dataset.petId = targetPetId;
  switchButton.textContent = `切换到 ${target.name}`;
  prompt.hidden = false;
  prompt.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

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
    node(
      "p",
      "真正需要关注的宠物排在前面，稳定宠物不会制造额外任务。",
      "hint",
    ),
  );
  const controls = node("div", "", "multi-pet-controls");
  const summary = node("span", "0 只宠物", "badge");
  summary.id = "multi-pet-overview-summary";
  const nextButton = node("button", "下一只需要关注", "");
  nextButton.id = "multi-pet-next-button";
  nextButton.type = "button";
  nextButton.addEventListener("click", async () => {
    const targetPetId = multiPetOverviewState.nextPetId;
    if (!targetPetId) return;
    const target = multiPetOverviewState.items.find(
      (item) => item.pet_id === targetPetId,
    );
    nextButton.disabled = true;
    try {
      await switchPortalPetForRotation(targetPetId);
      setStatus(
        globalStatus,
        `已切换到 ${target?.name || "下一只宠物"}。`,
        "success",
      );
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
  ensureMultiPetAfterCarePrompt();
  return panel;
}

async function switchPortalPetForRotation(petId) {
  if (!petId || dashboard?.selected_pet_id === petId) return;
  dashboard = await api("/api/v1/portal/preference", {
    method: "PATCH",
    json: { selected_pet_id: petId },
  });
  await refreshPhase1PetData("multi-pet-switch");
  renderDashboard();
  renderPortalPhase1({ reason: "multi-pet-switch" });
  await refreshMultiPetOverview();
}

async function careForOverviewPet(item, button) {
  if (!item.recommended_action || !item.action_available) return;
  if (dashboard?.selected_pet_id !== item.pet_id) {
    await switchPortalPetForRotation(item.pet_id);
  }
  await performPhase1Care(item.recommended_action, button);
}

function effectiveMultiPetNextId() {
  const selectedPetId = dashboard?.selected_pet_id || multiPetOverviewState.currentPetId;
  if (multiPetOverviewState.nextPetId !== selectedPetId) {
    return multiPetOverviewState.nextPetId;
  }
  return (
    multiPetOverviewState.items.find(
      (item) => item.pet_id !== selectedPetId && item.priority !== "stable",
    )?.pet_id || null
  );
}

function renderMultiPetOverview() {
  ensureMultiPetOverviewPanel();
  const panel = $("multi-pet-overview-panel");
  if (panel) panel.hidden = !accessToken || multiPetOverviewState.totalCount < 2;

  const selectedPetId = dashboard?.selected_pet_id || multiPetOverviewState.currentPetId;
  const nextPetId = effectiveMultiPetNextId();
  const summary = $("multi-pet-overview-summary");
  if (summary) {
    summary.textContent = multiPetOverviewState.needsAttentionCount
      ? `${multiPetOverviewState.totalCount} 只 · ${multiPetOverviewState.needsAttentionCount} 只需关注`
      : `${multiPetOverviewState.totalCount} 只 · 当前都稳定`;
    summary.classList.toggle("urgent", multiPetOverviewState.urgentCount > 0);
  }
  const nextButton = $("multi-pet-next-button");
  if (nextButton) {
    nextButton.disabled = !nextPetId;
    nextButton.textContent = nextPetId
      ? "切换下一只需要关注"
      : "暂无其他需关注宠物";
  }

  const list = $("multi-pet-overview-list");
  if (!list) return;
  list.replaceChildren();
  if (!multiPetOverviewState.items.length) {
    empty(list, "还没有可显示的宠物。");
    return;
  }

  multiPetOverviewState.items.forEach((item) => {
    const current = item.pet_id === selectedPetId;
    const card = node(
      "article",
      "",
      `multi-pet-card priority-${item.priority}${current ? " current" : ""}`,
    );
    const header = node("div", "", "multi-pet-card-header");
    const identity = node("div");
    identity.append(
      node("strong", item.name),
      node(
        "span",
        `Lv.${item.growth_level} · 羁绊 Lv.${item.bond_level}`,
        "hint",
      ),
    );
    const badge = node(
      "span",
      multiPetPriorityLabels[item.priority] || item.priority,
      "multi-pet-priority",
    );
    header.append(identity, badge);

    const status = node("p", item.status_summary, "multi-pet-status");
    const detail = node("p", item.recommendation_detail, "hint");
    const task = node(
      "div",
      `今日任务 ${item.daily_completed_tasks}/${item.daily_total_tasks}${
        item.daily_all_completed ? " · 已完成" : ""
      }`,
      "multi-pet-task",
    );
    const progress = document.createElement("progress");
    progress.className = "multi-pet-progress";
    progress.max = Math.max(1, Number(item.daily_total_tasks));
    progress.value = Math.max(0, Number(item.daily_completed_tasks));
    progress.setAttribute("aria-label", `${item.name} 今日任务进度`);

    const actions = node("div", "", "multi-pet-actions");
    if (!current) {
      actions.append(
        actionButton(
          "切换到它",
          async () => {
            await switchPortalPetForRotation(item.pet_id);
            setStatus(globalStatus, `已切换到 ${item.name}。`, "success");
          },
          "secondary",
        ),
      );
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

function resetMultiPetOverview() {
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
  const prompt = $("multi-pet-after-care-prompt");
  if (prompt) prompt.hidden = true;
  renderMultiPetOverview();
}

async function refreshMultiPetOverview() {
  if (!accessToken) {
    resetMultiPetOverview();
    return;
  }
  const offset = new Date().getTimezoneOffset();
  const payload = await api(
    `/api/v1/multi-pet-overview?timezone_offset_minutes=${encodeURIComponent(offset)}`,
  );
  multiPetOverviewState.currentPetId = payload.current_pet_id || null;
  multiPetOverviewState.nextPetId = payload.next_pet_id || null;
  multiPetOverviewState.totalCount = Number(payload.total_count || 0);
  multiPetOverviewState.needsAttentionCount = Number(
    payload.needs_attention_count || 0,
  );
  multiPetOverviewState.urgentCount = Number(payload.urgent_count || 0);
  multiPetOverviewState.careReadyCount = Number(payload.care_ready_count || 0);
  multiPetOverviewState.completedTodayCount = Number(
    payload.completed_today_count || 0,
  );
  multiPetOverviewState.items = Array.isArray(payload.items) ? payload.items : [];
  renderMultiPetOverview();
}

function startMultiPetPolling() {
  if (multiPetOverviewState.timerId) return;
  multiPetOverviewState.timerId = window.setInterval(() => {
    if (!accessToken) return;
    refreshMultiPetOverview().catch(() => {});
  }, 60000);
}

function stopMultiPetPolling() {
  if (!multiPetOverviewState.timerId) return;
  window.clearInterval(multiPetOverviewState.timerId);
  multiPetOverviewState.timerId = 0;
}

portalRuntime.registerFeature({
  id: "multi-pet-overview",
  label: "多宠状态总览",
  order: 180,
  mount: () => {
    ensureMultiPetOverviewPanel();
    renderMultiPetOverview();
  },
  onRefreshComplete: async () => {
    await refreshMultiPetOverview();
    startMultiPetPolling();
  },
  onDashboardRenderComplete: renderMultiPetOverview,
  onPhase1RenderComplete: renderMultiPetOverview,
  onSectionEnter: ({ sectionId, source }) => {
    if (
      sectionId === "dashboard-section"
      && source !== "startup"
      && source !== "anonymous"
      && accessToken
    ) {
      return refreshMultiPetOverview();
    }
  },
  onCareComplete: async () => {
    await refreshMultiPetOverview();
    showMultiPetAfterCarePrompt();
  },
  onRealtime: () => {
    const section = $("dashboard-section");
    if (accessToken && section && !section.hidden) {
      return refreshMultiPetOverview();
    }
  },
  onLogout: () => {
    stopMultiPetPolling();
    resetMultiPetOverview();
  },
});
