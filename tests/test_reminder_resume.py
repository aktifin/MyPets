from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.domain import ReminderOccurrence, ReminderOccurrenceState
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.reminder_cache import ReminderCache
from onepic_desktop_pet.reminder_card import ReminderCard
from onepic_desktop_pet.reminder_resume import ReminderResumeSummary
from onepic_desktop_pet.reminder_scheduler import ReminderScheduler


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


def _occurrence(occurrence_id: str, scheduled_at: datetime) -> ReminderOccurrence:
    return ReminderOccurrence(
        occurrence_id=occurrence_id,
        source="myreminder",
        source_reminder_id=f"source-{occurrence_id}",
        account_id="account-1",
        title=f"提醒 {occurrence_id}",
        content="处理这一项",
        scheduled_at=scheduled_at,
        timezone="Asia/Tokyo",
        state=ReminderOccurrenceState.PENDING,
        priority="normal",
        category="general",
        version=1,
    )


def test_cold_start_is_normal_delivery_but_long_running_gap_is_resume_summary(
    tmp_path: Path,
) -> None:
    initial = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    clock = [initial]
    store = LocalStateStore(tmp_path / "state.sqlite3")
    cache = ReminderCache(store)
    cache.put(_occurrence("cold", initial - timedelta(minutes=5)))

    scheduler = ReminderScheduler(
        cache,
        timer=FakeTimer(),
        clock=lambda: clock[0],
        interval_ms=15_000,
        resume_gap_seconds=120,
    )
    ordinary: list[list[ReminderOccurrence]] = []
    summaries: list[ReminderResumeSummary] = []
    deliveries: list[str] = []
    scheduler.reminders_due.connect(ordinary.append)
    scheduler.resume_summary_due.connect(summaries.append)
    scheduler.delivery_requested.connect(deliveries.append)

    scheduler.start("account-1")
    assert [[item.occurrence_id for item in batch] for batch in ordinary] == [["cold"]]
    assert summaries == []

    next_due = initial + timedelta(minutes=3)
    cache.put(_occurrence("after-sleep-one", next_due))
    cache.put(_occurrence("after-sleep-two", next_due + timedelta(minutes=1)))
    clock[0] = initial + timedelta(minutes=10)
    resumed = scheduler.scan()

    assert [item.occurrence_id for item in resumed] == [
        "after-sleep-one",
        "after-sleep-two",
    ]
    assert len(ordinary) == 1
    assert len(summaries) == 1
    assert summaries[0].count == 2
    assert summaries[0].gap_seconds == 600
    assert deliveries == ["cold", "after-sleep-one", "after-sleep-two"]
    assert scheduler.scan(clock[0]) == []
    assert len(summaries) == 1
    store.close()


def test_reminder_card_shows_one_resume_summary_before_individual_actions() -> None:
    app = QApplication.instance() or QApplication([])
    resumed_at = datetime(2026, 7, 25, 9, 0, tzinfo=UTC)
    items = (
        _occurrence("one", resumed_at - timedelta(minutes=20)),
        _occurrence("two", resumed_at - timedelta(minutes=5)),
    )
    summary = ReminderResumeSummary(
        occurrences=items,
        previous_scan_at=resumed_at - timedelta(minutes=30),
        resumed_at=resumed_at,
    )
    card = ReminderCard()
    completed: list[str] = []
    card.complete_requested.connect(completed.append)

    card.show_resume_summary(summary)
    assert card.showing_resume_summary is True
    assert card.current_occurrence_id is None
    assert "错过 2 条提醒" in card.title_label.text()
    assert card.review_button.isVisible() is True
    assert card.complete_button.isVisible() is False
    card.complete_button.click()
    assert completed == []

    card.review_button.click()
    assert card.showing_resume_summary is False
    assert card.current_occurrence_id == "one"
    assert card.complete_button.isVisible() is True
    card.complete_button.click()
    assert completed == ["one"]
    card.close()
    assert app is not None
