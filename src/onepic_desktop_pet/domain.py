"""
MyPets 云养宠领域模型。

本模块只依赖 Python 标准库，用于统一描述多宠物账户、成长、位置、消息、提醒
和云端语义事件。桌面窗口、网络客户端和持久化层不应在这里出现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class GrowthStage(str, Enum):
    """宠物成长阶段。等级可以持续增长，阶段只在关键节点变化。"""

    NEWBORN = "newborn"
    CHILD = "child"
    JUVENILE = "juvenile"
    ADULT = "adult"
    BOND = "bond"


class PresenceStatus(str, Enum):
    """宠物在家、串门和返家过程中的位置状态。"""

    HOME = "home"
    PREPARING = "preparing"
    TRAVELLING = "travelling"
    VISITING = "visiting"
    GATHERING = "gathering"
    RETURNING = "returning"
    RESTING = "resting"


class PetRole(str, Enum):
    """账户与宠物之间的权限角色。"""

    OWNER = "owner"
    CO_OWNER = "co_owner"
    CAREGIVER = "caregiver"
    VIEWER = "viewer"


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
class PetStats:
    """服务端权威的宠物成长和日常状态快照。"""

    growth_stage: GrowthStage = GrowthStage.NEWBORN
    growth_level: int = 1
    growth_exp: int = 0
    bond_level: int = 1
    bond_exp: int = 0
    hunger: int = 100
    energy: int = 100
    mood: int = 80
    cleanliness: int = 100
    health: int = 100
    boredom: int = 0
    state_version: int = 1

    def clamp(self) -> None:
        """约束数值，避免客户端或迁移数据产生越界状态。"""

        self.growth_level = max(1, int(self.growth_level))
        self.growth_exp = max(0, int(self.growth_exp))
        self.bond_level = max(1, int(self.bond_level))
        self.bond_exp = max(0, int(self.bond_exp))
        self.state_version = max(1, int(self.state_version))
        for name in (
            "hunger",
            "energy",
            "mood",
            "cleanliness",
            "health",
            "boredom",
        ):
            setattr(self, name, min(100, max(0, int(getattr(self, name)))))


@dataclass(frozen=True)
class PetIdentity:
    """宠物实例的稳定身份，不包含平台窗口或动画帧信息。"""

    pet_id: str
    name: str
    template_id: str
    template_version: str
    identity_version: str
    primary_owner_account_id: str

    def __post_init__(self) -> None:
        if not self.pet_id.strip():
            raise ValueError("pet_id 不能为空")
        if not self.name.strip():
            raise ValueError("宠物名称不能为空")
        if not self.template_id.strip():
            raise ValueError("template_id 不能为空")


@dataclass
class PetProfile:
    """客户端可缓存的宠物资料与状态。"""

    identity: PetIdentity
    stats: PetStats = field(default_factory=PetStats)
    presence: PresenceStatus = PresenceStatus.HOME
    personality_type: str = "balanced"
    asset_version: str = "1.0.0"
    updated_at: datetime | None = None

    def normalize(self) -> None:
        self.stats.clamp()
        self.personality_type = self.personality_type.strip() or "balanced"
        self.asset_version = self.asset_version.strip() or "1.0.0"


@dataclass(frozen=True)
class AccountPetRelation:
    """账户对指定宠物的角色、亲密度与照料贡献。"""

    account_id: str
    pet_id: str
    role: PetRole
    affinity: int = 0
    care_contribution: int = 0

    def __post_init__(self) -> None:
        if not self.account_id or not self.pet_id:
            raise ValueError("账户与宠物标识不能为空")
        if not 0 <= self.affinity <= 100:
            raise ValueError("affinity 必须在 0 到 100 之间")
        if self.care_contribution < 0:
            raise ValueError("care_contribution 不能为负数")


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


@dataclass(frozen=True)
class CloudEvent:
    """桌面端、小程序和云端之间同步的语义事件。"""

    event_id: str
    event_type: str
    sequence_number: int
    idempotency_key: str
    created_at: datetime
    payload: dict[str, Any]
    target_account_id: str
    target_device_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type or not self.idempotency_key:
            raise ValueError("云事件标识、类型和幂等键不能为空")
        if self.sequence_number < 0:
            raise ValueError("sequence_number 不能为负数")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at 必须包含时区")
