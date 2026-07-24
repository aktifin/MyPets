from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import Pet, SyncEvent
from mypets_backend.pet_settlement import HEALTH_FLOOR, settle_pet_state


def _create_pet(
    client: TestClient,
    auth: dict[str, str],
    *,
    key: str,
) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": "米粒",
            "template_id": "official.cat.settlement",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _bind_device(client: TestClient, auth: dict[str, str]) -> dict[str, str]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=auth,
        json={
            "public_id": "settlement-windows-device",
            "name": "结算测试电脑",
            "platform": "windows",
        },
    )
    assert bound.status_code == 201, bound.text
    data = bound.json()
    token = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": data["device"]["id"],
            "device_secret": data["device_secret"],
        },
    )
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_settlement_is_deterministic_and_not_repeated() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    pet = Pet(
        id="pet-settlement-unit",
        name="米粒",
        template_id="official.cat",
        template_version="1.0.0",
        identity_version="1.0.0",
        primary_owner_account_id="account-1",
        hunger=80,
        energy=70,
        mood=75,
        cleanliness=60,
        health=100,
        boredom=10,
        updated_at=now - timedelta(hours=3, minutes=45),
        created_at=now - timedelta(days=1),
    )

    mutation = settle_pet_state(pet, now)
    assert mutation.elapsed_hours == 3
    assert pet.hunger == 74
    assert pet.energy == 67
    assert pet.mood == 72
    assert pet.cleanliness == 57
    assert pet.boredom == 16
    assert pet.state_version == 2

    repeated = settle_pet_state(pet, now)
    assert repeated.elapsed_hours == 0
    assert not repeated.changed
    assert pet.state_version == 2


def test_long_absence_is_capped_and_health_has_a_floor() -> None:
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    pet = Pet(
        id="pet-settlement-long",
        name="米粒",
        template_id="official.cat",
        template_version="1.0.0",
        identity_version="1.0.0",
        primary_owner_account_id="account-1",
        hunger=0,
        energy=20,
        mood=20,
        cleanliness=0,
        health=55,
        boredom=90,
        updated_at=now - timedelta(days=90),
        created_at=now - timedelta(days=100),
    )

    mutation = settle_pet_state(pet, now)
    assert mutation.elapsed_hours == 24 * 30
    assert pet.health == HEALTH_FLOOR
    assert pet.hunger == 0
    assert pet.boredom == 100


def test_pet_list_lazily_settles_once_and_publishes_sync_event(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet = _create_pet(client, account_auth, key="create-settlement-list-pet")
    with client.app.state.session_factory() as session:
        row = session.get(Pet, pet["pet_id"])
        assert row is not None
        row.hunger = 80
        row.energy = 70
        row.updated_at = datetime.now(UTC) - timedelta(hours=4, minutes=10)
        session.commit()

    first = client.get("/api/v1/pets", headers=account_auth)
    assert first.status_code == 200, first.text
    snapshot = next(item for item in first.json() if item["pet_id"] == pet["pet_id"])
    assert snapshot["stats"]["hunger"] == 72
    assert snapshot["stats"]["energy"] == 66

    second = client.get("/api/v1/pets", headers=account_auth)
    assert second.status_code == 200
    repeated = next(item for item in second.json() if item["pet_id"] == pet["pet_id"])
    assert repeated["stats"]["hunger"] == 72

    with client.app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(SyncEvent).where(
                    SyncEvent.event_type == "pet_updated",
                    SyncEvent.idempotency_key.like("pet-settlement:%"),
                )
            )
        )
        assert len(events) == 1


def test_bootstrap_contains_settled_state_and_cursor(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet = _create_pet(client, account_auth, key="create-bootstrap-settlement-pet")
    device_auth = _bind_device(client, account_auth)
    with client.app.state.session_factory() as session:
        row = session.get(Pet, pet["pet_id"])
        assert row is not None
        row.cleanliness = 70
        row.updated_at = datetime.now(UTC) - timedelta(hours=2, minutes=5)
        session.commit()

    bootstrap = client.get("/api/v1/sync/bootstrap", headers=device_auth)
    assert bootstrap.status_code == 200, bootstrap.text
    snapshot = next(
        item for item in bootstrap.json()["pets"] if item["pet_id"] == pet["pet_id"]
    )
    assert snapshot["stats"]["cleanliness"] == 68
    assert bootstrap.json()["cursor"] >= 1


def test_care_emits_level_stage_and_bond_events_with_growth_history(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet = _create_pet(client, account_auth, key="create-growth-transition-pet")
    with client.app.state.session_factory() as session:
        row = session.get(Pet, pet["pet_id"])
        assert row is not None
        row.growth_exp = 199
        row.growth_level = 2
        row.growth_stage = "newborn"
        row.bond_exp = 79
        row.bond_level = 1
        row.updated_at = datetime.now(UTC)
        session.commit()

    care = client.post(
        f"/api/v1/pets/{pet['pet_id']}/interactions/feed",
        headers={**account_auth, "Idempotency-Key": "growth-transition-feed"},
        json={},
    )
    assert care.status_code == 200, care.text
    interaction = care.json()["interaction"]
    assert interaction["growth_level_changed"]
    assert interaction["growth_stage_changed"]
    assert interaction["bond_level_changed"]
    assert care.json()["pet"]["stats"]["growth_level"] == 3
    assert care.json()["pet"]["stats"]["growth_stage"] == "child"
    assert care.json()["pet"]["stats"]["bond_level"] == 2

    growth = client.get(f"/api/v1/pets/{pet['pet_id']}/growth", headers=account_auth)
    assert growth.status_code == 200, growth.text
    event_types = {item["event_type"] for item in growth.json()["history"]}
    assert event_types == {"growth_level_up", "growth_stage_changed", "bond_level_up"}
