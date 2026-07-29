from __future__ import annotations

from fastapi.testclient import TestClient


def test_final_bootstrap_bridges_completed_legacy_render_chains(
    client: TestClient,
) -> None:
    source = client.get("/portal/portal-bootstrap.js").text

    register_index = source.index('id: "legacy-render-projection-bridge"')
    ready_index = source.index("runtime.markExtensionsReady()")
    start_index = source.index("runtime.start()")
    assert register_index < ready_index < start_index
    assert 'order: 900' in source
    assert 'onDashboardRenderComplete: renderMigratedProjections' in source
    assert 'onPhase1RenderComplete: renderMigratedProjections' in source
    assert 'queueRenderHook("onDashboardRenderComplete")' in source
    assert 'queueRenderHook("onPhase1RenderComplete")' in source
    assert 'const baseRenderDashboard = renderDashboard' in source
    assert 'const baseRenderPortalPhase1 = renderPortalPhase1' in source
    assert 'renderDailyCareIntegrations()' in source
    assert 'renderGrowthExperience()' in source
    assert 'renderProactiveCareNotice()' in source
    assert source.count('window.__mypetsPortalRenderBridgeInstalled') == 2
    assert "new Worker" not in source
    assert "WebSocket" not in source


def test_render_bridge_does_not_add_data_or_background_execution(
    client: TestClient,
) -> None:
    source = client.get("/portal/portal-bootstrap.js").text

    assert "fetch(" not in source
    assert "api(" not in source
    assert "setInterval" not in source
    assert "setTimeout" not in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
