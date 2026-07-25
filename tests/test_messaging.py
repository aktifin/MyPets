from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.message_cache import MessageCache
from onepic_desktop_pet.message_drawer import MessageDrawer
from onepic_desktop_pet.messaging import ConversationRecord, MessageRecord
from onepic_desktop_pet.sync_apply import apply_events, stream_name


def _account(account_id: str, username: str, display_name: str) -> dict:
    return {
        "id": account_id,
        "username": username,
        "display_name": display_name,
        "created_at": "2026-07-24T10:00:00+00:00",
    }


def _message_payload(
    *,
    message_type: str = "text",
    sender_pet_id: str | None = None,
) -> dict:
    return {
        "message_id": "message-1",
        "sequence_number": 12,
        "conversation_id": "conversation-1",
        "sender_account_id": "account-sender",
        "sender_display_name": "小波",
        "sender_pet_id": sender_pet_id,
        "message_type": message_type,
        "content": "晚上一起照顾宠物吗？",
        "created_at": "2026-07-24T10:05:00+00:00",
    }


def _conversation_payload(
    unread_count: int,
    *,
    category: str = "direct",
    category_label: str = "普通私聊",
    kind: str = "direct",
    message_type: str = "text",
    sender_pet_id: str | None = None,
) -> dict:
    return {
        "conversation_id": "conversation-1",
        "kind": kind,
        "category": category,
        "category_label": category_label,
        "title": "小波" if kind == "direct" else category_label,
        "members": [
            _account("account-local", "local_user", "本机用户"),
            *(
                [_account("account-sender", "sender_user", "小波")]
                if kind == "direct"
                else []
            ),
        ],
        "peer": _account("account-sender", "sender_user", "小波") if kind == "direct" else None,
        "last_message": _message_payload(
            message_type=message_type,
            sender_pet_id=sender_pet_id,
        ),
        "unread_count": unread_count,
        "updated_at": "2026-07-24T10:05:00+00:00",
    }


def test_message_events_create_folded_notification_and_read_state(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.sqlite3")
    cache = MessageCache(store)
    incoming = {
        "events": [
            {
                "sequence_number": 1,
                "event_id": "sync-message-1",
                "event_type": "message_received",
                "idempotency_key": "message-event-1",
                "created_at": "2026-07-24T10:05:00+00:00",
                "target_account_id": "account-local",
                "target_device_id": None,
                "payload": {
                    "conversation": _conversation_payload(1),
                    "message": _message_payload(),
                    "receipt": {
                        "message_id": "message-1",
                        "account_id": "account-local",
                        "state": "delivered",
                        "delivered_at": "2026-07-24T10:05:00+00:00",
                        "read_at": None,
                    },
                },
            }
        ],
        "next_cursor": 1,
        "has_more": False,
    }
    result = apply_events(
        store,
        incoming,
        account_id="account-local",
        device_id="device-local",
    )
    assert result.events_applied == 1
    assert cache.unread_count("account-local") == 1
    conversation = cache.get_conversation("account-local", "conversation-1")
    assert conversation is not None
    assert conversation.category == "direct"
    assert conversation.category_label == "普通私聊"
    assert cache.list_messages("account-local", "conversation-1")[0].content.startswith(
        "晚上"
    )
    notifications = store.list_notifications("account-local", unread_only=True)
    assert len(notifications) == 1
    assert notifications[0].title == "小波"
    assert notifications[0].source_id == "conversation-1"

    read_event = {
        "events": [
            {
                "sequence_number": 2,
                "event_id": "sync-read-1",
                "event_type": "message_read",
                "idempotency_key": "read-event-1",
                "created_at": "2026-07-24T10:06:00+00:00",
                "target_account_id": "account-local",
                "target_device_id": None,
                "payload": {
                    "conversation": _conversation_payload(0),
                    "reader_account_id": "account-local",
                    "through_sequence": 12,
                    "receipt": {
                        "message_id": "message-1",
                        "account_id": "account-local",
                        "state": "read",
                        "delivered_at": "2026-07-24T10:05:00+00:00",
                        "read_at": "2026-07-24T10:06:00+00:00",
                    },
                },
            }
        ],
        "next_cursor": 2,
        "has_more": False,
    }
    apply_events(
        store,
        read_event,
        account_id="account-local",
        device_id="device-local",
    )
    assert cache.unread_count("account-local") == 0
    assert not store.list_notifications("account-local", unread_only=True)
    assert store.get_cursor(stream_name("account-local", "device-local")) == 2
    store.close()


def test_message_drawer_filters_categories_and_locks_system_conversations(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    store = LocalStateStore(tmp_path / "drawer.sqlite3")
    cache = MessageCache(store)
    direct_message = MessageRecord(
        account_id="account-local",
        message_id="message-1",
        sequence_number=12,
        conversation_id="conversation-1",
        sender_account_id="account-sender",
        sender_display_name="小波",
        sender_pet_id=None,
        message_type="text",
        content="晚上一起照顾宠物吗？",
        created_at=datetime(2026, 7, 24, 10, 5, tzinfo=UTC),
    )
    cache.upsert_conversation(
        ConversationRecord(
            account_id="account-local",
            conversation_id="conversation-1",
            kind="direct",
            category="direct",
            category_label="普通私聊",
            title="小波",
            peer_account_id="account-sender",
            peer_username="sender_user",
            peer_display_name="小波",
            last_message=direct_message,
            unread_count=1,
            updated_at=direct_message.created_at,
        )
    )
    growth_message = MessageRecord(
        account_id="account-local",
        message_id="message-growth",
        sequence_number=13,
        conversation_id="conversation-growth",
        sender_account_id="account-local",
        sender_display_name="本机用户",
        sender_pet_id="pet-1",
        message_type="growth_notice",
        content="小白：成长等级提升，2 → 3。",
        created_at=datetime(2026, 7, 24, 10, 6, tzinfo=UTC),
    )
    cache.upsert_conversation(
        ConversationRecord(
            account_id="account-local",
            conversation_id="conversation-growth",
            kind="system",
            category="growth",
            category_label="成长通知",
            title="成长通知",
            peer_account_id=None,
            peer_username=None,
            peer_display_name=None,
            last_message=growth_message,
            unread_count=1,
            updated_at=growth_message.created_at,
        )
    )

    drawer = MessageDrawer(cache)
    selected: list[str] = []
    reads: list[str] = []
    sends: list[tuple[str, str]] = []
    creates: list[str] = []
    drawer.conversation_selected.connect(selected.append)
    drawer.read_requested.connect(reads.append)
    drawer.send_requested.connect(lambda conversation_id, body: sends.append((conversation_id, body)))
    drawer.create_conversation_requested.connect(creates.append)
    drawer.set_account("account-local", "本机用户")
    app.processEvents()

    assert drawer.conversation_list.count() == 2
    assert any("🌱" in drawer.conversation_list.item(i).text() for i in range(2))

    growth_index = drawer.category_combo.findData("growth")
    drawer.category_combo.setCurrentIndex(growth_index)
    app.processEvents()
    assert drawer.conversation_list.count() == 1
    assert "成长通知" in drawer.conversation_title.text()
    assert drawer.send_button.isEnabled() is False
    assert drawer.message_input.isEnabled() is False
    assert reads[-1] == "message-growth"

    direct_index = drawer.category_combo.findData("direct")
    drawer.category_combo.setCurrentIndex(direct_index)
    app.processEvents()
    assert drawer.conversation_list.count() == 1
    assert drawer.send_button.isEnabled() is True
    drawer.message_input.setText("收到，我会准时上线。")
    drawer.send_button.click()
    assert sends == [("conversation-1", "收到，我会准时上线。")] 

    drawer.recipient_input.setText("another_user")
    drawer.create_button.click()
    assert creates == ["another_user"]

    drawer.close()
    store.close()
