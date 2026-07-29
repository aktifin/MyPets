from __future__ import annotations

from fastapi.testclient import TestClient


def test_party_portal_assets_are_injected_and_secured(client: TestClient) -> None:
    response = client.get("/portal")
    assert response.status_code == 200
    assert '/portal/party-experience.css' in response.text
    assert '/portal/party-experience.js' in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "script-src 'self'" in response.headers["content-security-policy"]

    script = client.get("/portal/party-experience.js")
    assert script.status_code == 200
    assert script.headers["x-content-type-options"] == "nosniff"
    assert "desktop_window_limit" in script.text
    assert "partySceneGuard" in script.text
    assert "邀请好友一起玩" in script.text
    assert "同一聚会场景" in script.text
    assert "window.open" not in script.text
    assert "new Worker" not in script.text
    assert "WebSocket" not in script.text

    stylesheet = client.get("/portal/party-experience.css")
    assert stylesheet.status_code == 200
    assert ".party-member-grid" in stylesheet.text
    assert ".party-scene-card" in stylesheet.text
    assert ".party-empty-state" in stylesheet.text
    assert ".party-activity-banner" in stylesheet.text
