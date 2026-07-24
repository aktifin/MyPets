from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import bind_device


def create_pet(
    client: TestClient,
    account_auth: dict[str, str],
    key: str = "pet-create-0001",
) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**account_auth, "Idempotency-Key": key},
        json={
            "name": "小白",
            "template_id": "official.cat.white",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pet_creation_is_idempotent_and_bootstrap_is_server_snapshot(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    device, device_auth, _ = bind_device(client, account_auth)
    first = create_pet(client, account_auth)
    second = create_pet(client, account_auth)
    assert first["pet_id"] == second["pet_id"]
    assert len(client.get("/api/v1/pets", headers=account_auth).json()) == 1

    active = client.patch(
        f"/api/v1/devices/{device['id']}/active-pet",
        headers={**device_auth, "Idempotency-Key": "active-pet-0001"},
        json={"pet_id": first["pet_id"]},
    )
    assert active.status_code == 200
    assert active.json()["active_pet_id"] == first["pet_id"]

    bootstrap = client.get("/api/v1/sync/bootstrap", headers=device_auth)
    assert bootstrap.status_code == 200
    body = bootstrap.json()
    assert body["schema_version"] == "1.0"
    assert body["device"]["active_pet_id"] == first["pet_id"]
    assert body["pets"][0]["stats"]["growth_stage"] == "newborn"
    assert body["relations"] == [
        {
            "account_id": body["account"]["id"],
            "pet_id": first["pet_id"],
            "role": "owner",
            "affinity": 0,
            "care_contribution": 0,
        }
    ]
    assert body["cursor"] >= 3


def test_incremental_events_are_filtered_per_device(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    device_one, device_one_auth, _ = bind_device(
        client,
        account_auth,
        public_id="windows-device-one",
        name="设备一",
    )
    _device_two, device_two_auth, _ = bind_device(
        client,
        account_auth,
        public_id="windows-device-two",
        name="设备二",
    )
    pet = create_pet(client, account_auth)
    client.patch(
        f"/api/v1/devices/{device_one['id']}/active-pet",
        headers={**device_one_auth, "Idempotency-Key": "active-one-0001"},
        json={"pet_id": pet["pet_id"]},
    )

    one = client.get("/api/v1/sync/events?after_sequence=0", headers=device_one_auth)
    two = client.get("/api/v1/sync/events?after_sequence=0", headers=device_two_auth)
    assert one.status_code == two.status_code == 200
    one_types = [event["event_type"] for event in one.json()["events"]]
    two_types = [event["event_type"] for event in two.json()["events"]]
    assert "pet_created" in one_types and "pet_created" in two_types
    assert "active_pet_changed" in one_types
    assert "active_pet_changed" not in two_types

    cursor = one.json()["next_cursor"]
    empty = client.get(
        f"/api/v1/sync/events?after_sequence={cursor}", headers=device_one_auth
    )
    assert empty.json() == {
        "events": [],
        "next_cursor": cursor,
        "has_more": False,
    }


def test_account_token_cannot_use_device_sync_endpoint(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    response = client.get("/api/v1/sync/bootstrap", headers=account_auth)
    assert response.status_code == 403


def test_idempotency_key_cannot_be_reused_for_another_mutation(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    device, device_auth, _ = bind_device(client, account_auth)
    pet = create_pet(client, account_auth, key="shared-key-0001")
    conflict = client.patch(
        f"/api/v1/devices/{device['id']}/active-pet",
        headers={**device_auth, "Idempotency-Key": "shared-key-0001"},
        json={"pet_id": pet["pet_id"]},
    )
    assert conflict.status_code == 409


def test_heartbeat_updates_liveness_and_returns_cursor(
    client: TestClient, account_auth: dict[str, str]
) -> None:
    _device, device_auth, _ = bind_device(client, account_auth)
    heartbeat = client.post("/api/v1/sync/heartbeat", headers=device_auth)
    assert heartbeat.status_code == 200
    assert heartbeat.json()["cursor"] >= 1
    server_time = heartbeat.json()["server_time"]
    assert server_time.endswith("Z") or "+00:00" in server_time
