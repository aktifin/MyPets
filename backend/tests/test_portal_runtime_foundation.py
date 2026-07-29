from __future__ import annotations

from fastapi.testclient import TestClient


def test_portal_runtime_loads_before_core_and_replaces_duplicate_bootstrap(
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
    assert runtime_index < app_index < phase1_index
    assert '/portal/phase1-bootstrap.js' not in response.text


def test_portal_asset_manifest_serves_runtime_and_legacy_compatibility_assets(
    client: TestClient,
) -> None:
    for path in (
        "/portal/portal-runtime.js",
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
    assert "captureLegacyRefresh" in source
    assert "window.refreshAll = requestRefresh" in source
    assert "state.refreshPromise" in source
    assert "state.refreshQueued" in source
    assert 'new CustomEvent("mypets:section-change"' in source
    assert 'new CustomEvent("mypets:portal-refreshed"' in source
    assert "invokeFeature" in source
    assert "recordFailure" in source
    assert "部分功能暂未完成加载" in source
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
