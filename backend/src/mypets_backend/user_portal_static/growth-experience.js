"use strict";

const portalGrowthExperienceState = { value: null, petId: "" };

function installGrowthExperience() {
  const dashboardSection = $("dashboard-section");
  if (dashboardSection && !$("growth-goal-panel")) {
    const panel = experienceNode("article", "panel growth-goal-panel");
    panel.id = "growth-goal-panel";
    panel.hidden = true;
    const heading = experienceNode("div", "section-heading");
    const headingCopy = experienceNode("div");
    headingCopy.append(experienceNode("p", "eyebrow", "GROWTH GOAL"), experienceNode("h2", "", "下一步成长目标"));
    const stage = experienceNode("span", "badge", "成长中");
    stage.id = "growth-current-stage";
    heading.append(headingCopy, stage);

    const summary = experienceNode("div", "growth-goal-summary");
    const copy = experienceNode("div", "growth-goal-copy");
    const headline = experienceNode("strong", "", "继续陪伴即可成长");
    headline.id = "growth-goal-headline";
    const detail = experienceNode("small", "", "正在读取成长目标…");
    detail.id = "growth-goal-detail";
    copy.append(headline, detail);
    const action = experienceNode("button", "secondary", "去玩耍");
    action.id = "growth-goal-action";
    action.type = "button";
    action.addEventListener("click", async () => {
      action.disabled = true;
      try {
        await performPhase1Care("play", action);
      } catch (error) {
        setStatus(globalStatus, error.message, "error");
      } finally {
        renderGrowthExperience();
      }
    });
    summary.append(copy, action);

    const grid = experienceNode("div", "growth-progress-grid");
    [["stage", "阶段进度"], ["level", "成长等级"], ["bond", "羁绊等级"]].forEach(([key, label]) => {
      const item = experienceNode("div", "growth-progress-item");
      const row = experienceNode("div", "growth-progress-label");
      const value = experienceNode("strong", "", "0 / 100");
      value.id = `growth-${key}-label`;
      row.append(experienceNode("span", "", label), value);
      const progress = document.createElement("progress");
      progress.id = `growth-${key}-progress`;
      progress.max = 100;
      progress.value = 0;
      item.append(row, progress);
      grid.append(item);
    });
    panel.append(heading, summary, grid);
    const daily = $("daily-care-panel");
    if (daily?.parentElement === dashboardSection) daily.insertAdjacentElement("afterend", panel);
    else dashboardSection.insertBefore(panel, dashboardSection.querySelector(".two-column"));
  }

  const growthDetail = $("pet-growth-detail");
  if (growthDetail && !$("pet-growth-memory-list")) {
    const wrapper = experienceNode("div", "growth-memory-section separated");
    wrapper.append(experienceNode("h3", "", "成长纪念册"), experienceNode("p", "hint", "升级、羁绊和阶段变化会保存在这里。"));
    const list = experienceNode("div", "growth-memory-list");
    list.id = "pet-growth-memory-list";
    wrapper.append(list);
    growthDetail.parentElement?.append(wrapper);
  }
}

async function refreshGrowthExperience() {
  const selected = selectedPortalPet();
  if (!accessToken || !selected) {
    portalGrowthExperienceState.value = null;
    portalGrowthExperienceState.petId = "";
    renderGrowthExperience();
    return;
  }
  const petId = selected.pet.pet_id;
  portalGrowthExperienceState.value = await api(`/api/v1/pets/${encodeURIComponent(petId)}/growth-experience?limit=30`);
  portalGrowthExperienceState.petId = petId;
  renderGrowthExperience();
}

function setGrowthProgress(id, current, target) {
  const progress = $(id);
  if (!progress) return;
  const safeTarget = Math.max(1, Number(target || 100));
  progress.max = safeTarget;
  progress.value = Math.max(0, Math.min(safeTarget, Number(current || 0)));
}

function renderGrowthExperience() {
  const data = portalGrowthExperienceState.value;
  const panel = $("growth-goal-panel");
  if (panel) panel.hidden = !data;
  if (!data) {
    $("pet-growth-memory-list")?.replaceChildren();
    return;
  }
  const progress = data.progress || {};
  $("growth-current-stage").textContent = progress.current_stage_label || "成长中";
  $("growth-goal-headline").textContent = progress.headline || "继续陪伴即可成长";
  $("growth-goal-detail").textContent = progress.detail || "不同照料方式都会积累成长经验。";
  const action = $("growth-goal-action");
  action.textContent = progress.final_stage ? "继续轻松玩耍" : `去${progress.suggested_action_label || "玩耍"}`;
  const availability = typeof dailyCareAvailability === "function" ? dailyCareAvailability(progress.suggested_action || "play") : null;
  action.disabled = Boolean(availability && !availability.available);
  action.title = availability?.reason || "玩耍能够较快积累成长经验，但不要求连续操作。";

  setGrowthProgress("growth-stage-progress", progress.stage_progress_percent, 100);
  $("growth-stage-label").textContent = progress.final_stage ? "成熟阶段" : `${progress.stage_progress_percent || 0}% · 目标 Lv.${progress.next_stage_target_level}`;
  setGrowthProgress("growth-level-progress", progress.growth_level_current, progress.growth_level_target);
  $("growth-level-label").textContent = `${progress.growth_level_current || 0} / ${progress.growth_level_target || 100} · 还差 ${progress.growth_exp_remaining || 0}`;
  setGrowthProgress("growth-bond-progress", progress.bond_level_current, progress.bond_level_target);
  $("growth-bond-label").textContent = `${progress.bond_level_current || 0} / ${progress.bond_level_target || 80} · 还差 ${progress.bond_exp_remaining || 0}`;
  renderGrowthMemories(data.memories || []);
}

function renderGrowthMemories(memories) {
  const list = $("pet-growth-memory-list");
  if (!list) return;
  list.replaceChildren();
  if (!memories.length) {
    empty(list, "还没有成长纪念，完成一次照料后会逐步积累。");
    return;
  }
  memories.forEach((memory) => {
    const card = experienceNode("article", "growth-memory-card");
    const icon = experienceNode("span", "growth-memory-icon", memory.icon || "🐾");
    const copy = experienceNode("div", "growth-memory-copy");
    const date = new Date(memory.occurred_at);
    const dateText = Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
    copy.append(experienceNode("strong", "", memory.title), experienceNode("p", "", memory.detail), experienceNode("small", "", `${dateText} · ${memory.source_label}`));
    card.append(icon, copy);
    list.append(card);
  });
}

installGrowthExperience();
const baseRefreshPhase1PetDataForGrowth = refreshPhase1PetData;
refreshPhase1PetData = async function refreshPhase1PetDataWithGrowth() {
  await baseRefreshPhase1PetDataForGrowth();
  await refreshGrowthExperience();
};
const baseRenderPortalPhase1ForGrowth = renderPortalPhase1;
renderPortalPhase1 = function renderPortalPhase1WithGrowth() {
  baseRenderPortalPhase1ForGrowth();
  renderGrowthExperience();
};
const baseLogoutForGrowth = logout;
logout = function logoutWithGrowth(message = "", kind = "") {
  portalGrowthExperienceState.value = null;
  portalGrowthExperienceState.petId = "";
  baseLogoutForGrowth(message, kind);
  renderGrowthExperience();
};
if (dashboard) refreshGrowthExperience().catch((error) => setStatus(globalStatus, error.message, "error"));
