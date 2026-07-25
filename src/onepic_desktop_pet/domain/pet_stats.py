"""宠物数值快照、基本身份与账户关联模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .pet_stage import GrowthStage, PetRole, PresenceStatus


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
    age_days: int = 0
    care_quality: int = 100
    state_version: int = 1

    def clamp(self) -> None:
        """约束数值，避免客户端或迁移数据产生越界状态。"""

        self.growth_level = max(1, int(self.growth_level))
        self.growth_exp = max(0, int(self.growth_exp))
        self.bond_level = max(1, int(self.bond_level))
        self.bond_exp = max(0, int(self.bond_exp))
        self.age_days = max(0, int(self.age_days))
        self.care_quality = min(100, max(0, int(self.care_quality)))
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
