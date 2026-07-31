"use strict";

const visitState = {
  visits: { incoming_requests: [], outgoing_requests: [], active: [], history: [] },
  friendPets: [],
  friendAccountId: "",
  friendPetsLoading: false,
  friendPetsError: "",
  loaded: false,
  loading: false,
  error: "",
};

const visitUI = window.MyPetsPortalUI;
if (!visitUI) throw new Error("MyPets 门户 UI 组件未加载");

function emptyVisitPayload() {
  return { incoming_requests: [], outgoing_requests: [], active: [], history: [] };
}

function visitStatusLabel(value) {
  return {
    pending: "等待处理",
    active: "正在串门",
    rejected: "已拒绝",
    cancelled: "已取消",
    completed: "已返家",
    recalled: "已召回",
    expired: "申请已过期",
  }[value] || value;
}

function presenceLabel(value) {
  return {
    home: "在家",
    resting: "休息中",
    visiting: "串门中",
  }[value] || value;
}

function completionLabel(value) {
  return {
    visit_auto_returned: "按时自动返家",
    visit_recalled: "主人主动召回",
    visit_rejected: "接待方拒绝",
    visit_cancelled: "申请方取消",
    visit_request_expired: "24 小时未处理",
    account_blocked: "账户关系已屏蔽",
    friend_removed: "好友关系已解除",
  }[value] || value || "—";
}

function localTime(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function replaceOptions(select, values, placeholder, previous = "") {
  select.replaceChildren();
  const first = node("option", placeholder);
  first.value = "";
  select.append(first);
  values.forEach(({ value, label, disabled = false }) => {
    const option = node("option", label);
    option.value = value;
    option.disabled = disabled;
    select.append(option);
  });
  if (values.some((item) => item.value === previous && !item.disabled)) {
    select.value = previous;
  }
}

function ownedAvailablePets() {
  if (!dashboard || !Array.isArray(dashboard.pets)) return [];
  return dashboard.pets.filter(
    (item) => item
      && item.can_configure
      && ["home", "resting"].includes(item.pet.presence),
  );
}

function ensureVisitWorkspaceState() {
  let state = $("visit-workspace-state");
  if (state) return state;
  const panel = document.querySelector("#visits-section .visit-compose-panel");
  if (!panel) return null;
  state = node("div", "", "visit-workspace-state");
  state.id = "visit-workspace-state";
  state.hidden = true;
  panel.append(state);
  return state;
}

function visitRetryAction() {
  return {
    label: "重新读取",
    busyLabel: "正在读取…",
    onClick: () => refreshVisitWorkspace({
      includeDependencies: true,
      announce: false,
      showLoading: true,
    }),
  };
}

function renderVisitWorkspaceState() {
  const state = ensureVisitWorkspaceState();
  if (!state) return;
  if (visitState.loaded && visitState.loading) {
    state.hidden = false;
    visitUI.renderState(state, {
      kind: "loading",
      compact: true,
      title: "正在更新串门状态",
      detail: "当前列表仍可查看，最新申请和返家状态正在同步。",
    });
    return;
  }
  if (visitState.loaded && visitState.error) {
    state.hidden = false;
    visitUI.renderState(state, {
      kind: "error",
      compact: true,
      title: "最新串门状态暂未更新",
      detail: `${visitState.error} 当前仍显示上次成功读取的内容。`,
      action: visitRetryAction(),
    });
    return;
  }
  state.replaceChildren();
  visitUI.clearState(state);
  state.hidden = true;
}

function renderVisitComposer() {
  const visitorSelect = $("visit-visitor-pet");
  const friendSelect = $("visit-friend");
  const hostPetSelect = $("visit-host-pet");
  const submit = $("send-visit-request");
  if (!visitorSelect || !friendSelect || !hostPetSelect || !submit) return;
  const previousVisitor = visitorSelect.value;
  const previousFriend = friendSelect.value;
  const previousHostPet = hostPetSelect.value;

  const visitors = ownedAvailablePets().map((item) => ({
    value: item.pet.pet_id,
    label: `${item.pet.name} · ${presenceLabel(item.pet.presence)} · ${roleLabel(item.relation.role)}`,
  }));
  replaceOptions(
    visitorSelect,
    visitors,
    visitors.length ? "选择来访宠物" : "没有可外出的自有宠物",
    previousVisitor,
  );

  const friends = Array.isArray(socialState.friends) ? socialState.friends : [];
  replaceOptions(
    friendSelect,
    friends.map((item) => ({
      value: item.friend.account_id,
      label: `${item.friend.display_name}（@${item.friend.username}）`,
    })),
    friends.length ? "选择接待好友" : "暂无好友",
    previousFriend || visitState.friendAccountId,
  );

  if (friendSelect.value !== visitState.friendAccountId) {
    visitState.friendPets = [];
    visitState.friendAccountId = friendSelect.value;
    visitState.friendPetsError = "";
  }
  const hostPets = visitState.friendPets.map((pet) => ({
    value: pet.pet_id,
    label: `${pet.name} · ${presenceLabel(pet.presence)} · ${visibilityLabel(pet.visibility)}`,
    disabled: !["home", "resting"].includes(pet.presence),
  }));
  let hostPlaceholder = "先选择好友";
  if (friendSelect.value) {
    if (visitState.friendPetsLoading) hostPlaceholder = "正在读取好友宠物";
    else if (visitState.friendPetsError) hostPlaceholder = "好友宠物读取失败，请重新选择";
    else hostPlaceholder = hostPets.length
      ? "选择接待宠物"
      : "该好友没有可接待的可见宠物";
  }
  replaceOptions(hostPetSelect, hostPets, hostPlaceholder, previousHostPet);
  hostPetSelect.disabled = visitState.friendPetsLoading || !friendSelect.value;

  submit.disabled = visitState.loading || !Boolean(
    visitorSelect.value && friendSelect.value && hostPetSelect.value,
  );
}

function petStatusCard(pet, label) {
  const card = node("section", "", "visit-pet-card");
  const heading = node("div", "", "visit-pet-heading");
  heading.append(
    node("span", label, "visit-pet-label"),
    node("span", presenceLabel(pet.presence), "badge"),
  );
  card.append(heading, node("strong", pet.name, "visit-pet-name"));
  const facts = node("div", "", "visit-pet-facts");
  facts.append(
    node("span", `成长：${pet.growth_stage} / Lv.${pet.growth_level}`),
    node("span", `心情：${pet.mood}/100`),
  );
  card.append(facts);
  const meter = node("meter");
  meter.min = "0";
  meter.max = "100";
  meter.value = String(Math.max(0, Math.min(100, Number(pet.mood) || 0)));
  meter.setAttribute("aria-label", `${pet.name} 心情`);
  card.append(meter);
  return card;
}

function visitPair(visit) {
  const pair = node("div", "", "visit-pair");
  pair.append(
    petStatusCard(visit.visitor_pet, "来访宠物"),
    node("div", "→", "visit-arrow"),
    petStatusCard(visit.host_pet, "接待宠物"),
  );
  return pair;
}

function visitMeta(visit) {
  const values = [
    `申请人：${visit.requester.display_name}（@${visit.requester.username}）`,
    `接待人：${visit.host.display_name}（@${visit.host.username}）`,
    `时长：${visit.duration_minutes} 分钟`,
  ];
  if (visit.note) values.push(`留言：${visit.note}`);
  if (visit.started_at) values.push(`开始：${localTime(visit.started_at)}`);
  if (visit.scheduled_end_at) values.push(`预计返家：${localTime(visit.scheduled_end_at)}`);
  return values;
}

function renderVisitCollectionState(container, copy) {
  if (visitState.loading) {
    visitUI.renderState(container, {
      kind: "loading",
      title: copy.loadingTitle,
      detail: copy.loadingDetail,
    });
    return true;
  }
  if (visitState.error) {
    visitUI.renderState(container, {
      kind: "error",
      title: copy.errorTitle,
      detail: visitState.error,
      action: visitRetryAction(),
    });
    return true;
  }
  visitUI.renderState(container, {
    kind: "idle",
    title: copy.idleTitle,
    detail: "进入串门页面后读取最新状态。",
  });
  return true;
}

async function mutateVisit(visit, action) {
  await api(`/api/v1/visits/${encodeURIComponent(visit.visit_id)}/${action}`, {
    method: "POST",
  });
  const changesPresence = action === "accept" || action === "recall";
  await refreshVisitWorkspace({
    includeDependencies: changesPresence,
    announce: false,
    showLoading: false,
  });
  setStatus(
    globalStatus,
    {
      accept: "串门申请已接受，来访宠物已进入串门状态。",
      reject: "串门申请已拒绝。",
      cancel: "串门申请已取消。",
      recall: "来访宠物已召回并恢复在家。",
    }[action] || "串门状态已更新。",
    "success",
  );
}

function renderRequestList(containerId, items, mode) {
  const container = $(containerId);
  if (!container) return;
  if (!visitState.loaded) {
    renderVisitCollectionState(container, {
      idleTitle: mode === "incoming" ? "收到的申请尚未读取" : "发出的申请尚未读取",
      loadingTitle: mode === "incoming" ? "正在读取收到的申请" : "正在读取发出的申请",
      loadingDetail: "正在同步尚未处理的串门申请。",
      errorTitle: "串门申请读取失败",
    });
    return;
  }
  container.replaceChildren();
  visitUI.clearState(container);
  if (!items.length) {
    visitUI.renderState(container, {
      kind: "empty",
      title: mode === "incoming" ? "没有待处理的收到申请" : "没有待处理的发出申请",
      detail: mode === "incoming"
        ? "好友发来新的串门申请后会显示在这里。"
        : "你发出的串门申请会在这里等待好友处理。",
    });
    return;
  }
  items.forEach((visit) => {
    const built = itemCard(
      `${visit.visitor_pet.name} → ${visit.host_pet.name}`,
      [
        `${visitStatusLabel(visit.status)} · ${visit.duration_minutes} 分钟`,
        ...visitMeta(visit),
      ],
    );
    built.card.classList.add("visit-request-card");
    built.card.insertBefore(visitPair(visit), built.actions);
    if (mode === "incoming" && visit.can_accept) {
      built.actions.append(
        actionButton("接受", () => mutateVisit(visit, "accept")),
        actionButton("拒绝", () => mutateVisit(visit, "reject"), "secondary"),
      );
    }
    if (mode === "outgoing" && visit.can_cancel) {
      built.actions.append(
        actionButton("取消申请", () => mutateVisit(visit, "cancel"), "secondary"),
      );
    }
    container.append(built.card);
  });
}

function renderActiveVisits() {
  const container = $("active-visits");
  if (!container) return;
  const items = visitState.visits.active || [];
  $("active-visit-count").textContent = String(items.length);
  if (!visitState.loaded) {
    renderVisitCollectionState(container, {
      idleTitle: "正在串门状态尚未读取",
      loadingTitle: "正在读取串门状态",
      loadingDetail: "正在确认宠物是否已经出发或返家。",
      errorTitle: "正在串门状态读取失败",
    });
    return;
  }
  container.replaceChildren();
  visitUI.clearState(container);
  if (!items.length) {
    visitUI.renderState(container, {
      kind: "empty",
      title: "当前没有正在进行的串门",
      detail: "接受串门申请后，来访宠物状态会显示在这里。",
    });
    return;
  }
  items.forEach((visit) => {
    const card = node("article", "", "active-visit-card");
    const heading = node("div", "", "section-heading compact-heading");
    heading.append(
      node("strong", `${visit.visitor_pet.name} 正在拜访 ${visit.host_pet.name}`),
      node("span", visitStatusLabel(visit.status), "badge"),
    );
    card.append(heading, visitPair(visit));
    const meta = node("div", "", "item-meta visit-summary");
    visitMeta(visit).forEach((line) => meta.append(node("div", line)));
    card.append(meta);
    if (visit.can_recall) {
      const actions = node("div", "", "item-actions");
      actions.append(actionButton("立即召回", () => mutateVisit(visit, "recall"), "danger"));
      card.append(actions);
    }
    container.append(card);
  });
}

function renderVisitHistory() {
  const container = $("visit-history");
  if (!container) return;
  const items = visitState.visits.history || [];
  if (!visitState.loaded) {
    renderVisitCollectionState(container, {
      idleTitle: "串门历史尚未读取",
      loadingTitle: "正在读取串门历史",
      loadingDetail: "正在加载最近完成、召回或取消的串门记录。",
      errorTitle: "串门历史读取失败",
    });
    return;
  }
  container.replaceChildren();
  visitUI.clearState(container);
  if (!items.length) {
    visitUI.renderState(container, {
      kind: "empty",
      title: "尚无串门历史",
      detail: "完成第一场串门后，可以在这里查看返家和处理记录。",
    });
    return;
  }
  items.forEach((visit) => {
    const built = itemCard(
      `${visit.visitor_pet.name} → ${visit.host_pet.name}`,
      [
        `${visitStatusLabel(visit.status)} · ${completionLabel(visit.completion_reason)}`,
        `创建：${localTime(visit.created_at)} · 完成：${localTime(visit.completed_at)}`,
        ...visitMeta(visit),
      ],
    );
    built.card.classList.add("visit-history-card");
    built.card.insertBefore(visitPair(visit), built.actions);
    container.append(built.card);
  });
}

function renderVisits() {
  const incoming = visitState.visits.incoming_requests || [];
  const outgoing = visitState.visits.outgoing_requests || [];
  $("incoming-visit-count").textContent = String(incoming.length);
  $("outgoing-visit-count").textContent = String(outgoing.length);
  renderVisitComposer();
  renderRequestList("incoming-visits", incoming, "incoming");
  renderRequestList("outgoing-visits", outgoing, "outgoing");
  renderActiveVisits();
  renderVisitHistory();
  renderVisitWorkspaceState();
  portalRuntime.applyFeatureHook("onVisitsRenderComplete", {
    visits: visitState.visits,
    loaded: visitState.loaded,
    loading: visitState.loading,
    error: visitState.error,
  });
}

async function loadFriendPets(accountId) {
  const value = accountId.trim();
  const sameFriend = value === visitState.friendAccountId;
  visitState.friendAccountId = value;
  if (!sameFriend) visitState.friendPets = [];
  visitState.friendPetsLoading = Boolean(value);
  visitState.friendPetsError = "";
  renderVisitComposer();
  if (!value) {
    visitState.friendPetsLoading = false;
    renderVisitComposer();
    return [];
  }
  try {
    const pets = await api(`/api/v1/friends/${encodeURIComponent(value)}/pets`);
    if (visitState.friendAccountId !== value) return [];
    visitState.friendPets = Array.isArray(pets) ? pets : [];
    return visitState.friendPets;
  } catch (error) {
    if (visitState.friendAccountId === value) {
      visitState.friendPetsError = error.message || "好友宠物读取失败";
    }
    throw error;
  } finally {
    if (visitState.friendAccountId === value) {
      visitState.friendPetsLoading = false;
      renderVisitComposer();
    }
  }
}

async function refreshVisitWorkspace({
  includeDependencies = false,
  announce = true,
  showLoading = !visitState.loaded,
} = {}) {
  if (!accessToken) {
    resetVisitState();
    return null;
  }
  visitState.loading = true;
  visitState.error = "";
  if (showLoading || !visitState.loaded) renderVisits();
  else {
    ["incoming-visits", "outgoing-visits", "active-visits", "visit-history"]
      .forEach((id) => visitUI.setRegionBusy($(id), true));
    renderVisitComposer();
    renderVisitWorkspaceState();
  }
  if (announce) setStatus(globalStatus, "正在刷新串门数据…");
  try {
    if (includeDependencies) {
      await Promise.all([refreshDashboard(), refreshSocial()]);
    }
    const payload = await api("/api/v1/visits");
    visitState.visits = payload || emptyVisitPayload();
    visitState.loaded = true;
    const selectedFriend = $("visit-friend")?.value || visitState.friendAccountId;
    if (selectedFriend) await loadFriendPets(selectedFriend);
    if (announce) {
      setStatus(globalStatus, "串门申请、状态卡和历史已刷新。", "success");
    }
    return payload;
  } catch (error) {
    visitState.error = error.message || "串门数据读取失败";
    throw error;
  } finally {
    visitState.loading = false;
    renderVisits();
  }
}

function installVisitActions() {
  $("visit-friend")?.addEventListener("change", (event) => {
    loadFriendPets(event.target.value).catch((error) => {
      setStatus(globalStatus, error.message, "error");
    });
  });
  $("visit-visitor-pet")?.addEventListener("change", renderVisitComposer);
  $("visit-host-pet")?.addEventListener("change", renderVisitComposer);

  $("visit-request-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const friendId = $("visit-friend").value;
    const friendEntry = (socialState.friends || []).find(
      (item) => item.friend.account_id === friendId,
    );
    if (!friendEntry) {
      setStatus(globalStatus, "请选择有效好友。", "error");
      return;
    }
    visitUI.runAction({
      control: $("send-visit-request"),
      statusNode: globalStatus,
      busyLabel: "正在发送…",
      task: async () => {
        await api("/api/v1/visits", {
          method: "POST",
          json: {
            host_username: friendEntry.friend.username,
            visitor_pet_id: $("visit-visitor-pet").value,
            host_pet_id: $("visit-host-pet").value,
            duration_minutes: Number($("visit-duration").value),
            note: $("visit-note").value.trim(),
          },
        });
        $("visit-note").value = "";
        await refreshVisitWorkspace({ announce: false, showLoading: false });
        setStatus(globalStatus, "串门申请已发送，等待好友处理。", "success");
      },
    });
  });

  $("refresh-visits")?.addEventListener("click", () => {
    visitUI.runAction({
      control: $("refresh-visits"),
      statusNode: globalStatus,
      busyLabel: "正在刷新…",
      successMessage: "串门申请、状态卡和历史已刷新。",
      task: () => refreshVisitWorkspace({
        includeDependencies: true,
        announce: false,
        showLoading: true,
      }),
    });
  });
}

function resetVisitState() {
  visitState.visits = emptyVisitPayload();
  visitState.friendPets = [];
  visitState.friendAccountId = "";
  visitState.friendPetsLoading = false;
  visitState.friendPetsError = "";
  visitState.loaded = false;
  visitState.loading = false;
  visitState.error = "";
  renderVisits();
}

portalRuntime.registerFeature({
  id: "visits",
  label: "宠物串门",
  order: 350,
  mount: () => {
    installVisitActions();
    ensureVisitWorkspaceState();
    renderVisits();
  },
  onRefreshComplete: renderVisitComposer,
  onSectionEnter: async ({ sectionId, source }) => {
    if (
      sectionId === "visits-section"
      && accessToken
      && source !== "startup"
      && source !== "anonymous"
    ) {
      await refreshVisitWorkspace({
        includeDependencies: true,
        announce: false,
        showLoading: !visitState.loaded,
      });
    }
  },
  onRealtime: async () => {
    const section = $("visits-section");
    if (!accessToken || !section || section.hidden) return;
    await refreshVisitWorkspace({
      includeDependencies: true,
      announce: false,
      showLoading: false,
    });
  },
  onLogout: resetVisitState,
});
