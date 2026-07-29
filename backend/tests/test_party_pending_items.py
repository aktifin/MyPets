from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import bind_device, register_account


def _create_pet(
    client: TestClient,
    auth: dict[str, str],
    *,
    name: str,
    key: str,
) -> dict[str, object]:
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


def _make_friends(
    client: TestClient,
    sender_auth: dict[str, str],
    recipient_auth: dict[str, str],
    *,
    recipient_username: str,
) -> None:
    created = client.post(
        "/api/v1/friend-requests",
        headers=sender_auth,
        json={"username": recipient_username},
    )
    assert created.status_code == 201, created.text
    accepted = client.post(
        f"/api/v1/friend-requests/{created.json()['request_id']}/accept",
        headers=recipient_auth,
    )
    assert accepted.status_code == 200, accepted.text


def _invite_owner_to_party(
    client: TestClient,
    owner_auth: dict[str, str],
) -> tuple[str, str]:
    host_auth = register_account(
        client,
        "pending_party_host",
        display_name="聚会发起人",
    )
    _make_friends(
        client,
        host_auth,
        owner_auth,
        recipient_username="owner_1",
    )
    host_pet = _create_pet(
        client,
        host_auth,
        name="奶盖",
        key="pending-party-host-pet",
    )
    guest_pet = _create_pet(
        client,
        owner_auth,
        name="团子",
        key="pending-party-guest-pet",
    )
    created = client.post(
        "/api/v1/parties",
        headers=host_auth,
        json={
            "host_pet_id": host_pet["pet_id"],
            "title": "周末小聚",
            "note": "一起轻松玩一会儿",
            "max_members": 4,
            "duration_minutes": 60,
        },
    )
    assert created.status_code == 201, created.text
    party_id = str(created.json()["party_id"])
    invited = client.post(
        f"/api/v1/parties/{party_id}/invitations",
        headers=host_auth,
        json={"username": "owner_1"},
    )
    assert invited.status_code == 200, invited.text
    return party_id, str(guest_pet["pet_id"])


def test_party_invitation_is_read_only_pending_projection(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    party_id, guest_pet_id = _invite_owner_to_party(client, account_auth)

    response = client.get("/api/v1/pending-items", headers=account_auth)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["kind"] == "party_invitation"
    assert item["item_id"] == party_id
    assert item["title"] == "聚会发起人 邀请你参加“周末小聚”"
    assert item["pet_name"] == "奶盖"
    assert item["actions"] == []
    assert "选择一只自己管理且当前在家的宠物" in item["detail"]

    bypass = client.post(
        f"/api/v1/pending-items/party_invitation/{party_id}/accept",
        headers={**account_auth, "Idempotency-Key": "party-pending-bypass"},
        json={},
    )
    assert bypass.status_code == 422, bypass.text

    accepted = client.post(
        f"/api/v1/parties/{party_id}/accept",
        headers=account_auth,
        json={"pet_id": guest_pet_id},
    )
    assert accepted.status_code == 200, accepted.text

    cleared = client.get("/api/v1/pending-items", headers=account_auth)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["count"] == 0


def test_party_invitation_contributes_to_device_tray_count(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    party_id, _guest_pet_id = _invite_owner_to_party(client, account_auth)
    _device, device_auth, _secret = bind_device(
        client,
        account_auth,
        public_id="party-pending-device-0001",
    )

    response = client.get("/api/v1/pending-items", headers=device_auth)

    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["item_id"] == party_id
    assert response.json()["items"][0]["kind"] == "party_invitation"
