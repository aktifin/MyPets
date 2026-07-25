"""
MyPets 云养宠领域模型。

本模块只依赖 Python 标准库，用于统一描述多宠物账户、成长、位置、消息、提醒
和云端语义事件。桌面窗口、网络客户端和持久化层不应在这里出现。
"""

from __future__ import annotations

from .event import CloudEvent
from .notification import (
    FoldedNotification,
    MessageReceiptState,
    NotificationKind,
    ReminderOccurrence,
    ReminderOccurrenceState,
)
from .pet_stage import GrowthStage, PetRole, PresenceStatus
from .pet_stats import AccountPetRelation, PetIdentity, PetProfile, PetStats

__all__ = [
    "AccountPetRelation",
    "CloudEvent",
    "FoldedNotification",
    "GrowthStage",
    "MessageReceiptState",
    "NotificationKind",
    "PetIdentity",
    "PetProfile",
    "PetRole",
    "PetStats",
    "PresenceStatus",
    "ReminderOccurrence",
    "ReminderOccurrenceState",
]
