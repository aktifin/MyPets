"use strict";

const partyExperienceState = {
  invitations: [],
  open: [],
  active: [],
  history: [],
  detail: null,
  activities: {},
};

const partyStatusLabels = {
  open: "等待好友",
  active: "欢乐进行中",
  completed: "温馨结束",
  cancelled: "本次已取消",
};

const partyMemberLabels = {
  invited: "等待回应",
  accepted: "已经准备好",
  declined: "这次不参加",
  joined: "正在聚会",
  left: "已回到家",
  completed: "聚会完成",
  expired: "邀请已结束",
};

const partyInteractionLabels = {
  greet_circle: "围圈打招呼",
  play_together: "一起玩耍",
  group_photo: "留下合影",
  rest_together: "一起休息",
};

const partyActivityPresentation = {
  greet_circle: { icon: "👋", title: "大家正在互相打招呼", member: "开心打招呼" },
  play_together: { icon: "🧶", title: "它们正在一起玩耍", member: "一起玩耍" },
  group_photo: { icon: "📷", title: "宠物们刚刚留下了合影", member: "等待合影" },
  rest_together: { icon: "☁️", title: "它们正在安静地一起休息", member: "一起休息" },
  waiting: { icon: "🐾", title: "等待好友宠物到齐", member: "等待开始" },
  free_play: { icon: "✨", title: "宠物们正在自由玩耍", member: "自由玩耍" },
  ended: { icon: "🏠", title: "宠物们已经安全回家", member: "已经回家" },
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

function partyActivateSection(source = "party") {
  return portalRuntime.navigate("parties-section", { source });
}

function ensurePartyExperience() {
  if ($("parties-section")) return;
  const nav = document.querySelector(".main-tabs");
  const app = $("app-view");
  if (!nav || !app) return;

  const tab = node("button", "宠物聚会", "main-tab");
  tab.type = "button";
  tab.dataset.section = "parties-section";
  const settingsTab = [...nav.querySelectorAll(".main-tab")]
    .find((item) => item.dataset.section === "account-section");
  if (settingsTab) nav.insertBefore(tab, settingsTab);
  else nav.append(tab);

  const section = node("section", "", "workspace party-workspace");
  section.id = "parties-section";
  section.hidden = true;
  section.tabIndex = -1;

  const hero = node("article", "", "panel party-hero");
  const heroCopy = node("div", "", "party-hero-copy");
  heroCopy.append(
    node("p", "PET SOCIAL", "eyebrow"),
    node("h2", "让宠物和好友一起玩"),
    node(
      "p",
      "发起一场最多四只宠物的小聚会。所有成员集中在一个轻量场景中，不会增加桌面宠物窗口。",
      "hint",
    ),
  );
  const heroActions = node("div", "", "party-hero-actions");
  const createShortcut = node("button", "发起新聚会");
  createShortcut.type = "button";
  createShortcut.addEventListener("click", () => {
    $("party-create-panel")?.scrollIntoView({ behavior: "smooth", block: "center" });
    $("party-title")?.focus();
  });
  const refresh = node("button", "刷新聚会", "secondary");
  refresh.type = "button";
  refresh.addEventListener("click", async () => {
    refresh.disabled = true;
    try {
      await refreshParties("manual");
      setStatus(globalStatus, "聚会动态已刷新。", "success");
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      refresh.disabled = false;
    }
  });
  heroActions.append(createShortcut, refresh);
  hero.append(heroCopy, heroActions);

  const createPanel = node("article", "", "panel party-create-panel");
  createPanel.id = "party-create-panel";
  const createHeading = node("div", "", "section-heading");
  const createCopy = node("div");
  createCopy.append(
    node("p", "START A PARTY", "eyebrow"),
    node("h2", "发起宠物小聚会"),
    node("p", "每位好友带一只自己管理的宠物，邀请成功后即可一起开始。", "hint"),
  );
  createHeading.append(createCopy);

  const form = node("form", "", "grid-form party-create-form");
  form.id = "party-create-form";
  const petLabel = node("label", "带哪只宠物参加");
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
  const countLabel = node("label", "邀请规模");
  const countSelect = document.createElement("select");
  countSelect.id = "party-max-members";
  [2, 3, 4].forEach((count) => {
    const option = node("option", `${count} 只宠物`);
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
  const noteLabel = node("label", "给好友的话");
  const noteInput = document.createElement("input");
  noteInput.id = "party-note";
  noteInput.maxLength = 200;
  noteInput.placeholder = "例如：周末一起玩一会儿";
  noteLabel.append(noteInput);
  const submit = node("button", "创建聚会");
  submit.id = "party-create-submit";
  submit.type = "submit";
  form.append(petLabel, titleLabel, countLabel, durationLabel, noteLabel, submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = selectedPortalPet();
    if (
      !selected
      || !["owner", "co_owner"].includes(selected.relation.role)
      || !["home", "resting"].includes(selected.pet.presence)
    ) {
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
      await refreshParties("created");
      setStatus(globalStatus, "聚会已创建，现在可以邀请好友宠物。", "success");
      $("party-open-list")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      submit.disabled = false;
    }
  });
  createPanel.append(createHeading, form);

  const summary = node("div", "", "party-summary-grid");
  [
    ["party-invitation-count", "等我回应"],
    ["party-open-count", "等待开始"],
    ["party-active-count", "正在玩耍"],
    ["party-history-count", "温馨回忆"],
  ].forEach(([id, label]) => {
    const card = node("div", "", "summary-card party-summary-card");
    card.append(node("span", label));
    const value = node("strong", "0");
    value.id = id;
    card.append(value);
    summary.append(card);
  });

  const invitationsPanel = partyListPanel(
    "好友发来的邀请",
    "选择一只在家的宠物接受邀请。",
    "party-invitations",
  );
  const openPanel = partyListPanel(
    "等待开始",
    "邀请好友、确认成员，然后开始聚会。",
    "party-open-list",
  );
  const activePanel = partyListPanel(
    "正在进行的聚会",
    "全部宠物都在同一个聚会场景中。",
    "party-active-list",
  );
  const detailPanel = partyListPanel(
    "聚会故事",
    "按时间回看邀请、互动和返家记录。",
    "party-detail",
  );
  detailPanel.id = "party-detail-panel";
  detailPanel.hidden = true;
  const historyPanel = partyListPanel(
    "最近的聚会回忆",
    "已经结束的聚会仍可查看完整故事。",
    "party-history-list",
  );

  section.append(
    hero,
    summary,
    invitationsPanel,
    openPanel,
    activePanel,
    detailPanel,
    historyPanel,
    createPanel,
  );
  app.append(section);
}

function partyListPanel(title, detail, listId) {
  const panel = node("article", "", "panel party-list-panel");
  const heading = node("div", "", "section-heading");
  const copy = node("div", "", "party-heading-copy");
  copy.append(
    node("p", "PARTY", "eyebrow"),
    node("h2", title),
    node("p", detail, "hint"),
  );
  heading.append(copy);
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
  input.value = selected
    ? `${selected.pet.name} · ${allowed ? "可以参加" : "当前不在家"}`
    : "请先选择一只宠物";
  button.disabled = !allowed;
}

async function refreshParties(reason = "refresh") {
  ensurePartyExperience();
  if (!accessToken) return null;
  const payload = await api("/api/v1/parties");
  partyExperienceState.invitations = payload.invitations || [];
  partyExperienceState.open = payload.open || [];
  partyExperienceState.active = payload.active || [];
  partyExperienceState.history = payload.history || [];
  renderParties();
  await portalRuntime.runFeatureHook("onPartiesRefreshComplete", {
    reason,
    parties: payload,
  });
  return payload;
}

function renderParties() {
  ensurePartyExperience();
  updatePartyCreateState();
  const invitationCount = $("party-invitation-count");
  const openCount = $("party-open-count");
  const activeCount = $("party-active-count");
  const historyCount = $("party-history-count");
  if (!invitationCount || !openCount || !activeCount || !historyCount) return;
  invitationCount.textContent = String(partyExperienceState.invitations.length);
  openCount.textContent = String(partyExperienceState.open.length);
  activeCount.textContent = String(partyExperienceState.active.length);
  historyCount.textContent = String(partyExperienceState.history.length);
  renderPartyInvitations();
  renderPartyOpen();
  renderPartyActive();
  renderPartyHistory();
}

function partyPetIcon(pet) {
  const template = String(pet?.template_id || "").toLowerCase();
  if (template.includes("dog")) return "🐶";
  if (template.includes("rabbit") || template.includes("bunny")) return "🐰";
  if (template.includes("bird")) return "🐦";
  return "🐱";
}

function partyElapsedText(party) {
  if (party.status !== "active" || !party.started_at) {
    return `${party.duration_minutes} 分钟`;
  }
  const started = new Date(party.started_at).getTime();
  if (!Number.isFinite(started)) return `${party.duration_minutes} 分钟`;
  const minutes = Math.max(1, Math.floor((Date.now() - started) / 60000));
  return `已相聚 ${minutes} 分钟`;
}

function partyStateDescription(party) {
  if (party.status === "open") {
    if (party.accepted_count >= 2) return "好友宠物已经准备好，可以开始啦";
    return "正在等待好友带宠物加入";
  }
  if (party.status === "active") {
    return `${party.joined_count} 只宠物正在同一个场景里玩耍`;
  }
  if (party.status === "cancelled") return "这次没有成行，下次再约";
  return "宠物们已经安全回家";
}

function partyActivityKey(party) {
  const recorded = partyExperienceState.activities[party.party_id];
  if (recorded && partyActivityPresentation[recorded]) return recorded;
  if (party.status === "open") return "waiting";
  if (party.status === "active") return "free_play";
  return "ended";
}

function partyRememberActivity(detail) {
  if (!detail?.party_id || !Array.isArray(detail.timeline)) return;
  const interaction = [...detail.timeline].reverse().find((entry) => (
    entry.kind === "interaction" && partyActivityPresentation[entry.action]
  ));
  if (interaction) {
    partyExperienceState.activities[detail.party_id] = interaction.action;
  }
}

function partyMemberChips(party) {
  const row = node("div", "", "party-member-chips");
  party.members.forEach((member) => {
    const chip = node("div", "", `party-member-chip status-${member.status}`);
    chip.append(
      node("span", partyPetIcon(member.pet), "party-chip-avatar"),
      node("span", member.pet?.name || member.account.display_name),
      node("small", partyMemberLabels[member.status] || "参与成员"),
    );
    row.append(chip);
  });
  return row;
}

function partySummaryCard(party) {
  const card = node("article", "", `party-social-card status-${party.status}`);
  const header = node("div", "", "party-social-card-header");
  const copy = node("div");
  copy.append(
    node("span", partyStatusLabels[party.status] || "宠物聚会", "party-status-pill"),
    node("h3", party.title),
    node("p", partyStateDescription(party), "party-state-copy"),
  );
  const count = node("div", "", "party-capacity");
  count.append(
    node("strong", `${party.accepted_count}/${party.max_members}`),
    node("span", "只已确认"),
  );
  header.append(copy, count);

  const facts = node("div", "", "party-facts");
  facts.append(
    node("span", `⏱ ${partyElapsedText(party)}`),
    node("span", `🐾 ${party.member_count} 位参与成员`),
  );
  const note = node("p", party.note || "一起轻松玩一会儿。", "party-note");
  const actions = node("div", "", "item-actions party-card-actions");
  card.append(header, facts, partyMemberChips(party), note, actions);
  return { card, actions };
}

function partyEmptyState(
  container,
  icon,
  title,
  detail,
  actionLabel = "",
  action = null,
) {
  const emptyState = node("div", "", "party-empty-state");
  emptyState.append(
    node("div", icon, "party-empty-icon"),
    node("h3", title),
    node("p", detail, "hint"),
  );
  if (actionLabel && typeof action === "function") {
    const button = node("button", actionLabel, "secondary");
    button.type = "button";
    button.addEventListener("click", action);
    emptyState.append(button);
  }
  container.append(emptyState);
}

function managedPetSelect() {
  const select = document.createElement("select");
  select.className = "party-pet-select";
  const pets = partyManagedPets();
  pets.forEach((item) => {
    const option = node("option", `${partyPetIcon(item.pet)} ${item.pet.name}`);
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
    partyEmptyState(
      container,
      "💌",
      "暂时没有新邀请",
      "好友发起聚会后，会在这里等你回应。",
      "刷新看看",
      () => refreshParties("empty-refresh"),
    );
    return;
  }
  partyExperienceState.invitations.forEach((party) => {
    const built = partySummaryCard(party);
    const selectWrap = node("label", "带哪只宠物参加", "party-accept-select");
    const select = managedPetSelect();
    selectWrap.append(select);
    built.card.insertBefore(selectWrap, built.actions);
    built.actions.append(
      actionButton("接受邀请", async () => {
        if (!select.value) throw new Error("没有可参加聚会的在家宠物。");
        await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/accept`, {
          method: "POST",
          json: { pet_id: select.value },
        });
        await refreshParties("accepted");
        setStatus(globalStatus, "已接受邀请，宠物会在聚会开始后进入场景。", "success");
      }),
      actionButton(
        "这次不参加",
        async () => {
          await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/decline`, {
            method: "POST",
          });
          await refreshParties("declined");
          setStatus(globalStatus, "已礼貌谢绝本次邀请。", "success");
        },
        "secondary",
      ),
      partyDetailButton(party.party_id),
    );
    container.append(built.card);
  });
}

function renderPartyOpen() {
  const container = $("party-open-list");
  container.replaceChildren();
  if (!partyExperienceState.open.length) {
    partyEmptyState(
      container,
      "🎈",
      "还没有等待开始的聚会",
      "选一只在家的宠物，邀请好友一起玩。",
      "邀请好友一起玩",
      () => $("party-create-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
    return;
  }
  partyExperienceState.open.forEach((party) => {
    const built = partySummaryCard(party);
    if (party.can_invite) {
      const invite = node("form", "", "inline-form party-invite-form");
      const input = document.createElement("input");
      input.placeholder = "输入好友的精确用户名";
      input.minLength = 3;
      input.maxLength = 64;
      input.required = true;
      const submit = node("button", "发送邀请");
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
          await refreshParties("invited");
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
      built.actions.append(
        actionButton("大家到齐，开始聚会", async () => {
          await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/start`, {
            method: "POST",
          });
          await Promise.all([refreshParties("started"), refreshDashboard()]);
          setStatus(globalStatus, "聚会开始了，宠物们已进入同一个场景。", "success");
        }),
      );
    }
    if (party.can_cancel) {
      built.actions.append(
        actionButton(
          "取消本次聚会",
          async () => {
            await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/cancel`, {
              method: "POST",
            });
            await refreshParties("cancelled");
            setStatus(globalStatus, "本次聚会已取消。", "success");
          },
          "secondary",
        ),
      );
    }
    built.actions.append(partyDetailButton(party.party_id));
    container.append(built.card);
  });
}

function partySceneGuard(party) {
  return Math.min(2, Number(party.desktop_window_limit || 2));
}

function renderPartyActive() {
  const container = $("party-active-list");
  container.replaceChildren();
  if (!partyExperienceState.active.length) {
    partyEmptyState(
      container,
      "🧸",
      "宠物们现在都在家",
      "开始一场聚会后，这里会变成它们共同玩耍的小场景。",
      "发起新聚会",
      () => $("party-create-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
    return;
  }
  partyExperienceState.active.forEach((party) => {
    const scene = node("article", "", "party-scene-card");
    scene.dataset.desktopGuard = String(partySceneGuard(party));
    const activityKey = partyActivityKey(party);
    const activity = partyActivityPresentation[activityKey];
    const header = node("div", "", "party-scene-header");
    const copy = node("div");
    copy.append(
      node("span", "正在聚会", "party-status-pill"),
      node("h3", party.title),
      node("p", `${party.joined_count} 只宠物已经相聚，${partyElapsedText(party)}。`, "hint"),
    );
    header.append(copy, node("span", "同一聚会场景", "party-scene-badge"));

    const stage = node("div", "", `party-stage activity-${activityKey}`);
    const activityBanner = node("div", "", "party-activity-banner");
    activityBanner.append(
      node("span", activity.icon, "party-activity-icon"),
      node("strong", activity.title),
    );
    const members = node("div", "", "party-member-grid");
    party.members
      .filter((member) => member.status === "joined")
      .forEach((member, index) => {
        const card = node("div", "", `party-member-card member-${index + 1}`);
        card.append(
          node("div", partyPetIcon(member.pet), "party-member-avatar"),
          node("strong", member.pet?.name || "宠物"),
          node(
            "span",
            member.role === "host" ? "聚会发起宠物" : member.account.display_name,
            "party-member-owner",
          ),
          node("span", activity.member, "party-member-activity"),
        );
        members.append(card);
      });
    stage.append(activityBanner, members);

    const actions = node("div", "", "item-actions party-scene-actions");
    if (party.can_interact) {
      Object.entries(partyInteractionLabels).forEach(([action, label]) => {
        actions.append(
          actionButton(
            label,
            async () => {
              await api(
                `/api/v1/parties/${encodeURIComponent(party.party_id)}/interactions/${action}`,
                {
                  method: "POST",
                  json: { idempotency_key: partyRandom(action) },
                },
              );
              partyExperienceState.activities[party.party_id] = action;
              await openPartyDetail(party.party_id, { scroll: false });
              renderParties();
              setStatus(globalStatus, `${label}已经成为新的聚会动态。`, "success");
            },
            "secondary",
          ),
        );
      });
    }
    const current = party.members.find((member) => member.is_current_account);
    if (current?.can_leave) {
      actions.append(
        actionButton(
          "带宠物回家",
          async () => {
            await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/leave`, {
              method: "POST",
            });
            await Promise.all([refreshParties("left"), refreshDashboard()]);
            setStatus(globalStatus, "宠物已经离开聚会并安全回家。", "success");
          },
          "secondary",
        ),
      );
    }
    if (party.can_end) {
      actions.append(
        actionButton(
          "结束聚会",
          async () => {
            await api(`/api/v1/parties/${encodeURIComponent(party.party_id)}/end`, {
              method: "POST",
            });
            await Promise.all([refreshParties("ended"), refreshDashboard()]);
            setStatus(globalStatus, "聚会已温馨结束，仍在场的宠物都已回家。", "success");
          },
          "danger",
        ),
      );
    }
    actions.append(partyDetailButton(party.party_id));
    scene.append(header, stage, actions);
    container.append(scene);
  });
}

function renderPartyHistory() {
  const container = $("party-history-list");
  container.replaceChildren();
  if (!partyExperienceState.history.length) {
    partyEmptyState(
      container,
      "📖",
      "还没有聚会回忆",
      "完成第一场聚会后，可以在这里回看宠物们的故事。",
      "发起第一场聚会",
      () => $("party-create-panel")?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
    return;
  }
  partyExperienceState.history.slice(0, 30).forEach((party) => {
    const built = partySummaryCard(party);
    built.actions.append(partyDetailButton(party.party_id));
    container.append(built.card);
  });
}

function partyDetailButton(partyId) {
  return actionButton(
    "查看聚会故事",
    async () => openPartyDetail(partyId),
    "secondary",
  );
}

async function openPartyDetail(partyId, options = {}) {
  const detail = await api(`/api/v1/parties/${encodeURIComponent(partyId)}`);
  partyExperienceState.detail = detail;
  partyRememberActivity(detail);
  renderPartyDetail(options);
  return detail;
}

function renderPartyDetail(options = {}) {
  const panel = $("party-detail-panel");
  const container = $("party-detail");
  const detail = partyExperienceState.detail;
  if (!panel || !container || !detail) return;
  panel.hidden = false;
  container.replaceChildren();
  const summary = partySummaryCard(detail);
  container.append(summary.card);
  const timeline = node("ol", "", "party-timeline");
  (detail.timeline || []).forEach((entry) => {
    const item = node("li", "", `party-timeline-entry kind-${entry.kind}`);
    const icon = entry.kind === "interaction"
      ? "✨"
      : entry.kind === "started"
        ? "🎉"
        : entry.kind === "ended"
          ? "🏠"
          : "🐾";
    const copy = node("div");
    copy.append(
      node("strong", entry.title),
      node("p", entry.detail),
      node(
        "span",
        `${new Date(entry.occurred_at).toLocaleString()}${entry.actor_display_name ? ` · ${entry.actor_display_name}` : ""}`,
        "hint",
      ),
    );
    item.append(node("span", icon, "party-timeline-icon"), copy);
    timeline.append(item);
  });
  if (!timeline.children.length) {
    partyEmptyState(
      timeline,
      "📝",
      "故事刚刚开始",
      "聚会开始和互动后，动态会按时间记录在这里。",
    );
  }
  container.append(timeline);
  if (options.scroll !== false) {
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function resetPartyExperienceState() {
  partyExperienceState.invitations = [];
  partyExperienceState.open = [];
  partyExperienceState.active = [];
  partyExperienceState.history = [];
  partyExperienceState.detail = null;
  partyExperienceState.activities = {};
  renderParties();
  const detailPanel = $("party-detail-panel");
  if (detailPanel) detailPanel.hidden = true;
}

portalRuntime.registerFeature({
  id: "party-experience",
  label: "宠物聚会",
  order: 400,
  mount: () => {
    ensurePartyExperience();
    renderParties();
  },
  onRefreshComplete: updatePartyCreateState,
  onPetContextRefresh: updatePartyCreateState,
  onSectionEnter: async ({ sectionId, source }) => {
    if (
      sectionId === "parties-section"
      && accessToken
      && source !== "anonymous"
    ) {
      await refreshParties("section-enter");
    }
  },
  onRealtime: async () => {
    const section = $("parties-section");
    if (!accessToken || !section || section.hidden) return;
    await refreshParties("realtime");
    if (partyExperienceState.detail?.party_id) {
      await openPartyDetail(partyExperienceState.detail.party_id, {
        scroll: false,
      });
    }
  },
  onLogout: resetPartyExperienceState,
});
