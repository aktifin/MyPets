"""Pure local proactive care rules for bundled desktop pets."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Iterable, Mapping

from .domain import PetProfile, PresenceStatus


def _parse_clock(value: str, fallback: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, ValueError):
        hour_text, minute_text = fallback.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    return time(max(0, min(23, hour)), max(0, min(59, minute)))


def is_quiet_time(now: datetime, start: str, end: str) -> bool:
    current = now.astimezone().time().replace(tzinfo=None)
    start_value = _parse_clock(start, "22:00")
    end_value = _parse_clock(end, "08:00")
    if start_value == end_value:
        return True
    if start_value < end_value:
        return start_value <= current < end_value
    return current >= start_value or current < end_value


def _latest_interaction(
    records: Iterable[Mapping[str, str]],
    *,
    now: datetime,
) -> datetime | None:
    latest: datetime | None = None
    for record in records:
        if str(record.get("action_type") or "") not in {"feed", "play", "clean", "pet", "rest"}:
            continue
        try:
            created = datetime.fromisoformat(str(record.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=now.tzinfo)
        created = created.astimezone(now.tzinfo)
        if latest is None or created > latest:
            latest = created
    return latest


def _pet_baseline(pet: PetProfile, now: datetime) -> datetime:
    cached = pet.updated_at
    if cached is None:
        return now
    if cached.tzinfo is None:
        cached = cached.replace(tzinfo=now.tzinfo)
    return cached.astimezone(now.tzinfo)


def build_local_proactive_notice(
    pet: PetProfile,
    records: Iterable[Mapping[str, str]],
    *,
    now: datetime | None = None,
    low_state_enabled: bool = True,
    inactivity_enabled: bool = True,
) -> dict[str, object] | None:
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    if pet.presence is not PresenceStatus.HOME:
        return None

    if low_state_enabled:
        stats = pet.stats
        checks = [
            (int(stats.health), 70, "health", None, "状态需要留意", "打开状态页看看最近变化。", "查看状态"),
            (int(stats.energy), 35, "energy", "rest", "有点累了", "让它休息一会儿，会更适合继续互动。", "去休息"),
            (int(stats.hunger), 45, "hunger", "feed", "有点饿了", "现在投喂一次，补充今天的照料。", "去投喂"),
            (int(stats.cleanliness), 45, "cleanliness", "clean", "需要整理一下", "清洁一次，让它保持舒适。", "去清洁"),
            (int(stats.mood), 45, "mood", "play", "心情有点低", "陪它玩一会儿，增加今天的互动。", "去陪伴"),
            (100 - int(stats.boredom), 35, "boredom", "play", "有点无聊", "陪它玩一会儿，换个轻松的状态。", "去陪伴"),
        ]
        candidates = [
            (threshold - score, state, action, title, detail, label)
            for score, threshold, state, action, title, detail, label in checks
            if score < threshold
        ]
        if candidates:
            _severity, state, action, title, detail, label = max(candidates, key=lambda item: item[0])
            return {
                "notice_key": f"pet:{pet.identity.pet_id}:low:{state}",
                "kind": "low_state",
                "pet_id": pet.identity.pet_id,
                "title": f"{pet.identity.name}{title}",
                "detail": detail,
                "action_label": label,
                "care_action": action,
                "target_section": "stats" if action is None else "dashboard",
            }

    if inactivity_enabled:
        latest = _latest_interaction(records, now=current)
        baseline = latest or _pet_baseline(pet, current)
        if current - baseline >= timedelta(hours=12):
            return {
                "notice_key": f"pet:{pet.identity.pet_id}:inactive",
                "kind": "inactivity",
                "pet_id": pet.identity.pet_id,
                "title": f"{pet.identity.name} 等你一会儿了",
                "detail": "今天还没有新的陪伴记录，摸摸或玩耍一次就好。",
                "action_label": "去陪伴",
                "care_action": "pet",
                "target_section": "dashboard",
            }
    return None
