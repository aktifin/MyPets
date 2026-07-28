from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.message_cache import MessageCache
from onepic_desktop_pet.message_efficiency_client import MessageEfficiencyClient
from onepic_desktop_pet.message_efficiency_drawer import MessageEfficiencyDrawer
from onepic_desktop_pet.messaging import ConversationRecord, MessageRecord


class FakeSession(QObject):
    state_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.connected = True


class FakeTransport(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict[str, object]] = []

    def request(self, operation, method, path, *, body=None, query=None) -> None:
        self.requests.append(
            {
                "operation": operation,
                "method": method,
                "path": path,
                "body": body,
                "query": query,
            }
        )


def _conversation() -> ConversationRecord:
    account_id = "account-local"
    message = MessageRecord(
        account_id=account_id,
        message_id="message-3",
        sequence_number=3,
        conversation_id="conversation-1",
        sender_account_id="account-peer",
        sender_display_name="好友",
        sender_pet_id="pet-friend",
        message_type="text",
        content="第三条消息",
        created_at=datetime(2026, 7, 28, 8, 3, tzinfo=UTC),
    )
    return ConversationRecord(
        account_id=account_id,
        conversation_id="conversation-1",
        kind="direct",
        category="visit",
        category_label="串门留言",
        title="好友与团子",
        peer_account_id="account-peer",
        peer_username="peer",
        peer_display_name="好友",
        last_message=message,
        unread_count=3,
        updated_at=message.created_at,
    )


def _cache(tmp_path: Path) -> tuple[LocalStateStore, MessageCache]:
    store = LocalStateStore(tmp_path / "message-efficiency.sqlite3")
    cache = MessageCache(store)
    conversation = _conversation()
    cache.upsert_conversation(conversation)
    for sequence in range(1, 4):
        cache.upsert_message(
            MessageRecord(
                account_id="account-local",
                message_id=f"message-{sequence}",
                sequence_number=sequence,
                conversation_id="conversation-1",
                sender_account_id="account-peer",
                sender_display_name="好友",
                sender_pet_id="pet-friend" if sequence == 2 else None,
                message_type="text",
                content=f"第{sequence}条消息",
                created_at=datetime(2026, 7, 28, 8, sequence, tzinfo=UTC),
            )
        )
    return store, cache


def test_drawer_search_unread_navigation_and_explicit_quick_reply(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    store, cache = _cache(tmp_path)
    drawer = MessageEfficiencyDrawer(cache)
    sends: list[tuple[str, str]] = []
    windows: list[tuple[str, int]] = []
    unread_requests: list[tuple[str, int]] = []
    reads: list[str] = []
    searches: list[str] = []
    drawer.send_requested.connect(lambda conversation_id, text: sends.append((conversation_id, text)))
    drawer.window_requested.connect(lambda conversation_id, sequence: windows.append((conversation_id, sequence)))
    drawer.unread_requested.connect(
        lambda conversation_id, sequence: unread_requests.append((conversation_id, sequence))
    )
    drawer.read_requested.connect(reads.append)
    drawer.search_requested.connect(searches.append)
    drawer.set_account("account-local", "本机用户")
    drawer.show()
    app.processEvents()

    drawer.set_quick_reply_preferences(
        {
            "categories": {
                "visit": ["先看看", "可以来玩", "稍后回复", "已收到"],
            },
            "defaults": {},
        }
    )
    visible = [button for button in drawer._quick_buttons if button.isVisible()]
    assert [button.text() for button in visible] == ["先看看", "可以来玩", "稍后回复", "已收到"]
    visible[0].click()
    assert drawer.message_input.text() == "先看看"
    assert sends == []
    drawer.send_button.click()
    assert sends == [("conversation-1", "先看看")]

    # Selecting a conversation requests a centered window and unread data, but
    # never emits a read mutation by itself.
    assert windows
    assert unread_requests
    assert reads == []

    drawer.set_unread_navigation(
        "conversation-1",
        {
            "unread_count": 3,
            "first": {"message_id": "message-1", "sequence_number": 1},
            "previous": None,
            "current": {"message_id": "message-1", "sequence_number": 1},
            "next": {"message_id": "message-2", "sequence_number": 2},
        },
    )
    assert drawer.unread_status.text().startswith("3 条未读")
    drawer.next_unread_button.click()
    assert windows[-1] == ("conversation-1", 2)
    assert unread_requests[-1] == ("conversation-1", 2)
    drawer.read_through_button.click()
    assert reads == ["message-1"]

    drawer.search_input.setText("团子")
    drawer._submit_search()
    assert searches == ["团子"]
    drawer.set_search_results(
        "团子",
        {
            "count": 1,
            "items": [
                {
                    "conversation": {
                        "conversation_id": "conversation-1",
                    },
                    "matched_message": {
                        "message_id": "message-2",
                        "sequence_number": 2,
                    },
                    "snippet": "团子周末一起玩",
                }
            ],
        },
    )
    assert drawer.conversation_list.count() == 1
    assert "团子周末一起玩" in drawer.conversation_list.item(0).text()

    drawer.close()
    store.close()


def test_message_efficiency_client_builds_account_scoped_requests() -> None:
    session = FakeSession()
    transport = FakeTransport()
    client = MessageEfficiencyClient(session, object(), transport=transport)
    searches: list[tuple[str, object]] = []
    windows: list[tuple[str, object]] = []
    unread: list[tuple[str, object]] = []
    quick: list[object] = []
    client.search_received.connect(lambda query, payload: searches.append((query, payload)))
    client.window_received.connect(lambda conversation_id, payload: windows.append((conversation_id, payload)))
    client.unread_received.connect(lambda conversation_id, payload: unread.append((conversation_id, payload)))
    client.quick_replies_received.connect(quick.append)

    assert client.search(" 奶糖猫 ") is True
    assert client.load_window("conversation-1", center_sequence=42) is True
    assert client.load_unread("conversation-1", current_sequence=42) is True
    assert client.load_quick_replies() is True
    assert client.update_quick_replies("direct", ["收到", "稍后回复"]) is True
    assert client.reset_quick_replies("all") is True

    assert transport.requests[0]["path"] == "/api/v1/message-search"
    assert transport.requests[0]["query"] == {"query": "奶糖猫", "limit": 100}
    assert transport.requests[1]["query"]["center_sequence"] == 42
    assert transport.requests[2]["query"] == {"current_sequence": 42}
    assert transport.requests[4]["body"] == {
        "categories": {"direct": ["收到", "稍后回复"]}
    }
    assert transport.requests[5]["body"] == {"category": "all"}

    transport.operation_succeeded.emit("message_search:奶糖猫", {"items": []})
    transport.operation_succeeded.emit("message_window:conversation-1", {"items": []})
    transport.operation_succeeded.emit("message_unread:conversation-1", {"unread_count": 0})
    transport.operation_succeeded.emit("message_quick_replies", {"categories": {}})
    assert searches == [("奶糖猫", {"items": []})]
    assert windows == [("conversation-1", {"items": []})]
    assert unread == [("conversation-1", {"unread_count": 0})]
    assert quick == [{"categories": {}}]
