from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QPushButton

from onepic_desktop_pet.actionable_message_drawer import ActionableMessageDrawer
from onepic_desktop_pet.actionable_pending_items_dialog import ActionablePendingItemsDialog
from onepic_desktop_pet.actionable_visit_dialog import ActionableVisitDialog
from onepic_desktop_pet.customer_navigation_client import CustomerNavigationClient
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.message_cache import MessageCache
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
        self.requests: list[tuple[str, str, str]] = []

    def request(self, operation, method, path, *, body=None, query=None) -> None:
        self.requests.append((operation, method, path))


def _conversation(category: str, *, kind: str = "direct") -> ConversationRecord:
    account_id = "account-local"
    conversation_id = f"conversation-{category}"
    message = MessageRecord(
        account_id=account_id,
        message_id=f"message-{category}",
        sequence_number=1,
        conversation_id=conversation_id,
        sender_account_id="account-peer" if kind == "direct" else account_id,
        sender_display_name="好友" if kind == "direct" else "系统",
        sender_pet_id="pet-visitor" if category == "visit" else None,
        message_type="visit_message"
        if category == "visit"
        else ("growth_notice" if kind == "system" else "text"),
        content="周末一起玩" if category == "visit" else "消息内容",
        created_at=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
    )
    return ConversationRecord(
        account_id=account_id,
        conversation_id=conversation_id,
        kind=kind,
        category=category,
        category_label="串门留言" if category == "visit" else "成长通知",
        title="好友" if kind == "direct" else "成长通知",
        peer_account_id="account-peer" if kind == "direct" else None,
        peer_username="peer" if kind == "direct" else None,
        peer_display_name="好友" if kind == "direct" else None,
        last_message=message,
        unread_count=1,
        updated_at=message.created_at,
    )


def test_actionable_message_drawer_sends_quick_reply_and_requests_detail(
    tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    store = LocalStateStore(tmp_path / "messages.sqlite3")
    cache = MessageCache(store)
    cache.upsert_conversation(_conversation("visit"))
    cache.upsert_conversation(_conversation("growth", kind="system"))

    drawer = ActionableMessageDrawer(cache)
    sent: list[tuple[str, str]] = []
    related: list[str] = []
    drawer.send_requested.connect(
        lambda conversation_id, content: sent.append((conversation_id, content))
    )
    drawer.related_detail_requested.connect(related.append)
    drawer.set_account("account-local", "本机用户")
    drawer.show()
    app.processEvents()

    visit_index = drawer.category_combo.findData("visit")
    drawer.category_combo.setCurrentIndex(visit_index)
    app.processEvents()
    visible_replies = [button for button in drawer._quick_buttons if button.isVisible()]
    assert [button.text() for button in visible_replies] == [
        "收到，我来看看",
        "可以，稍后处理",
        "谢谢，宠物已经到家",
    ]
    visible_replies[0].click()
    assert sent == [("conversation-visit", "收到，我来看看")]
    drawer.related_button.click()
    assert related == ["conversation-visit"]

    growth_index = drawer.category_combo.findData("growth")
    drawer.category_combo.setCurrentIndex(growth_index)
    app.processEvents()
    assert not any(button.isVisible() for button in drawer._quick_buttons)
    assert drawer.send_button.isEnabled() is False
    drawer.close()
    store.close()


def test_actionable_visit_dialog_emits_selection_and_renders_timeline() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = ActionableVisitDialog()
    requested: list[str] = []
    dialog.timeline_requested.connect(requested.append)
    visit = {
        "visit_id": "visit-1",
        "requester": {"account_id": "owner-1", "display_name": "来访主人"},
        "host": {"account_id": "owner-2", "display_name": "接待主人"},
        "visitor_pet": {"pet_id": "pet-1", "name": "小白"},
        "host_pet": {"pet_id": "pet-2", "name": "团子"},
        "duration_minutes": 60,
        "note": "一起玩",
        "created_at": "2026-07-27T08:00:00+00:00",
        "can_accept": True,
    }
    dialog.apply_snapshot(
        {
            "friends": [],
            "friend_pets": [],
            "visits": {
                "incoming_requests": [visit],
                "outgoing_requests": [],
                "active": [],
                "history": [],
            },
        }
    )
    dialog.incoming_table.selectRow(0)
    assert dialog.focus_visit("visit-1") is True
    dialog._request_selected_timeline()
    assert requested == ["visit-1"]

    dialog.show_timeline(
        {
            "visit_id": "visit-1",
            "status": "active",
            "visitor_pet_name": "小白",
            "host_pet_name": "团子",
            "entries": [
                {
                    "kind": "requested",
                    "title": "已发送串门申请",
                    "detail": "小白申请拜访团子。",
                    "actor_display_name": "来访主人",
                    "occurred_at": "2026-07-27T08:00:00+00:00",
                },
                {
                    "kind": "arrived",
                    "title": "来访宠物已到达",
                    "detail": "串门正式开始。",
                    "actor_display_name": None,
                    "occurred_at": "2026-07-27T08:05:00+00:00",
                },
            ],
        }
    )
    assert dialog.timeline_table.rowCount() == 2
    assert dialog.timeline_table.item(1, 0).text() == "已到达"
    assert "小白 → 团子" in dialog.timeline_summary.text()
    dialog.close()
    app.processEvents()


def test_pending_dialog_exposes_original_item_for_detail_navigation() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = ActionablePendingItemsDialog()
    details: list[object] = []
    dialog.detail_requested.connect(details.append)
    item = {
        "item_id": "visit-1",
        "kind": "visit_request",
        "title": "小白想来串门",
        "detail": "等待你处理",
        "priority": "normal",
        "actions": ["accept", "reject"],
    }
    dialog.set_items([item], total_count=1)
    detail_button = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "查看详情"
    )
    detail_button.click()
    assert details == [item]
    dialog.close()
    app.processEvents()


def test_customer_navigation_client_uses_read_only_paths() -> None:
    session = FakeSession()
    transport = FakeTransport()
    client = CustomerNavigationClient(session, object(), transport=transport)
    timelines: list[object] = []
    targets: list[tuple[str, object]] = []
    client.timeline_received.connect(timelines.append)
    client.target_received.connect(
        lambda conversation_id, payload: targets.append((conversation_id, payload))
    )

    assert client.load_timeline("visit-1") is True
    assert client.load_conversation_target("conversation-1") is True
    assert transport.requests == [
        ("timeline:visit-1", "GET", "/api/v1/visits/visit-1/timeline"),
        (
            "target:conversation-1",
            "GET",
            "/api/v1/conversations/conversation-1/target",
        ),
    ]
    transport.operation_succeeded.emit("timeline:visit-1", {"visit_id": "visit-1"})
    transport.operation_succeeded.emit(
        "target:conversation-1",
        {"kind": "friend", "target_id": "account-peer"},
    )
    assert timelines == [{"visit_id": "visit-1"}]
    assert targets == [
        ("conversation-1", {"kind": "friend", "target_id": "account-peer"})
    ]
