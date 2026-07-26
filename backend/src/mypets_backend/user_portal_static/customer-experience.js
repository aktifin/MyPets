"use strict";

const portalExperienceState = {
  presets: [],
  selectedPresetId: "",
  autoOpened: false,
  addingPet: false,
};

const ONBOARDING_DISMISSED_KEY = "mypets.portal.onboarding-dismissed";

function experienceNode(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function currentExperiencePreset() {
  return portalExperienceState.presets.find((item) => item.preset_id === portalExperienceState.selectedPresetId) || null;
}

function activatePortalSection(sectionId) {
  document.querySelectorAll(".workspace").forEach((section) => {
    section.hidden = section.id !== sectionId;
  });
  document.querySelectorAll(".main-tab[data-section]").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === sectionId);
  });
  const more = $("portal-more-navigation");
  if (more) more.open = false;
  const target = $(sectionId);
  if (target) target.focus({ preventScroll: true });
}

function installCustomerNavigation() {
  const navigation = document.querySelector(".main-tabs");
  if (!navigation || $("portal-more-navigation")) return;

  const labels = {
    "dashboard-section": "养宠首页",
    "pets-section": "我的宠物",
    "friends-section": "好友",
    "messages-section": "消息",
  };
  Object.entries(labels).forEach(([sectionId, label]) => {
    const button = navigation.querySelector(`[data-section="${sectionId}"]`);
    if (button) button.textContent = label;
  });

  const more = document.createElement("details");
  more.id = "portal-more-navigation";
  more.className = "portal-more-navigation";
  const summary = document.createElement("summary");
  summary.className = "main-tab portal-more-summary";
  summary.textContent = "更多";
  const menu = experienceNode("div", "portal-more-menu");
  ["reminders-section", "visits-section", "account-section"].forEach((sectionId) => {
    const button = navigation.querySelector(`[data-section="${sectionId}"]`);
    if (button) {
      button.classList.add("portal-more-item");
      menu.append(button);
    }
  });
  more.append(summary, menu);
  navigation.append(more);

  navigation.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-section]");
    if (!button) return;
    window.setTimeout(() => activatePortalSection(button.dataset.section), 0);
  }, true);
}

function installPetSwitcher() {
  const sessionBox = document.querySelector(".session-box");
  if (!sessionBox || $("portal-pet-switcher-wrap")) return;

  const wrap = experienceNode("label", "portal-pet-switcher-wrap");
  wrap.id = "portal-pet-switcher-wrap";
  wrap.hidden = true;
  wrap.append(experienceNode("span", "portal-switcher-label", "当前宠物"));
  const select = document.createElement("select");
  select.id = "portal-pet-switcher";
  select.setAttribute("aria-label", "切换当前宠物");
  wrap.append(select);

  const addButton = experienceNode("button", "secondary portal-add-pet", "添加宠物");
  addButton.id = "portal-add-pet";
  addButton.type = "button";
  addButton.hidden = true;
  addButton.addEventListener("click", () => openPetOnboarding(true));

  select.addEventListener("change", async () => {
    if (!select.value || !dashboard || select.value === dashboard.selected_pet_id) return;
    select.disabled = true;
    try {
      dashboard = await api("/api/v1/portal/preference", {
        method: "PATCH",
        json: { selected_pet_id: select.value },
      });
      await refreshPhase1PetData();
      renderDashboard();
      renderPortalPhase1();
      setStatus(globalStatus, `已切换到 ${selectedPortalPet()?.pet.name || "当前宠物"}。`, "success");
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      select.disabled = false;
    }
  });

  sessionBox.insertBefore(wrap, logoutButton);
  sessionBox.insertBefore(addButton, logoutButton);
}

function installSimplifiedPetCreation() {
  const legacyForm = $("create-pet-form");
  if (!legacyForm || $("simple-pet-create")) return;
  legacyForm.hidden = true;
  legacyForm.setAttribute("aria-hidden", "true");

  const panel = experienceNode("div", "simple-pet-create");
  panel.id = "simple-pet-create";
  const copy = experienceNode("div", "simple-pet-create-copy");
  copy.append(
    experienceNode("strong", "", "选择形象、填写名字，就可以开始养宠"),
    experienceNode("p", "hint", "不再需要填写模板 ID 或版本号，系统会自动选择可用版本。"),
  );
  const button = experienceNode("button", "", "添加一只宠物");
  button.type = "button";
  button.addEventListener("click", () => openPetOnboarding(true));
  panel.append(copy, button);
  legacyForm.parentElement.append(panel);
}

function installDashboardGuidance() {
  const content = $("dashboard-pet-content");
  if (content && !$("dashboard-care-recommendation")) {
    const recommendation = experienceNode("section", "care-recommendation");
    recommendation.id = "dashboard-care-recommendation";
    recommendation.append(
      experienceNode("div", "care-recommendation-copy"),
      experienceNode("button", "care-recommendation-action"),
    );
    content.append(recommendation);
    recommendation.querySelector("button").type = "button";
  }

  const dashboardSection = $("dashboard-section");
  if (dashboardSection && !$("customer-next-steps")) {
    const panel = experienceNode("article", "panel customer-next-steps");
    panel.id = "customer-next-steps";
    const heading = experienceNode("div", "section-heading");
    const headingCopy = experienceNode("div");
    headingCopy.append(
      experienceNode("p", "eyebrow", "NEXT BEST ACTION"),
      experienceNode("h2", "", "接下来可以做什么"),
    );
    heading.append(headingCopy);
    const list = experienceNode("div", "next-step-list");
    list.id = "next-step-list";
    panel.append(heading, list);
    dashboardSection.append(panel);
  }

  const emptyState = $("dashboard-empty-pet");
  if (emptyState && !$("dashboard-first-pet-button")) {
    emptyState.textContent = "先领养第一只宠物，之后的照料、成长、好友和串门功能才会开始。";
    const button = experienceNode("button", "dashboard-first-pet-button", "领养第一只宠物");
    button.id = "dashboard-first-pet-button";
    button.type = "button";
    button.addEventListener("click", () => openPetOnboarding(false));
    emptyState.append(button);
  }
}

function installPetOnboarding() {
  if ($("pet-onboarding-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "pet-onboarding-dialog";
  dialog.className = "pet-onboarding-dialog";
  dialog.innerHTML = `
    <form id="pet-onboarding-form" method="dialog">
      <div class="onboarding-header">
        <div><p class="eyebrow">START CARING</p><h2 id="pet-onboarding-title">领养第一只宠物</h2></div>
        <button id="pet-onboarding-close" class="ghost compact" type="button" aria-label="关闭">稍后</button>
      </div>
      <ol class="onboarding-steps" aria-label="领养步骤">
        <li id="onboarding-step-indicator-1" class="active">1 选择形象</li>
        <li id="onboarding-step-indicator-2">2 名字与性格</li>
      </ol>
      <section id="pet-onboarding-step-1">
        <p class="hint">选择一个喜欢的形象。版本和素材由系统自动处理。</p>
        <div id="pet-preset-grid" class="pet-preset-grid"></div>
        <div class="dialog-actions"><button id="pet-onboarding-next" type="button" disabled>下一步</button></div>
      </section>
      <section id="pet-onboarding-step-2" hidden>
        <div id="selected-preset-summary" class="selected-preset-summary"></div>
        <label>给它起个名字<input id="onboarding-pet-name" required maxlength="80" autocomplete="off" placeholder="例如：团子"></label>
        <label>选择性格<select id="onboarding-pet-personality"></select></label>
        <div class="dialog-actions">
          <button id="pet-onboarding-back" type="button" class="secondary">上一步</button>
          <button id="pet-onboarding-create" type="submit">开始养宠</button>
        </div>
      </section>
      <p id="pet-onboarding-status" class="status" aria-live="polite"></p>
    </form>`;
  document.body.append(dialog);

  $("pet-onboarding-close").addEventListener("click", () => {
    if (!dashboard?.pets.length) sessionStorage.setItem(ONBOARDING_DISMISSED_KEY, "1");
    dialog.close();
  });
  $("pet-onboarding-next").addEventListener("click", () => showOnboardingStep(2));
  $("pet-onboarding-back").addEventListener("click", () => showOnboardingStep(1));
  $("pet-onboarding-form").addEventListener("submit", createPetFromOnboarding);
}

function showOnboardingStep(step) {
  $("pet-onboarding-step-1").hidden = step !== 1;
  $("pet-onboarding-step-2").hidden = step !== 2;
  $("onboarding-step-indicator-1").classList.toggle("active", step === 1);
  $("onboarding-step-indicator-2").classList.toggle("active", step === 2);
  if (step === 2) {
    const preset = currentExperiencePreset();
    const summary = $("selected-preset-summary");
    summary.replaceChildren();
    if (preset) {
      summary.append(
        experienceNode("span", "selected-preset-icon", preset.icon),
        experienceNode("div", "", preset.display_name),
      );
    }
    $("onboarding-pet-name").focus();
  }
}

async function loadPetPresets() {
  if (portalExperienceState.presets.length) return;
  portalExperienceState.presets = await api("/api/v1/portal/pet-presets");
  renderPetPresets();
}

function renderPetPresets() {
  const grid = $("pet-preset-grid");
  grid.replaceChildren();
  portalExperienceState.presets.forEach((preset) => {
    const button = experienceNode("button", "pet-preset-card");
    button.type = "button";
    button.dataset.presetId = preset.preset_id;
    button.append(
      experienceNode("span", "pet-preset-icon", preset.icon),
      experienceNode("strong", "", preset.display_name),
      experienceNode("small", "", preset.description),
    );
    button.addEventListener("click", () => {
      portalExperienceState.selectedPresetId = preset.preset_id;
      grid.querySelectorAll(".pet-preset-card").forEach((item) => {
        item.classList.toggle("selected", item.dataset.presetId === preset.preset_id);
      });
      $("pet-onboarding-next").disabled = false;
    });
    grid.append(button);
  });
}

function populateOnboardingPersonalities() {
  const select = $("onboarding-pet-personality");
  select.replaceChildren();
  const personalities = dashboard?.personalities?.length
    ? dashboard.personalities
    : ["balanced", "playful", "gentle", "energetic", "sleepy", "curious"];
  personalities.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = personalityLabel(value);
    select.append(option);
  });
}

async function openPetOnboarding(addingPet) {
  if (!accessToken || !dashboard) {
    setStatus(authStatus, "请先登录后再添加宠物。", "error");
    return;
  }
  portalExperienceState.addingPet = addingPet;
  portalExperienceState.selectedPresetId = "";
  $("pet-onboarding-title").textContent = addingPet ? "添加一只宠物" : "领养第一只宠物";
  $("onboarding-pet-name").value = "";
  $("pet-onboarding-next").disabled = true;
  setStatus($("pet-onboarding-status"), "");
  populateOnboardingPersonalities();
  showOnboardingStep(1);
  try {
    await loadPetPresets();
    renderPetPresets();
    const dialog = $("pet-onboarding-dialog");
    if (!dialog.open) dialog.showModal();
  } catch (error) {
    setStatus(globalStatus, `宠物形象加载失败：${error.message}`, "error");
  }
}

async function createPetFromOnboarding(event) {
  event.preventDefault();
  const preset = currentExperiencePreset();
  const name = $("onboarding-pet-name").value.trim();
  if (!preset) {
    setStatus($("pet-onboarding-status"), "请先选择宠物形象。", "error");
    showOnboardingStep(1);
    return;
  }
  if (!name) {
    setStatus($("pet-onboarding-status"), "请给宠物起一个名字。", "error");
    return;
  }
  const createButton = $("pet-onboarding-create");
  createButton.disabled = true;
  setStatus($("pet-onboarding-status"), "正在创建宠物…");
  try {
    const random = typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    const pet = await api("/api/v1/pets", {
      method: "POST",
      headers: { "Idempotency-Key": `portal-onboarding-${random}` },
      json: {
        name,
        template_id: preset.template_id,
        template_version: preset.template_version,
        identity_version: preset.identity_version,
        asset_version: preset.asset_version,
      },
    });
    dashboard = await api("/api/v1/portal/preference", {
      method: "PATCH",
      json: { selected_pet_id: pet.pet_id },
    });
    await refreshPhase1PetData();
    renderDashboard();
    renderPortalPhase1();
    sessionStorage.removeItem(ONBOARDING_DISMISSED_KEY);
    $("pet-onboarding-dialog").close();
    activatePortalSection("dashboard-section");
    setStatus(globalStatus, `${pet.name} 已来到你的桌面宠物家庭，现在可以开始照料。`, "success");
  } catch (error) {
    setStatus($("pet-onboarding-status"), error.message, "error");
  } finally {
    createButton.disabled = false;
  }
}

function renderPetSwitcher() {
  const wrap = $("portal-pet-switcher-wrap");
  const select = $("portal-pet-switcher");
  const addButton = $("portal-add-pet");
  if (!wrap || !select || !addButton) return;
  const authenticated = Boolean(accessToken && dashboard);
  addButton.hidden = !authenticated;
  if (!authenticated) {
    wrap.hidden = true;
    select.replaceChildren();
    return;
  }
  wrap.hidden = dashboard.pets.length === 0;
  select.replaceChildren();
  dashboard.pets.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.pet.pet_id;
    option.textContent = `${item.pet.name} · Lv.${item.pet.stats.growth_level}`;
    option.selected = item.pet.pet_id === dashboard.selected_pet_id;
    select.append(option);
  });
}

function recommendedCare(selected) {
  if (!selected) return null;
  if (selected.pet.presence !== "home") {
    return {
      title: `${selected.pet.name} 正在串门`,
      detail: "返回家中后再进行照料；现在可以查看串门进度。",
      targetSection: "visits-section",
    };
  }
  const stats = selected.pet.stats || {};
  const options = [
    { value: Number(stats.hunger ?? 100), action: "feed", title: "该投喂了", detail: "饱食状态最低，投喂能让它恢复精神。" },
    { value: Number(stats.energy ?? 100), action: "rest", title: "让它休息一下", detail: "精力偏低，休息后更适合继续互动。" },
    { value: Number(stats.cleanliness ?? 100), action: "clean", title: "需要清洁", detail: "保持清洁有助于维持健康和好心情。" },
    { value: Number(stats.mood ?? 100), action: "play", title: "陪它玩一会儿", detail: "心情偏低，玩耍可以增加互动和羁绊。" },
  ].sort((left, right) => left.value - right.value);
  if (options[0].value >= 80) {
    return { action: "pet", title: "状态不错，摸摸它吧", detail: "当前状态稳定，轻松互动也能积累羁绊。" };
  }
  return options[0];
}

function renderCareRecommendation() {
  const recommendation = $("dashboard-care-recommendation");
  if (!recommendation) return;
  const selected = selectedPortalPet();
  recommendation.hidden = !selected;
  if (!selected) return;
  const suggestion = recommendedCare(selected);
  const copy = recommendation.querySelector(".care-recommendation-copy");
  const button = recommendation.querySelector("button");
  copy.replaceChildren(
    experienceNode("span", "recommendation-label", "现在最需要"),
    experienceNode("strong", "", suggestion.title),
    experienceNode("small", "", suggestion.detail),
  );
  button.textContent = suggestion.targetSection ? "查看串门" : careActionLabel(suggestion.action);
  button.onclick = async () => {
    if (suggestion.targetSection) {
      activatePortalSection(suggestion.targetSection);
      return;
    }
    try {
      await performPhase1Care(suggestion.action, button);
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    }
  };
}

function addNextStep(container, title, description, actionLabel, handler, emphasis = false) {
  const card = experienceNode("button", emphasis ? "next-step-card emphasis" : "next-step-card");
  card.type = "button";
  const copy = experienceNode("span", "next-step-copy");
  copy.append(experienceNode("strong", "", title), experienceNode("small", "", description));
  card.append(copy, experienceNode("span", "next-step-action", actionLabel));
  card.addEventListener("click", handler);
  container.append(card);
}

function renderNextSteps() {
  const container = $("next-step-list");
  if (!container || !dashboard) return;
  container.replaceChildren();
  if (!dashboard.pets.length) {
    addNextStep(container, "领养第一只宠物", "完成后即可开始照料和成长。", "开始", () => openPetOnboarding(false), true);
    return;
  }

  const unread = portalPhase1State.conversations.reduce((sum, item) => sum + Number(item.unread_count || 0), 0);
  const pendingReminderStates = new Set(["pending", "delivered", "seen", "snoozed"]);
  const pendingReminders = portalPhase1State.reminders.filter((item) => pendingReminderStates.has(item.state)).length;
  const selected = selectedPortalPet();

  if (unread > 0) {
    addNextStep(container, `${unread} 条消息待查看`, "好友和系统消息集中在消息中心。", "查看", () => activatePortalSection("messages-section"), true);
  }
  if (pendingReminders > 0) {
    addNextStep(container, `${pendingReminders} 条提醒待处理`, "完成或稍后处理今天的提醒。", "处理", () => activatePortalSection("reminders-section"));
  }
  if (!socialState.friends.length) {
    addNextStep(container, "添加第一位好友", "好友之间可以聊天、共同照料和串门。", "添加", () => activatePortalSection("friends-section"));
  }
  if (selected?.pet.presence !== "home") {
    addNextStep(container, "宠物正在串门", "查看当前访问状态或召回宠物。", "查看", () => activatePortalSection("visits-section"));
  }
  if (container.childElementCount < 3) {
    addNextStep(container, "查看成长档案", "了解成长等级、羁绊和最近互动。", "查看", () => activatePortalSection("pets-section"));
  }
}

function renderCustomerExperience() {
  renderPetSwitcher();
  renderCareRecommendation();
  renderNextSteps();
  if (
    accessToken
    && dashboard
    && dashboard.pets.length === 0
    && !portalExperienceState.autoOpened
    && sessionStorage.getItem(ONBOARDING_DISMISSED_KEY) !== "1"
  ) {
    portalExperienceState.autoOpened = true;
    window.setTimeout(() => openPetOnboarding(false), 0);
  }
}

installCustomerNavigation();
installPetSwitcher();
installSimplifiedPetCreation();
installDashboardGuidance();
installPetOnboarding();

const baseRefreshAllForCustomerExperience = refreshAll;
refreshAll = async function refreshAllWithCustomerExperience() {
  await baseRefreshAllForCustomerExperience();
  renderCustomerExperience();
};

const baseRenderDashboardForCustomerExperience = renderDashboard;
renderDashboard = function renderDashboardWithCustomerExperience() {
  baseRenderDashboardForCustomerExperience();
  renderCustomerExperience();
};

const baseRenderPortalPhase1ForCustomerExperience = renderPortalPhase1;
renderPortalPhase1 = function renderPortalPhase1WithCustomerExperience() {
  baseRenderPortalPhase1ForCustomerExperience();
  renderCustomerExperience();
};

const baseLogoutForCustomerExperience = logout;
logout = function logoutWithCustomerExperience(message = "", kind = "") {
  const dialog = $("pet-onboarding-dialog");
  if (dialog?.open) dialog.close();
  portalExperienceState.autoOpened = false;
  baseLogoutForCustomerExperience(message, kind);
  renderPetSwitcher();
};

if (dashboard) renderCustomerExperience();
