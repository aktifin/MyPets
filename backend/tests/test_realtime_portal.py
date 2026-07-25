from __future__ import annotations

from fastapi.testclient import TestClient


def test_portal_loads_same_origin_realtime_client_with_websocket_csp(
    client: TestClient,
) -> None:
    page = client.get("/portal")
    assert page.status_code == 200
    assert '<script src="/portal/realtime.js" defer></script>' in page.text
    csp = page.headers["content-security-policy"]
    assert "connect-src 'self' ws: wss:" in csp
    assert page.headers["cache-control"] == "no-store"

    script = client.get("/portal/realtime.js")
    assert script.status_code == 200
    assert script.headers["cache-control"] == "no-store"
    assert "mypets.realtime.v1" in script.text
    assert "/api/v1/realtime/ticket" in script.text
    assert "localStorage" not in script.text
    assert "sessionStorage.setItem" not in script.text
