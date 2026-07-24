"""本地提醒仓库的跨时区比较回归测试。"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from onepic_desktop_pet.domain import ReminderOccurrence
from onepic_desktop_pet.local_store import LocalStateStore


def test_due_reminders_are_compared_in_utc(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.db")
    tokyo = timezone(timedelta(hours=9))
    store.put_reminder(
        ReminderOccurrence(
            occurrence_id="r-tokyo",
            source="myreminder",
            source_reminder_id="source-1",
            account_id="account-1",
            title="东京时间提醒",
            content="东京时间提醒",
            scheduled_at=datetime(2026, 7, 24, 17, 0, tzinfo=tokyo),
            timezone="Asia/Tokyo",
        )
    )

    due = store.list_due_reminders(
        "account-1",
        datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
    )

    assert [item.occurrence_id for item in due] == ["r-tokyo"]
    assert due[0].scheduled_at == datetime(2026, 7, 24, 8, 0, tzinfo=UTC)
    store.close()
