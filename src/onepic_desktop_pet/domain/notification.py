"""折叠通知与单次提醒实例领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class MessageReceiptState(str, Enum):
    """折叠消息从送达到归档的状态。"""

    CREATED = "created"
    DELIVERED = "delivered"
    INDICATOR_SHOWN = "indicator_shown"
    READ = "read"
    ARCHIVED = "archived"


class ReminderOccurrenceState(str, Enum):
    """单次提醒实例状态。"""

    PENDING = "pending"
    DELIVERED = "delivered"
    SEEN = "seen"
    SNOOZED = "snoozed"
    COMPLETED = "completed"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class NotificationKind(str, Enum):
    """桌面低打扰入口的通知类别。"""

    MESSAGE = "message"
    REMINDER = "reminder"
    VISIT = "visit"
    GROWTH = "growth"
    SYSTEM = "system"


@dataclass
class FoldedNotification:
    """附着在宠物、外出标识或托盘上的折叠通知。"""

    notification_id: str
    account_id: str
    kind: NotificationKind
    title: str
    body: str
    created_at: datetime
    pet_id: str | None = None
    source_id: str | None = None
    is_read: bool = False
    is_archived: bool = False

    def mark_read(self) -> None:
        self.is_read = True

    def archive(self) -> None:
        self.is_read = True
        self.is_archived = True


@dataclass
class ReminderOccurrence:
    """由 MyReminder 或其他数据源生成的一次具体提醒。"""

    occurrence_id: str
    source: str
    source_reminder_id: str
    account_id: str
    title: str
    content: str
    scheduled_at: datetime
    timezone: str
    state: ReminderOccurrenceState = ReminderOccurrenceState.PENDING
    priority: str = "normal"
    category: str = "general"
    version: int = 1

    def __post_init__(self) -> None:
        if not self.occurrence_id.strip():
            raise ValueError("occurrence_id 不能为空")
        if self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at 必须包含时区")
        self.version = max(1, int(self.version))

    @property
    def terminal(self) -> bool:
        return self.state in {
            ReminderOccurrenceState.COMPLETED,
            ReminderOccurrenceState.DISMISSED,
            ReminderOccurrenceState.EXPIRED,
        }
