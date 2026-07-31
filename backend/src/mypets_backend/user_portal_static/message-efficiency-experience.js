"use strict";

const messageEfficiencyState = {
  query: "",
  searchItems: [],
  searchCount: 0,
  searchLoaded: false,
  searchLoading: false,
  searchError: "",
  searchResultQuery: "",
  searchRequestId: 0,
  activeConversation: null,
  activeSequence: 0,
  unread: null,
  quickReplies: null,
  searchTimer: 0,
};

const messageEfficiencyUI = window.MyPetsPortalUI;
if (!messageEfficiencyUI) throw new Error("MyPets 门户 UI 组件未加载");

const messageMatchLabels = {
  contact: "联系人",
  pet: "宠物",
  content: "内容",
  title: "会话",
};

function messageEfficiencyNode(tag, text = "", className = "") {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function messageSearchRetryAction() {
  return {
    label: "重新搜索",
    busyLabel: "正在搜索…",
    onClick: () => runMessageSearch(messageEfficiencyState.query),
  };
}

function renderMessageSearchStatus() {
  const result = $("message-search-result");
  if (!result) return;
  if (!messageEfficiencyState.query) {
    result.hidden = true;
    result.replaceChildren();
    messageEfficiencyUI.clearState(result);
    return;
  }
  result.hidden = false;
  if (messageEfficiencyState.searchLoading) {
    messageEfficiencyUI.renderState(result, {
      kind: "loading",
      compact: true,
      title: "正在搜索消息",
      detail: messageEfficiencyState.searchLoaded
        ? "当前结果仍可查看，正在同步最新匹配。"
        : "正在匹配联系人、宠物、会话标题和消息内容。",
    });
    return;
  }
  if (messageEfficiencyState.searchError) {
    messageEfficiencyUI.renderState(result, {
      kind: "error",
      compact: true,
      title: "消息搜索失败",
      detail: messageEfficiencyState.searchLoaded
        ? `${messageEfficiencyState.searchError} 当前仍显示上次成功搜索的结果。`
        : messageEfficiencyState.searchError,
    });
    return;
  }
  if (messageEfficiencyState.searchLoaded) {
    messageEfficiencyUI.renderState(result, {
      kind: messageEfficiencyState.searchCount ? "info" : "empty",
      compact: true,
      title: messageEfficiencyState.searchCount
        ? `${messageEfficiencyState.searchCount} 个匹配会话`
        : "没有匹配会话",
      detail: messageEfficiencyState.searchCount
        ? `搜索词：${messageEfficiencyState.searchResultQuery}`
        : "可以尝试缩短关键词或更换联系人、宠物名称。",
    });
    return;
  }
  messageEfficiencyUI.renderState(result, {
    kind: "idle",
    compact: true,
    title: "输入关键词开始搜索",
    detail: "支持联系人、宠物、会话标题和消息内容。",
  });
}

function renderMessageSearchListState() {
  const list = $("conversation-list");
  if (!list || !messageEfficiencyState.query) return false;
  if (messageEfficiencyState.searchLoading && !messageEfficiencyState.searchLoaded) {
    messageEfficiencyUI.renderState(list, {
      kind: "loading",
      title: "正在搜索相关会话",
      detail: "正在从当前账户的消息记录中查找匹配内容。",
    });
    return true;
  }
  if (messageEfficiencyState.searchError && !messageEfficiencyState.searchLoaded) {
    messageEfficiencyUI.renderState(list, {
      kind: "error",
      title: "相关会话搜索失败",
      detail: messageEfficiencyState.searchError,
      action: messageSearchRetryAction(),
    });
    return true;
  }
  if (messageEfficiencyState.searchLoaded && !messageEfficiencyState.searchItems.length) {
    messageEfficiencyUI.renderState(list, {
      kind: "empty",
      title: "没有找到相关会话",
      detail: "可以尝试缩短关键词，或使用联系人、宠物名称重新搜索。",
    });
    return true;
  }
  return false;
}

function ensureMessageEfficiencyControls() {
  const section = $("messages-section");
  if (!section) return;
  const columns = section.querySelectorAll("article.panel");
  const listPanel = columns[0];
  const detailPanel = columns[1];
  if (listPanel && !$("message-search-form")) {
    const form = messageEfficiencyNode("form", "", "message-search-form");
    form.id = "message-search-form";
    const input = document.createElement("input");
    input.id = "message-search-input";
    input.type = "search";
    input.maxLength = 100;
    input.placeholder = "搜索联系人、宠物或消息内容";
    input.autocomplete = "off";
    const clear = messageEfficiencyNode("button", "清除", "secondary");
    clear.type = "button";
    clear.id = "message-search-clear";
    clear.hidden = true;
    const result = messageEfficiencyNode("div", "", "message-search-result");
    result.id = "message-search-result";
    result.hidden = true;
    form.append(input, clear, result);
    const categoryLabel = $("message-category-filter")?.closest("label");
    if (categoryLabel) listPanel.insertBefore(form, categoryLabel);
    else listPanel.append(form);

    form.addEventListener("submit", (event) => event.preventDefault());
    input.addEventListener("input", () => {
      if (messageEfficiencyState.searchTimer) {
        window.clearTimeout(messageEfficiencyState.searchTimer);
      }
      messageEfficiencyState.searchTimer = window.setTimeout(() => {
        messageEfficiencyState.searchTimer = 0;
        runMessageSearch(input.value).catch(() => {});
      }, 260);
    });
    clear.addEventListener("click", () => {
      input.value = "";
      runMessageSearch("").catch(() => {});
      input.focus();
    });
  }

  if (detailPanel && !$("message-unread-navigation")) {
    const toolbar = messageEfficiencyNode("div", "", "message-unread-navigation");
    toolbar.id = "message-unread-navigation";
    toolbar.hidden = true;
    const status = messageEfficiencyNode("span", "", "message-unread-status");
    status.id = "message-unread-status";
    const first = messageEfficiencyNode("button", "第一条未读", "secondary compact");
    first.type = "button";
    first.id = "message-unread-first";
    const previous = messageEfficiencyNode("button", "上一条未读", "secondary compact");
    previous.type = "button";
    previous.id = "message-unread-previous";
    const next = messageEfficiencyNode("button", "下一条未读", "secondary compact");
    next.type = "button";
    next.id = "message-unread-next";
    const read = messageEfficiencyNode("button", "读到这里", "compact");
    read.type = "button";
    read.id = "message-unread-read";
    toolbar.append(status, first, previous, next, read);
    const detail = $("message-detail");
    if (detail) detailPanel.insertBefore(toolbar, detail);
    else detailPanel.append(toolbar);

    first.addEventListener("click", () => navigateUnreadMessage("first"));
    previous.addEventListener("click", () => navigateUnreadMessage("previous"));
    next.addEventListener("click", () => navigateUnreadMessage("next"));
    read.addEventListener("click", () => {
      markCurrentMessageRead().catch((error) => {
        setStatus(globalStatus, error.message, "error");
      });
    });
  }

  ensureQuickReplySettings();
  renderMessageSearchStatus();
}

function ensureQuickReplySettings() {
  if (!$("message-quick-reply-settings-button")) {
    const panel = $("message-compose-actions");
    if (panel) {
      const button = messageEfficiencyNode("button", "管理快捷回复", "ghost compact");
      button.id = "message-quick-reply-settings-button";
      button.type = "button";
      button.addEventListener("click", () => {
        openQuickReplySettings().catch((error) => {
          setStatus(globalStatus, error.message, "error");
        });
      });
      panel.append(button);
    }
  }
  if ($("message-quick-reply-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "message-quick-reply-dialog";
  dialog.className = "message-quick-reply-dialog";
  const form = messageEfficiencyNode("form", "", "message-quick-reply-form");
  form.method = "dialog";
  const heading = messageEfficiencyNode("div", "", "section-heading");
  const copy = messageEfficiencyNode("div");
  copy.append(
    messageEfficiencyNode("p", "QUICK REPLIES", "eyebrow"),
    messageEfficiencyNode("h2", "快捷回复设置"),
    messageEfficiencyNode(
      "p",
      "每行一条，当前顺序就是会话中展示顺序。点击快捷回复只会填入输入框，确认后再发送。",
      "hint",
    ),
  );
  const close = messageEfficiencyNode("button", "关闭", "secondary");
  close.type = "button";
  close.addEventListener("click", () => dialog.close());
  heading.append(copy, close);

  const categoryLabel = messageEfficiencyNode("label");
  categoryLabel.append(messageEfficiencyNode("span", "回复分类"));
  const category = document.createElement("select");
  category.id = "message-quick-reply-category";
  [
    ["direct", "普通私聊"],
    ["friend_pet", "好友宠物"],
    ["visit", "串门留言"],
    ["shared_care", "共同照料"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    category.append(option);
  });
  categoryLabel.append(category);
  const repliesLabel = messageEfficiencyNode("label");
  repliesLabel.append(messageEfficiencyNode("span", "回复内容（1 至 6 条）"));
  const replies = document.createElement("textarea");
  replies.id = "message-quick-reply-values";
  replies.rows = 7;
  replies.maxLength = 600;
  repliesLabel.append(replies);
  const status = messageEfficiencyNode("p", "", "status");
  status.id = "message-quick-reply-status";
  const actions = messageEfficiencyNode("div", "", "message-quick-reply-actions");
  const resetCategory = messageEfficiencyNode("button", "恢复本类默认", "secondary");
  resetCategory.type = "button";
  const resetAll = messageEfficiencyNode("button", "恢复全部默认", "secondary");
  resetAll.type = "button";
  const save = messageEfficiencyNode("button", "保存设置", "");
  save.type = "submit";
  actions.append(resetCategory, resetAll, save);
  form.append(heading, categoryLabel, repliesLabel, status, actions);
  dialog.append(form);
  document.body.append(dialog);

  category.addEventListener("change", renderQuickReplyEditor);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    save.disabled = true;
    try {
      const values = replies.value
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
      if (values.length < 1 || values.length > 6) {
        throw new Error("每类需要保留 1 至 6 条快捷回复。");
      }
      messageEfficiencyState.quickReplies = await api("/api/v1/message-quick-replies", {
        method: "PATCH",
        json: { categories: { [category.value]: values } },
      });
      renderQuickReplyEditor();
      renderConfiguredQuickReplies(messageEfficiencyState.activeConversation);
      setStatus(status, "快捷回复已同步到当前账户。", "success");
    } catch (error) {
      setStatus(status, error.message, "error");
    } finally {
      save.disabled = false;
    }
  });
  resetCategory.addEventListener("click", () => resetQuickReplies(category.value, status));
  resetAll.addEventListener("click", () => resetQuickReplies("all", status));
}

async function refreshMessageQuickReplies() {
  if (!accessToken) {
    messageEfficiencyState.quickReplies = null;
    return;
  }
  messageEfficiencyState.quickReplies = await api("/api/v1/message-quick-replies");
  renderConfiguredQuickReplies(messageEfficiencyState.activeConversation);
}

async function openQuickReplySettings() {
  ensureQuickReplySettings();
  if (!messageEfficiencyState.quickReplies) await refreshMessageQuickReplies();
  renderQuickReplyEditor();
  $("message-quick-reply-dialog")?.showModal();
}

function renderQuickReplyEditor() {
  const category = $("message-quick-reply-category")?.value || "direct";
  const values = messageEfficiencyState.quickReplies?.categories?.[category] || [];
  const textarea = $("message-quick-reply-values");
  if (textarea) textarea.value = values.join("\n");
}

async function resetQuickReplies(category, status) {
  const payload = await api("/api/v1/message-quick-replies/reset", {
    method: "POST",
    json: { category },
  });
  messageEfficiencyState.quickReplies = payload;
  renderQuickReplyEditor();
  renderConfiguredQuickReplies(messageEfficiencyState.activeConversation);
  setStatus(
    status,
    category === "all"
      ? "全部快捷回复已恢复默认。"
      : "本类快捷回复已恢复默认。",
    "success",
  );
}

function configuredQuickReplies(conversation) {
  const category = conversation?.category || "direct";
  return messageEfficiencyState.quickReplies?.categories?.[category]
    || messageEfficiencyState.quickReplies?.defaults?.[category]
    || [];
}

function renderConfiguredQuickReplies(conversation) {
  ensureQuickReplySettings();
  const panel = $("message-compose-actions");
  const quick = $("message-quick-replies");
  if (!panel || !quick) return;
  messageEfficiencyState.activeConversation = conversation || null;
  const writable = Boolean(conversation && conversation.kind === "direct");
  panel.hidden = !writable;
  quick.replaceChildren();
  if (!writable) return;
  configuredQuickReplies(conversation).forEach((reply) => {
    const button = messageEfficiencyNode("button", reply, "ghost compact");
    button.type = "button";
    button.addEventListener("click", () => {
      const input = $("message-compose-input");
      if (!input) return;
      input.value = reply;
      input.focus();
      setStatus(globalStatus, "快捷回复已填入，请确认后发送。", "success");
    });
    quick.append(button);
  });
}

async function runMessageSearch(rawQuery) {
  ensureMessageEfficiencyControls();
  const query = rawQuery.trim();
  const sameResult = Boolean(
    query
      && messageEfficiencyState.searchLoaded
      && messageEfficiencyState.searchResultQuery === query,
  );
  messageEfficiencyState.query = query;
  const clear = $("message-search-clear");
  if (clear) clear.hidden = !query;

  if (!query) {
    messageEfficiencyState.searchRequestId += 1;
    messageEfficiencyState.searchItems = [];
    messageEfficiencyState.searchCount = 0;
    messageEfficiencyState.searchLoaded = false;
    messageEfficiencyState.searchLoading = false;
    messageEfficiencyState.searchError = "";
    messageEfficiencyState.searchResultQuery = "";
    renderMessageSearchStatus();
    renderConversations();
    return null;
  }

  const requestId = messageEfficiencyState.searchRequestId + 1;
  messageEfficiencyState.searchRequestId = requestId;
  if (!sameResult) {
    messageEfficiencyState.searchItems = [];
    messageEfficiencyState.searchCount = 0;
    messageEfficiencyState.searchLoaded = false;
    messageEfficiencyState.searchResultQuery = "";
  }
  messageEfficiencyState.searchLoading = true;
  messageEfficiencyState.searchError = "";
  renderMessageSearchStatus();
  renderConversations();

  try {
    const payload = await api(
      `/api/v1/message-search?query=${encodeURIComponent(query)}&limit=100`,
    );
    if (
      messageEfficiencyState.searchRequestId !== requestId
      || messageEfficiencyState.query !== query
    ) {
      return null;
    }
    messageEfficiencyState.searchItems = Array.isArray(payload?.items)
      ? payload.items
      : [];
    messageEfficiencyState.searchCount = Number(payload?.count || 0);
    messageEfficiencyState.searchLoaded = true;
    messageEfficiencyState.searchResultQuery = query;
    return payload;
  } catch (error) {
    if (
      messageEfficiencyState.searchRequestId !== requestId
      || messageEfficiencyState.query !== query
    ) {
      return null;
    }
    messageEfficiencyState.searchError = error.message || "消息搜索失败";
    if (!sameResult) {
      messageEfficiencyState.searchLoaded = false;
      messageEfficiencyState.searchItems = [];
      messageEfficiencyState.searchCount = 0;
      messageEfficiencyState.searchResultQuery = "";
    }
    throw error;
  } finally {
    if (
      messageEfficiencyState.searchRequestId === requestId
      && messageEfficiencyState.query === query
    ) {
      messageEfficiencyState.searchLoading = false;
      renderMessageSearchStatus();
      renderConversations();
    }
  }
}

function messageSearchConversationValues() {
  return messageEfficiencyState.searchItems.map((item) => ({
    ...item.conversation,
    message_search_result: item,
  }));
}

function decorateMessageSearchResults(values) {
  if (!messageEfficiencyState.query || !messageEfficiencyState.searchLoaded) return;
  const list = $("conversation-list");
  if (!list) return;
  const cards = [...list.children].filter((item) => item.classList.contains("item-card"));
  cards.forEach((card, index) => {
    const result = values[index]?.message_search_result;
    if (!result) return;
    const labels = (result.matched_fields || [])
      .map((field) => messageMatchLabels[field] || field)
      .join("、");
    const detail = messageEfficiencyNode(
      "p",
      `${labels ? `匹配：${labels} · ` : ""}${result.snippet || "匹配到相关会话"}`,
      "message-search-match",
    );
    const actions = card.querySelector(".item-actions");
    if (actions) card.insertBefore(detail, actions);
    else card.append(detail);
  });
  if (messageEfficiencyState.searchError) {
    messageEfficiencyUI.renderInlineNotice(list, {
      kind: "error",
      title: "最新搜索结果暂未更新",
      detail: `${messageEfficiencyState.searchError} 当前仍显示上次成功搜索的结果。`,
      action: messageSearchRetryAction(),
    });
  }
}

async function loadUnreadNavigation(conversationId, currentSequence = 0) {
  const query = currentSequence > 0 ? `?current_sequence=${currentSequence}` : "";
  const payload = await api(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/unread-navigation${query}`,
  );
  if (messageEfficiencyState.activeConversation?.conversation_id !== conversationId) {
    return null;
  }
  messageEfficiencyState.unread = payload;
  renderUnreadNavigation();
  return payload;
}

function renderUnreadNavigation() {
  const toolbar = $("message-unread-navigation");
  if (!toolbar) return;
  const conversation = messageEfficiencyState.activeConversation;
  const unread = messageEfficiencyState.unread;
  toolbar.hidden = !conversation;
  if (!conversation) return;
  const current = unread?.current;
  const status = $("message-unread-status");
  if (status) {
    status.textContent = unread?.unread_count
      ? `${unread.unread_count} 条未读${current ? ` · 当前第 ${current.sequence_number} 条` : ""}`
      : "暂无未读消息";
  }
  $("message-unread-first").disabled = !unread?.first;
  $("message-unread-previous").disabled = !unread?.previous;
  $("message-unread-next").disabled = !unread?.next;
  $("message-unread-read").disabled = !current;
}

function renderMessageWindow(conversation, payload, anchorSequence = 0) {
  portalPhase1State.activeConversationId = conversation.conversation_id;
  $("message-detail-title").textContent = conversation.title;
  const detail = $("message-detail");
  detail.replaceChildren();
  const items = Array.isArray(payload?.items) ? payload.items : [];
  if (!items.length) empty(detail, "该会话暂无消息。");
  items.forEach((message) => {
    const card = messageEfficiencyNode("article", "", "message-bubble");
    card.dataset.messageId = message.message_id;
    card.dataset.sequence = String(message.sequence_number || 0);
    card.append(
      messageEfficiencyNode("strong", message.sender_display_name),
      messageEfficiencyNode("p", message.content),
      messageEfficiencyNode("span", phase1Time(message.created_at), "hint"),
    );
    if (Number(message.sequence_number) === Number(anchorSequence)) {
      card.classList.add("message-anchor");
    }
    detail.append(card);
  });
  const target = detail.querySelector(`[data-sequence="${Number(anchorSequence)}"]`);
  if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
  else if (detail.lastElementChild) detail.lastElementChild.scrollIntoView({ block: "end" });
  return items;
}

async function openConversationWithMessageEfficiency(conversation, anchorSequence = 0) {
  ensureMessageEfficiencyControls();
  messageEfficiencyState.activeConversation = conversation;
  messageEfficiencyState.unread = null;
  if (!messageEfficiencyState.quickReplies) {
    refreshMessageQuickReplies().catch(() => {});
  }

  let resolvedAnchor = Number(
    anchorSequence
      || conversation?.message_search_result?.matched_message?.sequence_number
      || 0,
  );
  const initialUnread = await loadUnreadNavigation(conversation.conversation_id, 0);
  if (!resolvedAnchor) {
    resolvedAnchor = Number(
      initialUnread?.current?.sequence_number
        || conversation.last_message?.sequence_number
        || 0,
    );
  }
  const query = resolvedAnchor > 0
    ? `?center_sequence=${resolvedAnchor}&before=45&after=45`
    : "?before=45&after=45";
  const payload = await api(
    `/api/v1/conversations/${encodeURIComponent(conversation.conversation_id)}/message-window${query}`,
  );
  messageEfficiencyState.activeSequence = resolvedAnchor;
  const messages = renderMessageWindow(conversation, payload, resolvedAnchor);
  await loadUnreadNavigation(conversation.conversation_id, resolvedAnchor);
  renderConversations();
  return { payload, messages, resolvedAnchor };
}

async function navigateUnreadMessage(direction) {
  const unread = messageEfficiencyState.unread;
  const conversation = messageEfficiencyState.activeConversation;
  if (!unread || !conversation) return;
  const message = direction === "first" ? unread.first : unread[direction];
  if (!message) return;
  await openConversation(conversation, {
    anchorSequence: Number(message.sequence_number || 0),
    source: "unread-navigation",
  });
}

async function markCurrentMessageRead() {
  const unread = messageEfficiencyState.unread;
  const conversation = messageEfficiencyState.activeConversation;
  const current = unread?.current;
  if (!current || !conversation) return;
  await api(`/api/v1/messages/${encodeURIComponent(current.message_id)}/read`, {
    method: "POST",
  });
  await refreshPhase1Messages();
  const refreshed = portalPhase1State.conversations.find(
    (item) => item.conversation_id === conversation.conversation_id,
  ) || conversation;
  const navigation = await loadUnreadNavigation(
    conversation.conversation_id,
    Number(current.sequence_number || 0),
  );
  const nextSequence = Number(navigation?.next?.sequence_number || 0);
  await openConversation(refreshed, {
    anchorSequence: nextSequence || Number(current.sequence_number || 0),
    source: "mark-read",
  });
  setStatus(globalStatus, "已将当前消息及之前内容标为已读。", "success");
}

async function refreshMessageEfficiencyView() {
  ensureMessageEfficiencyControls();
  if (!accessToken) return;
  if (!messageEfficiencyState.quickReplies) {
    await refreshMessageQuickReplies();
  }
  if (messageEfficiencyState.query) {
    await runMessageSearch(messageEfficiencyState.query);
  }
  if (messageEfficiencyState.activeConversation) {
    await loadUnreadNavigation(
      messageEfficiencyState.activeConversation.conversation_id,
      messageEfficiencyState.activeSequence,
    );
  }
}

function resetMessageEfficiencyState() {
  if (messageEfficiencyState.searchTimer) {
    window.clearTimeout(messageEfficiencyState.searchTimer);
    messageEfficiencyState.searchTimer = 0;
  }
  messageEfficiencyState.query = "";
  messageEfficiencyState.searchItems = [];
  messageEfficiencyState.searchCount = 0;
  messageEfficiencyState.searchLoaded = false;
  messageEfficiencyState.searchLoading = false;
  messageEfficiencyState.searchError = "";
  messageEfficiencyState.searchResultQuery = "";
  messageEfficiencyState.searchRequestId += 1;
  messageEfficiencyState.activeConversation = null;
  messageEfficiencyState.activeSequence = 0;
  messageEfficiencyState.unread = null;
  messageEfficiencyState.quickReplies = null;
  const input = $("message-search-input");
  const clear = $("message-search-clear");
  if (input) input.value = "";
  if (clear) clear.hidden = true;
  renderMessageSearchStatus();
  const dialog = $("message-quick-reply-dialog");
  if (dialog?.open) dialog.close();
  renderUnreadNavigation();
  renderConfiguredQuickReplies(null);
}

portalRuntime.registerFeature({
  id: "message-efficiency",
  label: "消息搜索与快捷回复",
  order: 250,
  mount: ensureMessageEfficiencyControls,
  onFilterConversations: (context) => {
    if (!messageEfficiencyState.query) return;
    context.values = messageEfficiencyState.searchLoaded
      ? messageSearchConversationValues().filter(
        (item) => context.filter === "all" || item.category === context.filter,
      )
      : [];
  },
  onConversationsRenderComplete: ({ conversations }) => {
    renderMessageSearchStatus();
    if (renderMessageSearchListState()) return;
    decorateMessageSearchResults(conversations);
  },
  onConversationOpenRequest: async (context) => {
    const anchorSequence = Number(context.options?.anchorSequence || 0);
    const result = await openConversationWithMessageEfficiency(
      context.conversation,
      anchorSequence,
    );
    context.handled = true;
    context.result = result.payload;
    context.messages = result.messages;
    context.options = {
      ...context.options,
      anchorSequence: result.resolvedAnchor,
    };
  },
  onMessageActionsRenderComplete: ({ conversation }) => {
    renderConfiguredQuickReplies(conversation);
  },
  onSectionEnter: async ({ sectionId }) => {
    if (sectionId === "messages-section") {
      await refreshMessageEfficiencyView();
    }
  },
  onRealtime: async () => {
    if (!accessToken) return;
    if (messageEfficiencyState.query) {
      await runMessageSearch(messageEfficiencyState.query);
    }
    if (messageEfficiencyState.activeConversation) {
      await loadUnreadNavigation(
        messageEfficiencyState.activeConversation.conversation_id,
        messageEfficiencyState.activeSequence,
      );
    }
  },
  onLogout: resetMessageEfficiencyState,
});
