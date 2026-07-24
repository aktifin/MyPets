from __future__ import annotations

from fastapi.testclient import TestClient


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


def _bind(
    client: TestClient,
    auth: dict[str, str],
    public_id: str,
) -> dict[str, str]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=auth,
        json={"public_id": public_id, "name": public_id, "platform": "windows"},
    )
    assert bound.status_code == 201, bound.text
    payload = bound.json()
    exchanged = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": payload["device"]["id"],
            "device_secret": payload["device_secret"],
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    return {"Authorization": f"Bearer {exchanged.json()['access_token']}"}


def test_direct_message_idempotency_receipts_and_sync_events(client: TestClient) -> None:
    alice_auth = _register(client, "alice_message", "小爱")
    bob_auth = _register(client, "bob_message", "小波")
    charlie_auth = _register(client, "charlie_message", "小查")
    alice_device = _bind(client, alice_auth, "alice-message-device")
    bob_device = _bind(client, bob_auth, "bob-message-device")

    created = client.post(
        "/api/v1/conversations",
        headers={**alice_auth, "Idempotency-Key": "conversation-alice-bob-001"},
        json={"recipient_username": "bob_message"},
    )
    assert created.status_code == 201, created.text
    conversation = created.json()
    conversation_id = conversation["conversation_id"]
    assert conversation["peer"]["display_name"] == "小波"
    assert conversation["unread_count"] == 0

    retried = client.post(
        "/api/v1/conversations",
        headers={**alice_auth, "Idempotency-Key": "conversation-alice-bob-001"},
        json={"recipient_username": "bob_message"},
    )
    assert retried.status_code == 201
    assert retried.json()["conversation_id"] == conversation_id

    denied = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=charlie_auth,
    )
    assert denied.status_code == 404

    sent = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**alice_device, "Idempotency-Key": "message-alice-bob-001"},
        json={"content": "晚上一起照顾宠物吗？"},
    )
    assert sent.status_code == 201, sent.text
    message = sent.json()["message"]
    assert message["content"] == "晚上一起照顾宠物吗？"
    assert sent.json()["receipt"]["state"] == "read"

    duplicate = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**alice_device, "Idempotency-Key": "message-alice-bob-001"},
        json={"content": "这次重试不应产生第二条消息"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["message"]["message_id"] == message["message_id"]

    bob_conversations = client.get("/api/v1/conversations", headers=bob_auth)
    assert bob_conversations.status_code == 200
    assert bob_conversations.json()[0]["unread_count"] == 1
    assert bob_conversations.json()[0]["last_message"]["message_id"] == message["message_id"]

    history = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=bob_auth,
    )
    assert history.status_code == 200
    assert len(history.json()["items"]) == 1

    bob_events = client.get(
        "/api/v1/sync/events?after_sequence=0&limit=200",
        headers=bob_device,
    )
    assert bob_events.status_code == 200
    bob_event_types = [item["event_type"] for item in bob_events.json()["events"]]
    assert "conversation_updated" in bob_event_types
    assert "message_received" in bob_event_types

    read = client.post(
        f"/api/v1/messages/{message['message_id']}/read",
        headers=bob_device,
    )
    assert read.status_code == 200, read.text
    assert read.json()["receipt"]["state"] == "read"
    assert read.json()["conversation"]["unread_count"] == 0

    bob_after = client.get("/api/v1/conversations", headers=bob_auth)
    assert bob_after.json()[0]["unread_count"] == 0

    alice_events = client.get(
        "/api/v1/sync/events?after_sequence=0&limit=200",
        headers=alice_device,
    )
    assert alice_events.status_code == 200
    alice_event_types = [item["event_type"] for item in alice_events.json()["events"]]
    assert "message_received" in alice_event_types
    assert "message_read" in alice_event_types


def test_conversation_creation_rejects_self_and_unknown_account(client: TestClient) -> None:
    auth = _register(client, "solo_message", "单人")
    self_chat = client.post(
        "/api/v1/conversations",
        headers={**auth, "Idempotency-Key": "conversation-self-001"},
        json={"recipient_username": "solo_message"},
    )
    assert self_chat.status_code == 409

    missing = client.post(
        "/api/v1/conversations",
        headers={**auth, "Idempotency-Key": "conversation-missing-001"},
        json={"recipient_username": "not_a_real_account"},
    )
    assert missing.status_code == 404
