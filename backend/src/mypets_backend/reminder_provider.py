"""Provider-neutral reminder adapter contract.

Concrete MyReminder or third-party integrations convert their source records into
ProviderOccurrence values. The HTTP and persistence layers consume only this stable contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderOccurrence:
    source_reminder_id: str
    title: str
    content: str
    scheduled_at: datetime
    timezone: str
    priority: str = "normal"
    category: str = "general"
    version: int = 1

    def __post_init__(self) -> None:
        if not self.source_reminder_id.strip():
            raise ValueError("source_reminder_id 不能为空")
        if not self.title.strip():
            raise ValueError("提醒标题不能为空")
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at 必须包含时区")
        if not self.timezone.strip():
            raise ValueError("timezone 不能为空")
        if self.version < 1:
            raise ValueError("version 不能小于 1")


@runtime_checkable
class ReminderProvider(Protocol):
    """Pull concrete reminder occurrences from one external reminder source."""

    provider_id: str

    def pull_occurrences(
        self,
        *,
        account_external_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> Iterable[ProviderOccurrence]: ...
