"use strict";

const portalPhase1State = {
  growth: null,
  activity: [],
  conversations: [],
  reminders: [],
  deployment: null,
  activeConversationId: "",
};

function phase1Text(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function phase1Time(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function phase1DateKey(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return `${parsed.getFullYear()}-${parsed.getMonth()}-${parsed.getDate()}`;
}

function careActionLabel(value) {
  return {
    feed: "投喂",
    play: "玩耍",
    clean: "清洁",
    pet: "摸摸",
    rest: "休息",
  }[value] || value;
}

function growthEventLabel(value) {
  return {
    growth_level_up: "成长等级提升",
    bond_level_up: "羁绊等级提升",
    growth_stage_changed: "成长阶段变化",
  }[value] || value;
}

function reminderStateLabel(value) {
  return {
    pending: "待处理",
    delivered: "已送达",
    seen: "已查看",
    snoozed: "已贪睡",
    completed: "已完成",
    dismissed: "已忽略",
    expired: "已过期",
  }[value] || value;
}

async function optionalApi(path) {
  try {
    return await api(path);
  } catch (error) {
    if (
      String(error.message).includes("不存在")
      || String(error.message).includes("404")
    ) {
      return null;
    }
    throw error;
  }
}

function selectedPhase1Pet() {
  return selectedPortalPet();
}

function clearPhase1PetData() {
  portalPhase1State.growth = null;
  portalPhase1State.activity = [];
  portalPhase1State.deployment = null;
}

function clearPortalPhase1State() {
  clearPhase1PetData();
  portalPhase1State.conversations = [];
  portalPhase1State.reminders = [];
  portalPhase1State.activeConversationId = "";
}

async function notifyPetContextRefresh(selected, reason) {
  await portalRuntime.runFeatureHook("onPetContextRefresh", {
    reason,
    petId: selected?.pet.pet_id || "",
    selectedPet: selected || null,
  });
}

async function refreshPhase1PetData(reason = "pet-context-refresh") {
  const selected = selectedPhase1Pet();
  if (!selected) {
    clearPhase1PetData();
    await notifyPetContextRefresh(null, reason);
    return;
  }
  const rawPetId = selected.pet.pet_id;
  const petId = encodeURIComponent(rawPetId);
  const [growth, activity, deployment] = await Promise.all([
    api(`/api/v1/pets/${petId}/growth?limit=20`),
    api(`/api/v1/pets/${petId}/activity?limit=20`),
    optionalApi(`/api/v1/pets/${petId}/personal-asset-deployment`),
  ]);
  portalPhase1State.growth = growth;
  portalPhase1State.activity = activity?.items || [];
  portalPhase1State.deployment = deployment;
  await notifyPetContextRefresh(selected, reason);
}

async function refreshPhase1Messages() {
  portalPhase1State.conversations = await api("/api/v1/conversations?limit=100");
}

async function refreshPhase1Reminders() {
  const snapshot = await api("/api/v1/reminders/snapshot?limit=200");
  portalPhase1State.reminders = snapshot?.items || [];
}

async function refreshPortalPhase1(reason = "phase1-refresh") {
  if (!accessToken || !dashboard) return;
  await Promise.all([
    refreshPhase1PetData(reason),
    refreshPhase1Messages(),
    refreshPhase1Reminders(),
  ]);
  renderPortalPhase1();
}

function setMeter(id, value) {
  const meter = $(id);
  const normalized = Math.max(0, Math.min(100, Number(value) || 0));
  meter.value = String(normalized);
  return normalized;
}

function renderDashboardPet() {
  const selected = selectedPhase1Pet();
  $("dashboard-empty-pet").hidden = Boolean(selected);
  $("dashboard-pet-content").hidden = !selected;
  if (!selected) {
    $("dashboard-pet-name").textContent = "当前宠物";
    $("dashboard-pet-presence").textContent = "无宠物";
    return;
  }
  const pet = selected.pet;
  const stats = pet.stats || {};
  $("dashboard-pet-name").textContent = pet.name;
  $("dashboard-pet-presence").textContent = presenceLabel(pet.presence);
  $("dashboard-pet-level").textContent =
    `成长 Lv.${phase1Text(stats.growth_level, 1)} · 羁绊 Lv.${phase1Text(stats.bond_level, 1)}`;
  $("dashboard-pet-meta").textContent =
    `${personalityLabel(pet.personality_type)} · ${phase1Text(stats.growth_stage, "newborn")} · ${roleLabel(selected.relation.role)}`;
  const values = {
    hunger: setMeter("dashboard-hunger-meter", stats.hunger),
    energy: setMeter("dashboard-energy-meter", stats.energy),
    cleanliness: setMeter("dashboard-cleanliness-meter", stats.cleanliness),
    mood: setMeter("dashboard-mood-meter", stats.mood),
  };
  $("dashboard-hunger").textContent = `${values.hunger}/100`;
  $("dashboard-energy").textContent = `${values.energy}/100`;
  $("dashboard-cleanliness").textContent = `${values.cleanliness}/100`;
  $("dashboard-mood").textContent = `${values.mood}/100`;
}

function renderGrowthLists() {
  const growthList = $("dashboard-growth-list");
  growthList.replaceChildren();
  const history = portalPhase1State.growth?.history || [];
  if (!history.length) {
    empty(growthList, "暂无成长变化，继续照料即可积累成长记录。");
  }
  history.slice(0, 8).forEach((item) => {
    const built = itemCard(
      growthEventLabel(item.event_type),
      [
        `${phase1Text(item.previous_value)} → ${phase1Text(item.current_value)}`,
        `${phase1Time(item.created_at)} · ${phase1Text(item.source)}`,
      ],
    );
    growthList.append(built.card);
  });

  const activityList = $("dashboard-activity-list");
  activityList.replaceChildren();
  if (!portalPhase1State.activity.length) {
    empty(activityList, "暂无互动履历，可在上方执行一次照料。");
  }
  portalPhase1State.activity.slice(0, 10).forEach((item) => {
    const deltas = Object.entries(item.deltas || {})
      .map(([key, value]) => `${key} ${Number(value) >= 0 ? "+" : ""}${value}`)
      .join(" · ");
    const built = itemCard(careActionLabel(item.action), [
      deltas || "状态已更新",
      phase1Time(item.created_at),
    ]);
    activityList.append(built.card);
  });
}

function renderPetDetails() {
  const selected = selectedPhase1Pet();
  const growth = $("pet-growth-detail");
  const deployment = $("pet-deployment-detail");
  growth.replaceChildren();
  deployment.replaceChildren();
  if (!selected) return;
  const stats = selected.pet.stats || {};
  const growthCard = itemCard("成长档案", [
    `成长阶段：${phase1Text(stats.growth_stage)}`,
    `成长等级：Lv.${phase1Text(stats.growth_level, 1)} · 经验 ${phase1Text(stats.growth_exp, 0)}`,
    `羁绊等级：Lv.${phase1Text(stats.bond_level, 1)} · 经验 ${phase1Text(stats.bond_exp, 0)}`,
    `亲密度：${phase1Text(selected.relation.affinity, 0)} · 照料贡献：${phase1Text(selected.relation.care_contribution, 0)}`,
  ]);
  growth.append(growthCard.card);

  if (!portalPhase1State.deployment) {
    empty(deployment, "当前使用公共模板素材，尚未部署专属 Release。");
    return;
  }
  const active = portalPhase1State.deployment.active_release || {};
  const previous = portalPhase1State.deployment.previous_release;
  const versionCard = itemCard("专属素材部署", [
    `当前版本：${phase1Text(active.identity_version)} / ${phase1Text(active.asset_version)}`,
    `发布时间：${phase1Time(active.published_at)}`,
    `上一版本：${previous ? `${phase1Text(previous.identity_version)} / ${phase1Text(previous.asset_version)}` : "无"}`,
    `更新原因：${phase1Text(portalPhase1State.deployment.reason)}`,
  ]);
  deployment.append(versionCard.card);
}

function filteredConversations() {
  const filter = $("message-category-filter").value;
  const values = portalPhase1State.conversations.filter(
    (item) => filter === "all" || item.category === filter,
  );
  const projection = portalRuntime.applyFeatureHook("onFilterConversations", {
    filter,
    conversations: portalPhase1State.conversations,
    values,
  });
  return Array.isArray(projection.values) ? projection.values : values;
}

function completeConversationRender(values) {
  portalRuntime.applyFeatureHook("onConversationsRenderComplete", {
    conversations: values,
    activeConversationId: portalPhase1State.activeConversationId,
  });
}

function renderConversations() {
  const totalUnread = portalPhase1State.conversations.reduce(
    (sum, item) => sum + Number(item.unread_count || 0),
    0,
  );
  $("message-unread-count").textContent = `${totalUnread} 未读`;
  $("dashboard-unread").textContent = String(totalUnread);
  const container = $("conversation-list");
  container.replaceChildren();
  const values = filteredConversations();
  if (!values.length) {
    empty(container, "当前分类暂无会话。");
    completeConversationRender(values);
    return;
  }
  values.forEach((conversation) => {
    const last = conversation.last_message;
    const built = itemCard(
      conversation.title,
      [
        `${conversation.category_label} · ${conversation.unread_count || 0} 未读`,
        last ? `${last.sender_display_name}：${last.content}` : "暂无消息",
        phase1Time(conversation.updated_at),
      ],
      conversation.conversation_id === portalPhase1State.activeConversationId,
    );
    built.actions.append(actionButton("查看", () => openConversation(conversation)));
    container.append(built.card);
  });
  completeConversationRender(values);
}

async function completeConversationOpen(conversation, messages, options, source) {
  return portalRuntime.runFeatureHook("onConversationOpenComplete", {
    conversation,
    messages,
    options,
    source,
  });
}

async function openConversation(conversation, options = {}) {
  const request = await portalRuntime.runFeatureHook("onConversationOpenRequest", {
    conversation,
    options,
    handled: false,
    result: null,
    messages: [],
  });
  if (request.handled) {
    await completeConversationOpen(
      request.conversation || conversation,
      Array.isArray(request.messages) ? request.messages : [],
      request.options || options,
      "feature",
    );
    return request.result;
  }

  portalPhase1State.activeConversationId = conversation.conversation_id;
  $("message-detail-title").textContent = conversation.title;
  const response = await api(
    `/api/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/messages?after_sequence=0&limit=100`,
  );
  const detail = $("message-detail");
  detail.replaceChildren();
  const items = response?.items || [];
  if (!items.length) empty(detail, "该会话暂无消息。");
  items.forEach((message) => {
    const card = node("article", "", "message-bubble");
    card.append(
      node("strong", message.sender_display_name),
      node("p", message.content),
      node("span", phase1Time(message.created_at), "hint"),
    );
    detail.append(card);
  });
  const last = items.at(-1);
  if (last && conversation.unread_count > 0) {
    await api(`/api/v1/messages/${encodeURIComponent(last.message_id)}/read`, {
      method: "POST",
    });
    await refreshPhase1Messages();
  }
  renderConversations();
  await completeConversationOpen(conversation, items, options, "core");
  return response;
}

function completeReminderRender(items) {
  portalRuntime.applyFeatureHook("onRemindersRenderComplete", { reminders: items });
}

function renderReminders() {
  const items = portalPhase1State.reminders;
  const todayKey = phase1DateKey(new Date());
  const pendingStates = new Set(["pending", "delivered", "seen", "snoozed"]);
  const todayPending = items.filter(
    (item) => phase1DateKey(item.scheduled_at) === todayKey && pendingStates.has(item.state),
  ).length;
  const completed = items.filter((item) => item.state === "completed").length;
  const snoozed = items.filter((item) => item.state === "snoozed").length;
  $("reminder-count").textContent = `${items.length} 条`;
  $("reminder-today-pending").textContent = String(todayPending);
  $("reminder-completed").textContent = String(completed);
  $("reminder-snoozed").textContent = String(snoozed);
  $("dashboard-pending-reminders").textContent = String(todayPending);

  const container = $("reminder-list");
  container.replaceChildren();
  if (!items.length) {
    empty(container, "暂无提醒。配置 MyReminder 后会在此同步展示。");
    completeReminderRender(items);
    return;
  }
  items
    .slice()
    .sort((left, right) => new Date(left.scheduled_at) - new Date(right.scheduled_at))
    .slice(0, 100)
    .forEach((item) => {
      const built = itemCard(item.title, [
        `${reminderStateLabel(item.state)} · ${phase1Text(item.category, "general")} · ${phase1Text(item.priority, "normal")}`,
        phase1Time(item.scheduled_at),
        item.content || "无补充说明",
      ]);
      container.append(built.card);
    });
  completeReminderRender(items);
}

function renderPortalPhase1() {
  renderDashboardPet();
  renderGrowthLists();
  renderPetDetails();
  renderConversations();
  renderReminders();
  const todayKey = phase1DateKey(new Date());
  const todayActions = portalPhase1State.activity.filter(
    (item) => phase1DateKey(item.created_at) === todayKey,
  ).length;
  $("dashboard-today-actions").textContent = String(todayActions);
  $("dashboard-deployment").textContent = portalPhase1State.deployment
    ? "已部署"
    : "公共素材";
}

async function performPhase1Care(action, button) {
  const selected = selectedPhase1Pet();
  if (!selected) throw new Error("请先选择一只宠物。");
  button.disabled = true;
  try {
    const random =
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
    await api(
      `/api/v1/pets/${encodeURIComponent(selected.pet.pet_id)}/interactions/${action}`,
      {
        method: "POST",
        headers: { "Idempotency-Key": `portal-care-${random}` },
        json: {},
      },
    );
    await Promise.all([
      refreshDashboard(),
      refreshPhase1PetData("care-complete"),
    ]);
    renderPortalPhase1();
    setStatus(
      globalStatus,
      `${careActionLabel(action)}完成，状态已进入同步事件流。`,
      "success",
    );
    await portalRuntime.runFeatureHook("onCareComplete", {
      action,
      petId: selected.pet.pet_id,
    });
  } finally {
    button.disabled = false;
  }
}

const baseRenderDashboardForPhase1 = renderDashboard;
renderDashboard = function renderDashboardWithPhase1() {
  baseRenderDashboardForPhase1();
  if (
    portalPhase1State.growth
    || portalPhase1State.activity.length
    || portalPhase1State.deployment
  ) {
    renderPortalPhase1();
  }
};

function installPhase1Actions() {
  document.querySelectorAll("[data-care-action]").forEach((button) => {
    if (button.dataset.phase1Bound === "1") return;
    button.dataset.phase1Bound = "1";
    button.addEventListener("click", async () => {
      try {
        await performPhase1Care(button.dataset.careAction, button);
      } catch (error) {
        setStatus(globalStatus, error.message, "error");
      }
    });
  });

  const refreshButton = $("refresh-phase1");
  if (refreshButton && refreshButton.dataset.phase1Bound !== "1") {
    refreshButton.dataset.phase1Bound = "1";
    refreshButton.addEventListener("click", async () => {
      refreshButton.disabled = true;
      try {
        await portalRuntime.requestRefresh({ reason: "manual-phase1" });
        setStatus(globalStatus, "首页、成长、消息和提醒已刷新。", "success");
      } catch (error) {
        setStatus(globalStatus, error.message, "error");
      } finally {
        refreshButton.disabled = false;
      }
    });
  }

  const categoryFilter = $("message-category-filter");
  if (categoryFilter && categoryFilter.dataset.phase1Bound !== "1") {
    categoryFilter.dataset.phase1Bound = "1";
    categoryFilter.addEventListener("change", renderConversations);
  }
}

async function refreshPhase1Section(sectionId) {
  if (!accessToken) return;
  if (sectionId === "dashboard-section" || sectionId === "pets-section") {
    await refreshPhase1PetData("section-enter");
  } else if (sectionId === "messages-section") {
    await refreshPhase1Messages();
  } else if (sectionId === "reminders-section") {
    await refreshPhase1Reminders();
  } else {
    return;
  }
  renderPortalPhase1();
}

portalRuntime.registerFeature({
  id: "phase1-core",
  label: "首页、成长、消息和提醒",
  order: 10,
  mount: installPhase1Actions,
  onRefreshComplete: ({ reason }) => refreshPortalPhase1(reason),
  onSectionEnter: ({ sectionId, source }) => {
    if (source === "startup" || source === "anonymous") return;
    return refreshPhase1Section(sectionId);
  },
  onRealtime: () => refreshPortalPhase1("realtime"),
  onLogout: () => {
    clearPortalPhase1State();
  },
});
