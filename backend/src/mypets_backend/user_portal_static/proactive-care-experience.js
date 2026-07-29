"use strict";

const portalProactiveCareState = {
  preferences: null,
  notice: null,
  nextCheckAt: 0,
  evaluating: false,
  timerId: 0,
};

function installProactiveCareExperience() {
  const dashboardSection = $("dashboard-section");
  if (dashboardSection && !$("proactive-care-banner")) {
    const banner = experienceNode("article", "panel proactive-care-banner");
    banner.id = "proactive-care-banner";
    banner.hidden = true;

    const icon = experienceNode("span", "proactive-care-icon", "🐾");
    const copy = experienceNode("div", "proactive-care-copy");
    copy.append(
      experienceNode("span", "recommendation-label", "轻提醒"),
      experienceNode("strong", "", "今天可以轻松陪伴一下"),
      experienceNode("small", "", ""),
    );
    copy.querySelector("strong").id = "proactive-care-title";
    copy.querySelector("small").id = "proactive-care-detail";

    const actions = experienceNode("div", "proactive-care-actions");
    const primary = experienceNode("button", "", "去看看");
    primary.id = "proactive-care-primary";
    primary.type = "button";
    const snooze = experienceNode("button", "secondary", "稍后提醒");
    snooze.id = "proactive-care-snooze";
    snooze.type = "button";
    const dismiss = experienceNode("button", "ghost compact", "今天不再提示");
    dismiss.id = "proactive-care-dismiss";
    dismiss.type = "button";
    actions.append(primary, snooze, dismiss);
    banner.append(icon, copy, actions);

    const dashboardGrid = dashboardSection.querySelector(".dashboard-grid");
    dashboardSection.insertBefore(banner, dashboardGrid || dashboardSection.firstChild);
    primary.addEventListener("click", actOnProactiveCareNotice);
    snooze.addEventListener("click", () => acknowledgeProactiveCare("snoozed"));
    dismiss.addEventListener("click", () => {
      acknowledgeProactiveCare("dismissed_today");
    });
  }

  const accountSection = $("account-section");
  if (accountSection && !$("proactive-care-settings")) {
    const panel = experienceNode("article", "panel proactive-care-settings");
    panel.id = "proactive-care-settings";
    const heading = experienceNode("div", "section-heading");
    const headingCopy = experienceNode("div");
    headingCopy.append(
      experienceNode("p", "eyebrow", "GENTLE CARE"),
      experienceNode("h2", "", "主动关怀与免打扰"),
    );
    const status = experienceNode("span", "badge", "读取中");
    status.id = "proactive-care-setting-status";
    heading.append(headingCopy, status);

    const form = document.createElement("form");
    form.id = "proactive-care-settings-form";
    form.className = "proactive-care-settings-form";
    form.innerHTML = `
      <div class="proactive-setting-switches">
        <label class="check-label"><input id="proactive-enabled" type="checkbox">启用主动关怀</label>
        <label class="check-label"><input id="proactive-low-state" type="checkbox">宠物状态偏低时提示</label>
        <label class="check-label"><input id="proactive-inactivity" type="checkbox">长时间未互动时提示</label>
        <label class="check-label"><input id="proactive-reminder" type="checkbox">提醒到期时提示</label>
      </div>
      <div class="proactive-setting-grid">
        <label class="check-label proactive-quiet-toggle"><input id="proactive-quiet-enabled" type="checkbox">启用免打扰</label>
        <label>开始时间<input id="proactive-quiet-start" type="time" required></label>
        <label>结束时间<input id="proactive-quiet-end" type="time" required></label>
        <label>两次提示至少间隔
          <select id="proactive-min-interval">
            <option value="30">30 分钟</option>
            <option value="60">1 小时</option>
            <option value="120">2 小时</option>
            <option value="180">3 小时</option>
            <option value="240">4 小时</option>
            <option value="480">8 小时</option>
          </select>
        </label>
        <label>每天最多提示
          <select id="proactive-max-daily">
            <option value="1">1 次</option>
            <option value="2">2 次</option>
            <option value="3">3 次</option>
            <option value="5">5 次</option>
          </select>
        </label>
      </div>
      <div class="proactive-settings-footer">
        <p class="hint">提示只用于状态、陪伴和已到期提醒，不在免打扰时段弹出，也不会替你自动操作。</p>
        <button id="save-proactive-settings" type="submit">保存主动关怀设置</button>
      </div>`;
    const formStatus = experienceNode("p", "status", "");
    formStatus.id = "proactive-care-form-status";
    formStatus.setAttribute("aria-live", "polite");
    panel.append(heading, form, formStatus);
    accountSection.append(panel);
    form.addEventListener("submit", saveProactiveCarePreferences);
    $("proactive-enabled").addEventListener(
      "change",
      syncProactivePreferenceControls,
    );
    $("proactive-quiet-enabled").addEventListener(
      "change",
      syncProactivePreferenceControls,
    );
  }
}

function ensureProactiveSelectValue(select, rawValue, suffix) {
  if (!select) return;
  const value = String(rawValue);
  if (![...select.options].some((option) => option.value === value)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = `${value} ${suffix}`;
    select.append(option);
  }
  select.value = value;
}

function renderProactiveCarePreferences() {
  const value = portalProactiveCareState.preferences;
  if (!value || !$("proactive-care-settings-form")) return;
  $("proactive-enabled").checked = Boolean(value.enabled);
  $("proactive-low-state").checked = Boolean(value.low_state_enabled);
  $("proactive-inactivity").checked = Boolean(value.inactivity_enabled);
  $("proactive-reminder").checked = Boolean(value.reminder_enabled);
  $("proactive-quiet-enabled").checked = Boolean(value.quiet_hours_enabled);
  $("proactive-quiet-start").value = value.quiet_start || "22:00";
  $("proactive-quiet-end").value = value.quiet_end || "08:00";
  ensureProactiveSelectValue(
    $("proactive-min-interval"),
    value.min_interval_minutes || 120,
    "分钟",
  );
  ensureProactiveSelectValue(
    $("proactive-max-daily"),
    value.max_daily_notices || 3,
    "次",
  );
  $("proactive-care-setting-status").textContent = value.enabled
    ? "已开启"
    : "已关闭";
  syncProactivePreferenceControls();
}

function syncProactivePreferenceControls() {
  const enabled = Boolean($("proactive-enabled")?.checked);
  [
    "proactive-low-state",
    "proactive-inactivity",
    "proactive-reminder",
    "proactive-quiet-enabled",
    "proactive-min-interval",
    "proactive-max-daily",
  ].forEach((id) => {
    if ($(id)) $(id).disabled = !enabled;
  });
  const quietEnabled = enabled && Boolean($("proactive-quiet-enabled")?.checked);
  if ($("proactive-quiet-start")) {
    $("proactive-quiet-start").disabled = !quietEnabled;
  }
  if ($("proactive-quiet-end")) {
    $("proactive-quiet-end").disabled = !quietEnabled;
  }
}

async function loadProactiveCarePreferences() {
  if (!accessToken) return;
  portalProactiveCareState.preferences = await api(
    "/api/v1/portal/proactive-care/preferences",
  );
  renderProactiveCarePreferences();
}

async function saveProactiveCarePreferences(event) {
  event.preventDefault();
  const button = $("save-proactive-settings");
  button.disabled = true;
  setStatus($("proactive-care-form-status"), "正在保存…");
  try {
    portalProactiveCareState.preferences = await api(
      "/api/v1/portal/proactive-care/preferences",
      {
        method: "PATCH",
        json: {
          enabled: $("proactive-enabled").checked,
          low_state_enabled: $("proactive-low-state").checked,
          inactivity_enabled: $("proactive-inactivity").checked,
          reminder_enabled: $("proactive-reminder").checked,
          quiet_hours_enabled: $("proactive-quiet-enabled").checked,
          quiet_start: $("proactive-quiet-start").value,
          quiet_end: $("proactive-quiet-end").value,
          min_interval_minutes: Number($("proactive-min-interval").value),
          max_daily_notices: Number($("proactive-max-daily").value),
        },
      },
    );
    portalProactiveCareState.nextCheckAt = 0;
    renderProactiveCarePreferences();
    if (!portalProactiveCareState.preferences.enabled) {
      hideProactiveCareNotice();
    }
    setStatus(
      $("proactive-care-form-status"),
      "主动关怀设置已同步到其他设备。",
      "success",
    );
    await evaluateProactiveCare(true);
  } catch (error) {
    setStatus($("proactive-care-form-status"), error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function scheduleProactiveCareEvaluation() {
  window.clearTimeout(portalProactiveCareState.timerId);
  if (!accessToken || !portalProactiveCareState.nextCheckAt) return;
  const delay = Math.max(
    15000,
    Math.min(
      2147480000,
      portalProactiveCareState.nextCheckAt - Date.now(),
    ),
  );
  portalProactiveCareState.timerId = window.setTimeout(() => {
    evaluateProactiveCare(true).catch((error) => {
      setStatus(globalStatus, error.message, "error");
    });
  }, delay);
}

async function evaluateProactiveCare(force = false) {
  if (!accessToken || !dashboard || portalProactiveCareState.evaluating) return;
  if (!force && portalProactiveCareState.nextCheckAt > Date.now()) return;
  portalProactiveCareState.evaluating = true;
  try {
    const selected = selectedPortalPet();
    const result = await api("/api/v1/portal/proactive-care/evaluate", {
      method: "POST",
      json: {
        timezone_offset_minutes: new Date().getTimezoneOffset(),
        surface: "web",
        pet_id: selected?.pet.pet_id || null,
      },
    });
    portalProactiveCareState.preferences = result.preferences;
    portalProactiveCareState.notice = result.notice;
    portalProactiveCareState.nextCheckAt =
      Date.parse(result.next_check_at) || Date.now() + 60 * 60 * 1000;
    renderProactiveCarePreferences();
    renderProactiveCareNotice();
    scheduleProactiveCareEvaluation();
  } finally {
    portalProactiveCareState.evaluating = false;
  }
}

function renderProactiveCareNotice() {
  const banner = $("proactive-care-banner");
  if (!banner) return;
  const notice = portalProactiveCareState.notice;
  banner.hidden = !notice;
  if (!notice) return;
  $("proactive-care-title").textContent = notice.title;
  $("proactive-care-detail").textContent = notice.detail;
  $("proactive-care-primary").textContent = notice.action_label;
}

function hideProactiveCareNotice() {
  portalProactiveCareState.notice = null;
  renderProactiveCareNotice();
}

async function acknowledgeProactiveCare(outcome) {
  const notice = portalProactiveCareState.notice;
  if (!notice) return;
  try {
    await api("/api/v1/portal/proactive-care/acknowledge", {
      method: "POST",
      json: {
        notice_key: notice.notice_key,
        outcome,
        timezone_offset_minutes: new Date().getTimezoneOffset(),
        snooze_minutes: 120,
      },
    });
    hideProactiveCareNotice();
    portalProactiveCareState.nextCheckAt =
      Date.now() + (outcome === "snoozed" ? 120 : 30) * 60 * 1000;
    scheduleProactiveCareEvaluation();
    setStatus(
      globalStatus,
      outcome === "dismissed_today"
        ? "今天不再显示这条提示。"
        : "已稍后提醒。",
      "success",
    );
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
}

async function switchToProactiveNoticePet(petId) {
  if (!petId || dashboard.selected_pet_id === petId) return;
  dashboard = await api("/api/v1/portal/preference", {
    method: "PATCH",
    json: { selected_pet_id: petId },
  });
  await refreshPhase1PetData("proactive-pet-switch");
  renderDashboard();
  renderPortalPhase1();
}

async function actOnProactiveCareNotice() {
  const notice = portalProactiveCareState.notice;
  if (!notice) return;
  const button = $("proactive-care-primary");
  button.disabled = true;
  try {
    if (notice.pet_id) await switchToProactiveNoticePet(notice.pet_id);
    if (notice.care_action) {
      await performPhase1Care(notice.care_action, button);
      await acknowledgeProactiveCare("acted");
      return;
    }
    activatePortalSection(notice.target_section || "dashboard-section");
    await acknowledgeProactiveCare("opened");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function refreshProactiveCareLifecycle() {
  await loadProactiveCarePreferences();
  await evaluateProactiveCare();
}

portalRuntime.registerFeature({
  id: "proactive-care",
  label: "主动关怀",
  order: 130,
  mount: installProactiveCareExperience,
  onRefreshComplete: refreshProactiveCareLifecycle,
  onSectionEnter: ({ sectionId }) => {
    if (sectionId === "dashboard-section") renderProactiveCareNotice();
    if (sectionId === "account-section") renderProactiveCarePreferences();
  },
  onRealtime: async () => {
    portalProactiveCareState.nextCheckAt = 0;
    await evaluateProactiveCare(true);
  },
  onLogout: () => {
    window.clearTimeout(portalProactiveCareState.timerId);
    portalProactiveCareState.preferences = null;
    portalProactiveCareState.notice = null;
    portalProactiveCareState.nextCheckAt = 0;
    portalProactiveCareState.evaluating = false;
    portalProactiveCareState.timerId = 0;
    renderProactiveCareNotice();
  },
});
