"use strict";

const pendingItemsState = {
  count: 0,
  urgentCount: 0,
  items: [],
  loaded: false,
  loading: false,
  error: "",
  timerId: 0,
};

const pendingItemsUI = window.MyPetsPortalUI;
if (!pendingItemsUI) throw new Error("MyPets 门户 UI 组件未加载");

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
  refresh.addEventListener("click", () => {
    pendingItemsUI.runAction({
      control: refresh,
      statusNode: globalStatus,
      busyLabel: "正在刷新…",
      successMessage: "待处理事项已刷新。",
      task: () => refreshPendingItems({ showLoading: true }),
    });
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
  await portalRuntime.requestRefresh({ reason: "pending-action" });
  setStatus(globalStatus, payload.message || "待处理事项已更新。", "success");
}

function completePendingItemsRender() {
  portalRuntime.applyFeatureHook("onPendingItemsRenderComplete", {
    items: pendingItemsState.items,
    count: pendingItemsState.count,
    urgentCount: pendingItemsState.urgentCount,
  });
}

function pendingRetryAction() {
  return {
    label: "重新读取",
    busyLabel: "正在读取…",
    onClick: () => refreshPendingItems({ showLoading: true }),
  };
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
  pendingItemsUI.setRegionBusy(list, pendingItemsState.loading);

  if (pendingItemsState.loading && !pendingItemsState.loaded) {
    pendingItemsUI.renderState(list, {
      kind: "loading",
      title: "正在读取待处理事项",
      detail: "正在汇总好友申请、共同照料、串门申请和到期提醒。",
    });
    return;
  }
  if (pendingItemsState.error && !pendingItemsState.loaded) {
    pendingItemsUI.renderState(list, {
      kind: "error",
      title: "待处理事项读取失败",
      detail: pendingItemsState.error,
      action: pendingRetryAction(),
    });
    return;
  }

  list.replaceChildren();
  pendingItemsUI.clearState(list);
  if (!pendingItemsState.items.length) {
    pendingItemsUI.renderState(list, {
      kind: "empty",
      title: "当前没有待处理事项",
      detail: "新的邀请、申请和到期提醒会集中显示在这里。",
    });
    completePendingItemsRender();
    return;
  }

  pendingItemsState.items.forEach((item) => {
    const card = node(
      "article",
      "",
      `pending-item-card${item.priority === "urgent" ? " urgent" : ""}`,
    );
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
      actions.append(
        actionButton(
          pendingActionLabels[action] || action,
          async () => actOnPendingItem(item, action),
          className,
        ),
      );
    });
    card.append(body, actions);
    list.append(card);
  });

  if (pendingItemsState.error) {
    pendingItemsUI.renderInlineNotice(list, {
      kind: "error",
      title: "最新状态暂未更新",
      detail: `${pendingItemsState.error} 当前仍显示上次成功读取的内容。`,
      action: pendingRetryAction(),
    });
  }
  completePendingItemsRender();
}

async function refreshPendingItems(options = {}) {
  if (!accessToken) {
    pendingItemsState.count = 0;
    pendingItemsState.urgentCount = 0;
    pendingItemsState.items = [];
    pendingItemsState.loaded = false;
    pendingItemsState.loading = false;
    pendingItemsState.error = "";
    renderPendingItems();
    return;
  }

  const showLoading = options.showLoading ?? !pendingItemsState.loaded;
  pendingItemsState.loading = true;
  pendingItemsState.error = "";
  if (showLoading || !pendingItemsState.loaded) renderPendingItems();
  else pendingItemsUI.setRegionBusy($("pending-items-list"), true);

  try {
    const payload = await api("/api/v1/pending-items?limit=100");
    pendingItemsState.count = Number(payload?.count || 0);
    pendingItemsState.urgentCount = Number(payload?.urgent_count || 0);
    pendingItemsState.items = Array.isArray(payload?.items) ? payload.items : [];
    pendingItemsState.loaded = true;
    startPendingItemsPolling();
  } catch (error) {
    pendingItemsState.error = error.message || "待处理事项读取失败";
    throw error;
  } finally {
    pendingItemsState.loading = false;
    renderPendingItems();
  }
}

function startPendingItemsPolling() {
  if (pendingItemsState.timerId || !accessToken) return;
  pendingItemsState.timerId = window.setInterval(() => {
    if (!accessToken) return;
    refreshPendingItems({ showLoading: false }).catch(() => {});
  }, 60000);
}

function stopPendingItemsPolling() {
  if (!pendingItemsState.timerId) return;
  window.clearInterval(pendingItemsState.timerId);
  pendingItemsState.timerId = 0;
}

portalRuntime.registerFeature({
  id: "pending-items",
  label: "待处理事项",
  order: 200,
  mount: () => {
    ensurePendingItemsPanel();
    renderPendingItems();
  },
  onRefreshComplete: async () => {
    await refreshPendingItems({ showLoading: !pendingItemsState.loaded });
    startPendingItemsPolling();
  },
  onSectionEnter: ({ sectionId }) => {
    if (sectionId === "dashboard-section") renderPendingItems();
  },
  onRealtime: async () => {
    if (accessToken) await refreshPendingItems({ showLoading: false });
  },
  onLogout: () => {
    stopPendingItemsPolling();
    pendingItemsState.count = 0;
    pendingItemsState.urgentCount = 0;
    pendingItemsState.items = [];
    pendingItemsState.loaded = false;
    pendingItemsState.loading = false;
    pendingItemsState.error = "";
    renderPendingItems();
  },
});
