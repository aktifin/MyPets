from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from onepic_desktop_pet.pending_items_dialog import PendingItemsDialog


@pytest.fixture(scope="module", autouse=True)
def _qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


def test_pending_items_dialog_renders_queue_and_emits_direct_action() -> None:
    dialog = PendingItemsDialog()
    emitted: list[tuple[str, str, str, int]] = []
    dialog.action_requested.connect(
        lambda kind, item_id, action, minutes: emitted.append(
            (kind, item_id, action, minutes)
        )
    )
    dialog.set_items(
        [
            {
                "item_id": "friend-1",
                "kind": "friend_request",
                "title": "新朋友想添加你为好友",
                "detail": "接受后可以互动。",
                "occurred_at": "2026-07-27T08:00:00+08:00",
                "priority": "normal",
                "actions": ["accept", "reject"],
            },
            {
                "item_id": "reminder-1",
                "kind": "reminder_due",
                "title": "给团团准备晚餐",
                "detail": "晚餐已经到时间。",
                "occurred_at": "2026-07-27T08:00:00+08:00",
                "due_at": "2026-07-27T07:55:00+08:00",
                "priority": "urgent",
                "actions": ["complete", "snooze", "dismiss"],
            },
        ],
        total_count=2,
        urgent_count=1,
    )

    assert dialog.summary_label.text() == "共 2 项，其中 1 项优先处理"
    buttons = dialog.findChildren(QPushButton)
    accept = next(button for button in buttons if button.text() == "接受")
    snooze = next(button for button in buttons if button.text() == "10 分钟后提醒")
    accept.click()
    snooze.click()

    assert emitted == [
        ("friend_request", "friend-1", "accept", 10),
        ("reminder_due", "reminder-1", "snooze", 10),
    ]
    dialog.close()


def test_pending_items_dialog_has_clear_empty_state() -> None:
    dialog = PendingItemsDialog()
    dialog.set_items([], total_count=0)

    assert dialog.summary_label.text() == "共 0 项"
    assert any(
        "当前没有需要处理的事项" in label.text()
        for label in dialog.findChildren(QLabel)
    )
    dialog.close()
