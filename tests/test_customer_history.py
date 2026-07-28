from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.customer_history_client import CustomerHistoryClient
from onepic_desktop_pet.customer_history_dialog import CustomerHistoryDialog


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
        self.requests: list[tuple[str, str, str, object]] = []

    def request(self, operation, method, path, *, body=None, query=None) -> None:
        self.requests.append((operation, method, path, query))


def _history_item() -> dict[str, object]:
    return {
        "history_id": "visit:visit-1:returned",
        "kind": "visit",
        "action": "returned",
        "direction": "outgoing",
        "title": "小白 · 按时返家",
        "detail": "串门时间结束，来访宠物已自动返家。",
        "occurred_at": "2026-07-28T09:30:00+00:00",
        "actor_display_name": None,
        "pet_id": "pet-1",
        "pet_name": "小白",
        "counterparty_account_id": "account-friend",
        "counterparty_display_name": "好友",
        "target_kind": "visit",
        "target_id": "visit-1",
        "target_label": "查看 小白 → 团子 的串门时间线",
    }


def test_customer_history_client_uses_filter_query_and_all_time_start() -> None:
    session = FakeSession()
    transport = FakeTransport()
    client = CustomerHistoryClient(session, object(), transport=transport)
    received: list[object] = []
    failures: list[str] = []
    client.history_received.connect(received.append)
    client.request_failed.connect(failures.append)

    assert client.refresh(kind="reminder", days=30, limit=120) is True
    assert transport.requests == [
        (
            "customer_history",
            "GET",
            "/api/v1/customer-history",
            {"kind": "reminder", "limit": 120, "days": 30},
        )
    ]
    transport.operation_succeeded.emit(
        "customer_history",
        {"count": 1, "items": [_history_item()]},
    )
    assert received == [{"count": 1, "items": [_history_item()]}]

    assert client.refresh(kind="all", days=0) is True
    assert transport.requests[-1][3] == {
        "kind": "all",
        "limit": 200,
        "start": "1970-01-01T00:00:00+00:00",
    }
    transport.operation_failed.emit("customer_history", 503, "服务暂不可用")
    assert failures == ["服务暂不可用"]


def test_customer_history_dialog_filters_and_reopens_selected_detail() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = CustomerHistoryDialog()
    refreshes: list[tuple[str, int]] = []
    details: list[object] = []
    dialog.refresh_requested.connect(lambda kind, days: refreshes.append((kind, days)))
    dialog.detail_requested.connect(details.append)
    dialog.show()
    app.processEvents()

    reminder_index = dialog.kind_combo.findData("reminder")
    all_time_index = dialog.days_combo.findData(0)
    dialog.kind_combo.setCurrentIndex(reminder_index)
    dialog.days_combo.setCurrentIndex(all_time_index)
    dialog.refresh_button.click()
    assert refreshes == [("reminder", 0)]

    item = _history_item()
    dialog.set_items([item], total_count=1)
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 0).text() == "串门"
    assert dialog.table.item(0, 1).text() == "已返家"
    assert "小白" in dialog.table.item(0, 2).text()
    dialog.table.selectRow(0)
    app.processEvents()
    assert dialog.open_button.isEnabled() is True
    dialog.open_button.click()
    assert details == [item]

    dialog.close()
    app.processEvents()
