"use strict";

const visitState = {
  visits: { incoming_requests: [], outgoing_requests: [], active: [], history: [] },
  friendPets: [],
  friendAccountId: "",
};

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
  if (values.some((item) => item.value === previous && !item.disabled)) select.value = previous;
}

function ownedAvailablePets() {
  if (!dashboard || !Array.isArray(dashboard.pets)) return [];
  return dashboard.pets.filter((item) =>
    item && item.can_configure && ["home", "resting"].includes(item.pet.presence),
  );
}

function renderVisitComposer() {
  const visitorSelect = $("visit-visitor-pet");
  const friendSelect = $("visit-friend");
  const hostPetSelect = $("visit-host-pet");
  const submit = $("send-visit-request");
  const previousVisitor = visitorSelect.value;
  const previousFriend = friendSelect.value;
  const previousHostPet = hostPetSelect.value;

  const visitors = ownedAvailablePets().map((item) => ({
    value: item.pet.pet_id,
    label: `${item.pet.name} · ${presenceLabel(item.pet.presence)} · ${roleLabel(item.relation.role)}`,
  }));
  replaceOptions(visitorSelect, visitors, visitors.length ? "选择来访宠物" : "没有可外出的自有宠物", previousVisitor);

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
  }
  const hostPets = visitState.friendPets.map((pet) => ({
    value: pet.pet_id,
    label: `${pet.name} · ${presenceLabel(pet.presence)} · ${visibilityLabel(pet.visibility)}`,
    disabled: !["home", "resting"].includes(pet.presence),
  }));
  replaceOptions(
    hostPetSelect,
    hostPets,
    friendSelect.value ? (hostPets.length ? "选择接待宠物" : "该好友没有可接待的可见宠物") : "先选择好友",
    previousHostPet,
  );

  const canSubmit = Boolean(visitorSelect.value && friendSelect.value && hostPetSelect.value);
  submit.disabled = !canSubmit;
}

function petStatusCard(pet, label) {
  const card = node("section", "", "visit-pet-card");
  const heading = node("div", "", "visit-pet-heading");
  heading.append(node("span", label, "visit-pet-label"), node("span", presenceLabel(pet.presence), "badge"));
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

async function mutateVisit(visit, action) {
  await api(`/api/v1/visits/${encodeURIComponent(visit.visit_id)}/${action}`, { method: "POST" });
  const changesPresence = action === "accept" || action === "recall";
  await Promise.all([refreshVisits(), changesPresence ? refreshDashboard() : Promise.resolve()]);
  renderVisitComposer();
  setStatus(globalStatus, {
    accept: "串门申请已接受，来访宠物已进入串门状态。",
    reject: "串门申请已拒绝。",
    cancel: "串门申请已取消。",
    recall: "来访宠物已召回并恢复在家。",
  }[action] || "串门状态已更新。", "success");
}

function renderRequestList(containerId, items, mode) {
  const container = $(containerId);
  container.replaceChildren();
  if (!items.length) {
    empty(container, mode === "incoming" ? "没有待处理的收到申请。" : "没有待处理的发出申请。");
    return;
  }
  items.forEach((visit) => {
    const built = itemCard(
      `${visit.visitor_pet.name} → ${visit.host_pet.name}`,
      [`${visitStatusLabel(visit.status)} · ${visit.duration_minutes} 分钟`, ...visitMeta(visit)],
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
      built.actions.append(actionButton("取消申请", () => mutateVisit(visit, "cancel"), "secondary"));
    }
    container.append(built.card);
  });
}

function renderActiveVisits() {
  const container = $("active-visits");
  container.replaceChildren();
  const items = visitState.visits.active || [];
  $("active-visit-count").textContent = String(items.length);
  if (!items.length) {
    empty(container, "当前没有正在进行的串门。");
    return;
  }
  items.forEach((visit) => {
    const card = node("article", "", "active-visit-card");
    const heading = node("div", "", "section-heading compact-heading");
    heading.append(node("strong", `${visit.visitor_pet.name} 正在拜访 ${visit.host_pet.name}`), node("span", visitStatusLabel(visit.status), "badge"));
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
  container.replaceChildren();
  const items = visitState.visits.history || [];
  if (!items.length) {
    empty(container, "尚无串门历史。");
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
}

async function refreshVisits() {
  visitState.visits = await api("/api/v1/visits");
  renderVisits();
}

async function loadFriendPets(accountId) {
  const value = accountId.trim();
  visitState.friendAccountId = value;
  visitState.friendPets = [];
  renderVisitComposer();
  if (!value) return;
  visitState.friendPets = await api(`/api/v1/friends/${encodeURIComponent(value)}/pets`);
  renderVisitComposer();
}

async function refreshVisitWorkspace({ includeDependencies = false } = {}) {
  setStatus(globalStatus, "正在刷新串门数据…");
  if (includeDependencies) await Promise.all([refreshDashboard(), refreshSocial()]);
  await refreshVisits();
  const selectedFriend = $("visit-friend").value;
  if (selectedFriend) await loadFriendPets(selectedFriend);
  setStatus(globalStatus, "串门申请、状态卡和历史已刷新。", "success");
}

$("visit-friend").addEventListener("change", async (event) => {
  try {
    await loadFriendPets(event.target.value);
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("visit-visitor-pet").addEventListener("change", renderVisitComposer);
$("visit-host-pet").addEventListener("change", renderVisitComposer);

$("visit-request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const friendId = $("visit-friend").value;
  const friendEntry = (socialState.friends || []).find((item) => item.friend.account_id === friendId);
  if (!friendEntry) {
    setStatus(globalStatus, "请选择有效好友。", "error");
    return;
  }
  try {
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
    await refreshVisits();
    setStatus(globalStatus, "串门申请已发送，等待好友处理。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("refresh-visits").addEventListener("click", async () => {
  try {
    await refreshVisitWorkspace({ includeDependencies: true });
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

document.querySelectorAll(".main-tab").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".workspace").forEach((section) => {
      section.hidden = section.id !== button.dataset.section;
    });
    if (button.dataset.section !== "visits-section" || !accessToken) return;
    try {
      await refreshVisitWorkspace({ includeDependencies: true });
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    }
  });
});
