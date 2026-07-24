from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.cloud_types import CloudIdentity
from onepic_desktop_pet.domain import (
    NotificationKind,
    ReminderOccurrence,
    ReminderOccurrenceState,
)
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.reminder_cache import ReminderCache
from onepic_desktop_pet.reminder_card import ReminderCard
from onepic_desktop_pet.reminder_cloud import ReminderCloudController
from onepic_desktop_pet.reminder_scheduler import ReminderScheduler
from onepic_desktop_pet.reminders import parse_reminder_occurrence


class FakeTimeout:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class FakeTimer:
    def __init__(self) -> None:
        self.timeout = FakeTimeout()
        self.interval = 0
        self.active = False

    def setInterval(self, value: int) -> None:
        self.interval = value

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


class FakeApi(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []

    def _require_device_token(self) -> str:
        return "device-token"

    def _request(self, operation: str, method: str, path: str, **kwargs) -> None:
        self.calls.append((operation, method, path, kwargs))

    def _json_request(
        self,
        operation: str,
        method: str,
        path: str,
        payload: dict,
        **kwargs,
    ) -> None:
        self.calls.append((operation, method, path, payload, kwargs))


class FakeSession(QObject):
    state_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.connected = True
        self.identity = CloudIdentity("account-1", "device-1", "测试用户")
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


def _occurrence(
    occurrence_id: str,
    scheduled_at: datetime,
    *,
    state: ReminderOccurrenceState = ReminderOccurrenceState.PENDING,
    version: int = 1,
) -> ReminderOccurrence:
    return ReminderOccurrence(
        occurrence_id=occurrence_id,
        source="myreminder",
        source_reminder_id=f"source-{occurrence_id}",
        account_id="account-1",
        title=f"提醒 {occurrence_id}",
        content="处理这一项",
        scheduled_at=scheduled_at,
        timezone="Asia/Tokyo",
        state=state,
        priority="normal",
        category="general",
        version=version,
    )


def _payload(occurrence: ReminderOccurrence) -> dict:
    return {
        "occurrence_id": occurrence.occurrence_id,
        "account_id": occurrence.account_id,
        "source": occurrence.source,
        "source_reminder_id": occurrence.source_reminder_id,
        "title": occurrence.title,
        "content": occurrence.content,
        "scheduled_at": occurrence.scheduled_at.isoformat(),
        "timezone": occurrence.timezone,
        "state": occurrence.state.value,
        "priority": occurrence.priority,
        "category": occurrence.category,
        "version": occurrence.version,
        "snooze_count": 0,
        "last_delivered_at": None,
        "completed_at": None,
        "dismissed_at": None,
        "updated_at": occurrence.scheduled_at.isoformat(),
    }


def test_parse_reminder_rejects_cross_account_and_naive_time() -> None:
    now = datetime.now(UTC)
    value = _payload(_occurrence("one", now))
    parsed = parse_reminder_occurrence(value, account_id="account-1")
    assert parsed.occurrence_id == "one"

    try:
        parse_reminder_occurrence(value, account_id="account-2")
    except ValueError as exc:
        assert "不属于当前账户" in str(exc)
    else:
        raise AssertionError("cross-account reminder was accepted")

    value["scheduled_at"] = "2026-07-25T10:00:00"
    try:
        parse_reminder_occurrence(value)
    except ValueError as exc:
        assert "包含时区" in str(exc)
    else:
        raise AssertionError("naive reminder time was accepted")


def test_scheduler_merges_sleep_recovery_and_does_not_redeliver(tmp_path: Path) -> None:
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    store = LocalStateStore(tmp_path / "state.sqlite3")
    cache = ReminderCache(store)
    cache.put(_occurrence("one", now - timedelta(minutes=20)))
    cache.put(_occurrence("two", now - timedelta(minutes=5)))

    timer = FakeTimer()
    scheduler = ReminderScheduler(cache, timer=timer, clock=lambda: now)
    batches: list[list[ReminderOccurrence]] = []
    deliveries: list[str] = []
    scheduler.reminders_due.connect(batches.append)
    scheduler.delivery_requested.connect(deliveries.append)

    scheduler.start("account-1")
    assert timer.active
    assert len(batches) == 1
    assert [item.occurrence_id for item in batches[0]] == ["one", "two"]
    assert deliveries == ["one", "two"]
    assert cache.get("one").state is ReminderOccurrenceState.DELIVERED
    assert cache.get("two").state is ReminderOccurrenceState.DELIVERED
    assert store.unread_counts("account-1")[NotificationKind.REMINDER] == 2

    assert scheduler.scan(now) == []
    assert deliveries == ["one", "two"]
    store.close()


def test_pending_command_protects_local_state_from_stale_snapshot(tmp_path: Path) -> None:
    now = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    store = LocalStateStore(tmp_path / "state.sqlite3")
    cache = ReminderCache(store)
    cache.put(_occurrence("one", now))
    cache.mark_delivered("one")
    command = cache.enqueue(
        account_id="account-1",
        occurrence_id="one",
        action="delivered",
        idempotency_key="stable-delivery-key",
    )

    accepted = cache.put(_occurrence("one", now, state=ReminderOccurrenceState.PENDING))
    assert accepted is False
    assert cache.get("one").state is ReminderOccurrenceState.DELIVERED

    accepted = cache.put(
        _occurrence("one", now, state=ReminderOccurrenceState.DELIVERED),
        authoritative=True,
    )
    assert accepted is True
    cache.acknowledge(command.command_id)
    assert cache.pending_commands("account-1") == []
    store.close()


def test_cloud_controller_queues_and_confirms_offline_capable_actions(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = LocalStateStore(tmp_path / "state.sqlite3")
    cache = ReminderCache(store)
    cache.put(_occurrence("one", now, state=ReminderOccurrenceState.DELIVERED))
    api = FakeApi()
    session = FakeSession()
    controller = ReminderCloudController(api, session, cache)

    assert controller.complete("one") is True
    assert cache.get("one").state is ReminderOccurrenceState.COMPLETED
    assert len(cache.pending_commands("account-1")) == 1
    operation = api.calls[-1][0]
    assert operation.startswith("reminder_command:")

    confirmed = _occurrence(
        "one",
        now,
        state=ReminderOccurrenceState.COMPLETED,
    )
    api.operation_succeeded.emit(
        operation,
        {
            "action": "completed",
            "occurrence": _payload(confirmed),
            "idempotency_key": "server-key",
        },
    )
    assert cache.pending_commands("account-1") == []
    assert cache.get("one").state is ReminderOccurrenceState.COMPLETED
    store.close()


def test_reminder_card_merges_queue_and_emits_actions() -> None:
    app = QApplication.instance() or QApplication([])
    now = datetime.now(UTC)
    card = ReminderCard()
    completed: list[str] = []
    snoozed: list[tuple[str, int]] = []
    card.complete_requested.connect(completed.append)
    card.snooze_requested.connect(lambda occurrence_id, minutes: snoozed.append((occurrence_id, minutes)))

    card.show_occurrences([_occurrence("one", now), _occurrence("two", now)])
    assert card.current_occurrence_id == "one"
    assert "另有 1 条" in card.title_label.text()
    card.complete_button.click()
    assert completed == ["one"]
    card._snooze(10)
    assert snoozed == [("one", 10)]
    card.resolve("one")
    assert card.current_occurrence_id == "two"
    card.close()
    assert app is not None
