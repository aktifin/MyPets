"use strict";

(() => {
  const runtime = window.MyPetsPortal;
  if (!runtime) {
    console.error("[MyPetsPortal] runtime missing before bootstrap");
    return;
  }

  function renderMigratedProjections() {
    if (typeof renderDailyCareIntegrations === "function") {
      renderDailyCareIntegrations();
    }
    if (typeof renderGrowthExperience === "function") {
      renderGrowthExperience();
    }
    if (typeof renderProactiveCareNotice === "function") {
      renderProactiveCareNotice();
    }
  }

  runtime.registerFeature({
    id: "legacy-render-projection-bridge",
    label: "首页扩展展示",
    order: 900,
    onDashboardRenderComplete: renderMigratedProjections,
    onPhase1RenderComplete: renderMigratedProjections,
  });

  let renderHookPromise = Promise.resolve();
  const queueRenderHook = (hook) => {
    renderHookPromise = renderHookPromise
      .then(() => runtime.runFeatureHook(hook))
      .catch((error) => {
        console.error(`[MyPetsPortal] ${hook} bridge failed`, error);
      });
  };

  if (!window.__mypetsPortalRenderBridgeInstalled) {
    window.__mypetsPortalRenderBridgeInstalled = true;

    if (typeof renderDashboard === "function") {
      const baseRenderDashboard = renderDashboard;
      renderDashboard = function renderDashboardWithLifecycle(...args) {
        const result = baseRenderDashboard(...args);
        queueRenderHook("onDashboardRenderComplete");
        return result;
      };
    }

    if (typeof renderPortalPhase1 === "function") {
      const baseRenderPortalPhase1 = renderPortalPhase1;
      renderPortalPhase1 = function renderPortalPhase1WithLifecycle(...args) {
        const result = baseRenderPortalPhase1(...args);
        queueRenderHook("onPhase1RenderComplete");
        return result;
      };
    }
  }

  runtime.markExtensionsReady();
  runtime.start().catch((error) => {
    console.error("[MyPetsPortal] startup failed", error);
  });
})();
