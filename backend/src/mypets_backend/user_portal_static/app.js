"use strict";

const TOKEN_KEY = "mypets.portal.account-token";
let accessToken = sessionStorage.getItem(TOKEN_KEY) || "";
let dashboard = null;
let socialState = {
  friends: [],
  requests: { incoming: [], outgoing: [] },
  blocks: [],
  invitations: { incoming: [], outgoing: [] },
};

const $ = (id) => document.getElementById(id);
const authView = $("auth-view");
const appView = $("app-view");
const logoutButton = $("logout-button");
const sessionLabel = $("session-label");
const authStatus = $("auth-status");
const globalStatus = $("global-status");
const portalRuntime = window.MyPetsPortal;

if (!portalRuntime) throw new Error("MyPets 前端运行时未加载");

function setStatus(node, message, kind = "") {
  if (!node) return;
  node.textContent = message || "";
  node.classList.remove("error", "success");
  if (kind) node.classList.add(kind);
}

function detailText(payload, fallback) {
  if (payload && typeof payload.detail === "string") return payload.detail;
  if (payload && Array.isArray(payload.detail)) {
    return payload.detail.map((item) => item.msg || "请求参数无效").join("；");
  }
  return fallback || "请求失败";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.json);
  }
  const response = await fetch(path, { ...options, headers });
  let payload = null;
  if (response.status !== 204) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) payload = await response.json();
    else payload = { detail: await response.text() };
  }
  if (!response.ok) {
    if (response.status === 401 && accessToken) {
      logout("登录已失效，请重新登录。", "error");
    }
    throw new Error(detailText(payload, `请求失败（${response.status}）`));
  }
  return payload;
}

function node(tag, text = "", className = "") {
  const value = document.createElement(tag);
  if (text) value.textContent = text;
  if (className) value.className = className;
  return value;
}

function actionButton(label, handler, className = "") {
  const button = node("button", label, className);
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await handler();
    } catch (error) {
      setStatus(globalStatus, error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function empty(container, text) {
  container.replaceChildren(node("div", text, "empty-state"));
}

function itemCard(title, metaLines = [], selected = false) {
  const card = node("div", "", selected ? "item-card selected" : "item-card");
  card.append(node("div", title, "item-title"));
  const meta = node("div", "", "item-meta");
  metaLines.forEach((line) => meta.append(node("div", line)));
  card.append(meta);
  const actions = node("div", "", "item-actions");
  card.append(actions);
  return { card, actions };
}

function personalityLabel(value) {
  return {
    balanced: "均衡",
    playful: "活泼",
    gentle: "温柔",
    energetic: "精力充沛",
    sleepy: "爱睡觉",
    curious: "好奇",
  }[value] || value;
}

function roleLabel(value) {
  return {
    owner: "主人",
    co_owner: "共同主人",
    caregiver: "照料者",
    viewer: "观察者",
  }[value] || value;
}

function visibilityLabel(value) {
  return {
    private: "仅自己",
    caregivers: "共同照料者",
    friends: "好友",
    public: "公开",
  }[value] || value;
}

function showLoginForm(showLogin) {
  $("login-form").hidden = !showLogin;
  $("register-form").hidden = showLogin;
  $("show-login").classList.toggle("active", showLogin);
  $("show-register").classList.toggle("active", !showLogin);
  setStatus(authStatus, "");
}

function enterApp() {
  authView.hidden = true;
  appView.hidden = false;
  logoutButton.hidden = false;
}

function logout(message = "", kind = "") {
  accessToken = "";
  dashboard = null;
  socialState = {
    friends: [],
    requests: { incoming: [], outgoing: [] },
    blocks: [],
    invitations: { incoming: [], outgoing: [] },
  };
  sessionStorage.removeItem(TOKEN_KEY);
  appView.hidden = true;
  authView.hidden = false;
  logoutButton.hidden = true;
  sessionLabel.textContent = "尚未登录";
  setStatus(globalStatus, "");
  setStatus(authStatus, message, kind);
  portalRuntime.sessionEnded({ message, kind });
}

async function login(username, password) {
  const body = new URLSearchParams({ username, password });
  const response = await fetch("/api/v1/auth/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
    },
    body,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(detailText(payload, "登录失败"));
  accessToken = payload.access_token;
  sessionStorage.setItem(TOKEN_KEY, accessToken);
  enterApp();
  await refreshAll({ reason: "login" });
}

async function registerAccount(username, displayName, password) {
  const payload = await api("/api/v1/auth/register", {
    method: "POST",
    json: { username, display_name: displayName, password },
  });
  accessToken = payload.access_token;
  sessionStorage.setItem(TOKEN_KEY, accessToken);
  enterApp();
  await refreshAll({ reason: "register" });
}

function selectedPortalPet() {
  if (!dashboard || !dashboard.selected_pet_id) return null;
  return dashboard.pets.find((item) => item.pet.pet_id === dashboard.selected_pet_id) || null;
}

async function refreshDashboard() {
  dashboard = await api("/api/v1/portal/dashboard");
  renderDashboard();
}

async function refreshSocial() {
  const [friends, requests, blocks, invitations] = await Promise.all([
    api("/api/v1/friends"),
    api("/api/v1/friend-requests?status=pending"),
    api("/api/v1/blocks"),
    api("/api/v1/caregiver-invitations?status=pending"),
  ]);
  socialState = { friends, requests, blocks, invitations };
  renderSocial();
}

async function refreshAll() {
  setStatus(globalStatus, "正在加载用户数据…");
  await Promise.all([refreshDashboard(), refreshSocial()]);
  setStatus(globalStatus, "数据已从服务端刷新。", "success");
}

function renderDashboard() {
  if (!dashboard) return;
  const account = dashboard.account;
  sessionLabel.textContent = `${account.display_name}（${account.username}）`;
  $("account-username").textContent = account.username;
  $("profile-display-name").value = account.display_name;

  const personalitySelect = $("pet-config-personality");
  personalitySelect.replaceChildren();
  dashboard.personalities.forEach((value) => {
    const option = node("option", personalityLabel(value));
    option.value = value;
    personalitySelect.append(option);
  });

  renderPets();
  renderSelectedPet();
}

function renderPets() {
  const container = $("pet-list");
  container.replaceChildren();
  if (!dashboard.pets.length) {
    empty(container, "还没有宠物，可使用上方表单创建第一只宠物。");
    return;
  }
  dashboard.pets.forEach((item) => {
    const pet = item.pet;
    const built = itemCard(
      pet.name,
      [
        `${roleLabel(item.relation.role)} · ${personalityLabel(pet.personality_type)}`,
        `成长 ${pet.stats.growth_stage} / Lv.${pet.stats.growth_level} · 羁绊 Lv.${pet.stats.bond_level}`,
        `${visibilityLabel(item.privacy.visibility)} · ${
          item.privacy.allow_remote_care ? "允许远程照料" : "关闭远程照料"
        }`,
      ],
      item.selected,
    );
    if (!item.selected) {
      built.actions.append(
        actionButton("设为 Web 当前宠物", async () => {
          dashboard = await api("/api/v1/portal/preference", {
            method: "PATCH",
            json: { selected_pet_id: pet.pet_id },
          });
          renderDashboard();
          setStatus(
            globalStatus,
            `已选择 ${pet.name}。此选择不覆盖各 PC 设备的当前宠物。`,
            "success",
          );
        }),
      );
    }
    container.append(built.card);
  });
}

function renderSelectedPet() {
  const selected = selectedPortalPet();
  const noSelection = $("no-selected-pet");
  const config = $("selected-pet-config");
  if (!selected) {
    noSelection.hidden = false;
    config.hidden = true;
    $("selected-pet-role").textContent = "无宠物";
    $("invite-pet-name").value = "";
    $("send-caregiver-invite").disabled = true;
    return;
  }
  noSelection.hidden = true;
  config.hidden = false;
  $("selected-pet-role").textContent = roleLabel(selected.relation.role);
  $("pet-config-name").value = selected.pet.name;
  $("pet-config-personality").value = selected.pet.personality_type;
  $("pet-visibility").value = selected.privacy.visibility;
  $("allow-remote-care").checked = selected.privacy.allow_remote_care;
  $("save-pet-config").disabled = !selected.can_configure;
  $("save-privacy").disabled = !selected.can_configure;
  $("pet-config-name").disabled = !selected.can_configure;
  $("pet-config-personality").disabled = !selected.can_configure;
  $("pet-visibility").disabled = !selected.can_configure;
  $("allow-remote-care").disabled = !selected.can_configure;
  $("invite-pet-name").value = selected.pet.name;
  $("send-caregiver-invite").disabled = !selected.can_configure;
}

function renderSocial() {
  renderFriends();
  renderFriendRequests();
  renderBlocks();
  renderInvitations();
}

function renderFriends() {
  const container = $("friend-list");
  container.replaceChildren();
  if (!socialState.friends.length) {
    empty(container, "暂无好友。");
    return;
  }
  socialState.friends.forEach((item) => {
    const friend = item.friend;
    const built = itemCard(friend.display_name, [
      `@${friend.username}`,
      `好友关系建立于 ${new Date(item.created_at).toLocaleString()}`,
    ]);
    built.actions.append(
      actionButton(
        "解除好友",
        async () => {
          await api(`/api/v1/friends/${encodeURIComponent(friend.account_id)}`, {
            method: "DELETE",
          });
          await refreshSocial();
          setStatus(globalStatus, `已解除与 ${friend.display_name} 的好友关系。`, "success");
        },
        "secondary",
      ),
      actionButton(
        "屏蔽",
        async () => {
          await api("/api/v1/blocks", {
            method: "POST",
            json: { username: friend.username },
          });
          await Promise.all([refreshSocial(), refreshDashboard()]);
          setStatus(
            globalStatus,
            `已屏蔽 ${friend.display_name}，相关共享宠物访问已撤销。`,
            "success",
          );
        },
        "danger",
      ),
    );
    container.append(built.card);
  });
}

function renderFriendRequests() {
  const incoming = $("incoming-requests");
  incoming.replaceChildren();
  if (!socialState.requests.incoming.length) {
    empty(incoming, "没有待处理的收到申请。");
  }
  socialState.requests.incoming.forEach((item) => {
    const built = itemCard(item.sender.display_name, [`@${item.sender.username}`]);
    built.actions.append(
      actionButton("接受", async () => {
        await api(`/api/v1/friend-requests/${encodeURIComponent(item.request_id)}/accept`, {
          method: "POST",
        });
        await refreshSocial();
        setStatus(globalStatus, "好友申请已接受。", "success");
      }),
      actionButton(
        "拒绝",
        async () => {
          await api(`/api/v1/friend-requests/${encodeURIComponent(item.request_id)}/reject`, {
            method: "POST",
          });
          await refreshSocial();
          setStatus(globalStatus, "好友申请已拒绝。", "success");
        },
        "secondary",
      ),
    );
    incoming.append(built.card);
  });

  const outgoing = $("outgoing-requests");
  outgoing.replaceChildren();
  if (!socialState.requests.outgoing.length) {
    empty(outgoing, "没有待处理的发出申请。");
  }
  socialState.requests.outgoing.forEach((item) => {
    const built = itemCard(item.recipient.display_name, [`@${item.recipient.username}`]);
    built.actions.append(
      actionButton(
        "取消申请",
        async () => {
          await api(`/api/v1/friend-requests/${encodeURIComponent(item.request_id)}/cancel`, {
            method: "POST",
          });
          await refreshSocial();
          setStatus(globalStatus, "好友申请已取消。", "success");
        },
        "secondary",
      ),
    );
    outgoing.append(built.card);
  });
}

function renderBlocks() {
  const container = $("block-list");
  container.replaceChildren();
  if (!socialState.blocks.length) {
    empty(container, "屏蔽列表为空。");
    return;
  }
  socialState.blocks.forEach((item) => {
    const account = item.account;
    const built = itemCard(account.display_name, [`@${account.username}`]);
    built.actions.append(
      actionButton(
        "解除屏蔽",
        async () => {
          await api(`/api/v1/blocks/${encodeURIComponent(account.account_id)}`, {
            method: "DELETE",
          });
          await refreshSocial();
          setStatus(
            globalStatus,
            `已解除对 ${account.display_name} 的屏蔽。历史好友和共享关系不会自动恢复。`,
            "success",
          );
        },
        "secondary",
      ),
    );
    container.append(built.card);
  });
}

function invitationTitle(item, incoming) {
  const person = incoming ? item.invited_by : item.invited_account;
  return `${item.pet.name} · ${person.display_name}`;
}

function renderInvitations() {
  const incoming = $("incoming-invitations");
  incoming.replaceChildren();
  if (!socialState.invitations.incoming.length) {
    empty(incoming, "没有待处理的共同照料邀请。");
  }
  socialState.invitations.incoming.forEach((item) => {
    const built = itemCard(invitationTitle(item, true), [
      `角色：${roleLabel(item.role)}`,
      `邀请人：@${item.invited_by.username}`,
    ]);
    built.actions.append(
      actionButton("接受", async () => {
        await api(
          `/api/v1/caregiver-invitations/${encodeURIComponent(item.invitation_id)}/accept`,
          { method: "POST" },
        );
        await Promise.all([refreshSocial(), refreshDashboard()]);
        setStatus(globalStatus, `已接受 ${item.pet.name} 的共同照料邀请。`, "success");
      }),
      actionButton(
        "拒绝",
        async () => {
          await api(
            `/api/v1/caregiver-invitations/${encodeURIComponent(item.invitation_id)}/reject`,
            { method: "POST" },
          );
          await refreshSocial();
          setStatus(globalStatus, "共同照料邀请已拒绝。", "success");
        },
        "secondary",
      ),
    );
    incoming.append(built.card);
  });

  const outgoing = $("outgoing-invitations");
  outgoing.replaceChildren();
  if (!socialState.invitations.outgoing.length) {
    empty(outgoing, "没有待处理的已发出邀请。");
  }
  socialState.invitations.outgoing.forEach((item) => {
    const built = itemCard(invitationTitle(item, false), [
      `角色：${roleLabel(item.role)}`,
      `受邀人：@${item.invited_account.username}`,
    ]);
    built.actions.append(
      actionButton(
        "取消邀请",
        async () => {
          await api(
            `/api/v1/caregiver-invitations/${encodeURIComponent(item.invitation_id)}/cancel`,
            { method: "POST" },
          );
          await refreshSocial();
          setStatus(globalStatus, "共同照料邀请已取消。", "success");
        },
        "secondary",
      ),
    );
    outgoing.append(built.card);
  });
}

$("show-login").addEventListener("click", () => showLoginForm(true));
$("show-register").addEventListener("click", () => showLoginForm(false));
logoutButton.addEventListener("click", () => {
  logout("已退出当前浏览器会话。", "success");
});

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus(authStatus, "正在登录…");
  try {
    await login($("login-username").value.trim(), $("login-password").value);
  } catch (error) {
    setStatus(authStatus, error.message, "error");
  }
});

$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus(authStatus, "正在创建账户…");
  try {
    await registerAccount(
      $("register-username").value.trim(),
      $("register-display-name").value.trim(),
      $("register-password").value,
    );
  } catch (error) {
    setStatus(authStatus, error.message, "error");
  }
});

$("profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/v1/portal/account", {
      method: "PATCH",
      json: { display_name: $("profile-display-name").value.trim() },
    });
    await refreshDashboard();
    setStatus(globalStatus, "账户资料已保存。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/v1/portal/account/password", {
      method: "POST",
      json: {
        current_password: $("current-password").value,
        new_password: $("new-password").value,
      },
    });
    $("current-password").value = "";
    $("new-password").value = "";
    setStatus(globalStatus, "密码已更新。当前短期登录会话保持有效。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("create-pet-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const key =
      typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
    const pet = await api("/api/v1/pets", {
      method: "POST",
      headers: { "Idempotency-Key": `portal-pet-${key}` },
      json: {
        name: $("new-pet-name").value.trim(),
        template_id: $("new-pet-template").value.trim(),
        template_version: $("new-pet-template-version").value.trim(),
        identity_version: $("new-pet-identity-version").value.trim(),
        asset_version: $("new-pet-asset-version").value.trim(),
      },
    });
    dashboard = await api("/api/v1/portal/preference", {
      method: "PATCH",
      json: { selected_pet_id: pet.pet_id },
    });
    $("new-pet-name").value = "";
    renderDashboard();
    setStatus(globalStatus, `宠物 ${pet.name} 已创建并设为 Web 当前宠物。`, "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("pet-config-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = selectedPortalPet();
  if (!selected) return;
  try {
    await api(`/api/v1/portal/pets/${encodeURIComponent(selected.pet.pet_id)}`, {
      method: "PATCH",
      json: {
        name: $("pet-config-name").value.trim(),
        personality_type: $("pet-config-personality").value,
      },
    });
    await refreshDashboard();
    setStatus(globalStatus, "宠物配置已保存并进入同步事件流。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("privacy-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = selectedPortalPet();
  if (!selected) return;
  try {
    await api(`/api/v1/pets/${encodeURIComponent(selected.pet.pet_id)}/privacy`, {
      method: "PATCH",
      json: {
        visibility: $("pet-visibility").value,
        allow_remote_care: $("allow-remote-care").checked,
      },
    });
    await refreshDashboard();
    setStatus(globalStatus, "宠物隐私与远程照料设置已保存。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("friend-request-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/v1/friend-requests", {
      method: "POST",
      json: { username: $("friend-username").value.trim() },
    });
    $("friend-username").value = "";
    await refreshSocial();
    setStatus(globalStatus, "好友申请已发送。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("caregiver-invite-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const selected = selectedPortalPet();
  if (!selected || !selected.can_configure) return;
  try {
    await api(
      `/api/v1/pets/${encodeURIComponent(selected.pet.pet_id)}/caregiver-invitations`,
      {
        method: "POST",
        json: {
          username: $("invite-username").value.trim(),
          role: $("invite-role").value,
        },
      },
    );
    $("invite-username").value = "";
    await refreshSocial();
    setStatus(globalStatus, "共同照料邀请已发送。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("refresh-pets").addEventListener("click", async () => {
  try {
    await refreshDashboard();
    setStatus(globalStatus, "宠物数据已刷新。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

$("refresh-social").addEventListener("click", async () => {
  try {
    await refreshSocial();
    setStatus(globalStatus, "好友与邀请数据已刷新。", "success");
  } catch (error) {
    setStatus(globalStatus, error.message, "error");
  }
});

portalRuntime.configure({
  hasSession: () => Boolean(accessToken),
  enter: enterApp,
  showLogin: () => showLoginForm(true),
  onError: (error) => {
    if (accessToken) setStatus(globalStatus, error.message, "error");
  },
});

window.setTimeout(() => {
  portalRuntime.start().catch((error) => {
    if (accessToken) setStatus(globalStatus, error.message, "error");
    else setStatus(authStatus, "用户门户初始化失败，请刷新页面重试。", "error");
  });
}, 0);
