from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import bind_device, register_account


def test_device_self_service_assets_are_loaded_with_portal_security_headers(
    client: TestClient,
) -> None:
    portal = client.get("/portal")

    assert portal.status_code == 200
    assert '/portal/device-self-service.css' in portal.text
    assert '/portal/device-self-service.js' in portal.text
    assert portal.text.index('/portal/party-pending-experience.js') < portal.text.index(
        '/portal/device-self-service.js'
    )
    assert portal.headers["cache-control"] == "no-store"

    script = client.get("/portal/device-self-service.js")
    stylesheet = client.get("/portal/device-self-service.css")
    assert script.status_code == 200
    assert stylesheet.status_code == 200
    assert script.headers["cache-control"] == "no-store"
    assert script.headers["x-content-type-options"] == "nosniff"
    assert stylesheet.headers["cache-control"] == "no-store"


def test_device_self_service_uses_authoritative_device_routes_and_safe_export(
    client: TestClient,
) -> None:
    script = client.get("/portal/device-self-service.js").text

    assert 'api("/api/v1/devices")' in script
    assert 'method: "DELETE"' in script
    assert "window.confirm" in script
    assert "downloadWebDiagnostics" in script
    assert "access_token" not in script
    assert "device_secret" not in script
    assert "message body" not in script.lower()
    assert "new Worker" not in script
    assert "WebSocket" not in script
    assert "window.open" not in script


def test_account_can_revoke_a_bound_device_and_the_device_token_stops_working(
    client: TestClient,
) -> None:
    account_auth = register_account(
        client,
        "device_self_service_owner",
        display_name="设备自助用户",
    )
    device, device_auth, _secret = bind_device(
        client,
        account_auth,
        public_id="device-self-service-windows-001",
        name="家用电脑",
    )

    listed = client.get("/api/v1/devices", headers=account_auth)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == device["id"] and item["revoked_at"] is None for item in listed.json())

    revoked = client.delete(f"/api/v1/devices/{device['id']}", headers=account_auth)
    assert revoked.status_code == 204, revoked.text

    listed_after = client.get("/api/v1/devices", headers=account_auth)
    assert listed_after.status_code == 200, listed_after.text
    record = next(item for item in listed_after.json() if item["id"] == device["id"])
    assert record["revoked_at"] is not None

    rejected = client.get("/api/v1/accounts/me", headers=device_auth)
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "设备已失效"
