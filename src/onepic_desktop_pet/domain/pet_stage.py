"""成长阶段、位置状态与权限角色枚举模型。"""

from __future__ import annotations

from enum import Enum


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
