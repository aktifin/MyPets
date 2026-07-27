"""Pure customer-facing proactive care rules.

The rules deliberately avoid medical or alarmist language. They select at most one
high-value notice per pet, add due reminders, aggregate multiple pet notices into one
summary, respect local quiet hours, and leave persistence/rate limiting to the API layer.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Iterable, Mapping


DEFAULT_PREFERENCES: dict[str, object] = {
    "enabled": True,
    "low_state_enabled": True,
    "inactivity_enabled": True,
    "reminder_enabled": True,
    "quiet_hours_enabled": True,
    "quiet_start": "22:00",
    "quiet_end": "08:00",
    "min_interval_minutes": 120,
    "max_daily_notices": 3,
}

CARE_ROLES = {"owner", "co_owner", "caregiver"}
PENDING_REMINDER_STATES = {"pending", "delivered", "seen", "snoozed"}
_PET_NOTICE_KINDS = {"low_state", "inactivity"}


def _value(item: object, field: str, default: object = None) -> object:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _timezone(offset_minutes: int) -> timezone:
    # JavaScript Date.getTimezoneOffset() is UTC - local time.
    normalized = max(-840, min(840, int(offset_minutes)))
    return timezone(timedelta(minutes=-normalized))


def _parse_clock(value: str, fallback: str) -> time:
    raw = (value or fallback).strip()
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError):
        hour_text, minute_text = fallback.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    return time(hour=max(0, min(23, hour)), minute=max(0, min(59, minute)))


def in_quiet_hours(
    *,
    now: datetime,
    timezone_offset_minutes: int,
    quiet_start: str,
    quiet_end: str,
) -> bool:
    local = _aware(now).astimezone(_timezone(timezone_offset_minutes))
    current = local.time().replace(tzinfo=None)
    start = _parse_clock(quiet_start, "22:00")
    end = _parse_clock(quiet_end, "08:00")
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def next_quiet_end(
    *,
    now: datetime,
    timezone_offset_minutes: int,
    quiet_start: str,
    quiet_end: str,
) -> datetime:
    tz = _timezone(timezone_offset_minutes)
    local = _aware(now).astimezone(tz)
    end = _parse_clock(quiet_end, "08:00")
    candidate = datetime.combine(local.date(), end, tzinfo=tz)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def normalize_preferences(raw: Mapping[str, object] | None) -> dict[str, object]:
    source = dict(DEFAULT_PREFERENCES)
    if raw:
        source.update(raw)
    source["enabled"] = bool(source.get("enabled", True))
    source["low_state_enabled"] = bool(source.get("low_state_enabled", True))
    source["inactivity_enabled"] = bool(source.get("inactivity_enabled", True))
    source["reminder_enabled"] = bool(source.get("reminder_enabled", True))
    source["quiet_hours_enabled"] = bool(source.get("quiet_hours_enabled", True))
    source["quiet_start"] = _parse_clock(
        str(source.get("quiet_start", "22:00")), "22:00"
    ).strftime("%H:%M")
    source["quiet_end"] = _parse_clock(
        str(source.get("quiet_end", "08:00")), "08:00"
    ).strftime("%H:%M")
    source["min_interval_minutes"] = max(
        15, min(1440, int(source.get("min_interval_minutes", 120)))
    )
    source["max_daily_notices"] = max(
        1, min(12, int(source.get("max_daily_notices", 3)))
    )
    return source


def _low_state_candidate(pet: object) -> dict[str, object] | None:
    name = str(_value(pet, "name", "宠物"))
    pet_id = str(_value(pet, "id", _value(pet, "pet_id", "")))
    values = [
        (
            int(_value(pet, "health", 100)),
            "health",
            70,
            None,
            "状态需要留意",
            "打开状态页看看最近变化。",
        ),
        (
            int(_value(pet, "energy", 100)),
            "energy",
            35,
            "rest",
            "有点累了",
            "让它休息一会儿，会更适合继续互动。",
        ),
        (
            int(_value(pet, "hunger", 100)),
            "hunger",
            45,
            "feed",
            "有点饿了",
            "现在投喂一次，补充今天的照料。",
        ),
        (
            int(_value(pet, "cleanliness", 100)),
            "cleanliness",
            45,
            "clean",
            "需要整理一下",
            "清洁一次，让它保持舒适。",
        ),
        (
            int(_value(pet, "mood", 100)),
            "mood",
            45,
            "play",
            "心情有点低",
            "陪它玩一会儿，增加今天的互动。",
        ),
        (
            100 - int(_value(pet, "boredom", 0)),
            "boredom",
            35,
            "play",
            "有点无聊",
            "陪它玩一会儿，换个轻松的状态。",
        ),
    ]
    candidates: list[tuple[int, dict[str, object]]] = []
    for score, state, threshold, action, title, detail in values:
        if score >= threshold:
            continue
        severity = threshold - score
        candidates.append(
            (
                severity,
                {
                    "notice_key": f"pet:{pet_id}:low:{state}",
                    "kind": "low_state",
                    "priority": 300 + severity,
                    "pet_id": pet_id,
                    "title": f"{name}{title}",
                    "detail": detail,
                    "action_label": "查看状态"
                    if action is None
                    else {
                        "feed": "去投喂",
                        "play": "去陪伴",
                        "clean": "去清洁",
                        "rest": "去休息",
                    }[action],
                    "care_action": action,
                    "target_section": "pets-section"
                    if action is None
                    else "dashboard-section",
                },
            )
        )
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def aggregate_multi_pet_candidates(
    candidates: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Collapse multiple per-pet prompts into one stable, actionable summary.

    Only the highest-priority prompt for each pet participates. Due reminders stay
    separate so a time-sensitive reminder is not hidden inside a pet status summary.
    """

    values = [dict(item) for item in candidates]
    best_by_pet: dict[str, dict[str, object]] = {}
    others: list[dict[str, object]] = []
    for item in values:
        pet_id = str(item.get("pet_id") or "")
        if not pet_id or str(item.get("kind")) not in _PET_NOTICE_KINDS:
            others.append(item)
            continue
        previous = best_by_pet.get(pet_id)
        if previous is None or int(item.get("priority") or 0) > int(
            previous.get("priority") or 0
        ):
            best_by_pet[pet_id] = item

    pet_items = sorted(
        best_by_pet.values(),
        key=lambda item: (-int(item.get("priority") or 0), str(item.get("notice_key") or "")),
    )
    if len(pet_items) < 2:
        return sorted(
            [*others, *pet_items],
            key=lambda item: (-int(item.get("priority") or 0), str(item.get("notice_key") or "")),
        )

    keys = sorted(str(item.get("notice_key") or "") for item in pet_items)
    digest = hashlib.sha256("|".join(keys).encode("utf-8")).hexdigest()[:16]
    detail_parts = [str(item.get("title") or "宠物需要关注") for item in pet_items[:4]]
    if len(pet_items) > 4:
        detail_parts.append(f"另有 {len(pet_items) - 4} 只宠物")
    summary = {
        "notice_key": f"multi-pet:{digest}",
        "kind": "multi_pet_summary",
        "priority": max(int(item.get("priority") or 0) for item in pet_items)
        + min(40, len(pet_items) * 5),
        "pet_id": None,
        "pet_ids": [str(item.get("pet_id") or "") for item in pet_items],
        "item_count": len(pet_items),
        "items": [
            {
                "notice_key": str(item.get("notice_key") or ""),
                "kind": str(item.get("kind") or "low_state"),
                "pet_id": str(item.get("pet_id") or ""),
                "title": str(item.get("title") or "宠物需要关注"),
                "detail": str(item.get("detail") or "有空时看看它就好。"),
                "care_action": item.get("care_action"),
            }
            for item in pet_items
        ],
        "title": f"{len(pet_items)} 只宠物需要你留意",
        "detail": "；".join(detail_parts),
        "action_label": "查看多宠总览",
        "care_action": None,
        "target_section": "dashboard-section",
    }
    return sorted(
        [*others, summary],
        key=lambda item: (-int(item.get("priority") or 0), str(item.get("notice_key") or "")),
    )


def build_proactive_candidates(
    *,
    pets: Iterable[object],
    relations: Mapping[str, object],
    last_interactions: Mapping[str, datetime | None],
    reminders: Iterable[object],
    preferences: Mapping[str, object] | None,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    current = _aware(now or datetime.now(UTC)).astimezone(UTC)
    prefs = normalize_preferences(preferences)
    candidates: list[dict[str, object]] = []

    for pet in pets:
        pet_id = str(_value(pet, "id", _value(pet, "pet_id", "")))
        relation = relations.get(pet_id)
        role = str(_value(relation, "role", "viewer"))
        presence = str(_value(pet, "presence", "home"))
        if role not in CARE_ROLES or presence not in {"home", "resting"}:
            continue

        if bool(prefs["low_state_enabled"]):
            candidate = _low_state_candidate(pet)
            if candidate is not None:
                candidates.append(candidate)

        if bool(prefs["inactivity_enabled"]):
            last = last_interactions.get(pet_id)
            baseline = (
                _aware(last)
                if last is not None
                else _aware(_value(pet, "created_at", current))
            )
            idle_hours = (current - baseline.astimezone(UTC)).total_seconds() / 3600
            if idle_hours >= 12:
                name = str(_value(pet, "name", "宠物"))
                candidates.append(
                    {
                        "notice_key": f"pet:{pet_id}:inactive",
                        "kind": "inactivity",
                        "priority": 180 + min(72, int(idle_hours)),
                        "pet_id": pet_id,
                        "title": f"{name} 等你一会儿了",
                        "detail": "今天还没有新的陪伴记录，摸摸或玩耍一次就好。",
                        "action_label": "去陪伴",
                        "care_action": "pet",
                        "target_section": "dashboard-section",
                    }
                )

    if bool(prefs["reminder_enabled"]):
        for reminder in reminders:
            state = str(_value(reminder, "state", "pending"))
            scheduled = _value(reminder, "scheduled_at")
            if state not in PENDING_REMINDER_STATES or not isinstance(
                scheduled, datetime
            ):
                continue
            scheduled_aware = _aware(scheduled).astimezone(UTC)
            if scheduled_aware > current:
                continue
            reminder_id = str(_value(reminder, "id", ""))
            title = str(_value(reminder, "title", "养宠提醒"))
            overdue_minutes = max(
                0, int((current - scheduled_aware).total_seconds() // 60)
            )
            candidates.append(
                {
                    "notice_key": f"reminder:{reminder_id}:due",
                    "kind": "reminder_due",
                    "priority": 240 + min(120, overdue_minutes // 5),
                    "pet_id": None,
                    "title": title,
                    "detail": "这条提醒已经到时间，可以现在处理或稍后再看。",
                    "action_label": "查看提醒",
                    "care_action": None,
                    "target_section": "reminders-section",
                }
            )

    return aggregate_multi_pet_candidates(candidates)
