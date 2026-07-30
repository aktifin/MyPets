from __future__ import annotations

from fastapi.testclient import TestClient


def test_final_bootstrap_only_opens_the_extension_readiness_gate(
    client: TestClient,
) -> None:
    source = client.get("/portal/portal-bootstrap.js").text

    ready_index = source.index("runtime.markExtensionsReady()")
    start_index = source.index("runtime.start()")
    assert ready_index < start_index
    assert "legacy-render-projection-bridge" not in source
    assert "renderMigratedProjections" not in source
    assert "baseRenderDashboard" not in source
    assert "baseRenderPortalPhase1" not in source
    assert "queueRenderHook" not in source
    assert "__mypetsPortalRenderBridgeInstalled" not in source
    assert "fetch(" not in source
    assert "api(" not in source
    assert "setInterval" not in source
    assert "setTimeout" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "new Worker" not in source
    assert "WebSocket" not in source


def test_core_renderers_publish_projection_lifecycle_directly(
    client: TestClient,
) -> None:
    app_source = client.get("/portal/app.js").text
    phase1_source = client.get("/portal/phase1.js").text

    assert 'portalRuntime.applyFeatureHook("onDashboardRenderComplete"' in app_source
    assert 'portalRuntime.applyFeatureHook("onSocialRenderComplete"' in app_source
    assert 'portalRuntime.applyFeatureHook("onPhase1RenderComplete"' in phase1_source
    assert "notifyExtensions: false" in phase1_source
    assert "onDashboardRenderComplete:" in phase1_source
    assert "baseRenderDashboardForPhase1" not in phase1_source
    assert "renderDashboard = function" not in phase1_source


def test_customer_experience_uses_projection_lifecycle_without_global_replacement(
    client: TestClient,
) -> None:
    source = client.get("/portal/customer-experience.js").text

    assert 'id: "customer-experience"' in source
    assert "order: 80" in source
    assert "onDashboardRenderComplete:" in source
    assert "onPhase1RenderComplete:" in source
    assert "onSocialRenderComplete:" in source
    assert "onSectionEnter:" in source
    assert "onLogout:" in source
    assert 'portalRuntime.navigate(sectionId, { source: "customer-experience" })' in source
    assert "baseRefreshAllForCustomerExperience" not in source
    assert "baseRenderDashboardForCustomerExperience" not in source
    assert "baseRenderPortalPhase1ForCustomerExperience" not in source
    assert "baseLogoutForCustomerExperience" not in source
    assert "refreshAll =" not in source
    assert "renderDashboard = function" not in source
    assert "renderPortalPhase1 = function" not in source
    assert "logout = function" not in source
    assert 'navigation.addEventListener("click"' not in source


def test_multi_pet_overview_uses_lifecycle_managed_polling(
    client: TestClient,
) -> None:
    source = client.get("/portal/multi-pet-overview.js").text

    assert 'id: "multi-pet-overview"' in source
    assert "order: 180" in source
    assert "onRefreshComplete:" in source
    assert "onDashboardRenderComplete:" in source
    assert "onPhase1RenderComplete:" in source
    assert "onSectionEnter:" in source
    assert "onCareComplete:" in source
    assert "onRealtime:" in source
    assert "onLogout:" in source
    assert "startMultiPetPolling" in source
    assert "stopMultiPetPolling" in source
    assert "window.clearInterval(multiPetOverviewState.timerId)" in source
    assert "baseRefreshAllForMultiPetOverview" not in source
    assert "basePerformPhase1CareForMultiPetOverview" not in source
    assert "refreshAll =" not in source
    assert "performPhase1Care =" not in source
