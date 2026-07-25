"""Local due-time scanning with explicit sleep recovery and folded delivery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from .domain import FoldedNotification, NotificationKind, ReminderOccurrence
from .reminder_cache import ReminderCache
from .reminder_resume import ReminderResumeSummary


class ReminderScheduler(QObject):
    """Deliver cached reminders locally even while the cloud is temporarily unavailable."""

    reminders_due = Signal(object)
    resume_summary_due = Signal(object)
    delivery_requested = Signal(str)
    state_changed = Signal(str)

    def __init__(
        self,
        cache: ReminderCache,
        *,
        timer: QTimer | None = None,
        clock: Callable[[], datetime] | None = None,
        interval_ms: int = 15_000,
        resume_gap_seconds: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = cache
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._timer = timer or QTimer(self)
        self._interval_ms = max(1_000, int(interval_ms))
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self.scan)
        default_gap = max(60, int(self._interval_ms / 1000) * 4)
        self._resume_gap_seconds = max(30, int(resume_gap_seconds or default_gap))
        self._account_id = ""
        self._last_scan_at: datetime | None = None

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def last_scan_at(self) -> datetime | None:
        return self._last_scan_at

    def start(self, account_id: str) -> None:
        normalized = account_id.strip()
        if not normalized:
            self.stop()
            return
        self._account_id = normalized
        self._timer.start()
        self.state_changed.emit("running")
        # Cold-start overdue reminders are ordinary folded delivery, not a false resume event.
        self._last_scan_at = None
        self.scan()

    def stop(self) -> None:
        self._timer.stop()
        self._account_id = ""
        self._last_scan_at = None
        self.state_changed.emit("stopped")

    def scan(self, now: datetime | None = None) -> list[ReminderOccurrence]:
        if not self._account_id:
            return []
        current = now or self._clock()
        if current.tzinfo is None:
            raise ValueError("提醒扫描时间必须包含时区")
        previous = self._last_scan_at
        self._last_scan_at = current
        due = self.cache.due(self._account_id, current)
        if not due:
            return []

        for occurrence in due:
            self.cache.mark_delivered(occurrence.occurrence_id)
            self.cache.store.put_notification(
                FoldedNotification(
                    notification_id=f"reminder:{occurrence.occurrence_id}",
                    account_id=occurrence.account_id,
                    kind=NotificationKind.REMINDER,
                    title=occurrence.title,
                    body=occurrence.content,
                    created_at=current,
                    source_id=occurrence.occurrence_id,
                )
            )
            self.delivery_requested.emit(occurrence.occurrence_id)
        delivered = [self.cache.get(item.occurrence_id) or item for item in due]

        resumed = bool(
            previous is not None
            and current >= previous
            and (current - previous).total_seconds() >= self._resume_gap_seconds
        )
        if resumed:
            self.resume_summary_due.emit(
                ReminderResumeSummary(
                    occurrences=tuple(delivered),
                    previous_scan_at=previous,
                    resumed_at=current,
                )
            )
        else:
            self.reminders_due.emit(delivered)
        return delivered
