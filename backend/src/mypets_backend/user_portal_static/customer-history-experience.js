"use strict";

const customerHistoryState = {
  kind: "all",
  days: 30,
  count: 0,
  items: [],
  loaded: false,
};

const customerHistoryKindLabels = {
  friend_request: "好友申请",
  caregiver_invitation: "共同照料",
  visit: "串门",
  reminder: "提醒",
};

const customerHistoryActionLabels = {
  accepted: "已接受",
  rejected: "已拒绝",
  cancelled: "已取消",
  completed: "已完成",
  snoozed: "稍后提醒",
  dismissed: "已忽略",
  returned: "已返家",
  expired: "已过期",
};

function historyNode(tag, text = "", className = "") {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function ensureCustomerHistoryWorkspace() {
  let section = $("history-section");
  if (section) return section;

  const navigation = document.querySelector(".main-tabs");
  if (navigation && !navigation.querySelector('[data-section="history-section"]')) {
    const button = historyNode("button", "处理记录", "main-tab portal-more-item");
    button.type = "button";
    button.dataset.section = "history-section";
    const moreMenu = $("portal-more-navigation")?.querySelector(".portal-more-menu");
    if (moreMenu) moreMenu.insertBefore(button, moreMenu.lastElementChild || null);
    else navigation.append(button);
  }

  const appView = $("app-view");
  if (!appView) return null;
  section = historyNode("section", "", "workspace customer-history-workspace");
  section.id = "history-section";
  section.hidden = true;
  section.tabIndex = -1;

  const panel = historyNode("article", "", "panel customer-history-panel");
  const heading = historyNode("div", "", "section-heading customer-history-heading");
  const copy = historyNode("div");
  copy.append(
    historyNode("p", "HISTORY", "eyebrow"),
    historyNode("h2", "处理记录"),
    historyNode(
      "p",
      "好友、共同照料、串门和提醒的处理结果集中保留，可再次打开相关详情。",
      "hint",
    ),
  );
  const badge = historyNode("span", "尚未读取", "badge");
  badge.id = "customer-history-count";
  heading.append(copy, badge);

  const filters = historyNode("form", "", "customer-history-filters");
  filters.id = "customer-history-filters";
  const kindLabel = historyNode("label");
  kindLabel.append(historyNode("span", "记录类型"));
  const kindSelect = document.createElement("select");
  kindSelect.id = "customer-history-kind";
  [
    ["all", "全部类型"],
    ["friend_request", "好友申请"],
    ["caregiver_invitation", "共同照料"],
    ["visit", "串门"],
    ["reminder", "提醒"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    kindSelect.append(option);
  });
  kindLabel.append(kindSelect);

  const timeLabel = historyNode("label");
  timeLabel.append(historyNode("span", "时间范围"));
  const timeSelect = document.createElement("select");
  timeSelect.id = "customer-history-days";
  [
    ["7", "最近 7 天"],
    ["30", "最近 30 天"],
    ["90", "最近 90 天"],
    ["365", "最近一年"],
    ["0", "全部记录"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (value === "30") option.selected = true;
    timeSelect.append(option);
  });
  timeLabel.append(timeSelect);

  const refresh = historyNode("button", "刷新记录", "secondary");
  refresh.type = "submit";
  filters.append(kindLabel, timeLabel, refresh);
  filters.addEventListener("submit", async (event) => {
    event.preventDefault();
    customerHistoryState.kind = kindSelect.value || "all";
    customerHistoryState.days = Number(timeSelect.value || 0);
    refresh.disabled = true;
    try {
      await refreshCustomerHistory();
      setStatus(globalStatus, "处理记录已刷新。", "success");
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      refresh.disabled = false;
    }
  });
  kindSelect.addEventListener("change", () => filters.requestSubmit());
  timeSelect.addEventListener("change", () => filters.requestSubmit());

  const list = historyNode("div", "", "customer-history-list");
  list.id = "customer-history-list";
  panel.append(heading, filters, list);
  section.append(panel);
  const accountSection = $("account-section");
  if (accountSection) appView.insertBefore(section, accountSection);
  else appView.append(section);
  renderCustomerHistory();
  return section;
}

function customerHistoryQuery() {
  const params = new URLSearchParams({
    kind: customerHistoryState.kind,
    limit: "200",
  });
  if (customerHistoryState.days > 0) {
    params.set("days", String(customerHistoryState.days));
  } else {
    params.set("start", "1970-01-01T00:00:00+00:00");
  }
  return params.toString();
}

async function refreshCustomerHistory() {
  ensureCustomerHistoryWorkspace();
  if (!accessToken) {
    customerHistoryState.count = 0;
    customerHistoryState.items = [];
    customerHistoryState.loaded = false;
    renderCustomerHistory();
    return;
  }
  const payload = await api(`/api/v1/customer-history?${customerHistoryQuery()}`);
  customerHistoryState.count = Number(payload?.count || 0);
  customerHistoryState.items = Array.isArray(payload?.items) ? payload.items : [];
  customerHistoryState.loaded = true;
  renderCustomerHistory();
}

function historyMeta(item) {
  const parts = [localTime(item.occurred_at)];
  if (item.actor_display_name) parts.push(`处理人：${item.actor_display_name}`);
  if (item.pet_name) parts.push(`宠物：${item.pet_name}`);
  if (item.counterparty_display_name) {
    parts.push(`相关用户：${item.counterparty_display_name}`);
  }
  return parts.join(" · ");
}

async function openCustomerHistoryTarget(item) {
  if (item.target_kind === "shared_care") {
    portalRuntime.navigate("friends-section", { source: "history-target" });
    await refreshSocial();
    const invitations = $("incoming-invitations") || $("outgoing-invitations");
    invitations?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  await activateCustomerTarget(item.target_kind, item.target_id, item.target_label);
}

function renderCustomerHistory() {
  ensureCustomerHistoryWorkspace();
  const count = $("customer-history-count");
  const list = $("customer-history-list");
  if (!count || !list) return;
  count.textContent = customerHistoryState.loaded
    ? `${customerHistoryState.count} 条`
    : "尚未读取";
  list.replaceChildren();
  if (!customerHistoryState.loaded) {
    list.append(
      historyNode(
        "div",
        "进入处理记录后，可按类型和时间查看已完成的操作。",
        "empty-state",
      ),
    );
    return;
  }
  if (!customerHistoryState.items.length) {
    list.append(historyNode("div", "当前筛选范围内没有处理记录。", "empty-state"));
    return;
  }
  customerHistoryState.items.forEach((item) => {
    const card = historyNode(
      "article",
      "",
      `customer-history-card action-${item.action}`,
    );
    const top = historyNode("div", "", "customer-history-card-top");
    const labels = historyNode("div", "", "customer-history-labels");
    labels.append(
      historyNode(
        "span",
        customerHistoryKindLabels[item.kind] || item.kind,
        "customer-history-kind",
      ),
      historyNode(
        "span",
        customerHistoryActionLabels[item.action] || item.action,
        "customer-history-action",
      ),
    );
    top.append(labels, historyNode("time", localTime(item.occurred_at), "customer-history-time"));
    const body = historyNode("div", "", "customer-history-body");
    body.append(
      historyNode("strong", item.title),
      historyNode("p", item.detail),
      historyNode("p", historyMeta(item), "hint"),
    );
    const actions = historyNode("div", "", "customer-history-actions");
    const open = historyNode("button", item.target_label || "查看详情", "secondary");
    open.type = "button";
    open.addEventListener("click", async () => {
      open.disabled = true;
      try {
        await openCustomerHistoryTarget(item);
      } catch (error) {
        setStatus(globalStatus, error.message, "error");
      } finally {
        open.disabled = false;
      }
    });
    actions.append(open);
    card.append(top, body, actions);
    list.append(card);
  });
}

portalRuntime.registerFeature({
  id: "customer-history",
  label: "处理记录",
  order: 300,
  mount: () => {
    ensureCustomerHistoryWorkspace();
    renderCustomerHistory();
  },
  onSectionEnter: async ({ sectionId }) => {
    if (sectionId === "history-section" && accessToken) {
      await refreshCustomerHistory();
    }
  },
  onRealtime: async () => {
    const section = $("history-section");
    if (accessToken && section && !section.hidden && customerHistoryState.loaded) {
      await refreshCustomerHistory();
    }
  },
  onLogout: () => {
    customerHistoryState.count = 0;
    customerHistoryState.items = [];
    customerHistoryState.loaded = false;
    renderCustomerHistory();
  },
});
