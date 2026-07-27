from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import Account, AccountPetRelation, Pet

from .conftest import bind_device, register_account


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


def test_multi_pet_overview_prioritizes_real_state_before_routine_tasks(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    hungry = _create_pet(client, account_auth, name="饿饿", key="multi-hungry")
    stable = _create_pet(client, account_auth, name="安稳", key="multi-stable")
    visiting = _create_pet(client, account_auth, name="串串", key="multi-visiting")
    with client.app.state.session_factory() as session:
        hungry_model = session.get(Pet, hungry["pet_id"])
        stable_model = session.get(Pet, stable["pet_id"])
        visiting_model = session.get(Pet, visiting["pet_id"])
        assert hungry_model is not None and stable_model is not None and visiting_model is not None
        hungry_model.hunger = 20
        stable_model.hunger = 92
        stable_model.energy = 90
        stable_model.cleanliness = 94
        stable_model.mood = 91
        stable_model.health = 96
        stable_model.boredom = 5
        visiting_model.presence = "visiting"
        session.commit()

    selected = client.patch(
        "/api/v1/portal/preference",
        headers=account_auth,
        json={"selected_pet_id": stable["pet_id"]},
    )
    assert selected.status_code == 200, selected.text

    response = client.get(
        "/api/v1/multi-pet-overview?timezone_offset_minutes=-480",
        headers=account_auth,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_count"] == 3
    assert payload["urgent_count"] == 1
    assert payload["needs_attention_count"] == 2
    assert payload["current_pet_id"] == stable["pet_id"]
    assert payload["next_pet_id"] == hungry["pet_id"]
    assert [item["pet_id"] for item in payload["items"]] == [
        hungry["pet_id"],
        stable["pet_id"],
        visiting["pet_id"],
    ]
    by_id = {item["pet_id"]: item for item in payload["items"]}
    assert by_id[hungry["pet_id"]]["priority"] == "urgent"
    assert by_id[hungry["pet_id"]]["recommended_action"] == "feed"
    assert by_id[hungry["pet_id"]]["action_available"] is True
    assert by_id[stable["pet_id"]]["priority"] == "routine"
    assert by_id[stable["pet_id"]]["current"] is True
    assert by_id[visiting["pet_id"]]["priority"] == "unavailable"
    assert by_id[visiting["pet_id"]]["switch_candidate"] is False


def test_multi_pet_overview_respects_cooldown_and_device_current_pet(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    hungry = _create_pet(client, account_auth, name="小饿", key="multi-device-hungry")
    other = _create_pet(client, account_auth, name="小伴", key="multi-device-other")
    with client.app.state.session_factory() as session:
        pet = session.get(Pet, hungry["pet_id"])
        assert pet is not None
        pet.hunger = 18
        session.commit()

    cared = client.post(
        f"/api/v1/pets/{hungry['pet_id']}/interactions/feed",
        headers={**account_auth, "Idempotency-Key": "multi-feed-cooldown"},
        json={},
    )
    assert cared.status_code == 200, cared.text

    device, device_auth, _secret = bind_device(
        client,
        account_auth,
        public_id="multi-pet-device-0001",
    )
    switched = client.patch(
        f"/api/v1/devices/{device['id']}/active-pet",
        headers={**device_auth, "Idempotency-Key": "multi-device-active"},
        json={"pet_id": hungry["pet_id"]},
    )
    assert switched.status_code == 200, switched.text

    response = client.get("/api/v1/multi-pet-overview", headers=device_auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["current_pet_id"] == hungry["pet_id"]
    by_id = {item["pet_id"]: item for item in payload["items"]}
    assert by_id[hungry["pet_id"]]["current"] is True
    assert by_id[hungry["pet_id"]]["recommended_action"] == "feed"
    assert by_id[hungry["pet_id"]]["action_available"] is False
    assert by_id[hungry["pet_id"]]["switch_candidate"] is False
    assert "秒后" in by_id[hungry["pet_id"]]["action_reason"]
    assert payload["next_pet_id"] == other["pet_id"]


def test_viewer_pet_is_visible_but_never_added_to_care_rotation(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet = _create_pet(client, account_auth, name="只读宠物", key="multi-viewer-pet")
    viewer_auth = register_account(client, "multi_viewer", display_name="观察者")
    with client.app.state.session_factory() as session:
        viewer = session.scalar(select(Account).where(Account.username == "multi_viewer"))
        assert viewer is not None
        session.add(
            AccountPetRelation(
                account_id=viewer.id,
                pet_id=pet["pet_id"],
                role="viewer",
                affinity=0,
                care_contribution=0,
            )
        )
        session.commit()

    response = client.get("/api/v1/multi-pet-overview", headers=viewer_auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["next_pet_id"] is None
    item = payload["items"][0]
    assert item["priority"] == "unavailable"
    assert item["can_care"] is False
    assert item["action_available"] is False
    assert item["switch_candidate"] is False
    assert "只读" in item["recommendation_title"]
