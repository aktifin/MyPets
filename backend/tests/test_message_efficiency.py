from __future__ import annotations

from fastapi.testclient import TestClient

from .test_messaging import _bind, _register
from .test_user_portal import _create_pet


def _create_conversation(
    client: TestClient,
    auth: dict[str, str],
    recipient_username: str,
    key: str,
) -> dict:
    response = client.post(
        "/api/v1/conversations",
        headers={**auth, "Idempotency-Key": key},
        json={"recipient_username": recipient_username},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _send(
    client: TestClient,
    auth: dict[str, str],
    conversation_id: str,
    content: str,
    key: str,
    *,
    sender_pet_id: str | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={**auth, "Idempotency-Key": key},
        json={"content": content, "sender_pet_id": sender_pet_id},
    )
    assert response.status_code == 201, response.text
    return response.json()["message"]


def test_message_search_window_and_explicit_unread_navigation(client: TestClient) -> None:
    alice = _register(client, "alice_efficiency", "小爱")
    bob = _register(client, "bob_efficiency", "小波")
    outsider = _register(client, "outsider_efficiency", "旁观者")
    bob_device = _bind(client, bob, "bob-efficiency-device")
    pet = _create_pet(
        client,
        alice,
        name="奶糖猫",
        key="message-efficiency-pet-0001",
    )
    conversation = _create_conversation(
        client,
        alice,
        "bob_efficiency",
        "message-efficiency-conversation-0001",
    )
    conversation_id = conversation["conversation_id"]

    messages = [
        _send(
            client,
            alice,
            conversation_id,
            "第一条普通消息",
            "message-efficiency-send-0001",
        ),
        _send(
            client,
            alice,
            conversation_id,
            "奶糖猫想周末一起去串门",
            "message-efficiency-send-0002",
            sender_pet_id=pet["pet_id"],
        ),
        _send(
            client,
            alice,
            conversation_id,
            "第三条中间消息，包含独特关键词星光饼干",
            "message-efficiency-send-0003",
        ),
        _send(
            client,
            alice,
            conversation_id,
            "第四条普通消息",
            "message-efficiency-send-0004",
        ),
        _send(
            client,
            alice,
            conversation_id,
            "第五条最新消息",
            "message-efficiency-send-0005",
        ),
    ]

    by_content = client.get(
        "/api/v1/message-search",
        headers=bob,
        params={"query": "星光饼干", "limit": 20},
    )
    assert by_content.status_code == 200, by_content.text
    assert by_content.json()["count"] == 1
    content_result = by_content.json()["items"][0]
    assert content_result["conversation"]["conversation_id"] == conversation_id
    assert content_result["matched_message"]["message_id"] == messages[2]["message_id"]
    assert "content" in content_result["matched_fields"]

    by_pet = client.get(
        "/api/v1/message-search",
        headers=bob_device,
        params={"query": "奶糖猫"},
    )
    assert by_pet.status_code == 200, by_pet.text
    assert by_pet.json()["items"][0]["matched_pet_name"] == "奶糖猫"
    assert "pet" in by_pet.json()["items"][0]["matched_fields"]

    by_contact = client.get(
        "/api/v1/message-search",
        headers=alice,
        params={"query": "bob_efficiency"},
    )
    assert by_contact.status_code == 200
    assert "contact" in by_contact.json()["items"][0]["matched_fields"]

    isolated = client.get(
        "/api/v1/message-search",
        headers=outsider,
        params={"query": "星光饼干"},
    )
    assert isolated.status_code == 200
    assert isolated.json() == {"query": "星光饼干", "count": 0, "items": []}

    window = client.get(
        f"/api/v1/conversations/{conversation_id}/message-window",
        headers=bob,
        params={
            "center_sequence": messages[2]["sequence_number"],
            "before": 1,
            "after": 1,
        },
    )
    assert window.status_code == 200, window.text
    assert [item["message_id"] for item in window.json()["items"]] == [
        messages[1]["message_id"],
        messages[2]["message_id"],
        messages[3]["message_id"],
    ]
    assert window.json()["has_earlier"] is True
    assert window.json()["has_later"] is True

    unread = client.get(
        f"/api/v1/conversations/{conversation_id}/unread-navigation",
        headers=bob_device,
    )
    assert unread.status_code == 200, unread.text
    assert unread.json()["unread_count"] == 5
    assert unread.json()["first"]["message_id"] == messages[0]["message_id"]
    assert unread.json()["current"]["message_id"] == messages[0]["message_id"]
    assert unread.json()["previous"] is None
    assert unread.json()["next"]["message_id"] == messages[1]["message_id"]

    # Reading navigation itself never mutates the cursor.
    unchanged = client.get("/api/v1/conversations", headers=bob).json()[0]
    assert unchanged["unread_count"] == 5

    read_first = client.post(
        f"/api/v1/messages/{messages[0]['message_id']}/read",
        headers=bob_device,
    )
    assert read_first.status_code == 200
    advanced = client.get(
        f"/api/v1/conversations/{conversation_id}/unread-navigation",
        headers=bob,
    )
    assert advanced.status_code == 200
    assert advanced.json()["unread_count"] == 4
    assert advanced.json()["first"]["message_id"] == messages[1]["message_id"]


def test_account_scoped_quick_reply_preferences_and_reset(client: TestClient) -> None:
    owner = _register(client, "quick_reply_owner", "快捷回复用户")
    other = _register(client, "quick_reply_other", "其他用户")
    device = _bind(client, owner, "quick-reply-device")

    defaults = client.get("/api/v1/message-quick-replies", headers=owner)
    assert defaults.status_code == 200, defaults.text
    assert defaults.json()["categories"]["direct"] == [
        "收到",
        "好的，谢谢",
        "我稍后回复你",
    ]
    assert defaults.json()["updated_at"] is None

    updated = client.patch(
        "/api/v1/message-quick-replies",
        headers=owner,
        json={
            "categories": {
                "direct": ["稍等，我确认一下", "收到", "收到", "明天回复你"],
                "visit": ["可以来玩", "稍后看串门详情"],
            }
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["categories"]["direct"] == [
        "稍等，我确认一下",
        "收到",
        "明天回复你",
    ]
    assert updated.json()["categories"]["visit"] == ["可以来玩", "稍后看串门详情"]

    device_view = client.get("/api/v1/message-quick-replies", headers=device)
    assert device_view.status_code == 200
    assert device_view.json()["categories"] == updated.json()["categories"]

    other_view = client.get("/api/v1/message-quick-replies", headers=other)
    assert other_view.status_code == 200
    assert other_view.json()["categories"]["direct"] == [
        "收到",
        "好的，谢谢",
        "我稍后回复你",
    ]

    reset_direct = client.post(
        "/api/v1/message-quick-replies/reset",
        headers=device,
        json={"category": "direct"},
    )
    assert reset_direct.status_code == 200
    assert reset_direct.json()["categories"]["direct"] == reset_direct.json()["defaults"]["direct"]
    assert reset_direct.json()["categories"]["visit"] == ["可以来玩", "稍后看串门详情"]

    reset_all = client.post(
        "/api/v1/message-quick-replies/reset",
        headers=owner,
        json={"category": "all"},
    )
    assert reset_all.status_code == 200
    assert reset_all.json()["categories"] == reset_all.json()["defaults"]

    empty = client.patch(
        "/api/v1/message-quick-replies",
        headers=owner,
        json={"categories": {"direct": []}},
    )
    assert empty.status_code == 422
    too_many = client.patch(
        "/api/v1/message-quick-replies",
        headers=owner,
        json={"categories": {"direct": [str(index) for index in range(7)]}},
    )
    assert too_many.status_code == 422
    too_long = client.patch(
        "/api/v1/message-quick-replies",
        headers=owner,
        json={"categories": {"direct": ["很" * 81]}},
    )
    assert too_long.status_code == 422
