from __future__ import annotations

from fastapi.testclient import TestClient


def test_portal_runtime_loads_before_core_and_waits_for_final_bootstrap(
    client: TestClient,
) -> None:
    response = client.get("/portal")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert '/portal/portal-runtime.css' in response.text
    runtime_index = response.text.index('/portal/portal-runtime.js')
    app_index = response.text.index('/portal/app.js')
    phase1_index = response.text.index('/portal/phase1.js')
    last_extension_index = response.text.index('/portal/device-self-service.js')
    bootstrap_index = response.text.index('/portal/portal-bootstrap.js')
    assert runtime_index < app_index < phase1_index
    assert phase1_index < last_extension_index < bootstrap_index
    assert '/portal/phase1-bootstrap.js' not in response.text


def test_portal_asset_manifest_serves_runtime_and_legacy_compatibility_assets(
    client: TestClient,
) -> None:
    for path in (
        "/portal/portal-runtime.js",
        "/portal/portal-bootstrap.js",
        "/portal/portal-runtime.css",
        "/portal/app.js",
        "/portal/customer-experience.js",
        "/portal/device-self-service.js",
        "/portal/css/portal_cute.css",
        "/portal/js/portal.js",
        "/portal/phase1-bootstrap.js",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"

    missing = client.get("/portal/not-a-real-asset.js")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "用户门户资源不存在"


def test_portal_runtime_centralizes_refresh_navigation_and_failure_isolation(
    client: TestClient,
) -> None:
    source = client.get("/portal/portal-runtime.js").text

    assert "registerFeature" in source
    assert "runFeatureHook" in source
    assert "markExtensionsReady" in source
    assert "waitForExtensionsReady" in source
    assert "await waitForExtensionsReady()" in source
    assert "captureLegacyRefresh" in source
    assert "window.refreshAll = requestRefresh" in source
    assert "state.refreshPromise" in source
    assert "state.refreshQueued" in source
    assert "state.sectionHookPromise" in source
    assert 'runFeatureHook("onRefreshComplete"' in source
    assert 'runFeatureHook("onSectionEnter"' in source
    assert 'runFeatureHook("onRealtime"' in source
    assert 'runFeatureHook("onLogout"' in source
    assert 'new CustomEvent("mypets:extensions-ready"' in source
    assert 'new CustomEvent("mypets:section-change"' in source
    assert 'new CustomEvent("mypets:portal-refreshed"' in source
    assert "invokeFeature" in source
    assert "recordFailure" in source
    assert "部分功能暂未完成加载" in source
    assert "new Worker" not in source
    assert "WebSocket" not in source


def test_final_bootstrap_marks_extensions_ready_before_starting_runtime(
    client: TestClient,
) -> None:
    source = client.get("/portal/portal-bootstrap.js").text

    ready_index = source.index("runtime.markExtensionsReady()")
    start_index = source.index("runtime.start()")
    assert ready_index < start_index
    assert "setTimeout" not in source
    assert "new Worker" not in source
    assert "WebSocket" not in source


def test_core_portal_uses_runtime_startup_and_no_longer_owns_tab_switching(
    client: TestClient,
) -> None:
    source = client.get("/portal/app.js").text

    assert "const portalRuntime = window.MyPetsPortal" in source
    assert "portalRuntime.configure" in source
    assert "portalRuntime.start()" in source
    assert "portalRuntime.sessionEnded" in source
    assert 'document.querySelectorAll(".main-tab")' not in source
    assert "await refreshAll({ reason: \"login\" })" in source
    assert "await refreshAll({ reason: \"register\" })" in source


def test_phase1_core_uses_ordered_runtime_lifecycle_hooks(client: TestClient) -> None:
    source = client.get("/portal/phase1.js").text

    assert 'id: "phase1-core"' in source
    assert "order: 10" in source
    assert 'portalRuntime.runFeatureHook("onPetContextRefresh"' in source
    assert 'portalRuntime.runFeatureHook("onCareComplete"' in source
    assert "onRefreshComplete:" in source
    assert "onSectionEnter:" in source
    assert "onRealtime:" in source
    assert "onLogout:" in source
    assert 'portalRuntime.requestRefresh({ reason: "manual-phase1" })' in source
    assert "const baseRefreshAllForPhase1" not in source
    assert 'document.querySelectorAll(".main-tab")' not in source
    assert 'window.addEventListener("mypets:realtime-cursor"' not in source


def test_daily_care_no_longer_replaces_shared_global_functions(
    client: TestClient,
) -> None:
    source = client.get("/portal/daily-care-experience.js").text

    assert 'id: "daily-care"' in source
    assert "order: 100" in source
    assert "onPetContextRefresh:" in source
    assert "onRefreshComplete:" in source
    assert "onSectionEnter:" in source
    assert "onCareComplete:" in source
    assert "onLogout:" in source
    assert "renderDailyCareIntegrations" in source
    assert "baseRefreshPhase1PetDataForDailyCare" not in source
    assert "baseRenderPortalPhase1ForDailyCare" not in source
    assert "baseRecommendedCareForDailyCare" not in source
    assert "baseRenderCareRecommendationForDailyCare" not in source
    assert "baseRenderNextStepsForDailyCare" not in source
    assert "basePerformPhase1CareForDailyCare" not in source
    assert "baseLogoutForDailyCare" not in source
    assert "refreshPhase1PetData =" not in source
    assert "renderPortalPhase1 =" not in source
    assert "performPhase1Care =" not in source
    assert "logout =" not in source


def test_growth_experience_uses_pet_context_lifecycle_without_global_replacement(
    client: TestClient,
) -> None:
    source = client.get("/portal/growth-experience.js").text

    assert 'id: "growth-experience"' in source
    assert "order: 110" in source
    assert "onPetContextRefresh:" in source
    assert "onRefreshComplete:" in source
    assert "onSectionEnter:" in source
    assert "onCareComplete:" in source
    assert "onLogout:" in source
    assert "baseRefreshPhase1PetDataForGrowth" not in source
    assert "baseRenderPortalPhase1ForGrowth" not in source
    assert "baseLogoutForGrowth" not in source
    assert "refreshPhase1PetData =" not in source
    assert "renderPortalPhase1 =" not in source
    assert "logout =" not in source


def test_proactive_care_uses_refresh_realtime_and_logout_lifecycle_hooks(
    client: TestClient,
) -> None:
    source = client.get("/portal/proactive-care-experience.js").text

    assert 'id: "proactive-care"' in source
    assert "order: 130" in source
    assert "onRefreshComplete:" in source
    assert "onSectionEnter:" in source
    assert "onRealtime:" in source
    assert "onLogout:" in source
    assert "baseRefreshAllForProactiveCare" not in source
    assert "baseRenderDashboardForProactiveCare" not in source
    assert "baseLogoutForProactiveCare" not in source
    assert 'window.addEventListener("mypets:realtime-cursor"' not in source
    assert "refreshAll =" not in source
    assert "renderDashboard =" not in source
    assert "logout =" not in source
