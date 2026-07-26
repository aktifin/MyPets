"""Pure customer-experience rules for the desktop pet.

These helpers translate server-authoritative pet snapshots and local interaction
records into plain-language recommendations, daily tasks, streaks, cooldowns, and
result summaries without depending on Qt or network code.
"""

from __future__ import annotations

import math
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from .domain import PetProfile, PresenceStatus


CARE_ACTION_LABELS = {
    "feed": "投喂",
    "play": "玩耍",
    "clean": "清洁",
    "pet": "摸摸",
    "rest": "休息",
}

_STAT_LABELS = {
    "hunger": "饱食",
    "energy": "精力",
    "mood": "心情",
    "cleanliness": "清洁",
    "health": "健康",
    "boredom": "无聊",
    "growth_exp": "成长经验",
    "bond_exp": "羁绊经验",
}


@dataclass(frozen=True)
class CareRecommendation:
    action: str | None
    title: str
    detail: str


@dataclass(frozen=True)
class CareResultSummary:
    title: str
    detail: str


def snapshot_stats(pet: PetProfile) -> dict[str, int]:
    stats = pet.stats
    return {
        "hunger": int(stats.hunger),
        "energy": int(stats.energy),
        "mood": int(stats.mood),
        "cleanliness": int(stats.cleanliness),
        "health": int(stats.health),
        "boredom": int(stats.boredom),
        "growth_exp": int(stats.growth_exp),
        "growth_level": int(stats.growth_level),
        "bond_exp": int(stats.bond_exp),
        "bond_level": int(stats.bond_level),
    }


def recommend_care(pet: PetProfile) -> CareRecommendation:
    if pet.presence is not PresenceStatus.HOME:
        return CareRecommendation(
            None,
            f"{pet.identity.name} 正在串门",
            "返家后才能照料；现在可从串门面板查看进度或召回。",
        )

    stats = pet.stats
    candidates = [
        (int(stats.hunger), "feed", "该投喂了", "饱食状态最低，投喂能让它恢复精神。"),
        (int(stats.energy), "rest", "让它休息一下", "精力偏低，休息后更适合继续互动。"),
        (
            int(stats.cleanliness),
            "clean",
            "需要清洁",
            "清洁状态偏低，先整理干净会更舒服。",
        ),
        (int(stats.mood), "play", "陪它玩一会儿", "心情偏低，玩耍可以增加互动和羁绊。"),
        (100 - int(stats.boredom), "play", "它有点无聊", "陪它玩一会儿，缓解无聊并积累羁绊。"),
    ]
    value, action, title, detail = min(candidates, key=lambda item: item[0])
    if value >= 80:
        return CareRecommendation(
            "pet",
            "状态不错，摸摸它吧",
            "当前状态稳定，轻松互动也能积累羁绊。",
        )
    return CareRecommendation(action, title, detail)


def plain_status_summary(pet: PetProfile) -> str:
    if pet.presence is not PresenceStatus.HOME:
        return "串门中，暂时不能在本机照料"

    stats = pet.stats
    concerns: list[tuple[int, str]] = []
    if stats.hunger < 65:
        concerns.append((stats.hunger, "有点饿"))
    if stats.energy < 55:
        concerns.append((stats.energy, "需要休息"))
    if stats.cleanliness < 65:
        concerns.append((stats.cleanliness, "需要清洁"))
    if stats.mood < 60:
        concerns.append((stats.mood, "心情偏低"))
    if stats.boredom > 55:
        concerns.append((100 - stats.boredom, "有点无聊"))
    if stats.health < 70:
        concerns.append((stats.health, "健康状态需关注"))
    if not concerns:
        return "状态良好，可以轻松互动"
    return " · ".join(text for _value, text in sorted(concerns)[:2])


def format_care_result(
    pet_name: str,
    action: str,
    before: Mapping[str, int],
    after: Mapping[str, int],
) -> CareResultSummary:
    label = CARE_ACTION_LABELS.get(action, "照料")
    changes: list[str] = []
    for field in ("hunger", "energy", "mood", "cleanliness", "health", "boredom"):
        previous = int(before.get(field, 0))
        current = int(after.get(field, previous))
        delta = current - previous
        if delta:
            sign = "+" if delta > 0 else ""
            changes.append(f"{_STAT_LABELS[field]} {sign}{delta}")

    previous_growth_level = int(before.get("growth_level", 1))
    growth_level = int(after.get("growth_level", previous_growth_level))
    previous_bond_level = int(before.get("bond_level", 1))
    bond_level = int(after.get("bond_level", previous_bond_level))
    if growth_level > previous_growth_level:
        changes.append(f"成长升至 Lv.{growth_level}")
    if bond_level > previous_bond_level:
        changes.append(f"羁绊升至 Lv.{bond_level}")

    for field in ("growth_exp", "bond_exp"):
        previous = int(before.get(field, 0))
        current = int(after.get(field, previous))
        delta = current - previous
        if delta > 0:
            changes.append(f"{_STAT_LABELS[field]} +{delta}")

    detail = " · ".join(changes[:5]) if changes else "状态已同步，没有额外数值变化。"
    return CareResultSummary(f"{pet_name} · {label}完成", detail)


def _record_values(
    records: Iterable[Mapping[str, str]],
    *,
    local_now: datetime,
) -> tuple[dict[object, list[str]], dict[str, datetime]]:
    by_date: dict[object, list[str]] = defaultdict(list)
    latest: dict[str, datetime] = {}
    for record in records:
        action = str(record.get("action_type") or record.get("action") or "")
        if action not in CARE_ACTION_LABELS:
            continue
        raw = str(record.get("created_at") or "")
        try:
            created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=local_now.tzinfo)
        local_created = created.astimezone(local_now.tzinfo)
        by_date[local_created.date()].append(action)
        previous = latest.get(action)
        if previous is None or local_created > previous:
            latest[action] = local_created
    return by_date, latest


def _task_rows(actions: list[str]) -> list[dict[str, object]]:
    distinct = len(set(actions))
    bond_count = sum(action in {"play", "pet"} for action in actions)
    return [
        {
            "task_id": "care-three-times",
            "title": "3 次照料",
            "current": min(len(actions), 3),
            "target": 3,
            "completed": len(actions) >= 3,
        },
        {
            "task_id": "care-two-types",
            "title": "2 种方式",
            "current": min(distinct, 2),
            "target": 2,
            "completed": distinct >= 2,
        },
        {
            "task_id": "bond-once",
            "title": "1 次陪伴",
            "current": min(bond_count, 1),
            "target": 1,
            "completed": bond_count >= 1,
        },
    ]


def _day_completed(actions: list[str]) -> bool:
    return all(bool(task["completed"]) for task in _task_rows(actions))


def build_local_daily_care_summary(
    records: Iterable[Mapping[str, str]],
    *,
    now: datetime | None = None,
    cooldown_seconds: int = 5,
    daily_limit: int = 50,
) -> dict[str, object]:
    local_now = now or datetime.now().astimezone()
    if local_now.tzinfo is None:
        local_now = local_now.astimezone()
    by_date, latest = _record_values(records, local_now=local_now)
    today = local_now.date()
    today_actions = by_date.get(today, [])
    tasks = _task_rows(today_actions)
    completed_tasks = sum(bool(task["completed"]) for task in tasks)
    completed_dates = {day for day, actions in by_date.items() if _day_completed(actions)}
    cursor = today if today in completed_dates else today - timedelta(days=1)
    streak = 0
    while cursor in completed_dates:
        streak += 1
        cursor -= timedelta(days=1)

    safe_limit = max(1, int(daily_limit))
    limit_reached = len(today_actions) >= safe_limit
    safe_cooldown = max(0, int(cooldown_seconds))
    actions: list[dict[str, object]] = []
    for action, label in CARE_ACTION_LABELS.items():
        remaining = 0
        previous = latest.get(action)
        if previous is not None and safe_cooldown:
            remaining = max(
                0,
                math.ceil(safe_cooldown - (local_now - previous).total_seconds()),
            )
        if limit_reached:
            reason = f"今天已完成 {safe_limit} 次照料，明天可以继续。"
        elif remaining:
            reason = f"{label}刚刚完成，{remaining} 秒后可再次操作。"
        else:
            reason = "现在可以操作。"
        actions.append(
            {
                "action": action,
                "label": label,
                "available": not limit_reached and remaining <= 0,
                "remaining_seconds": remaining,
                "reason": reason,
            }
        )

    all_completed = completed_tasks == len(tasks)
    return {
        "tasks": tasks,
        "completed_tasks": completed_tasks,
        "total_tasks": len(tasks),
        "all_tasks_completed": all_completed,
        "streak_days": streak,
        "reward_title": "今日陪伴徽章" if all_completed else "完成全部任务可点亮陪伴徽章",
        "reward_detail": (
            f"今天的任务已完成，连续陪伴 {streak} 天。"
            if all_completed
            else f"还剩 {len(tasks) - completed_tasks} 项任务。"
        ),
        "care_count": len(today_actions),
        "daily_limit": safe_limit,
        "daily_remaining": max(0, safe_limit - len(today_actions)),
        "daily_limit_reached": limit_reached,
        "actions": actions,
    }


def daily_care_progress(
    records: Iterable[Mapping[str, str]],
    *,
    now: datetime | None = None,
    goal: int = 3,
) -> tuple[int, int]:
    summary = build_local_daily_care_summary(records, now=now)
    count = int(summary["care_count"])
    safe_goal = max(1, int(goal))
    return min(count, safe_goal), safe_goal


def apply_local_demo_care(pet: PetProfile, action: str) -> PetProfile:
    """Apply a small reversible-feeling interaction only to bundled local demo pets."""

    if action not in CARE_ACTION_LABELS:
        raise ValueError("不支持的照料动作")
    updated = deepcopy(pet)
    stats = updated.stats
    deltas = {
        "feed": {"hunger": 18, "mood": 2, "boredom": -2},
        "play": {"energy": -8, "mood": 12, "boredom": -20},
        "clean": {"cleanliness": 20, "health": 2},
        "pet": {"mood": 8, "boredom": -8},
        "rest": {"energy": 22, "hunger": -4},
    }[action]
    for field, delta in deltas.items():
        setattr(stats, field, int(getattr(stats, field)) + delta)
    stats.growth_exp += 2
    stats.bond_exp += 1
    stats.state_version += 1
    stats.clamp()
    updated.updated_at = datetime.now().astimezone()
    return updated
