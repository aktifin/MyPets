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
        headers={**auth, "Idempotency-Key": f"visit-pet-{key}"},
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


def test_visit_requires_friendship_and_supports_accept_recall(client: TestClient) -> None:
    alice = _register(client, "visit_alice")
    bob = _register(client, "visit_bob")
    visitor = _create_pet(client, alice, "小访客")
    host_pet = _create_pet(client, bob, "小主人")

    forbidden = client.post(
        "/api/v1/visits",
        headers=alice,
        json={
            "host_username": "visit_bob",
            "visitor_pet_id": visitor["pet_id"],
            "host_pet_id": host_pet["pet_id"],
            "duration_minutes": 60,
        },
    )
    assert forbidden.status_code == 409
    assert "好友" in forbidden.json()["detail"]

    _friend(client, alice, bob, "visit_bob")
    request = _request_visit(
        client,
        alice,
        host_username="visit_bob",
        visitor_pet_id=visitor["pet_id"],
        host_pet_id=host_pet["pet_id"],
    )
    visit_id = request["visit_id"]
    assert request["status"] == "pending"
    assert request["can_cancel"] is True

    wrong_accept = client.post(f"/api/v1/visits/{visit_id}/accept", headers=alice)
    assert wrong_accept.status_code == 403

    incoming = client.get("/api/v1/visits", headers=bob)
    assert incoming.status_code == 200
    assert incoming.json()["incoming_requests"][0]["visit_id"] == visit_id

    accepted = client.post(f"/api/v1/visits/{visit_id}/accept", headers=bob)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "active"
    assert accepted.json()["scheduled_end_at"] is not None

    alice_pets = client.get("/api/v1/pets", headers=alice)
    assert alice_pets.status_code == 200
    assert alice_pets.json()[0]["presence"] == "visiting"

    blocked_care = client.post(
        f"/api/v1/pets/{visitor['pet_id']}/interactions/play",
        headers={**alice, "Idempotency-Key": "visit-care-blocked-0001"},
        json={},
    )
    assert blocked_care.status_code == 409
    assert "外出" in blocked_care.json()["detail"]

    recalled = client.post(f"/api/v1/visits/{visit_id}/recall", headers=alice)
    assert recalled.status_code == 200, recalled.text
    assert recalled.json()["status"] == "recalled"
    assert recalled.json()["completion_reason"] == "visit_recalled"
    assert client.get("/api/v1/pets", headers=alice).json()[0]["presence"] == "home"


def test_visit_auto_return_settles_before_pet_snapshot_and_care(client: TestClient) -> None:
    owner = _register(client, "auto_owner")
    host = _register(client, "auto_host")
    visitor = _create_pet(client, owner, "自动返家")
    host_pet = _create_pet(client, host, "接待伙伴")
    _friend(client, owner, host, "auto_host")
    request = _request_visit(
        client,
        owner,
        host_username="auto_host",
        visitor_pet_id=visitor["pet_id"],
        host_pet_id=host_pet["pet_id"],
        duration_minutes=15,
    )
    accepted = client.post(
        f"/api/v1/visits/{request['visit_id']}/accept",
        headers=host,
    )
    assert accepted.status_code == 200

    with client.app.state.session_factory() as session:
        value = session.get(PetVisit, request["visit_id"])
        assert value is not None
        value.scheduled_end_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    snapshot = client.get("/api/v1/pets", headers=owner)
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()[0]["presence"] == "home"

    care = client.post(
        f"/api/v1/pets/{visitor['pet_id']}/interactions/pet",
        headers={**owner, "Idempotency-Key": "visit-care-after-return-01"},
        json={},
    )
    assert care.status_code == 200, care.text

    visits = client.get("/api/v1/visits", headers=owner)
    history = visits.json()["history"]
    assert history[0]["status"] == "completed"
    assert history[0]["completion_reason"] == "visit_auto_returned"


def test_reject_cancel_and_block_recall_active_visit(client: TestClient) -> None:
    left = _register(client, "visit_left")
    right = _register(client, "visit_right")
    left_pet = _create_pet(client, left, "左边宠物")
    right_pet = _create_pet(client, right, "右边宠物")
    _friend(client, left, right, "visit_right")

    rejected_request = _request_visit(
        client,
        left,
        host_username="visit_right",
        visitor_pet_id=left_pet["pet_id"],
        host_pet_id=right_pet["pet_id"],
    )
    rejected = client.post(
        f"/api/v1/visits/{rejected_request['visit_id']}/reject",
        headers=right,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    cancelled_request = _request_visit(
        client,
        left,
        host_username="visit_right",
        visitor_pet_id=left_pet["pet_id"],
        host_pet_id=right_pet["pet_id"],
    )
    cancelled = client.post(
        f"/api/v1/visits/{cancelled_request['visit_id']}/cancel",
        headers=left,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    active_request = _request_visit(
        client,
        left,
        host_username="visit_right",
        visitor_pet_id=left_pet["pet_id"],
        host_pet_id=right_pet["pet_id"],
    )
    accepted = client.post(
        f"/api/v1/visits/{active_request['visit_id']}/accept",
        headers=right,
    )
    assert accepted.status_code == 200
    assert client.get("/api/v1/pets", headers=left).json()[0]["presence"] == "visiting"

    blocked = client.post(
        "/api/v1/blocks",
        headers=right,
        json={"username": "visit_left"},
    )
    assert blocked.status_code == 201, blocked.text
    assert client.get("/api/v1/pets", headers=left).json()[0]["presence"] == "home"
    history = client.get("/api/v1/visits", headers=left).json()["history"]
    blocked_visit = next(item for item in history if item["visit_id"] == active_request["visit_id"])
    assert blocked_visit["status"] == "recalled"
    assert blocked_visit["completion_reason"] == "account_blocked"
