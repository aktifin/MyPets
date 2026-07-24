from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.domain import ReminderOccurrence, ReminderOccurrenceState
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.myreminder_sync import MyReminderSyncController
from onepic_desktop_pet.reminder_cache import ReminderCache
from onepic_desktop_pet.reminder_manager import ReminderManagerDialog


class FakeSession:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected


class FakeTransport(QObject):
    operation_succeeded = Signal(object)
    operation_failed = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def sync(self) -> None:
        self.calls += 1


def _occurrence(
    occurrence_id: str,
    state: ReminderOccurrenceState,
    scheduled_at: datetime,
) -> ReminderOccurrence:
    return ReminderOccurrence(
        occurrence_id=occurrence_id,
        source="myreminder",
        source_reminder_id=f"rule:{occurrence_id}",
        account_id="account-1",
        title=f"提醒 {occurrence_id}",
        content="处理这一项",
        scheduled_at=scheduled_at,
        timezone="Asia/Tokyo",
        state=state,
        priority="normal",
        category="general",
        version=1,
    )


def test_reminder_manager_filters_rows_and_emits_selected_actions(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    store = LocalStateStore(tmp_path / "state.sqlite3")
    cache = ReminderCache(store)
    now = datetime.now(UTC)
    cache.put(_occurrence("pending", ReminderOccurrenceState.PENDING, now + timedelta(hours=1)))
    cache.put(_occurrence("delivered", ReminderOccurrenceState.DELIVERED, now))
    cache.put(_occurrence("completed", ReminderOccurrenceState.COMPLETED, now - timedelta(hours=1)))

    dialog = ReminderManagerDialog(cache)
    completed: list[str] = []
    synced: list[bool] = []
    dialog.complete_requested.connect(completed.append)
    dialog.sync_requested.connect(lambda: synced.append(True))
    dialog.set_account("account-1", "测试用户")

    assert dialog.table.rowCount() == 2
    dialog.filter_combo.setCurrentIndex(1)
    assert dialog.table.rowCount() == 1
    assert dialog.selected_occurrence_id() == "completed"
    assert dialog.complete_button.isEnabled() is False

    dialog.filter_combo.setCurrentIndex(2)
    assert dialog.table.rowCount() == 3
    pending_row = next(
        row
        for row in range(dialog.table.rowCount())
        if dialog.table.item(row, 0).data(256) == "pending"
    )
    dialog.table.selectRow(pending_row)
    assert dialog.complete_button.isEnabled() is True
    dialog.complete_button.click()
    dialog.sync_button.click()
    assert completed == ["pending"]
    assert synced == [True]

    dialog.close()
    store.close()
    assert app is not None


def test_myreminder_sync_controller_validates_connection_and_response() -> None:
    transport = FakeTransport()
    session = FakeSession(connected=True)
    controller = MyReminderSyncController(session, object(), transport=transport)
    started: list[bool] = []
    succeeded: list[dict] = []
    failed: list[str] = []
    controller.sync_started.connect(lambda: started.append(True))
    controller.sync_succeeded.connect(succeeded.append)
    controller.sync_failed.connect(failed.append)

    assert controller.sync() is True
    assert controller.busy is True
    assert transport.calls == 1
    assert started == [True]
    transport.operation_succeeded.emit(
        {
            "pulled": 3,
            "created": 2,
            "updated": 1,
            "unchanged": 0,
            "expired": 0,
        }
    )
    assert controller.busy is False
    assert succeeded[0]["created"] == 2

    session.connected = False
    assert controller.sync() is False
    assert "云端未连接" in failed[-1]

    session.connected = True
    assert controller.sync() is True
    transport.operation_succeeded.emit({"pulled": 1})
    assert "缺少统计字段" in failed[-1]
