"""Local due-time scanning with sleep recovery and folded delivery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from .domain import FoldedNotification, NotificationKind, ReminderOccurrence
from .reminder_cache import ReminderCache


class ReminderScheduler(QObject):
    """Deliver cached reminders locally even while the cloud is temporarily unavailable."""

    reminders_due = Signal(object)
    delivery_requested = Signal(str)
    state_changed = Signal(str)

    def __init__(
        self,
        cache: ReminderCache,
        *,
        timer: QTimer | None = None,
        clock: Callable[[], datetime] | None = None,
        interval_ms: int = 15_000,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache = cache
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._timer = timer or QTimer(self)
        self._timer.setInterval(max(1_000, int(interval_ms)))
        self._timer.timeout.connect(self.scan)
        self._account_id = ""

    @property
    def account_id(self) -> str:
        return self._account_id

    def start(self, account_id: str) -> None:
        normalized = account_id.strip()
        if not normalized:
            self.stop()
            return
        self._account_id = normalized
        self._timer.start()
        self.state_changed.emit("running")
        self.scan()

    def stop(self) -> None:
        self._timer.stop()
        self._account_id = ""
        self.state_changed.emit("stopped")

    def scan(self, now: datetime | None = None) -> list[ReminderOccurrence]:
        if not self._account_id:
            return []
        current = now or self._clock()
        if current.tzinfo is None:
            raise ValueError("提醒扫描时间必须包含时区")
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
        self.reminders_due.emit(delivered)
        return delivered
