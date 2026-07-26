"""Pure customer-facing growth goals and milestone copy.

The functions in this module translate the existing server-authoritative growth model
into understandable progress. They do not mutate pet state or add a second reward system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


STAGES = (
    {
        "code": "newborn",
        "label": "初生期",
        "minimum_level": 1,
        "detail": "正在熟悉新的家和日常照料。",
        "next_hint": "保持稳定照料，逐步建立生活习惯。",
    },
    {
        "code": "child",
        "label": "幼年期",
        "minimum_level": 3,
        "detail": "已经能够形成更稳定的互动和陪伴节奏。",
        "next_hint": "尝试不同照料方式，继续积累成长经验。",
    },
    {
        "code": "adult",
        "label": "成熟期",
        "minimum_level": 7,
        "detail": "已经形成稳定性格和长期陪伴关系。",
        "next_hint": "成熟期没有终点，可继续提升等级和羁绊。",
    },
)

_STAGE_BY_CODE = {str(item["code"]): item for item in STAGES}


@dataclass(frozen=True)
class GrowthProgress:
    current_stage: str
    current_stage_label: str
    current_stage_detail: str
    growth_level: int
    growth_exp: int
    growth_level_current: int
    growth_level_target: int
    growth_exp_remaining: int
    growth_level_percent: int
    bond_level: int
    bond_exp: int
    bond_level_current: int
    bond_level_target: int
    bond_exp_remaining: int
    bond_level_percent: int
    next_stage: str | None
    next_stage_label: str | None
    next_stage_target_level: int | None
    next_stage_exp_remaining: int
    stage_progress_percent: int
    headline: str
    detail: str
    suggested_action: str
    suggested_action_label: str
    estimated_actions: int
    final_stage: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


def _read(value: object, name: str, default: object) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _stage_for(level: int, raw_stage: str) -> dict[str, object]:
    # The level is authoritative for progression. The stored code is retained when valid
    # and compatible, otherwise the closest current stage is used.
    eligible = [item for item in STAGES if level >= int(item["minimum_level"])]
    calculated = eligible[-1]
    stored = _STAGE_BY_CODE.get(raw_stage)
    if stored is not None and level >= int(stored["minimum_level"]):
        return stored
    return calculated


def build_growth_progress(pet: object) -> GrowthProgress:
    """Build an understandable next goal from the current pet snapshot."""

    level = max(1, int(_read(pet, "growth_level", 1)))
    growth_exp = max(0, int(_read(pet, "growth_exp", 0)))
    bond_level = max(1, int(_read(pet, "bond_level", 1)))
    bond_exp = max(0, int(_read(pet, "bond_exp", 0)))
    raw_stage = str(_read(pet, "growth_stage", "newborn") or "newborn")
    stage = _stage_for(level, raw_stage)

    growth_base = (level - 1) * 100
    growth_current = max(0, growth_exp - growth_base)
    growth_target = 100
    growth_remaining = max(0, level * 100 - growth_exp)
    growth_percent = min(100, max(0, round(growth_current / growth_target * 100)))

    bond_base = (bond_level - 1) * 80
    bond_current = max(0, bond_exp - bond_base)
    bond_target = 80
    bond_remaining = max(0, bond_level * 80 - bond_exp)
    bond_percent = min(100, max(0, round(bond_current / bond_target * 100)))

    stage_index = next(
        index for index, item in enumerate(STAGES) if item["code"] == stage["code"]
    )
    next_stage = STAGES[stage_index + 1] if stage_index + 1 < len(STAGES) else None
    if next_stage is None:
        next_stage_remaining = 0
        stage_percent = 100
        headline = f"当前处于{stage['label']}"
        detail = f"距离成长 Lv.{level + 1} 还差 {growth_remaining} 点成长经验。"
        estimated = max(1, math.ceil(growth_remaining / 7)) if growth_remaining else 0
    else:
        target_level = int(next_stage["minimum_level"])
        target_exp = (target_level - 1) * 100
        current_stage_exp = (int(stage["minimum_level"]) - 1) * 100
        next_stage_remaining = max(0, target_exp - growth_exp)
        span = max(1, target_exp - current_stage_exp)
        stage_percent = min(
            100,
            max(0, round((growth_exp - current_stage_exp) / span * 100)),
        )
        headline = f"下一阶段：{next_stage['label']}"
        detail = (
            f"达到成长 Lv.{target_level} 即可进入{next_stage['label']}，"
            f"还差 {next_stage_remaining} 点成长经验。"
        )
        estimated = max(1, math.ceil(next_stage_remaining / 7)) if next_stage_remaining else 0

    return GrowthProgress(
        current_stage=str(stage["code"]),
        current_stage_label=str(stage["label"]),
        current_stage_detail=str(stage["detail"]),
        growth_level=level,
        growth_exp=growth_exp,
        growth_level_current=growth_current,
        growth_level_target=growth_target,
        growth_exp_remaining=growth_remaining,
        growth_level_percent=growth_percent,
        bond_level=bond_level,
        bond_exp=bond_exp,
        bond_level_current=bond_current,
        bond_level_target=bond_target,
        bond_exp_remaining=bond_remaining,
        bond_level_percent=bond_percent,
        next_stage=str(next_stage["code"]) if next_stage is not None else None,
        next_stage_label=str(next_stage["label"]) if next_stage is not None else None,
        next_stage_target_level=(
            int(next_stage["minimum_level"]) if next_stage is not None else None
        ),
        next_stage_exp_remaining=next_stage_remaining,
        stage_progress_percent=stage_percent,
        headline=headline,
        detail=detail,
        suggested_action="play",
        suggested_action_label="玩耍",
        estimated_actions=estimated,
        final_stage=next_stage is None,
    )


def stage_label(value: object) -> str:
    code = str(value or "")
    return str(_STAGE_BY_CODE.get(code, {}).get("label") or code or "未知阶段")
