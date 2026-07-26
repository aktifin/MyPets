"use strict";

const portalDailyCareState = {
  summary: null,
  petId: "",
  clockOffsetMs: 0,
};

function installDailyCarePanel() {
  const dashboardSection = $("dashboard-section");
  if (!dashboardSection || $("daily-care-panel")) return;

  const panel = experienceNode("article", "panel daily-care-panel");
  panel.id = "daily-care-panel";
  panel.hidden = true;

  const heading = experienceNode("div", "section-heading daily-care-heading");
  const copy = experienceNode("div");
  copy.append(
    experienceNode("p", "eyebrow", "TODAY CARE"),
    experienceNode("h2", "", "今天还需要做什么"),
  );
  const streak = experienceNode("span", "badge daily-care-streak", "连续 0 天");
  streak.id = "daily-care-streak";
  heading.append(copy, streak);

  const overview = experienceNode("div", "daily-care-overview");
  const progressCopy = experienceNode("div", "daily-care-progress-copy");
  progressCopy.append(
    experienceNode("strong", "", "今日任务 0 / 3"),
    experienceNode("small", "", "完成后获得今日陪伴徽章"),
  );
  progressCopy.firstElementChild.id = "daily-care-progress-label";
  progressCopy.lastElementChild.id = "daily-care-progress-detail";
  const progress = document.createElement("progress");
  progress.id = "daily-care-progress";
  progress.max = 3;
  progress.value = 0;
  overview.append(progressCopy, progress);

  const taskList = experienceNode("div", "daily-care-task-list");
  taskList.id = "daily-care-task-list";
  const footer = experienceNode("div", "daily-care-footer");
  footer.id = "daily-care-footer";
  panel.append(heading, overview, taskList, footer);

  const firstTwoColumn = dashboardSection.querySelector(".two-column");
  dashboardSection.insertBefore(panel, firstTwoColumn || null);
}

function dailyCareAvailability(action) {
  const summary = portalDailyCareState.summary;
  if (!summary) return null;
  const raw = (summary.actions || []).find((item) => item.action === action);
  if (!raw) return null;
  const effectiveNow = Date.now() + portalDailyCareState.clockOffsetMs;
  const nextAt = raw.next_available_at ? Date.parse(raw.next_available_at) : Number.NaN;
  const remaining = Number.isNaN(nextAt)
    ? Math.max(0, Number(raw.remaining_seconds || 0))
    : Math.max(0, Math.ceil((nextAt - effectiveNow) / 1000));
  const selected = selectedPortalPet();
  if (!selected || selected.pet.presence !== "home") {
    return { ...raw, available: false, remaining_seconds: 0, reason: "宠物串门期间不能照料，请先查看串门状态。" };
  }
  if (!new Set(["owner", "co_owner", "caregiver"]).has(selected.relation.role)) {
    return { ...raw, available: false, remaining_seconds: 0, reason: "当前关系仅可查看宠物状态，不能执行照料。" };
  }
  if (summary.daily_limit_reached) {
    return { ...raw, available: false, remaining_seconds: 0, reason: `今天已完成 ${summary.daily_limit} 次照料，明天可以继续。` };
  }
  return {
    ...raw,
    available: remaining <= 0,
    remaining_seconds: remaining,
    reason: remaining > 0 ? `${raw.label}刚刚完成，${remaining} 秒后可再次操作。` : "现在可以操作。",
  };
}

function syncDailyCareButtons() {
  document.querySelectorAll("[data-care-action]").forEach((button) => {
    const availability = dailyCareAvailability(button.dataset.careAction);
    if (!availability) return;
    button.disabled = !availability.available;
    button.title = availability.reason;
    button.setAttribute("aria-label", availability.available
      ? `${availability.label}，现在可以操作`
      : `${availability.label}，${availability.reason}`);
  });
}

function renderDailyCarePanel() {
  const panel = $("daily-care-panel");
  if (!panel) return;
  const summary = portalDailyCareState.summary;
  panel.hidden = !summary;
  if (!summary) {
    syncDailyCareButtons();
    return;
  }

  $("daily-care-streak").textContent = `连续 ${summary.streak_days} 天`;
  $("daily-care-progress-label").textContent = `今日任务 ${summary.completed_tasks} / ${summary.total_tasks}`;
  $("daily-care-progress-detail").textContent = summary.reward_detail;
  const progress = $("daily-care-progress");
  progress.max = Math.max(1, Number(summary.total_tasks || 3));
  progress.value = Number(summary.completed_tasks || 0);

  const taskList = $("daily-care-task-list");
  taskList.replaceChildren();
  (summary.tasks || []).forEach((task) => {
    const card = experienceNode("div", task.completed ? "daily-care-task completed" : "daily-care-task");
    const icon = experienceNode("span", "daily-care-task-icon", task.completed ? "✓" : `${task.current}/${task.target}`);
    const taskCopy = experienceNode("span", "daily-care-task-copy");
    taskCopy.append(experienceNode("strong", "", task.title), experienceNode("small", "", task.detail));
    card.append(icon, taskCopy);
    taskList.append(card);
  });

  const footer = $("daily-care-footer");
  footer.replaceChildren();
  const reward = experienceNode("div", summary.all_tasks_completed ? "daily-care-reward earned" : "daily-care-reward");
  reward.append(
    experienceNode("strong", "", summary.reward_title),
    experienceNode("small", "", summary.all_tasks_completed ? "今天的陪伴任务已经完成。" : "完成全部任务后自动点亮。"),
  );
  const limit = experienceNode(
    "span",
    "daily-care-limit",
    summary.daily_limit_reached
      ? `今日 ${summary.daily_limit} 次上限已用完`
      : `今日已照料 ${summary.care_count} 次 · 还可 ${summary.daily_remaining} 次`,
  );
  footer.append(reward, limit);

  if ($("dashboard-today-actions")) $("dashboard-today-actions").textContent = String(summary.care_count);
  syncDailyCareButtons();
}

async function refreshDailyCareSummary() {
  const selected = selectedPortalPet();
  if (!accessToken || !selected) {
    portalDailyCareState.summary = null;
    portalDailyCareState.petId = "";
    renderDailyCarePanel();
    return;
  }
  const petId = selected.pet.pet_id;
  const offset = new Date().getTimezoneOffset();
  const summary = await api(`/api/v1/pets/${encodeURIComponent(petId)}/daily-care?timezone_offset_minutes=${offset}`);
  portalDailyCareState.summary = summary;
  portalDailyCareState.petId = petId;
  portalDailyCareState.clockOffsetMs = Date.parse(summary.server_time) - Date.now();
  renderDailyCarePanel();
}

installDailyCarePanel();

const baseRefreshPhase1PetDataForDailyCare = refreshPhase1PetData;
refreshPhase1PetData = async function refreshPhase1PetDataWithDailyCare() {
  await baseRefreshPhase1PetDataForDailyCare();
  await refreshDailyCareSummary();
};

const baseRenderPortalPhase1ForDailyCare = renderPortalPhase1;
renderPortalPhase1 = function renderPortalPhase1WithDailyCare() {
  baseRenderPortalPhase1ForDailyCare();
  renderDailyCarePanel();
};

const baseRecommendedCareForDailyCare = recommendedCare;
recommendedCare = function recommendedCareWithAvailability(selected) {
  const suggestion = baseRecommendedCareForDailyCare(selected);
  if (!suggestion?.action) return suggestion;
  const availability = dailyCareAvailability(suggestion.action);
  return availability && !availability.available
    ? { ...suggestion, detail: availability.reason, availability }
    : { ...suggestion, availability };
};

const baseRenderCareRecommendationForDailyCare = renderCareRecommendation;
renderCareRecommendation = function renderCareRecommendationWithDailyCare() {
  baseRenderCareRecommendationForDailyCare();
  const recommendation = $("dashboard-care-recommendation");
  const button = recommendation?.querySelector("button");
  const suggestion = recommendedCare(selectedPortalPet());
  if (!button || !suggestion?.action || !suggestion.availability) return;
  button.disabled = !suggestion.availability.available;
  button.title = suggestion.availability.reason;
  if (!suggestion.availability.available && suggestion.availability.remaining_seconds > 0) {
    button.textContent = `${suggestion.availability.remaining_seconds} 秒后可${careActionLabel(suggestion.action)}`;
  }
};

const baseRenderNextStepsForDailyCare = renderNextSteps;
renderNextSteps = function renderNextStepsWithDailyCare() {
  baseRenderNextStepsForDailyCare();
  const container = $("next-step-list");
  const summary = portalDailyCareState.summary;
  if (!container || !summary || summary.all_tasks_completed) return;
  const remaining = Math.max(0, summary.total_tasks - summary.completed_tasks);
  const card = experienceNode("button", "next-step-card emphasis");
  card.type = "button";
  const copy = experienceNode("span", "next-step-copy");
  copy.append(
    experienceNode("strong", "", `今天还有 ${remaining} 项养宠任务`),
    experienceNode("small", "", "完成后点亮今日陪伴徽章，并延续连续陪伴记录。"),
  );
  card.append(copy, experienceNode("span", "next-step-action", "去完成"));
  card.addEventListener("click", () => $("daily-care-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }));
  container.prepend(card);
};

const basePerformPhase1CareForDailyCare = performPhase1Care;
performPhase1Care = async function performPhase1CareWithDailyCare(action, button) {
  await basePerformPhase1CareForDailyCare(action, button);
  renderDailyCarePanel();
  const summary = portalDailyCareState.summary;
  if (!summary) return;
  const message = summary.all_tasks_completed
    ? `${careActionLabel(action)}完成，今日陪伴徽章已点亮，连续 ${summary.streak_days} 天。`
    : `${careActionLabel(action)}完成，今日任务 ${summary.completed_tasks}/${summary.total_tasks}。`;
  setStatus(globalStatus, message, "success");
};

const baseLogoutForDailyCare = logout;
logout = function logoutWithDailyCare(message = "", kind = "") {
  portalDailyCareState.summary = null;
  portalDailyCareState.petId = "";
  baseLogoutForDailyCare(message, kind);
  renderDailyCarePanel();
};

window.setInterval(() => {
  if (!portalDailyCareState.summary) return;
  syncDailyCareButtons();
  renderCareRecommendation();
}, 1000);

if (dashboard) {
  refreshDailyCareSummary().catch((error) => setStatus(globalStatus, error.message, "error"));
}
