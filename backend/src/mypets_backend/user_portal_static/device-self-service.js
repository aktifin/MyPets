"use strict";

const deviceSelfServiceState = {
  devices: [],
  health: null,
  loaded: false,
  loading: false,
  error: "",
};

const deviceSelfServiceUI = window.MyPetsPortalUI;
if (!deviceSelfServiceUI) throw new Error("MyPets 门户 UI 组件未加载");

const devicePlatformLabels = {
  windows: "Windows",
  macos: "macOS",
  linux: "Linux",
  mini_program: "小程序",
  web: "Web",
};

function deviceNode(tag, text = "", className = "") {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function readableDeviceTime(value) {
  if (!value) return "暂无记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "暂无记录" : parsed.toLocaleString();
}

function maskedIdentifier(value) {
  const text = String(value || "");
  if (text.length <= 8) return text || "—";
  return `${text.slice(0, 4)}…${text.slice(-4)}`;
}

function ensureDeviceSelfServicePanel() {
  let panel = $("device-self-service-panel");
  if (panel) return panel;
  const accountSection = $("account-section");
  if (!accountSection) return null;

  panel = deviceNode("article", "", "panel device-self-service-panel");
  panel.id = "device-self-service-panel";

  const heading = deviceNode("div", "", "section-heading device-self-service-heading");
  const copy = deviceNode("div");
  copy.append(
    deviceNode("p", "DEVICES", "eyebrow"),
    deviceNode("h2", "登录设备与诊断"),
    deviceNode(
      "p",
      "查看绑定过的设备，撤销不再使用的设备，并下载不包含密码、令牌和设备密钥的诊断信息。",
      "hint",
    ),
  );
  const badge = deviceNode("span", "尚未读取", "badge");
  badge.id = "device-self-service-count";
  heading.append(copy, badge);

  const toolbar = deviceNode("div", "", "device-self-service-toolbar");
  const refresh = deviceNode("button", "刷新设备", "secondary");
  refresh.type = "button";
  refresh.id = "refresh-device-self-service";
  const download = deviceNode("button", "下载诊断信息", "secondary");
  download.type = "button";
  download.id = "download-web-diagnostics";
  toolbar.append(refresh, download);

  const status = deviceNode("p", "", "status");
  status.id = "device-self-service-status";
  status.setAttribute("aria-live", "polite");
  const list = deviceNode("div", "", "device-self-service-list");
  list.id = "device-self-service-list";
  panel.append(heading, toolbar, status, list);
  accountSection.append(panel);

  refresh.addEventListener("click", () => {
    deviceSelfServiceUI.runAction({
      control: refresh,
      statusNode: status,
      busyLabel: "正在刷新…",
      successMessage: "设备列表已刷新。",
      task: () => refreshDeviceSelfService({ showLoading: true }),
    });
  });
  download.addEventListener("click", () => {
    deviceSelfServiceUI.runAction({
      control: download,
      statusNode: status,
      busyLabel: "正在生成…",
      successMessage: "诊断信息已下载。",
      task: async () => downloadWebDiagnostics(),
    });
  });
  return panel;
}

function deviceRetryAction() {
  return {
    label: "重新读取",
    busyLabel: "正在读取…",
    onClick: () => refreshDeviceSelfService({ showLoading: true }),
  };
}

function renderDeviceSelfService() {
  ensureDeviceSelfServicePanel();
  const list = $("device-self-service-list");
  const badge = $("device-self-service-count");
  if (!list || !badge) return;
  deviceSelfServiceUI.setRegionBusy(list, deviceSelfServiceState.loading);

  if (deviceSelfServiceState.loading && !deviceSelfServiceState.loaded) {
    badge.textContent = "正在读取";
    deviceSelfServiceUI.renderState(list, {
      kind: "loading",
      title: "正在读取登录设备",
      detail: "正在加载设备记录和服务诊断状态。",
    });
    return;
  }
  if (deviceSelfServiceState.error && !deviceSelfServiceState.loaded) {
    badge.textContent = "读取失败";
    deviceSelfServiceUI.renderState(list, {
      kind: "error",
      title: "设备列表读取失败",
      detail: deviceSelfServiceState.error,
      action: deviceRetryAction(),
    });
    return;
  }
  if (!deviceSelfServiceState.loaded) {
    badge.textContent = "尚未读取";
    deviceSelfServiceUI.renderState(list, {
      kind: "idle",
      title: "设备列表尚未读取",
      detail: "进入设置页后读取已绑定设备和服务诊断状态。",
    });
    return;
  }

  const active = deviceSelfServiceState.devices.filter((item) => !item.revoked_at);
  badge.textContent = `${active.length} 台可用 · ${deviceSelfServiceState.devices.length} 台记录`;
  list.replaceChildren();
  deviceSelfServiceUI.clearState(list);
  if (!deviceSelfServiceState.devices.length) {
    deviceSelfServiceUI.renderState(list, {
      kind: "empty",
      title: "当前账户还没有绑定设备",
      detail: "桌面端或其他客户端完成登录和绑定后，会在这里显示设备记录。",
    });
    return;
  }

  deviceSelfServiceState.devices.forEach((item) => {
    const revoked = Boolean(item.revoked_at);
    const card = deviceNode(
      "article",
      "",
      `device-card${revoked ? " revoked" : ""}`,
    );
    const title = deviceNode("div", "", "device-card-title");
    title.append(
      deviceNode("strong", item.name || "未命名设备"),
      deviceNode(
        "span",
        revoked ? "已撤销" : "可用",
        revoked ? "badge device-revoked" : "badge device-active",
      ),
    );
    const meta = deviceNode("div", "", "device-card-meta");
    meta.append(
      deviceNode("span", devicePlatformLabels[item.platform] || item.platform || "未知平台"),
      deviceNode("span", `最后在线：${readableDeviceTime(item.last_seen_at)}`),
      deviceNode("span", `绑定时间：${readableDeviceTime(item.created_at)}`),
      deviceNode("span", `设备标识：${maskedIdentifier(item.public_id)}`),
    );
    if (revoked) {
      meta.append(deviceNode("span", `撤销时间：${readableDeviceTime(item.revoked_at)}`));
    }
    const actions = deviceNode("div", "", "item-actions");
    if (!revoked) {
      const revoke = deviceNode("button", "撤销此设备", "danger");
      revoke.type = "button";
      revoke.addEventListener("click", () => {
        const confirmed = window.confirm(
          `撤销“${item.name || "未命名设备"}”后，该设备需要重新登录和绑定。是否继续？`,
        );
        if (!confirmed) return;
        deviceSelfServiceUI.runAction({
          control: revoke,
          statusNode: $("device-self-service-status"),
          busyLabel: "正在撤销…",
          successMessage: "设备已撤销。",
          task: async () => {
            await api(`/api/v1/devices/${encodeURIComponent(item.id)}`, {
              method: "DELETE",
            });
            await refreshDeviceSelfService({ showLoading: false });
          },
        });
      });
      actions.append(revoke);
    }
    card.append(title, meta, actions);
    list.append(card);
  });

  if (deviceSelfServiceState.error) {
    deviceSelfServiceUI.renderInlineNotice(list, {
      kind: "error",
      title: "最新设备状态暂未更新",
      detail: `${deviceSelfServiceState.error} 当前仍显示上次成功读取的设备记录。`,
      action: deviceRetryAction(),
    });
  }
}

async function refreshDeviceSelfService(options = {}) {
  ensureDeviceSelfServicePanel();
  if (!accessToken) {
    deviceSelfServiceState.devices = [];
    deviceSelfServiceState.health = null;
    deviceSelfServiceState.loaded = false;
    deviceSelfServiceState.loading = false;
    deviceSelfServiceState.error = "";
    renderDeviceSelfService();
    return;
  }

  const showLoading = options.showLoading ?? !deviceSelfServiceState.loaded;
  deviceSelfServiceState.loading = true;
  deviceSelfServiceState.error = "";
  if (showLoading || !deviceSelfServiceState.loaded) renderDeviceSelfService();
  else deviceSelfServiceUI.setRegionBusy($("device-self-service-list"), true);

  try {
    const [devices, healthResponse] = await Promise.all([
      api("/api/v1/devices"),
      fetch("/health", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      }),
    ]);
    deviceSelfServiceState.devices = Array.isArray(devices) ? devices : [];
    deviceSelfServiceState.health = healthResponse.ok ? await healthResponse.json() : null;
    deviceSelfServiceState.loaded = true;
  } catch (error) {
    deviceSelfServiceState.error = error.message || "设备列表读取失败";
    throw error;
  } finally {
    deviceSelfServiceState.loading = false;
    renderDeviceSelfService();
  }
}

function safeDiagnosticDevices() {
  return deviceSelfServiceState.devices.map((item) => ({
    name: item.name || "",
    platform: item.platform || "",
    public_id: maskedIdentifier(item.public_id),
    active_pet_configured: Boolean(item.active_pet_id),
    created_at: item.created_at || null,
    last_seen_at: item.last_seen_at || null,
    revoked_at: item.revoked_at || null,
  }));
}

function downloadWebDiagnostics() {
  const account = dashboard?.account || null;
  const payload = {
    generated_at: new Date().toISOString(),
    application: {
      name: "MyPets Web",
      version: deviceSelfServiceState.health?.version || "unknown",
      channel: deviceSelfServiceState.health?.channel || "unknown",
    },
    server: {
      origin: window.location.origin,
      status: deviceSelfServiceState.health?.status || "unknown",
    },
    browser: {
      user_agent: navigator.userAgent,
      language: navigator.language,
      online: navigator.onLine,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "unknown",
    },
    account: account
      ? { username: account.username, display_name: account.display_name }
      : null,
    devices: safeDiagnosticDevices(),
    privacy: "不包含密码、访问令牌、设备密钥、消息正文或宠物私密数据。",
  };
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], {
    type: "application/json;charset=utf-8",
  });
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  const date = new Date().toISOString().slice(0, 10);
  link.href = url;
  link.download = `mypets-web-diagnostics-${date}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

portalRuntime.registerFeature({
  id: "device-self-service",
  label: "设备管理",
  order: 320,
  mount: () => {
    ensureDeviceSelfServicePanel();
    renderDeviceSelfService();
  },
  onSectionEnter: async ({ sectionId }) => {
    if (sectionId === "account-section" && accessToken) {
      await refreshDeviceSelfService({ showLoading: !deviceSelfServiceState.loaded });
    }
  },
  onLogout: () => {
    deviceSelfServiceState.devices = [];
    deviceSelfServiceState.health = null;
    deviceSelfServiceState.loaded = false;
    deviceSelfServiceState.loading = false;
    deviceSelfServiceState.error = "";
    renderDeviceSelfService();
    setStatus($("device-self-service-status"), "");
  },
});
