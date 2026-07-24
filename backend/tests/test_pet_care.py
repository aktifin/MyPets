from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import bind_device, register_account
from mypets_backend.models import Account, AccountPetRelation, Pet, SyncEvent


def _create_pet(client: TestClient, auth: dict[str, str], *, key: str = "create-care-pet") -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": key},
        json={
            "name": "团团",
            "template_id": "official.cat.care",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_feed_updates_server_state_and_is_idempotent(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet = _create_pet(client, account_auth)
    pet_id = pet["pet_id"]

    with client.app.state.session_factory() as session:
        row = session.get(Pet, pet_id)
        assert row is not None
        row.hunger = 70
        session.commit()

    headers = {**account_auth, "Idempotency-Key": "care-feed-once"}
    first = client.post(
        f"/api/v1/pets/{pet_id}/interactions/feed",
        headers=headers,
        json={},
    )
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["pet"]["stats"]["hunger"] == 88
    assert payload["pet"]["stats"]["growth_exp"] == 4
    assert payload["relation"]["affinity"] == 2
    assert payload["interaction"]["deltas"]["hunger"] == 18

    retry = client.post(
        f"/api/v1/pets/{pet_id}/interactions/feed",
        headers=headers,
        json={},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json() == payload

    with client.app.state.session_factory() as session:
        row = session.get(Pet, pet_id)
        relation = session.get(AccountPetRelation, (row.primary_owner_account_id, pet_id))
        assert row is not None and relation is not None
        assert row.hunger == 88
        assert row.growth_exp == 4
        assert relation.affinity == 2
        care_events = list(
            session.scalars(
                select(SyncEvent).where(
                    SyncEvent.account_id == row.primary_owner_account_id,
                    SyncEvent.event_type == "pet_updated",
                )
            )
        )
        assert len(care_events) == 1


def test_device_token_can_play_and_sync_pet_update(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet = _create_pet(client, account_auth, key="create-device-care-pet")
    device, device_auth, _secret = bind_device(client, account_auth)

    response = client.post(
        f"/api/v1/pets/{pet['pet_id']}/interactions/play",
        headers={**device_auth, "Idempotency-Key": "device-play-care"},
        json={"device_id": device["id"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["interaction"]["device_id"] == device["id"]
    assert data["pet"]["stats"]["energy"] == 88
    assert data["pet"]["stats"]["mood"] == 90
    assert data["pet"]["stats"]["boredom"] == 0

    events = client.get(
        "/api/v1/sync/events?after_sequence=0&limit=100",
        headers=device_auth,
    )
    assert events.status_code == 200, events.text
    care = [
        item
        for item in events.json()["events"]
        if item["event_type"] == "pet_updated"
        and item["payload"].get("cause") == "pet_care"
    ]
    assert len(care) == 1
    assert care[0]["payload"]["pet"]["stats"]["energy"] == 88


def test_same_action_has_cooldown_but_different_action_is_allowed(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth, key="create-cooldown-pet")["pet_id"]
    first = client.post(
        f"/api/v1/pets/{pet_id}/interactions/pet",
        headers={**account_auth, "Idempotency-Key": "care-pet-first"},
        json={},
    )
    assert first.status_code == 200

    cooldown = client.post(
        f"/api/v1/pets/{pet_id}/interactions/pet",
        headers={**account_auth, "Idempotency-Key": "care-pet-second"},
        json={},
    )
    assert cooldown.status_code == 429
    assert int(cooldown.headers["Retry-After"]) >= 1

    clean = client.post(
        f"/api/v1/pets/{pet_id}/interactions/clean",
        headers={**account_auth, "Idempotency-Key": "care-clean-after-pet"},
        json={},
    )
    assert clean.status_code == 200, clean.text


def test_viewer_and_unrelated_accounts_cannot_care_for_pet(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet = _create_pet(client, account_auth, key="create-private-care-pet")
    viewer_auth = register_account(client, "viewer_user")
    stranger_auth = register_account(client, "stranger_user")

    with client.app.state.session_factory() as session:
        viewer = session.scalar(select(Account).where(Account.username == "viewer_user"))
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

    viewer_response = client.post(
        f"/api/v1/pets/{pet['pet_id']}/interactions/feed",
        headers={**viewer_auth, "Idempotency-Key": "viewer-care-denied"},
        json={},
    )
    assert viewer_response.status_code == 403

    stranger_response = client.post(
        f"/api/v1/pets/{pet['pet_id']}/interactions/feed",
        headers={**stranger_auth, "Idempotency-Key": "stranger-care-denied"},
        json={},
    )
    assert stranger_response.status_code == 404


def test_activity_contains_interactions_visible_to_pet_member(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    pet_id = _create_pet(client, account_auth, key="create-activity-pet")["pet_id"]
    for action, key in (("feed", "activity-feed"), ("play", "activity-play")):
        response = client.post(
            f"/api/v1/pets/{pet_id}/interactions/{action}",
            headers={**account_auth, "Idempotency-Key": key},
            json={},
        )
        assert response.status_code == 200, response.text

    activity = client.get(f"/api/v1/pets/{pet_id}/activity", headers=account_auth)
    assert activity.status_code == 200, activity.text
    assert [item["action"] for item in activity.json()["items"]] == ["play", "feed"]
