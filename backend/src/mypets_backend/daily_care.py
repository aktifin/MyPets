"""Pure daily-care progress, streak, cooldown, and limit rules.

The customer experience needs one interpretation of "today" and one task model on
Web and desktop. This module has no FastAPI or database dependency; callers provide
care interactions and a timezone offset, and receive JSON-ready customer language.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Iterable, Mapping, Protocol


CARE_ACTIONS = ("feed", "play", "clean", "pet", "rest")
CARE_ACTION_LABELS = {
    "feed": "投喂",
    "play": "玩耍",
    "clean": "清洁",
    "pet": "摸摸",
    "rest": "休息",
}


class CareInteractionLike(Protocol):
    action: str
    created_at: datetime


def _value(item: object, field: str) -> object:
    if isinstance(item, Mapping):
        return item.get(field)
    return getattr(item, field, None)


def _created_at(item: object) -> datetime | None:
    raw = _value(item, "created_at")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _timezone(timezone_offset_minutes: int) -> timezone:
    # JavaScript Date.getTimezoneOffset() is UTC - local time.
    normalized = max(-840, min(840, int(timezone_offset_minutes)))
    return timezone(timedelta(minutes=-normalized))


def _task_rows(actions: list[str]) -> list[dict[str, object]]:
    distinct = len(set(actions))
    bond_count = sum(action in {"play", "pet"} for action in actions)
    return [
        {
            "task_id": "care-three-times",
            "title": "完成 3 次照料",
            "detail": "投喂、玩耍、清洁、摸摸或休息都可以。",
            "current": min(len(actions), 3),
            "target": 3,
            "completed": len(actions) >= 3,
        },
        {
            "task_id": "care-two-types",
            "title": "使用 2 种不同照料",
            "detail": "换一种互动，宠物的一天会更丰富。",
            "current": min(distinct, 2),
            "target": 2,
            "completed": distinct >= 2,
        },
        {
            "task_id": "bond-once",
            "title": "完成 1 次陪伴互动",
            "detail": "玩耍或摸摸可以积累今天的陪伴。",
            "current": min(bond_count, 1),
            "target": 1,
            "completed": bond_count >= 1,
        },
    ]


def _day_completed(actions: list[str]) -> bool:
    return all(bool(task["completed"]) for task in _task_rows(actions))


def _streak_days(completed_dates: set[date], today: date) -> int:
    cursor = today if today in completed_dates else today - timedelta(days=1)
    streak = 0
    while cursor in completed_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def build_daily_care_summary(
    interactions: Iterable[object],
    *,
    pet_id: str,
    now: datetime | None = None,
    timezone_offset_minutes: int = 0,
    cooldown_seconds: int = 5,
    daily_limit: int = 50,
) -> dict[str, object]:
    """Return customer-ready progress using the viewer's local calendar day."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    local_tz = _timezone(timezone_offset_minutes)
    local_now = current.astimezone(local_tz)
    today = local_now.date()

    by_date: dict[date, list[str]] = defaultdict(list)
    latest_by_action: dict[str, datetime] = {}
    for item in interactions:
        action = str(_value(item, "action") or _value(item, "action_type") or "").strip()
        created = _created_at(item)
        if action not in CARE_ACTION_LABELS or created is None:
            continue
        created_utc = created.astimezone(UTC)
        by_date[created_utc.astimezone(local_tz).date()].append(action)
        previous = latest_by_action.get(action)
        if previous is None or created_utc > previous:
            latest_by_action[action] = created_utc

    today_actions = by_date.get(today, [])
    tasks = _task_rows(today_actions)
    completed = all(bool(task["completed"]) for task in tasks)
    completed_dates = {day for day, actions in by_date.items() if _day_completed(actions)}
    streak = _streak_days(completed_dates, today)

    safe_limit = max(1, int(daily_limit))
    used_today = len(today_actions)
    limit_reached = used_today >= safe_limit
    safe_cooldown = max(0, int(cooldown_seconds))
    availability: list[dict[str, object]] = []
    for action in CARE_ACTIONS:
        remaining = 0
        latest = latest_by_action.get(action)
        if latest is not None and safe_cooldown:
            elapsed = max(0.0, (current - latest).total_seconds())
            remaining = max(0, math.ceil(safe_cooldown - elapsed))
        available = not limit_reached and remaining <= 0
        if limit_reached:
            reason = f"今天已完成 {safe_limit} 次照料，明天可以继续。"
        elif remaining > 0:
            reason = f"{CARE_ACTION_LABELS[action]}刚刚完成，{remaining} 秒后可再次操作。"
        else:
            reason = "现在可以操作。"
        availability.append(
            {
                "action": action,
                "label": CARE_ACTION_LABELS[action],
                "available": available,
                "remaining_seconds": remaining,
                "next_available_at": (
                    (current + timedelta(seconds=remaining)).isoformat()
                    if remaining > 0
                    else None
                ),
                "reason": reason,
            }
        )

    tomorrow = today + timedelta(days=1)
    task_day_ends = datetime.combine(tomorrow, time.min, tzinfo=local_tz).astimezone(UTC)
    completed_count = sum(bool(task["completed"]) for task in tasks)
    return {
        "pet_id": pet_id,
        "local_date": today.isoformat(),
        "timezone_offset_minutes": int(timezone_offset_minutes),
        "server_time": current.isoformat(),
        "task_day_ends_at": task_day_ends.isoformat(),
        "tasks": tasks,
        "completed_tasks": completed_count,
        "total_tasks": len(tasks),
        "all_tasks_completed": completed,
        "streak_days": streak,
        "reward_title": "今日陪伴徽章" if completed else "完成全部任务可获得今日陪伴徽章",
        "reward_detail": (
            f"今天的任务已完成，连续陪伴 {streak} 天。"
            if completed
            else f"还剩 {len(tasks) - completed_count} 项任务，今天结束前都可以完成。"
        ),
        "care_count": used_today,
        "daily_limit": safe_limit,
        "daily_remaining": max(0, safe_limit - used_today),
        "daily_limit_reached": limit_reached,
        "actions": availability,
    }
