"""Pure desktop growth goals and local milestone helpers."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable, Mapping

from .domain import GrowthStage, PetProfile


STAGE_LABELS = {
    "newborn": "初生期",
    "child": "幼年期",
    "adult": "成熟期",
}


def _stage_code(level: int) -> str:
    if level >= 7:
        return "adult"
    if level >= 3:
        return "child"
    return "newborn"


def apply_growth_levels(pet: PetProfile) -> PetProfile:
    """Align local experience pets with the server's existing level thresholds."""

    stats = pet.stats
    stats.growth_level = max(1, 1 + int(stats.growth_exp) // 100)
    stats.bond_level = max(1, 1 + int(stats.bond_exp) // 80)
    stats.growth_stage = GrowthStage(_stage_code(stats.growth_level))
    stats.clamp()
    return pet


def build_growth_progress(pet: PetProfile) -> dict[str, object]:
    stats = pet.stats
    level = max(1, int(stats.growth_level))
    growth_exp = max(0, int(stats.growth_exp))
    bond_level = max(1, int(stats.bond_level))
    bond_exp = max(0, int(stats.bond_exp))
    stage = _stage_code(level)

    growth_current = max(0, growth_exp - (level - 1) * 100)
    growth_remaining = max(0, level * 100 - growth_exp)
    bond_current = max(0, bond_exp - (bond_level - 1) * 80)
    bond_remaining = max(0, bond_level * 80 - bond_exp)

    if level < 3:
        next_stage, next_label, target_level = "child", "幼年期", 3
    elif level < 7:
        next_stage, next_label, target_level = "adult", "成熟期", 7
    else:
        next_stage, next_label, target_level = None, None, None

    if target_level is None:
        stage_remaining = 0
        stage_percent = 100
        headline = "当前处于成熟期"
        detail = f"距离成长 Lv.{level + 1} 还差 {growth_remaining} 点成长经验。"
        estimated = max(1, math.ceil(growth_remaining / 7)) if growth_remaining else 0
    else:
        target_exp = (target_level - 1) * 100
        stage_base = 0 if stage == "newborn" else 200
        stage_remaining = max(0, target_exp - growth_exp)
        stage_percent = min(100, max(0, round((growth_exp - stage_base) / max(1, target_exp - stage_base) * 100)))
        headline = f"下一阶段：{next_label}"
        detail = f"达到成长 Lv.{target_level} 即可进入{next_label}，还差 {stage_remaining} 点成长经验。"
        estimated = max(1, math.ceil(stage_remaining / 7)) if stage_remaining else 0

    return {
        "current_stage": stage,
        "current_stage_label": STAGE_LABELS[stage],
        "growth_level": level,
        "growth_exp": growth_exp,
        "growth_level_current": growth_current,
        "growth_level_target": 100,
        "growth_exp_remaining": growth_remaining,
        "bond_level": bond_level,
        "bond_exp": bond_exp,
        "bond_level_current": bond_current,
        "bond_level_target": 80,
        "bond_exp_remaining": bond_remaining,
        "next_stage": next_stage,
        "next_stage_label": next_label,
        "next_stage_target_level": target_level,
        "next_stage_exp_remaining": stage_remaining,
        "stage_progress_percent": stage_percent,
        "headline": headline,
        "detail": detail,
        "suggested_action": "play",
        "suggested_action_label": "玩耍",
        "estimated_actions": estimated,
        "final_stage": target_level is None,
    }


def build_growth_milestones(
    *,
    pet_name: str,
    before: Mapping[str, int],
    after: Mapping[str, int],
    previous_stage: str,
    current_stage: str,
) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    previous_level = int(before.get("growth_level", 1))
    current_level = int(after.get("growth_level", previous_level))
    if current_level > previous_level:
        values.append({
            "memory_type": "growth_level",
            "icon": "⭐",
            "title": f"{pet_name} 升到成长 Lv.{current_level}",
            "detail": f"从 Lv.{previous_level} 成长到 Lv.{current_level}。",
        })
    previous_bond = int(before.get("bond_level", 1))
    current_bond = int(after.get("bond_level", previous_bond))
    if current_bond > previous_bond:
        values.append({
            "memory_type": "bond_level",
            "icon": "🤝",
            "title": f"羁绊提升到 Lv.{current_bond}",
            "detail": f"共同照料让羁绊从 Lv.{previous_bond} 提升到 Lv.{current_bond}。",
        })
    if current_stage != previous_stage:
        values.append({
            "memory_type": "growth_stage",
            "icon": "🌱",
            "title": f"进入{STAGE_LABELS.get(current_stage, current_stage)}",
            "detail": (
                f"{pet_name} 从{STAGE_LABELS.get(previous_stage, previous_stage)}"
                f"成长为{STAGE_LABELS.get(current_stage, current_stage)}。"
            ),
        })
    return values


def build_local_memories(
    records: Iterable[Mapping[str, object]],
    *,
    pet_name: str,
) -> list[dict[str, object]]:
    memories: list[dict[str, object]] = []
    for index, record in enumerate(records):
        action_type = str(record.get("action_type") or "")
        if action_type not in {"growth_level", "bond_level", "growth_stage"}:
            continue
        memories.append({
            "memory_id": f"local:{action_type}:{index}:{record.get('created_at', '')}",
            "memory_type": action_type,
            "icon": {"growth_level": "⭐", "bond_level": "🤝", "growth_stage": "🌱"}[action_type],
            "title": str(record.get("action_name") or "成长纪念"),
            "detail": str(record.get("detail") or "记录了一次成长变化。"),
            "occurred_at": record.get("created_at"),
            "source_label": "本地照料",
        })
    memories.append({
        "memory_id": "local-adoption",
        "memory_type": "adoption",
        "icon": "🏠",
        "title": f"{pet_name} 开始陪伴",
        "detail": "本地成长、照料和陪伴记录会保存在这台电脑上。",
        "occurred_at": None,
        "source_label": "本地体验",
    })
    return memories
