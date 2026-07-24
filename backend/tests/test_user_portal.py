from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import bind_device, register_account


def _create_pet(
    client: TestClient,
    auth: dict[str, str],
    *,
    name: str,
    key: str,
) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": name,
            "template_id": "official.cat.white",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_portal_static_assets_are_same_origin_and_not_cached(client: TestClient) -> None:
    root = client.get("/", follow_redirects=False)
    assert root.status_code in {302, 307}
    assert root.headers["location"] == "/portal"

    page = client.get("/portal")
    assert page.status_code == 200
    assert "MyPets 用户中心" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert "camera=()" in page.headers["permissions-policy"]

    script = client.get("/portal/app.js")
    assert script.status_code == 200
    assert "sessionStorage" in script.text
    assert "localStorage" not in script.text
    assert "/api/v1/portal/dashboard" in script.text
    assert "/api/v1/friend-requests" in script.text


def test_account_profile_and_password_maintenance(client: TestClient) -> None:
    auth = register_account(
        client,
        "portal_owner",
        display_name="旧名称",
        password="old-password-strong-001",
    )
    dashboard = client.get("/api/v1/portal/dashboard", headers=auth)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["account"]["display_name"] == "旧名称"
    assert dashboard.json()["pets"] == []

    updated = client.patch(
        "/api/v1/portal/account",
        headers=auth,
        json={"display_name": "新名称"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "新名称"
    assert client.get("/api/v1/accounts/me", headers=auth).json()["display_name"] == "新名称"

    wrong = client.post(
        "/api/v1/portal/account/password",
        headers=auth,
        json={
            "current_password": "not-the-current-password",
            "new_password": "new-password-strong-002",
        },
    )
    assert wrong.status_code == 403

    changed = client.post(
        "/api/v1/portal/account/password",
        headers=auth,
        json={
            "current_password": "old-password-strong-001",
            "new_password": "new-password-strong-002",
        },
    )
    assert changed.status_code == 204, changed.text

    old_login = client.post(
        "/api/v1/auth/token",
        data={"username": "portal_owner", "password": "old-password-strong-001"},
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/api/v1/auth/token",
        data={"username": "portal_owner", "password": "new-password-strong-002"},
    )
    assert new_login.status_code == 200, new_login.text


def test_pet_selection_configuration_and_friend_maintenance(client: TestClient) -> None:
    owner = register_account(client, "web_pet_owner", display_name="Web 主人")
    friend = register_account(client, "web_friend", display_name="Web 好友")
    first = _create_pet(client, owner, name="小一", key="portal-create-pet-0001")
    second = _create_pet(client, owner, name="小二", key="portal-create-pet-0002")
    _, device_auth, _ = bind_device(
        client,
        owner,
        public_id="portal-device-0001",
        name="门户联动设备",
    )

    initial = client.get("/api/v1/portal/dashboard", headers=owner)
    assert initial.status_code == 200, initial.text
    assert initial.json()["selected_pet_id"] == first["pet_id"]
    assert {item["pet"]["pet_id"] for item in initial.json()["pets"]} == {
        first["pet_id"],
        second["pet_id"],
    }

    selected = client.patch(
        "/api/v1/portal/preference",
        headers=owner,
        json={"selected_pet_id": second["pet_id"]},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_pet_id"] == second["pet_id"]
    assert next(
        item for item in selected.json()["pets"] if item["pet"]["pet_id"] == second["pet_id"]
    )["selected"] is True

    configured = client.patch(
        f"/api/v1/portal/pets/{second['pet_id']}",
        headers=owner,
        json={"name": "小二号", "personality_type": "curious"},
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["pet"]["name"] == "小二号"
    assert configured.json()["pet"]["personality_type"] == "curious"

    events = client.get(
        "/api/v1/sync/events?after_sequence=0&limit=500",
        headers=device_auth,
    )
    assert events.status_code == 200, events.text
    matching = [
        event
        for event in events.json()["events"]
        if event["event_type"] == "pet_updated"
        and event["payload"].get("cause") == "portal_pet_config"
    ]
    assert matching
    assert matching[-1]["payload"]["pet"]["name"] == "小二号"

    request = client.post(
        "/api/v1/friend-requests",
        headers=owner,
        json={"username": "web_friend"},
    )
    assert request.status_code == 201, request.text
    incoming = client.get("/api/v1/friend-requests", headers=friend)
    assert incoming.status_code == 200
    assert incoming.json()["incoming"][0]["sender"]["username"] == "web_pet_owner"
    accepted = client.post(
        f"/api/v1/friend-requests/{request.json()['request_id']}/accept",
        headers=friend,
    )
    assert accepted.status_code == 200, accepted.text
    friends = client.get("/api/v1/friends", headers=owner)
    assert friends.status_code == 200
    assert friends.json()[0]["friend"]["username"] == "web_friend"
