from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import register_account


def test_unrelated_account_cannot_process_someone_elses_friend_request(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    sender_auth = register_account(client, "pending_security_sender")
    stranger_auth = register_account(client, "pending_security_stranger")
    created = client.post(
        "/api/v1/friend-requests",
        headers=sender_auth,
        json={"username": "owner_1"},
    )
    assert created.status_code == 201, created.text

    denied = client.post(
        f"/api/v1/pending-items/friend_request/{created.json()['request_id']}/accept",
        headers={**stranger_auth, "Idempotency-Key": "pending-stranger-denied"},
        json={},
    )

    assert denied.status_code == 403
    queue = client.get("/api/v1/pending-items", headers=account_auth)
    assert queue.status_code == 200
    assert queue.json()["count"] == 1


def test_pending_item_rejects_action_that_does_not_match_kind(
    client: TestClient,
    account_auth: dict[str, str],
) -> None:
    sender_auth = register_account(client, "pending_invalid_action_sender")
    created = client.post(
        "/api/v1/friend-requests",
        headers=sender_auth,
        json={"username": "owner_1"},
    )
    assert created.status_code == 201, created.text

    response = client.post(
        f"/api/v1/pending-items/friend_request/{created.json()['request_id']}/complete",
        headers={**account_auth, "Idempotency-Key": "pending-action-not-allowed"},
        json={},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "当前待处理事项不支持该操作"
