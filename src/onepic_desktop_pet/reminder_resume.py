"""Pure data model for reminders recovered after a long desktop sleep gap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .domain import ReminderOccurrence


@dataclass(frozen=True)
class ReminderResumeSummary:
    occurrences: tuple[ReminderOccurrence, ...]
    previous_scan_at: datetime
    resumed_at: datetime

    def __post_init__(self) -> None:
        if self.previous_scan_at.tzinfo is None or self.resumed_at.tzinfo is None:
            raise ValueError("休眠恢复时间必须包含时区")
        if self.resumed_at < self.previous_scan_at:
            raise ValueError("恢复时间不能早于上次扫描时间")
        if not self.occurrences:
            raise ValueError("休眠恢复摘要至少包含一条提醒")

    @property
    def gap_seconds(self) -> int:
        return max(0, int((self.resumed_at - self.previous_scan_at).total_seconds()))

    @property
    def count(self) -> int:
        return len(self.occurrences)

    @property
    def first_due_at(self) -> datetime:
        return min(item.scheduled_at for item in self.occurrences)

    @property
    def last_due_at(self) -> datetime:
        return max(item.scheduled_at for item in self.occurrences)
