"""Pure desktop helpers for local and merged multi-pet overview rows."""

from __future__ import annotations

from collections.abc import Mapping

from .desktop_experience import CARE_ACTION_LABELS, recommend_care
from .domain import PetProfile, PresenceStatus

_PRIORITY_ORDER = {
    "urgent": 0,
    "attention": 1,
    "routine": 2,
    "stable": 3,
    "unavailable": 4,
}


def _action_state(
    daily_summary: Mapping[str, object],
    action: str | None,
) -> tuple[bool, str]:
    if not action:
        return False, "当前无需直接照料操作。"
    actions = daily_summary.get("actions")
    for raw in actions if isinstance(actions, list) else []:
        if isinstance(raw, Mapping) and raw.get("action") == action:
            return bool(raw.get("available", False)), str(raw.get("reason") or "")
    return True, "现在可以操作。"


def _state_score(pet: PetProfile) -> int:
    stats = pet.stats
    return min(
        int(stats.health),
        int(stats.hunger),
        int(stats.energy),
        int(stats.cleanliness),
        int(stats.mood),
        100 - int(stats.boredom),
    )


def build_local_overview_item(
    pet: PetProfile,
    daily_summary: Mapping[str, object],
    *,
    current: bool,
) -> dict[str, object]:
    score = _state_score(pet)
    completed = int(daily_summary.get("completed_tasks") or 0)
    total = max(1, int(daily_summary.get("total_tasks") or 3))
    all_completed = bool(daily_summary.get("all_tasks_completed"))
    at_home = pet.presence is PresenceStatus.HOME
    recommendation = recommend_care(pet)

    if not at_home:
        priority = "unavailable"
        action = None
        title = "正在串门"
        detail = "返家后才能继续照料，现在可查看串门进度。"
    elif score < 35:
        priority = "urgent"
        action = recommendation.action
        title = recommendation.title
        detail = recommendation.detail
    elif score < 65:
        priority = "attention"
        action = recommendation.action
        title = recommendation.title
        detail = recommendation.detail
    elif not all_completed:
        priority = "routine"
        action = recommendation.action or "pet"
        title = "继续今天的陪伴"
        detail = f"今日任务已完成 {completed}/{total}，可以用一次轻松互动继续。"
    else:
        priority = "stable"
        action = None
        title = "状态稳定"
        detail = "今天的基础照料和陪伴任务已经完成。"

    available, reason = _action_state(daily_summary, action)
    available = at_home and bool(action) and available
    needs_attention = priority in {"urgent", "attention", "routine"}
    return {
        "pet_id": pet.identity.pet_id,
        "name": pet.identity.name,
        "role": "owner",
        "presence": pet.presence.value,
        "growth_stage": pet.stats.growth_stage.value,
        "growth_level": int(pet.stats.growth_level),
        "bond_level": int(pet.stats.bond_level),
        "state_score": max(0, min(100, score)),
        "priority": priority,
        "status_summary": (
            "状态良好，今日任务已完成"
            if priority == "stable"
            else f"状态良好，今日任务 {completed}/{total}"
            if priority == "routine"
            else title
        ),
        "recommendation_title": title,
        "recommendation_detail": detail,
        "recommended_action": action,
        "recommended_action_label": CARE_ACTION_LABELS.get(action or "", "查看状态"),
        "can_care": at_home,
        "action_available": available,
        "action_reason": reason if at_home else detail,
        "needs_attention": needs_attention,
        "switch_candidate": needs_attention and available,
        "current": bool(current),
        "daily_completed_tasks": completed,
        "daily_total_tasks": total,
        "daily_all_completed": all_completed,
        "daily_remaining": max(0, int(daily_summary.get("daily_remaining") or 0)),
        "updated_at": pet.updated_at.isoformat() if pet.updated_at else "",
        "source": "local",
    }


def merge_overview_items(
    local_items: list[dict[str, object]],
    cloud_items: list[dict[str, object]],
    *,
    current_pet_id: str | None,
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for raw in [*cloud_items, *local_items]:
        pet_id = str(raw.get("pet_id") or "")
        if not pet_id:
            continue
        item = dict(raw)
        item["current"] = pet_id == current_pet_id
        merged[pet_id] = item
    return sorted(
        merged.values(),
        key=lambda item: (
            _PRIORITY_ORDER.get(str(item.get("priority")), 99),
            int(item.get("state_score") or 100),
            int(item.get("daily_completed_tasks") or 0)
            - int(item.get("daily_total_tasks") or 0),
            str(item.get("name") or "").casefold(),
            str(item.get("pet_id") or ""),
        ),
    )


def next_rotation_pet_id(
    items: list[dict[str, object]],
    *,
    current_pet_id: str | None,
) -> str | None:
    for item in items:
        pet_id = str(item.get("pet_id") or "")
        if pet_id and pet_id != current_pet_id and bool(item.get("switch_candidate")):
            return pet_id
    return None
