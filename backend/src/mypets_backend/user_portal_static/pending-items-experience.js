"use strict";

const pendingItemsState = {
  count: 0,
  urgentCount: 0,
  items: [],
};

const pendingKindLabels = {
  friend_request: "好友申请",
  caregiver_invitation: "共同照料",
  visit_request: "串门申请",
  reminder_due: "到期提醒",
};

const pendingActionLabels = {
  accept: "接受",
  reject: "拒绝",
  complete: "完成",
  snooze: "10 分钟后提醒",
  dismiss: "忽略",
};

function pendingTime(value) {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function ensurePendingItemsPanel() {
  let panel = $("pending-items-panel");
  if (panel) return panel;
  const dashboardSection = $("dashboard-section");
  if (!dashboardSection) return null;

  panel = node("article", "", "panel pending-items-panel");
  panel.id = "pending-items-panel";
  const heading = node("div", "", "section-heading");
  const copy = node("div");
  copy.append(
    node("p", "TO DO", "eyebrow"),
    node("h2", "待处理事项"),
    node("p", "好友、共同照料、串门和提醒集中在这里处理。", "hint"),
  );
  const controls = node("div", "", "pending-heading-controls");
  const badge = node("span", "0 项", "badge");
  badge.id = "pending-items-count";
  const refresh = node("button", "刷新", "secondary");
  refresh.type = "button";
  refresh.addEventListener("click", async () => {
    refresh.disabled = true;
    try {
      await refreshPendingItems();
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      refresh.disabled = false;
    }
  });
  controls.append(badge, refresh);
  heading.append(copy, controls);
  const list = node("div", "", "pending-items-list");
  list.id = "pending-items-list";
  panel.append(heading, list);

  const firstGrid = dashboardSection.querySelector(".two-column");
  if (firstGrid) firstGrid.insertAdjacentElement("afterend", panel);
  else dashboardSection.append(panel);

  const summaryGrid = dashboardSection.querySelector(".summary-grid");
  if (summaryGrid && !$("dashboard-pending-items")) {
    const summary = node("div", "", "summary-card pending-summary-card");
    summary.append(node("span", "待处理事项"));
    const value = node("strong", "0");
    value.id = "dashboard-pending-items";
    summary.append(value);
    summaryGrid.prepend(summary);
  }
  return panel;
}

function pendingIdempotencyKey(item, action) {
  const random = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
  return `portal-pending-${item.kind}-${action}-${random}`;
}

async function actOnPendingItem(item, action) {
  const path = `/api/v1/pending-items/${encodeURIComponent(item.kind)}/${encodeURIComponent(item.item_id)}/${encodeURIComponent(action)}`;
  const payload = await api(path, {
    method: "POST",
    headers: { "Idempotency-Key": pendingIdempotencyKey(item, action) },
    json: { snooze_minutes: 10 },
  });
  await refreshAll();
  setStatus(globalStatus, payload.message || "待处理事项已更新。", "success");
}

function renderPendingItems() {
  ensurePendingItemsPanel();
  const count = $("pending-items-count");
  const dashboardCount = $("dashboard-pending-items");
  if (count) {
    count.textContent = pendingItemsState.urgentCount
      ? `${pendingItemsState.count} 项 · ${pendingItemsState.urgentCount} 项优先`
      : `${pendingItemsState.count} 项`;
    count.classList.toggle("urgent", pendingItemsState.urgentCount > 0);
  }
  if (dashboardCount) dashboardCount.textContent = String(pendingItemsState.count);

  const list = $("pending-items-list");
  if (!list) return;
  list.replaceChildren();
  if (!pendingItemsState.items.length) {
    empty(list, "当前没有需要处理的事项。新的邀请、申请和到期提醒会集中显示在这里。");
    return;
  }

  pendingItemsState.items.forEach((item) => {
    const card = node("article", "", `pending-item-card${item.priority === "urgent" ? " urgent" : ""}`);
    const body = node("div", "", "pending-item-body");
    const heading = node("div", "", "pending-item-title-row");
    heading.append(
      node("span", pendingKindLabels[item.kind] || item.kind, "pending-kind"),
      node("strong", item.title),
    );
    const detail = node("p", item.detail, "pending-item-detail");
    const metaParts = [];
    if (item.due_at) metaParts.push(`到期：${pendingTime(item.due_at)}`);
    else if (item.occurred_at) metaParts.push(`收到：${pendingTime(item.occurred_at)}`);
    if (item.pet_name) metaParts.push(`宠物：${item.pet_name}`);
    const meta = node("p", metaParts.join(" · "), "hint");
    body.append(heading, detail, meta);

    const actions = node("div", "", "pending-item-actions");
    item.actions.forEach((action) => {
      const className = action === "reject" || action === "dismiss" ? "secondary" : "";
      actions.append(actionButton(pendingActionLabels[action] || action, async () => {
        await actOnPendingItem(item, action);
      }, className));
    });
    card.append(body, actions);
    list.append(card);
  });
}

async function refreshPendingItems() {
  if (!accessToken) {
    pendingItemsState.count = 0;
    pendingItemsState.urgentCount = 0;
    pendingItemsState.items = [];
    renderPendingItems();
    return;
  }
  const payload = await api("/api/v1/pending-items?limit=100");
  pendingItemsState.count = Number(payload?.count || 0);
  pendingItemsState.urgentCount = Number(payload?.urgent_count || 0);
  pendingItemsState.items = Array.isArray(payload?.items) ? payload.items : [];
  renderPendingItems();
}

const baseRefreshAllForPendingItems = refreshAll;
refreshAll = async function refreshAllWithPendingItems() {
  await baseRefreshAllForPendingItems();
  await refreshPendingItems();
};

ensurePendingItemsPanel();
window.setInterval(() => {
  if (accessToken) refreshPendingItems().catch(() => {});
}, 60000);
