"use strict";

const customerActionsState = {
  activeConversation: null,
  conversationTarget: null,
  activeVisitId: "",
};

const visitTimelineKindLabels = {
  requested: "已申请",
  accepted: "已接受",
  arrived: "已到达",
  interaction: "互动",
  rejected: "已拒绝",
  cancelled: "已取消",
  returned: "已返家",
  expired: "已过期",
};

function customerActionRandom(prefix) {
  const random = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
  return `${prefix}-${random}`;
}

function activateCustomerSection(sectionId) {
  if (typeof activatePortalSection === "function") {
    activatePortalSection(sectionId);
    return;
  }
  document.querySelectorAll(".workspace").forEach((section) => {
    section.hidden = section.id !== sectionId;
  });
  document.querySelectorAll(".main-tab[data-section]").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === sectionId);
  });
}

function ensureMessageActions() {
  if ($("message-compose-actions")) return;
  const detail = $("message-detail");
  if (!detail || !detail.parentElement) return;

  const targetRow = node("div", "", "message-related-row");
  targetRow.id = "message-related-row";
  targetRow.hidden = true;
  const targetButton = node("button", "查看相关详情", "secondary");
  targetButton.id = "message-related-target";
  targetButton.type = "button";
  targetButton.addEventListener("click", async () => {
    const target = customerActionsState.conversationTarget;
    if (!target || target.kind === "none") return;
    await activateCustomerTarget(target.kind, target.target_id, target.label);
  });
  targetRow.append(targetButton);

  const panel = node("section", "", "message-compose-actions");
  panel.id = "message-compose-actions";
  panel.hidden = true;
  const quick = node("div", "", "message-quick-replies");
  quick.id = "message-quick-replies";
  const form = document.createElement("form");
  form.id = "message-compose-form";
  form.className = "message-compose-form";
  const input = document.createElement("input");
  input.id = "message-compose-input";
  input.maxLength = 2000;
  input.placeholder = "输入回复内容";
  input.autocomplete = "off";
  const send = node("button", "发送", "");
  send.id = "message-compose-send";
  send.type = "submit";
  form.append(input, send);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;
    send.disabled = true;
    try {
      await sendCustomerConversationMessage(content);
      input.value = "";
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      send.disabled = false;
    }
  });
  panel.append(quick, form);
  detail.insertAdjacentElement("afterend", panel);
  panel.insertAdjacentElement("beforebegin", targetRow);
}

function quickReplyValues(conversation) {
  if (!conversation) return [];
  if (conversation.category === "visit") {
    return ["收到，我来看看", "可以，稍后处理", "谢谢，宠物已经到家"];
  }
  if (conversation.category === "shared_care") {
    return ["收到，我会留意", "好的，谢谢", "我稍后处理"];
  }
  if (conversation.category === "friend_pet") {
    return ["好可爱", "收到啦", "下次一起玩"];
  }
  return ["收到", "好的，谢谢", "我稍后回复你"];
}

function renderMessageActions(conversation) {
  ensureMessageActions();
  customerActionsState.activeConversation = conversation || null;
  customerActionsState.conversationTarget = null;
  const panel = $("message-compose-actions");
  const quick = $("message-quick-replies");
  const targetRow = $("message-related-row");
  if (!panel || !quick || !targetRow) return;

  targetRow.hidden = true;
  quick.replaceChildren();
  const writable = Boolean(conversation && conversation.kind === "direct");
  panel.hidden = !writable;
  if (writable) {
    quickReplyValues(conversation).forEach((reply) => {
      const button = node("button", reply, "ghost compact");
      button.type = "button";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await sendCustomerConversationMessage(reply);
        } catch (error) {
          setStatus(globalStatus, error.message, "error");
        } finally {
          button.disabled = false;
        }
      });
      quick.append(button);
    });
  }
  if (conversation) loadConversationTarget(conversation.conversation_id).catch(() => {});
}

async function sendCustomerConversationMessage(content) {
  const conversation = customerActionsState.activeConversation;
  if (!conversation || conversation.kind !== "direct") throw new Error("请先选择一个可回复的会话。");
  const selected = selectedPortalPet();
  await api(`/api/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/messages`, {
    method: "POST",
    headers: { "Idempotency-Key": customerActionRandom("portal-message") },
    json: {
      content,
      sender_pet_id: selected?.pet?.pet_id || null,
    },
  });
  await refreshPhase1Messages();
  const refreshed = portalPhase1State.conversations.find(
    (item) => item.conversation_id === conversation.conversation_id,
  ) || conversation;
  await baseOpenConversationForCustomerActions(refreshed);
  renderMessageActions(refreshed);
  setStatus(globalStatus, "消息已发送。", "success");
}

async function loadConversationTarget(conversationId) {
  const target = await api(`/api/v1/conversations/${encodeURIComponent(conversationId)}/target`);
  if (customerActionsState.activeConversation?.conversation_id !== conversationId) return;
  customerActionsState.conversationTarget = target;
  const row = $("message-related-row");
  const button = $("message-related-target");
  if (!row || !button) return;
  row.hidden = !target || target.kind === "none";
  if (!row.hidden) button.textContent = target.label || "查看相关详情";
}

function ensureVisitTimelinePanel() {
  let panel = $("visit-timeline-panel");
  if (panel) return panel;
  const section = $("visits-section");
  if (!section) return null;
  panel = node("article", "", "panel visit-timeline-panel");
  panel.id = "visit-timeline-panel";
  panel.hidden = true;
  const heading = node("div", "", "section-heading");
  const copy = node("div");
  copy.append(
    node("p", "VISIT TIMELINE", "eyebrow"),
    node("h2", "串门时间线"),
    node("p", "申请、接受、到达、互动和返家集中展示。", "hint"),
  );
  const close = node("button", "关闭时间线", "secondary");
  close.type = "button";
  close.addEventListener("click", () => {
    panel.hidden = true;
    customerActionsState.activeVisitId = "";
  });
  heading.append(copy, close);
  const summary = node("p", "", "visit-timeline-summary");
  summary.id = "visit-timeline-summary";
  const list = node("ol", "", "visit-timeline-list");
  list.id = "visit-timeline-list";
  panel.append(heading, summary, list);
  const activePanel = $("active-visits")?.closest("article.panel");
  if (activePanel) section.insertBefore(panel, activePanel);
  else section.append(panel);
  return panel;
}

function renderVisitTimeline(payload) {
  const panel = ensureVisitTimelinePanel();
  const summary = $("visit-timeline-summary");
  const list = $("visit-timeline-list");
  if (!panel || !summary || !list) return;
  panel.hidden = false;
  customerActionsState.activeVisitId = payload.visit_id || "";
  summary.textContent = `${payload.visitor_pet_name} → ${payload.host_pet_name} · ${visitStatusLabel(payload.status)}`;
  list.replaceChildren();
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  if (!entries.length) {
    list.append(node("li", "暂无可展示的时间线记录。", "empty-state"));
  }
  entries.forEach((entry) => {
    const item = node("li", "", `visit-timeline-entry kind-${entry.kind}`);
    const marker = node("span", visitTimelineKindLabels[entry.kind] || entry.kind, "visit-timeline-kind");
    const body = node("div", "", "visit-timeline-body");
    body.append(
      node("strong", entry.title),
      node("p", entry.detail),
      node(
        "span",
        `${localTime(entry.occurred_at)}${entry.actor_display_name ? ` · ${entry.actor_display_name}` : ""}`,
        "hint",
      ),
    );
    item.append(marker, body);
    list.append(item);
  });
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function openVisitTimeline(visitId) {
  if (!visitId) return;
  activateCustomerSection("visits-section");
  const payload = await api(`/api/v1/visits/${encodeURIComponent(visitId)}/timeline`);
  renderVisitTimeline(payload);
}

function appendVisitTimelineButtons(container, visits) {
  if (!container) return;
  const cards = [...container.children];
  visits.forEach((visit, index) => {
    const card = cards[index];
    if (!card || card.querySelector(".visit-timeline-button")) return;
    card.dataset.visitId = visit.visit_id;
    const actions = card.querySelector(".item-actions") || card.querySelector(".pending-item-actions");
    const button = node("button", "查看时间线", "secondary visit-timeline-button");
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await openVisitTimeline(visit.visit_id);
      } catch (error) {
        setStatus(globalStatus, error.message, "error");
      } finally {
        button.disabled = false;
      }
    });
    if (actions) actions.append(button);
    else card.append(button);
  });
}

function assignReminderTargets() {
  const container = $("reminder-list");
  if (!container) return;
  const values = portalPhase1State.reminders
    .slice()
    .sort((left, right) => new Date(left.scheduled_at) - new Date(right.scheduled_at))
    .slice(0, 100);
  [...container.children].forEach((card, index) => {
    const item = values[index];
    if (item) card.dataset.reminderId = item.occurrence_id || item.id || "";
  });
}

async function activateCustomerTarget(kind, targetId, label = "") {
  if (kind === "visit") {
    await refreshVisits();
    await openVisitTimeline(targetId);
    return;
  }
  if (kind === "reminder") {
    activateCustomerSection("reminders-section");
    await refreshPhase1Reminders();
    renderReminders();
    assignReminderTargets();
    const card = [...document.querySelectorAll("#reminder-list [data-reminder-id]")]
      .find((item) => item.dataset.reminderId === targetId);
    if (card) {
      card.classList.add("customer-target-highlight");
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    return;
  }
  if (kind === "pet") {
    const pet = dashboard?.pets?.find((item) => item.pet.pet_id === targetId);
    if (pet && dashboard.selected_pet_id !== targetId) {
      dashboard = await api("/api/v1/portal/preference", {
        method: "PATCH",
        json: { selected_pet_id: targetId },
      });
      await refreshPhase1PetData();
      renderDashboard();
      renderPortalPhase1();
    }
    activateCustomerSection("pets-section");
    $("selected-pet-config")?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (!pet) setStatus(globalStatus, label || "相关宠物当前未同步到此账户。", "error");
    return;
  }
  if (kind === "friend") {
    activateCustomerSection("friends-section");
    await refreshSocial();
    $("friend-list")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  setStatus(globalStatus, label || "暂无可打开的关联详情。", "error");
}

function pendingTarget(item) {
  if (item.kind === "visit_request") return { kind: "visit", id: item.item_id };
  if (item.kind === "reminder_due") return { kind: "reminder", id: item.item_id };
  if (item.kind === "caregiver_invitation") return { kind: "pet", id: item.pet_id };
  if (item.kind === "friend_request") return { kind: "friend", id: "" };
  return { kind: "none", id: "" };
}

function decoratePendingItemDetails() {
  const list = $("pending-items-list");
  if (!list) return;
  [...list.children].forEach((card, index) => {
    const item = pendingItemsState.items[index];
    const actions = card.querySelector(".pending-item-actions");
    if (!item || !actions || actions.querySelector(".pending-detail-button")) return;
    const target = pendingTarget(item);
    const button = node("button", "查看详情", "ghost compact pending-detail-button");
    button.type = "button";
    button.disabled = target.kind === "none";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await activateCustomerTarget(target.kind, target.id, item.title);
      } catch (error) {
        setStatus(globalStatus, error.message, "error");
      } finally {
        button.disabled = target.kind === "none";
      }
    });
    actions.prepend(button);
  });
}

ensureMessageActions();
ensureVisitTimelinePanel();

const baseOpenConversationForCustomerActions = openConversation;
openConversation = async function openConversationWithCustomerActions(conversation) {
  await baseOpenConversationForCustomerActions(conversation);
  renderMessageActions(conversation);
};

const baseRenderConversationsForCustomerActions = renderConversations;
renderConversations = function renderConversationsWithCustomerActions() {
  baseRenderConversationsForCustomerActions();
  if (customerActionsState.activeConversation) renderMessageActions(customerActionsState.activeConversation);
};

const baseRenderRequestListForTimeline = renderRequestList;
renderRequestList = function renderRequestListWithTimeline(containerId, items, mode) {
  baseRenderRequestListForTimeline(containerId, items, mode);
  appendVisitTimelineButtons($(containerId), items);
};

const baseRenderActiveVisitsForTimeline = renderActiveVisits;
renderActiveVisits = function renderActiveVisitsWithTimeline() {
  baseRenderActiveVisitsForTimeline();
  appendVisitTimelineButtons($("active-visits"), visitState.visits.active || []);
};

const baseRenderVisitHistoryForTimeline = renderVisitHistory;
renderVisitHistory = function renderVisitHistoryWithTimeline() {
  baseRenderVisitHistoryForTimeline();
  appendVisitTimelineButtons($("visit-history"), visitState.visits.history || []);
};

const baseRenderPendingItemsForDetails = renderPendingItems;
renderPendingItems = function renderPendingItemsWithDetails() {
  baseRenderPendingItemsForDetails();
  decoratePendingItemDetails();
};

const baseRenderRemindersForTargets = renderReminders;
renderReminders = function renderRemindersWithTargets() {
  baseRenderRemindersForTargets();
  assignReminderTargets();
};

const baseLogoutForCustomerActions = logout;
logout = function logoutWithCustomerActions(message = "", kind = "") {
  customerActionsState.activeConversation = null;
  customerActionsState.conversationTarget = null;
  customerActionsState.activeVisitId = "";
  baseLogoutForCustomerActions(message, kind);
  renderMessageActions(null);
  const timeline = $("visit-timeline-panel");
  if (timeline) timeline.hidden = true;
};
