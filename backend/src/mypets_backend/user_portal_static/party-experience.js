"use strict";

const partyExperienceState = {
  invitations: [],
  open: [],
  active: [],
  history: [],
  detail: null,
};

const partyStatusLabels = {
  open: "等待开始",
  active: "进行中",
  completed: "已结束",
  cancelled: "已取消",
};

const partyMemberLabels = {
  invited: "待回应",
  accepted: "已确认",
  declined: "已谢绝",
  joined: "在场",
  left: "已离场",
  completed: "已完成",
  expired: "已失效",
};

const partyInteractionLabels = {
  greet_circle: "围圈打招呼",
  play_together: "一起玩耍",
  group_photo: "留下合影记录",
  rest_together: "一起休息",
};

function partyRandom(prefix) {
  const value = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
  return `${prefix}-${value}`;
}

function partyManagedPets() {
  if (!dashboard || !Array.isArray(dashboard.pets)) return [];
  return dashboard.pets.filter((item) => (
    ["owner", "co_owner"].includes(item.relation?.role)
    && ["home", "resting"].includes(item.pet?.presence)
  ));
}

function partyActivateSection() {
  if (typeof activatePortalSection === "function") {
    activatePortalSection("parties-section");
    return;
  }
  document.querySelectorAll(".workspace").forEach((section) => {
    section.hidden = section.id !== "parties-section";
  });
  document.querySelectorAll(".main-tab[data-section]").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === "parties-section");
  });
}

function ensurePartyExperience() {
  if ($("parties-section")) return;
  const nav = document.querySelector(".main-tabs");
  const app = $("app-view");
  if (!nav || !app) return;

  const tab = node("button", "宠物聚会", "main-tab");
  tab.type = "button";
  tab.dataset.section = "parties-section";
  tab.addEventListener("click", async () => {
    partyActivateSection();
    try {
      await refreshParties();
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    }
  });
  const settingsTab = [...nav.querySelectorAll(".main-tab")]
    .find((item) => item.dataset.section === "account-section");
  if (settingsTab) nav.insertBefore(tab, settingsTab);
  else nav.append(tab);

  const section = node("section", "", "workspace party-workspace");
  section.id = "parties-section";
  section.hidden = true;

  const createPanel = node("article", "", "panel party-create-panel");
  const createHeading = node("div", "", "section-heading");
  const createCopy = node("div");
  createCopy.append(
    node("p", "MULTI-PET PARTY", "eyebrow"),
    node("h2", "发起宠物小聚会"),
    node("p", "每个账户带一只宠物，整场最多四只；桌面常驻宠物仍严格限制为两只。", "hint"),
  );
  const refresh = node("button", "刷新聚会", "secondary");
  refresh.type = "button";
  refresh.addEventListener("click", async () => {
    refresh.disabled = true;
    try {
      await refreshParties();
      setStatus(globalStatus, "聚会数据已刷新。", "success");
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      refresh.disabled = false;
    }
  });
  createHeading.append(createCopy, refresh);

  const form = node("form", "", "grid-form party-create-form");
  form.id = "party-create-form";
  const petLabel = node("label", "当前宠物");
  const petInput = document.createElement("input");
  petInput.id = "party-host-pet";
  petInput.disabled = true;
  petLabel.append(petInput);
  const titleLabel = node("label", "聚会名称");
  const titleInput = document.createElement("input");
  titleInput.id = "party-title";
  titleInput.maxLength = 80;
  titleInput.value = "宠物小聚会";
  titleInput.required = true;
  titleLabel.append(titleInput);
  const countLabel = node("label", "最多宠物数");
  const countSelect = document.createElement("select");
  countSelect.id = "party-max-members";
  [2, 3, 4].forEach((count) => {
    const option = node("option", `${count} 只`);
    option.value = String(count);
    if (count === 4) option.selected = true;
    countSelect.append(option);
  });
  countLabel.append(countSelect);
  const durationLabel = node("label", "聚会时长");
  const durationSelect = document.createElement("select");
  durationSelect.id = "party-duration";
  [30, 60, 120, 180].forEach((minutes) => {
    const option = node("option", `${minutes} 分钟`);
    option.value = String(minutes);
    if (minutes === 60) option.selected = true;
    durationSelect.append(option);
  });
  durationLabel.append(durationSelect);
  const noteLabel = node("label", "聚会说明");
  const noteInput = document.createElement("input");
  noteInput.id = "party-note";
  noteInput.maxLength = 200;
  noteInput.placeholder = "可选，仅用于参与者查看";
  noteLabel.append(noteInput);
  const submit = node("button", "创建聚会");
  submit.id = "party-create-submit";
  submit.type = "submit";
  form.append(petLabel, titleLabel, countLabel, durationLabel, noteLabel, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = selectedPortalPet();
    if (!selected || !["owner", "co_owner"].includes(selected.relation.role)) {
      setStatus(globalStatus, "请选择自己管理且当前在家的宠物。", "error");
      return;
    }
    submit.disabled = true;
    try {
      await api("/api/v1/parties", {
        method: "POST",
        json: {
          host_pet_id: selected.pet.pet_id,
          title: titleInput.value.trim(),
          note: noteInput.value.trim(),
          max_members: Number(countSelect.value),
          duration_minutes: Number(durationSelect.value),
        },
      });
      noteInput.value = "";
      await refreshParties();
      setStatus(globalStatus, "聚会已创建，可以逐位邀请好友。", "success");
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      submit.disabled = false;
    }
  });
  createPanel.append(createHeading, form);

  const summary = node("div", "", "party-summary-grid");
  [
    ["party-invitation-count", "待回应邀请"],
    ["party-open-count", "等待开始"],
    ["party-active-count", "进行中"],
    ["party-history-count", "最近记录"],
  ].forEach(([id, label]) => {
    const card = node("div", "", "summary-card");
    card.append(node("span", label));
    const value = node("strong", "0");
    value.id = id;
    card.append(value);
    summary.append(card);
  });

  const invitationsPanel = partyListPanel("收到的聚会邀请", "party-invitations");
  const openPanel = partyListPanel("等待开始的聚会", "party-open-list");
  const activePanel = partyListPanel("单场景聚会", "party-active-list");
  const detailPanel = partyListPanel("聚会时间线", "party-detail");
  detailPanel.id = "party-detail-panel";
  detailPanel.hidden = true;
  const historyPanel = partyListPanel("最近聚会记录", "party-history-list");

  section.append(
    createPanel,
    summary,
    invitationsPanel,
    openPanel,
    activePanel,
    detailPanel,
    historyPanel,
  );
  app.append(section);
}

function partyListPanel(title, listId) {
  const panel = node("article", "", "panel party-list-panel");
  const heading = node("div", "", "section-heading");
  heading.append(node("div", "", "party-heading-copy"));
  heading.firstChild.append(node("p", "PARTY", "eyebrow"), node("h2", title));
  const list = node("div", "", "card-list party-list");
  list.id = listId;
  panel.append(heading, list);
  return panel;
}

function updatePartyCreateState() {
  const selected = selectedPortalPet();
  const input = $("party-host-pet");
  const button = $("party-create-submit");
  if (!input || !button) return;
  const allowed = Boolean(
    selected
    && ["owner", "co_owner"].includes(selected.relation.role)
    && ["home", "resting"].includes(selected.pet.presence),
  );
  input.value = selected ? `${selected.pet.name} · ${selected.pet.presence}` : "未选择宠物";
  button.disabled = !allowed;
}

async function refreshParties() {
  ensurePartyExperience();
  if (!accessToken) return;
  const payload = await api("/api/v1/parties");
  partyExperienceState.invitations = payload.invitations || [];
  partyExperienceState.open = payload.open || [];
  partyExperienceState.active = payload.active || [];
  partyExperienceState.history = payload.history || [];
  renderParties();
}

function renderParties() {
  ensurePartyExperience();
  updatePartyCreateState();
  $("party-invitation-count").textContent = String(partyExperienceState.invitations.length);
  $("party-open-count").textContent = String(partyExperienceState.open.length);
  $("party-active-count").textContent = String(partyExperienceState.active.length);
  $("party-history-count").textContent = String(partyExperienceState.history.length);
  renderPartyInvitations();
  renderPartyOpen();
  renderPartyActive();
  renderPartyHistory();
}

function partyMeta(party) {
  return [
    `${partyStatusLabels[party.status] || party.status} · ${party.accepted_count}/${party.max_members} 只已确认`,
    `${party.duration_minutes} 分钟 · 桌面常驻上限 ${party.desktop_window_limit} 只`,
    party.note || "未填写聚会说明",
  ];
}

function partyMemberSummary(party) {
  return party.members.map((member) => {
    const petName = member.pet ? member.pet.name : "尚未选择宠物";
    return `${member.account.display_name} · ${petName} · ${partyMemberLabels[member.status] || member.status}`;
  });
}

function managedPetSelect() {
  const select = document.createElement("select");
  select.className = "party-pet-select";
  const pets = partyManagedPets();
  pets.forEach((item) => {
    const option = node("option", item.pet.name);
    option.value = item.pet.pet_id;
    select.append(option);
  });
  if (!pets.length) {
    const option = node("option", "没有可参加的在家宠物");
    option.value = "";
    select.append(option);
    select.disabled = true;
  }
  return select;
}

function renderPartyInvitations() {
  const container = $("party-invitations");
  container.replaceChildren();
  if (!partyExperienceState.invitations.length) {
    empty(container, "当前没有待回应的聚会邀请。");
    return;
  }
  partyExperienceState.invitations.forEach((party) => {
    const built = itemCard(party.title, [...partyMeta(party), ...partyMemberSummary(party)]);
    const select = managedPetSelect();
    built.card.insertBefore(select, built.actions);
    built.actions.append(
      actionButton("接受并选择宠物", async () => {
        if (!select.value) throw new Error("没有可参加聚会的在家宠物。");
        await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/accept`, {
          method: "POST",
          json: { pet_id: select.value },
        });
        await refreshParties();
        setStatus(globalStatus, "已接受聚会邀请。", "success");
      }),
      actionButton("谢绝", async () => {
        await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/decline`, { method: "POST" });
        await refreshParties();
        setStatus(globalStatus, "已谢绝聚会邀请。", "success");
      }, "secondary"),
      partyDetailButton(party.party_id),
    );
    container.append(built.card);
  });
}

function renderPartyOpen() {
  const container = $("party-open-list");
  container.replaceChildren();
  if (!partyExperienceState.open.length) {
    empty(container, "没有等待开始的聚会。");
    return;
  }
  partyExperienceState.open.forEach((party) => {
    const built = itemCard(party.title, [...partyMeta(party), ...partyMemberSummary(party)]);
    if (party.can_invite) {
      const invite = node("form", "", "inline-form party-invite-form");
      const input = document.createElement("input");
      input.placeholder = "输入好友精确用户名";
      input.minLength = 3;
      input.maxLength = 64;
      input.required = true;
      const submit = node("button", "邀请好友");
      submit.type = "submit";
      invite.append(input, submit);
      invite.addEventListener("submit", async (event) => {
        event.preventDefault();
        submit.disabled = true;
        try {
          await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/invitations`, {
            method: "POST",
            json: { username: input.value.trim() },
          });
          input.value = "";
          await refreshParties();
          setStatus(globalStatus, "聚会邀请已发送。", "success");
        } catch (error) {
          setStatus(globalStatus, error.message, "error");
        } finally {
          submit.disabled = false;
        }
      });
      built.card.insertBefore(invite, built.actions);
    }
    if (party.can_start) {
      built.actions.append(actionButton("开始聚会", async () => {
        await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/start`, { method: "POST" });
        await Promise.all([refreshParties(), refreshDashboard()]);
        setStatus(globalStatus, "聚会已经开始，全部成员进入一个场景。", "success");
      }));
    }
    if (party.can_cancel) {
      built.actions.append(actionButton("取消聚会", async () => {
        await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/cancel`, { method: "POST" });
        await refreshParties();
        setStatus(globalStatus, "聚会已取消。", "success");
      }, "secondary"));
    }
    built.actions.append(partyDetailButton(party.party_id));
    container.append(built.card);
  });
}

function renderPartyActive() {
  const container = $("party-active-list");
  container.replaceChildren();
  if (!partyExperienceState.active.length) {
    empty(container, "当前没有进行中的聚会。");
    return;
  }
  partyExperienceState.active.forEach((party) => {
    const scene = node("article", "", "party-scene-card");
    const header = node("div", "", "party-scene-header");
    const copy = node("div");
    copy.append(
      node("h3", party.title),
      node("p", `全部 ${party.joined_count} 只宠物在一个聚会面板中呈现；桌面窗口绝不超过 ${party.desktop_window_limit} 只。`, "hint"),
    );
    header.append(copy, node("span", "单场景", "badge"));
    const members = node("div", "", "party-member-grid");
    party.members.filter((member) => member.status === "joined").forEach((member) => {
      const card = node("div", "", "party-member-card");
      card.append(
        node("div", "🐾", "party-member-avatar"),
        node("strong", member.pet?.name || "宠物"),
        node("span", member.account.display_name, "hint"),
        node("span", member.role === "host" ? "发起宠物" : "聚会成员", "badge"),
      );
      members.append(card);
    });
    const actions = node("div", "", "item-actions party-scene-actions");
    if (party.can_interact) {
      Object.entries(partyInteractionLabels).forEach(([action, label]) => {
        actions.append(actionButton(label, async () => {
          await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/interactions/${action}`, {
            method: "POST",
            json: { idempotency_key: partyRandom(action) },
          });
          await openPartyDetail(party.party_id);
          setStatus(globalStatus, `${label}互动已记录。`, "success");
        }, "secondary"));
      });
    }
    const current = party.members.find((member) => member.is_current_account);
    if (current?.can_leave) {
      actions.append(actionButton("提前离场", async () => {
        await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/leave`, { method: "POST" });
        await Promise.all([refreshParties(), refreshDashboard()]);
        setStatus(globalStatus, "宠物已离开聚会并返回家中。", "success");
      }, "secondary"));
    }
    if (party.can_end) {
      actions.append(actionButton("结束聚会", async () => {
        await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/end`, { method: "POST" });
        await Promise.all([refreshParties(), refreshDashboard()]);
        setStatus(globalStatus, "聚会已结束，仍在场宠物已返回家中。", "success");
      }, "danger"));
    }
    actions.append(partyDetailButton(party.party_id));
    scene.append(header, members, actions);
    container.append(scene);
  });
}

function renderPartyHistory() {
  const container = $("party-history-list");
  container.replaceChildren();
  if (!partyExperienceState.history.length) {
    empty(container, "暂无聚会历史记录。");
    return;
  }
  partyExperienceState.history.slice(0, 30).forEach((party) => {
    const built = itemCard(party.title, [...partyMeta(party), ...partyMemberSummary(party)]);
    built.actions.append(partyDetailButton(party.party_id));
    container.append(built.card);
  });
}

function partyDetailButton(partyId) {
  return actionButton("查看时间线", async () => {
    await openPartyDetail(partyId);
  }, "secondary");
}

async function openPartyDetail(partyId) {
  const detail = await api(`/api/v1/parties/${encodeURIComponent(partyId)}`);
  partyExperienceState.detail = detail;
  renderPartyDetail();
}

function renderPartyDetail() {
  const panel = $("party-detail-panel");
  const container = $("party-detail");
  const detail = partyExperienceState.detail;
  if (!panel || !container || !detail) return;
  panel.hidden = false;
  container.replaceChildren();
  const summary = itemCard(detail.title, [...partyMeta(detail), ...partyMemberSummary(detail)]);
  container.append(summary.card);
  const timeline = node("ol", "", "party-timeline");
  (detail.timeline || []).forEach((entry) => {
    const item = node("li", "", `party-timeline-entry kind-${entry.kind}`);
    item.append(
      node("strong", entry.title),
      node("p", entry.detail),
      node("span", `${new Date(entry.occurred_at).toLocaleString()}${entry.actor_display_name ? ` · ${entry.actor_display_name}` : ""}`, "hint"),
    );
    timeline.append(item);
  });
  if (!timeline.children.length) timeline.append(node("li", "暂无时间线记录。", "empty-state"));
  container.append(timeline);
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

const partyBaseRefreshAll = refreshAll;
refreshAll = async function refreshAllWithParties() {
  await partyBaseRefreshAll();
  await refreshParties();
};

const partyBaseRenderDashboard = renderDashboard;
renderDashboard = function renderDashboardWithPartyState() {
  partyBaseRenderDashboard();
  updatePartyCreateState();
};

ensurePartyExperience();
if (accessToken) {
  setTimeout(() => {
    refreshParties().catch((error) => {
      if (accessToken) setStatus(globalStatus, error.message, "error");
    });
  }, 0);
}
