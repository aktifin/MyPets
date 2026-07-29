"use strict";

(() => {
  if (window.MyPetsPortal) return;

  const features = new Map();
  const failures = new Map();
  const state = {
    adapters: null,
    started: false,
    startPromise: null,
    legacyRefresh: null,
    refreshPromise: null,
    refreshQueued: false,
    activeSection: "dashboard-section",
    navigationInstalled: false,
    runtimePanel: null,
  };

  function featureList() {
    return [...features.values()].sort((left, right) => {
      const order = Number(left.order || 0) - Number(right.order || 0);
      return order || left.id.localeCompare(right.id);
    });
  }

  function runtimePanel() {
    if (state.runtimePanel?.isConnected) return state.runtimePanel;
    const appView = document.getElementById("app-view");
    if (!appView) return null;
    const panel = document.createElement("aside");
    panel.id = "portal-runtime-status";
    panel.className = "portal-runtime-status";
    panel.hidden = true;
    panel.setAttribute("role", "status");
    panel.setAttribute("aria-live", "polite");

    const copy = document.createElement("span");
    copy.className = "portal-runtime-status-copy";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "secondary compact";
    retry.textContent = "重新加载";
    retry.addEventListener("click", () => {
      retry.disabled = true;
      requestRefresh({ reason: "runtime-retry" }).finally(() => {
        retry.disabled = false;
      });
    });
    panel.append(copy, retry);

    const globalStatus = document.getElementById("global-status");
    if (globalStatus?.parentElement === appView) globalStatus.insertAdjacentElement("afterend", panel);
    else appView.prepend(panel);
    state.runtimePanel = panel;
    return panel;
  }

  function renderRuntimeStatus() {
    const panel = runtimePanel();
    if (!panel) return;
    const count = failures.size;
    panel.hidden = count === 0;
    if (!count) return;
    const names = [...failures.values()].map((item) => item.label).slice(0, 3);
    const suffix = count > names.length ? `等 ${count} 项` : names.join("、");
    panel.querySelector(".portal-runtime-status-copy").textContent =
      `部分功能暂未完成加载：${suffix}。其他功能仍可继续使用。`;
  }

  function recordFailure(key, label, error) {
    failures.set(key, { label, message: String(error?.message || error || "未知错误") });
    console.error(`[MyPetsPortal] ${key}`, error);
    renderRuntimeStatus();
  }

  function clearFailure(key) {
    if (failures.delete(key)) renderRuntimeStatus();
  }

  async function invokeFeature(feature, hook, context) {
    const callback = feature[hook];
    if (typeof callback !== "function") return;
    const key = `${feature.id}:${hook}`;
    try {
      await callback(context);
      clearFailure(key);
    } catch (error) {
      recordFailure(key, feature.label || feature.id, error);
    }
  }

  async function mountFeature(feature) {
    if (feature.mounted) return;
    feature.mounted = true;
    await invokeFeature(feature, "mount", { runtime: api, reason: "mount" });
  }

  async function mountFeatures() {
    for (const feature of featureList()) await mountFeature(feature);
  }

  function registerFeature(definition) {
    if (!definition || typeof definition.id !== "string" || !definition.id.trim()) {
      throw new TypeError("前端功能必须提供非空 id");
    }
    const id = definition.id.trim();
    const feature = { ...definition, id, mounted: false };
    features.set(id, feature);
    if (state.started) mountFeature(feature);
    return () => features.delete(id);
  }

  function configure(adapters) {
    if (!adapters || typeof adapters.hasSession !== "function") {
      throw new TypeError("MyPetsPortal.configure 需要 hasSession 适配器");
    }
    state.adapters = { ...adapters };
  }

  function captureLegacyRefresh() {
    const candidate = window.refreshAll;
    if (typeof candidate !== "function" || candidate === requestRefresh) return;
    state.legacyRefresh = candidate;
    window.refreshAll = requestRefresh;
  }

  function installCompatibilityAliases() {
    if (typeof window.activatePortalSection === "function") {
      window.activatePortalSection = navigate;
    }
    if (typeof window.activateCustomerSection === "function") {
      window.activateCustomerSection = navigate;
    }
  }

  async function requestRefresh(...args) {
    captureLegacyRefresh();
    if (typeof state.legacyRefresh !== "function") {
      throw new Error("用户门户刷新入口尚未就绪");
    }
    if (state.refreshPromise) {
      state.refreshQueued = true;
      return state.refreshPromise;
    }

    const options = args.length === 1 && args[0] && typeof args[0] === "object"
      ? args[0]
      : { reason: "legacy", args };
    state.refreshPromise = (async () => {
      do {
        state.refreshQueued = false;
        try {
          const legacyArgs = Array.isArray(options.args) ? options.args : [];
          await state.legacyRefresh(...legacyArgs);
          clearFailure("runtime:refresh");
        } catch (error) {
          recordFailure("runtime:refresh", "基础数据", error);
          throw error;
        }
        const context = {
          runtime: api,
          reason: options.reason || "refresh",
          activeSection: state.activeSection,
        };
        for (const feature of featureList()) {
          await invokeFeature(feature, "onRefreshComplete", context);
        }
        window.dispatchEvent(new CustomEvent("mypets:portal-refreshed", { detail: context }));
      } while (state.refreshQueued);
    })().finally(() => {
      state.refreshPromise = null;
    });
    return state.refreshPromise;
  }

  function sectionExists(sectionId) {
    return Boolean(sectionId && document.getElementById(sectionId));
  }

  function navigate(sectionId, options = {}) {
    if (!sectionExists(sectionId)) return false;
    const target = document.getElementById(sectionId);
    const unchanged = state.activeSection === sectionId && !target.hidden;
    if (unchanged && !options.force) return false;

    document.querySelectorAll(".workspace").forEach((section) => {
      section.hidden = section.id !== sectionId;
    });
    document.querySelectorAll(".main-tab[data-section]").forEach((button) => {
      button.classList.toggle("active", button.dataset.section === sectionId);
      if (button.dataset.section === sectionId) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const more = document.getElementById("portal-more-navigation");
    if (more) more.open = false;
    state.activeSection = sectionId;
    if (options.focus !== false) target.focus({ preventScroll: true });

    const detail = {
      sectionId,
      source: options.source || "runtime",
      previousSectionId: options.previousSectionId || "",
    };
    window.dispatchEvent(new CustomEvent("mypets:section-change", { detail }));
    for (const feature of featureList()) {
      invokeFeature(feature, "onSectionEnter", { ...detail, runtime: api });
    }
    return true;
  }

  function installNavigation() {
    if (state.navigationInstalled) return;
    state.navigationInstalled = true;
    document.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-section]");
      if (!button || button.disabled) return;
      navigate(button.dataset.section, { source: "navigation" });
    });
  }

  function sessionEnded(context = {}) {
    window.queueMicrotask(async () => {
      state.refreshQueued = false;
      failures.clear();
      renderRuntimeStatus();
      for (const feature of featureList()) {
        await invokeFeature(feature, "onLogout", { ...context, runtime: api });
      }
      window.dispatchEvent(new CustomEvent("mypets:session-ended", { detail: context }));
    });
  }

  async function start() {
    if (state.startPromise) return state.startPromise;
    state.startPromise = (async () => {
      if (!state.adapters) throw new Error("用户门户运行时尚未配置");
      installNavigation();
      captureLegacyRefresh();
      installCompatibilityAliases();
      await mountFeatures();
      state.started = true;
      state.adapters.showLogin?.();

      const active = document.querySelector(".main-tab.active[data-section]")?.dataset.section;
      if (active && sectionExists(active)) state.activeSection = active;
      if (state.adapters.hasSession()) {
        state.adapters.enter?.();
        navigate(state.activeSection, { force: true, focus: false, source: "startup" });
        try {
          await requestRefresh({ reason: "startup" });
        } catch (error) {
          state.adapters.onError?.(error);
        }
      } else {
        navigate(state.activeSection, { force: true, focus: false, source: "anonymous" });
      }
      window.dispatchEvent(new CustomEvent("mypets:portal-ready"));
    })();
    return state.startPromise;
  }

  window.addEventListener("mypets:realtime-cursor", (event) => {
    for (const feature of featureList()) {
      invokeFeature(feature, "onRealtime", { event, runtime: api });
    }
  });

  const api = Object.freeze({
    configure,
    registerFeature,
    requestRefresh,
    navigate,
    sessionEnded,
    start,
    get activeSection() {
      return state.activeSection;
    },
    get failures() {
      return [...failures.values()].map((item) => ({ ...item }));
    },
  });

  window.MyPetsPortal = api;
})();
