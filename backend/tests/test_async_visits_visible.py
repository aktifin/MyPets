from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi.testclient import TestClient

from mypets_backend.visit_models import PetVisit


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": username.replace("_", " ").title(),
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_pet(client: TestClient, auth: dict[str, str], name: str) -> dict:
    key = sha256(name.encode("utf-8")).hexdigest()[:20]
    response = client.post(
        "/api/v1/pets",
        headers={**auth, "Idempotency-Key": f"visit-visible-pet-{key}"},
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


def _friend(
    client: TestClient,
    sender: dict[str, str],
    recipient: dict[str, str],
    recipient_username: str,
) -> None:
    request = client.post(
        "/api/v1/friend-requests",
        headers=sender,
        json={"username": recipient_username},
    )
    assert request.status_code == 201, request.text
    accepted = client.post(
        f"/api/v1/friend-requests/{request.json()['request_id']}/accept",
        headers=recipient,
    )
    assert accepted.status_code == 200, accepted.text


def _share_pet(client: TestClient, owner: dict[str, str], pet_id: str) -> None:
    response = client.patch(
        f"/api/v1/pets/{pet_id}/privacy",
        headers=owner,
        json={"visibility": "friends", "allow_remote_care": False},
    )
    assert response.status_code == 200, response.text


def _request_visit(
    client: TestClient,
    requester: dict[str, str],
    *,
    host_username: str,
    visitor_pet_id: str,
    host_pet_id: str,
    duration_minutes: int = 60,
) -> dict:
    response = client.post(
        "/api/v1/visits",
        headers=requester,
        json={
            "host_username": host_username,
            "visitor_pet_id": visitor_pet_id,
            "host_pet_id": host_pet_id,
            "duration_minutes": duration_minutes,
            "note": "一起玩一会儿",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_visit_friend_visibility_accept_recall_and_care_block(client: TestClient) -> None:
    alice = _register(client, "visit_visible_alice")
    bob = _register(client, "visit_visible_bob")
    visitor = _create_pet(client, alice, "可见小访客")
    host_pet = _create_pet(client, bob, "可见小主人")

    no_friend = client.post(
        "/api/v1/visits",
        headers=alice,
        json={
            "host_username": "visit_visible_bob",
            "visitor_pet_id": visitor["pet_id"],
            "host_pet_id": host_pet["pet_id"],
            "duration_minutes": 60,
        },
    )
    assert no_friend.status_code == 409

    _friend(client, alice, bob, "visit_visible_bob")
    private_pet = client.post(
        "/api/v1/visits",
        headers=alice,
        json={
            "host_username": "visit_visible_bob",
            "visitor_pet_id": visitor["pet_id"],
            "host_pet_id": host_pet["pet_id"],
            "duration_minutes": 60,
        },
    )
    assert private_pet.status_code == 404
    assert "不可见" in private_pet.json()["detail"]

    _share_pet(client, bob, host_pet["pet_id"])
    request = _request_visit(
        client,
        alice,
        host_username="visit_visible_bob",
        visitor_pet_id=visitor["pet_id"],
        host_pet_id=host_pet["pet_id"],
    )
    visit_id = request["visit_id"]
    assert client.post(f"/api/v1/visits/{visit_id}/accept", headers=alice).status_code == 403
    accepted = client.post(f"/api/v1/visits/{visit_id}/accept", headers=bob)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "active"
    assert client.get("/api/v1/pets", headers=alice).json()[0]["presence"] == "visiting"

    care = client.post(
        f"/api/v1/pets/{visitor['pet_id']}/interactions/play",
        headers={**alice, "Idempotency-Key": "visible-visit-care-blocked"},
        json={},
    )
    assert care.status_code == 409

    recalled = client.post(f"/api/v1/visits/{visit_id}/recall", headers=alice)
    assert recalled.status_code == 200, recalled.text
    assert recalled.json()["completion_reason"] == "visit_recalled"
    assert client.get("/api/v1/pets", headers=alice).json()[0]["presence"] == "home"


def test_visit_auto_return_and_block_recall(client: TestClient) -> None:
    owner = _register(client, "visit_visible_owner")
    host = _register(client, "visit_visible_host")
    visitor = _create_pet(client, owner, "自动返家的访客")
    host_pet = _create_pet(client, host, "负责接待的伙伴")
    _friend(client, owner, host, "visit_visible_host")
    _share_pet(client, host, host_pet["pet_id"])

    request = _request_visit(
        client,
        owner,
        host_username="visit_visible_host",
        visitor_pet_id=visitor["pet_id"],
        host_pet_id=host_pet["pet_id"],
        duration_minutes=15,
    )
    assert client.post(
        f"/api/v1/visits/{request['visit_id']}/accept", headers=host
    ).status_code == 200
    with client.app.state.session_factory() as session:
        value = session.get(PetVisit, request["visit_id"])
        assert value is not None
        value.scheduled_end_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert client.get("/api/v1/pets", headers=owner).json()[0]["presence"] == "home"
    history = client.get("/api/v1/visits", headers=owner).json()["history"]
    assert history[0]["completion_reason"] == "visit_auto_returned"

    second = _request_visit(
        client,
        owner,
        host_username="visit_visible_host",
        visitor_pet_id=visitor["pet_id"],
        host_pet_id=host_pet["pet_id"],
    )
    assert client.post(f"/api/v1/visits/{second['visit_id']}/accept", headers=host).status_code == 200
    blocked = client.post(
        "/api/v1/blocks",
        headers=host,
        json={"username": "visit_visible_owner"},
    )
    assert blocked.status_code == 201, blocked.text
    assert client.get("/api/v1/pets", headers=owner).json()[0]["presence"] == "home"
    history = client.get("/api/v1/visits", headers=owner).json()["history"]
    blocked_visit = next(item for item in history if item["visit_id"] == second["visit_id"])
    assert blocked_visit["status"] == "recalled"
    assert blocked_visit["completion_reason"] == "account_blocked"
