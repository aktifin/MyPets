from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from mypets_backend.models import Pet


def _register(client: TestClient, username: str, display_name: str) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": display_name,
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return {"Authorization": f"Bearer {payload['access_token']}"}, payload["account"]["id"]


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
    sender_auth: dict[str, str],
    recipient_auth: dict[str, str],
    recipient_username: str,
) -> None:
    requested = client.post(
        "/api/v1/friend-requests",
        headers=sender_auth,
        json={"username": recipient_username},
    )
    assert requested.status_code == 201, requested.text
    accepted = client.post(
        f"/api/v1/friend-requests/{requested.json()['request_id']}/accept",
        headers=recipient_auth,
    )
    assert accepted.status_code == 200, accepted.text


def _category(conversations: list[dict], value: str) -> dict:
    return next(item for item in conversations if item["category"] == value)


def test_pet_authored_text_is_friend_pet_category(client: TestClient) -> None:
    alice_auth, _ = _register(client, "category_alice", "小爱")
    bob_auth, _ = _register(client, "category_bob", "小波")
    pet = _create_pet(client, alice_auth, "小白")
    conversation = client.post(
        "/api/v1/conversations",
        headers={**alice_auth, "Idempotency-Key": "category-conversation-001"},
        json={"recipient_username": "category_bob"},
    )
    assert conversation.status_code == 201, conversation.text
    sent = client.post(
        f"/api/v1/conversations/{conversation.json()['conversation_id']}/messages",
        headers={**alice_auth, "Idempotency-Key": "category-message-001"},
        json={"content": "小白向你问好。", "sender_pet_id": pet["pet_id"]},
    )
    assert sent.status_code == 201, sent.text

    listed = client.get("/api/v1/conversations", headers=bob_auth)
    assert listed.status_code == 200, listed.text
    record = _category(listed.json(), "friend_pet")
    assert record["category_label"] == "好友宠物"
    assert record["last_message"]["message_type"] == "text"
    assert record["last_message"]["sender_pet_id"] == pet["pet_id"]


def test_visit_and_shared_care_events_project_once(client: TestClient) -> None:
    visitor_auth, _ = _register(client, "category_visitor", "访客主人")
    host_auth, host_id = _register(client, "category_host", "接待主人")
    visitor_pet = _create_pet(client, visitor_auth, "来访小白")
    host_pet = _create_pet(client, host_auth, "接待小蓝")
    _make_friends(client, visitor_auth, host_auth, "category_host")
    privacy = client.patch(
        f"/api/v1/pets/{host_pet['pet_id']}/privacy",
        headers=host_auth,
        json={"visibility": "friends", "allow_remote_care": False},
    )
    assert privacy.status_code == 200, privacy.text

    visit = client.post(
        "/api/v1/visits",
        headers=visitor_auth,
        json={
            "host_username": "category_host",
            "visitor_pet_id": visitor_pet["pet_id"],
            "host_pet_id": host_pet["pet_id"],
            "duration_minutes": 60,
            "note": "带了小玩具来串门。",
        },
    )
    assert visit.status_code == 201, visit.text

    first = client.get("/api/v1/conversations", headers=host_auth)
    assert first.status_code == 200, first.text
    visit_conversation = _category(first.json(), "visit")
    conversation_id = visit_conversation["conversation_id"]
    history = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=host_auth,
    )
    assert history.status_code == 200, history.text
    assert [item["message_type"] for item in history.json()["items"]] == ["visit_message"]

    second = client.get("/api/v1/conversations", headers=host_auth)
    assert second.status_code == 200, second.text
    history_again = client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=host_auth,
    )
    assert len(history_again.json()["items"]) == 1

    caregiver_auth, caregiver_id = _register(client, "category_caregiver", "照料好友")
    _make_friends(client, host_auth, caregiver_auth, "category_caregiver")
    invitation = client.post(
        f"/api/v1/pets/{host_pet['pet_id']}/caregiver-invitations",
        headers=host_auth,
        json={"username": "category_caregiver", "role": "caregiver"},
    )
    assert invitation.status_code == 201, invitation.text
    assert invitation.json()["invited_account"]["account_id"] == caregiver_id
    assert invitation.json()["invited_by"]["account_id"] == host_id

    caregiver_conversations = client.get("/api/v1/conversations", headers=caregiver_auth)
    assert caregiver_conversations.status_code == 200, caregiver_conversations.text
    shared = _category(caregiver_conversations.json(), "shared_care")
    assert shared["category_label"] == "共同照料"
    assert shared["last_message"]["message_type"] == "care_event"


def test_growth_event_creates_readable_system_conversation(client: TestClient) -> None:
    auth, _ = _register(client, "category_growth", "成长主人")
    pet = _create_pet(client, auth, "成长小白")
    with client.app.state.session_factory() as session:
        stored = session.get(Pet, pet["pet_id"])
        assert stored is not None
        stored.growth_exp = 99
        stored.growth_level = 1
        session.commit()

    cared = client.post(
        f"/api/v1/pets/{pet['pet_id']}/interactions/feed",
        headers={**auth, "Idempotency-Key": "category-growth-feed-001"},
        json={},
    )
    assert cared.status_code == 200, cared.text
    assert cared.json()["interaction"]["growth_level_changed"] is True

    listed = client.get("/api/v1/conversations", headers=auth)
    assert listed.status_code == 200, listed.text
    growth = _category(listed.json(), "growth")
    assert growth["kind"] == "system"
    assert growth["unread_count"] == 1
    assert growth["peer"] is None
    message = growth["last_message"]
    assert message["message_type"] == "growth_notice"
    assert "成长等级提升" in message["content"]

    read = client.post(f"/api/v1/messages/{message['message_id']}/read", headers=auth)
    assert read.status_code == 200, read.text
    after = client.get("/api/v1/conversations", headers=auth)
    assert _category(after.json(), "growth")["unread_count"] == 0
