from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from mypets_backend.models import SyncEvent


def _register(client: TestClient, username: str, display_name: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": display_name,
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_pet(client: TestClient, auth: dict[str, str], name: str) -> dict:
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": f"pet-{uuid4()}"},
        json={
            "name": name,
            "template_id": "official.onepic.demo",
            "template_version": "1.0.0",
            "identity_version": "1.0.0",
            "asset_version": "1.0.0",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _make_friends(
    client: TestClient,
    requester_auth: dict[str, str],
    host_auth: dict[str, str],
    host_username: str,
) -> None:
    requested = client.post(
        "/api/v1/friend-requests",
        headers=requester_auth,
        json={"username": host_username},
    )
    assert requested.status_code == 201, requested.text
    request_id = requested.json()["request_id"]
    accepted = client.post(
        f"/api/v1/friend-requests/{request_id}/accept",
        headers=host_auth,
    )
    assert accepted.status_code == 200, accepted.text


def _active_visit(client: TestClient) -> tuple[dict[str, str], dict[str, str], dict]:
    requester_auth = _register(client, "visitor_owner", "访客主人")
    host_auth = _register(client, "desktop_host", "接待主人")
    visitor_pet = _create_pet(client, requester_auth, "来访小白")
    host_pet = _create_pet(client, host_auth, "接待小蓝")
    _make_friends(client, requester_auth, host_auth, "desktop_host")

    privacy = client.patch(
        f"/api/v1/pets/{host_pet['pet_id']}/privacy",
        headers=host_auth,
        json={"visibility": "friends", "allow_remote_care": False},
    )
    assert privacy.status_code == 200, privacy.text

    requested = client.post(
        "/api/v1/visits",
        headers=requester_auth,
        json={
            "host_username": "desktop_host",
            "visitor_pet_id": visitor_pet["pet_id"],
            "host_pet_id": host_pet["pet_id"],
            "duration_minutes": 60,
            "note": "一起玩一会儿",
        },
    )
    assert requested.status_code == 201, requested.text
    accepted = client.post(
        f"/api/v1/visits/{requested.json()['visit_id']}/accept",
        headers=host_auth,
    )
    assert accepted.status_code == 200, accepted.text
    return requester_auth, host_auth, accepted.json()


def test_visit_scene_exposes_asset_identity_and_host_only_controls(client: TestClient) -> None:
    requester_auth, host_auth, visit = _active_visit(client)
    visit_id = visit["visit_id"]

    host_scene = client.get(f"/api/v1/visits/{visit_id}/scene", headers=host_auth)
    assert host_scene.status_code == 200, host_scene.text
    scene = host_scene.json()
    assert scene["requester"]["display_name"] == "访客主人"
    assert scene["host"]["display_name"] == "接待主人"
    assert scene["visitor_pet"]["name"] == "来访小白"
    assert scene["visitor_pet"]["template_id"] == "official.onepic.demo"
    assert scene["visitor_pet"]["identity_version"] == "1.0.0"
    assert scene["visitor_pet"]["asset_version"] == "1.0.0"
    assert scene["can_send_home"] is True
    assert scene["can_interact"] is True

    requester_scene = client.get(
        f"/api/v1/visits/{visit_id}/scene",
        headers=requester_auth,
    )
    assert requester_scene.status_code == 200
    assert requester_scene.json()["can_send_home"] is False
    assert requester_scene.json()["can_interact"] is False


def test_dual_pet_interactions_are_idempotent_and_emit_account_events(
    client: TestClient,
) -> None:
    requester_auth, host_auth, visit = _active_visit(client)
    visit_id = visit["visit_id"]

    denied = client.post(
        f"/api/v1/visits/{visit_id}/interactions/greet",
        headers=requester_auth,
        json={"idempotency_key": "requester-cannot-trigger"},
    )
    assert denied.status_code == 403

    created_ids: list[str] = []
    for action in ("greet", "wave", "play", "sit_together"):
        key = f"desktop-{action}-stable-key"
        response = client.post(
            f"/api/v1/visits/{visit_id}/interactions/{action}",
            headers=host_auth,
            json={"idempotency_key": key},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["action"] == action
        assert payload["visit_id"] == visit_id
        created_ids.append(payload["interaction_id"])

        replay = client.post(
            f"/api/v1/visits/{visit_id}/interactions/{action}",
            headers=host_auth,
            json={"idempotency_key": key},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["interaction_id"] == payload["interaction_id"]

    assert len(set(created_ids)) == 4
    with client.app.state.session_factory() as session:
        events = list(
            session.scalars(
                select(SyncEvent).where(SyncEvent.event_type == "pet_visit_interaction")
            )
        )
    assert len(events) == 8
    assert len({(item.account_id, item.idempotency_key) for item in events}) == 8

    sent_home = client.post(
        f"/api/v1/visits/{visit_id}/send-home",
        headers=host_auth,
    )
    assert sent_home.status_code == 200, sent_home.text
    inactive = client.post(
        f"/api/v1/visits/{visit_id}/interactions/play",
        headers=host_auth,
        json={"idempotency_key": "inactive-visit-action"},
    )
    assert inactive.status_code == 409
