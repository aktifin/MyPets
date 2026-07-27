"""Pure customer-facing multi-pet prioritization rules.

The overview deliberately ranks genuine state concerns before optional daily-task
progress. It never bypasses relationship, presence, cooldown, or daily-limit gates.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CARE_ROLES = {"owner", "co_owner", "caregiver"}

_ACTION_LABELS = {
    "feed": "投喂",
    "play": "玩耍",
    "clean": "清洁",
    "pet": "摸摸",
    "rest": "休息",
}

_PRIORITY_ORDER = {
    "urgent": 0,
    "attention": 1,
    "routine": 2,
    "stable": 3,
    "unavailable": 4,
}


def _value(item: object, field: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _daily_action(summary: Mapping[str, object], action: str | None) -> Mapping[str, object] | None:
    if not action:
        return None
    actions = summary.get("actions")
    for raw in actions if isinstance(actions, list) else []:
        if isinstance(raw, Mapping) and raw.get("action") == action:
            return raw
    return None


def _state_choice(pet: object) -> tuple[int, str | None, str, str]:
    values = [
        (
            int(_value(pet, "health", 100)),
            None,
            "健康状态需要留意",
            "先查看完整状态，再决定是否继续互动。",
        ),
        (
            int(_value(pet, "hunger", 100)),
            "feed",
            "有点饿了",
            "投喂一次可以补充当前饱食状态。",
        ),
        (
            int(_value(pet, "energy", 100)),
            "rest",
            "需要休息",
            "让它休息一会儿，再继续其他互动。",
        ),
        (
            int(_value(pet, "cleanliness", 100)),
            "clean",
            "需要清洁",
            "清洁一次，让它保持舒适。",
        ),
        (
            int(_value(pet, "mood", 100)),
            "play",
            "心情有点低",
            "陪它玩一会儿，增加轻松互动。",
        ),
        (
            100 - int(_value(pet, "boredom", 0)),
            "play",
            "有点无聊",
            "陪它玩一会儿，换个轻松的状态。",
        ),
    ]
    return min(values, key=lambda row: row[0])


def build_pet_overview_item(
    *,
    pet: object,
    role: str,
    daily_summary: Mapping[str, object],
    current: bool,
) -> dict[str, object]:
    pet_id = str(_value(pet, "id", _value(pet, "pet_id", "")))
    name = str(_value(pet, "name", "宠物"))
    presence = str(_value(pet, "presence", "home"))
    state_score, state_action, state_title, state_detail = _state_choice(pet)
    can_care = role in CARE_ROLES and presence in {"home", "resting"}

    completed = int(daily_summary.get("completed_tasks") or 0)
    total = max(1, int(daily_summary.get("total_tasks") or 3))
    all_completed = bool(daily_summary.get("all_tasks_completed"))

    recommended_action: str | None = state_action
    recommendation_title = state_title
    recommendation_detail = state_detail
    if state_score >= 65:
        recommended_action = None if all_completed else "pet"
        if all_completed:
            recommendation_title = "状态稳定"
            recommendation_detail = "今天的基础照料和陪伴任务已经完成。"
        else:
            recommendation_title = "继续今天的陪伴"
            recommendation_detail = f"今日任务已完成 {completed}/{total}，可以用一次轻松互动继续。"

    if presence not in {"home", "resting"}:
        priority = "unavailable"
        recommendation_title = "正在串门"
        recommendation_detail = "返家后才能继续照料，现在可查看串门进度。"
        recommended_action = None
    elif role not in CARE_ROLES:
        priority = "unavailable"
        recommendation_title = "当前为只读关系"
        recommendation_detail = "可以查看状态，但不能代替主人执行照料。"
        recommended_action = None
    elif state_score < 35:
        priority = "urgent"
    elif state_score < 65:
        priority = "attention"
    elif not all_completed:
        priority = "routine"
    else:
        priority = "stable"

    action_state = _daily_action(daily_summary, recommended_action)
    action_available = bool(
        can_care
        and recommended_action
        and (
            bool(action_state.get("available", False))
            if action_state is not None
            else True
        )
    )
    action_reason = ""
    if action_state is not None:
        action_reason = str(action_state.get("reason") or "")
    if not can_care:
        action_reason = recommendation_detail
    elif recommended_action is None:
        action_reason = "切换后可查看完整状态，不会自动执行照料。"

    needs_attention = priority in {"urgent", "attention", "routine"}
    switch_candidate = bool(
        needs_attention
        and can_care
        and (action_available or recommended_action is None)
    )
    status_summary = recommendation_title
    if priority == "stable":
        status_summary = "状态良好，今日任务已完成"
    elif priority == "routine":
        status_summary = f"状态良好，今日任务 {completed}/{total}"

    return {
        "pet_id": pet_id,
        "name": name,
        "role": role,
        "presence": presence,
        "growth_stage": str(_value(pet, "growth_stage", "newborn")),
        "growth_level": int(_value(pet, "growth_level", 1)),
        "bond_level": int(_value(pet, "bond_level", 1)),
        "state_score": max(0, min(100, state_score)),
        "priority": priority,
        "status_summary": status_summary,
        "recommendation_title": recommendation_title,
        "recommendation_detail": recommendation_detail,
        "recommended_action": recommended_action,
        "recommended_action_label": _ACTION_LABELS.get(recommended_action or "", "查看状态"),
        "can_care": can_care,
        "action_available": action_available,
        "action_reason": action_reason,
        "needs_attention": needs_attention,
        "switch_candidate": switch_candidate,
        "current": bool(current),
        "daily_completed_tasks": completed,
        "daily_total_tasks": total,
        "daily_all_completed": all_completed,
        "daily_remaining": max(0, int(daily_summary.get("daily_remaining") or 0)),
        "updated_at": _value(pet, "updated_at"),
    }


def sort_overview_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        items,
        key=lambda item: (
            _PRIORITY_ORDER.get(str(item.get("priority")), 99),
            int(item.get("state_score") or 100),
            -int(item.get("daily_total_tasks") or 0) + int(item.get("daily_completed_tasks") or 0),
            str(item.get("name") or "").casefold(),
            str(item.get("pet_id") or ""),
        ),
    )


def next_rotation_pet_id(
    items: list[dict[str, object]],
    *,
    current_pet_id: str | None,
) -> str | None:
    candidates = [
        str(item.get("pet_id"))
        for item in items
        if bool(item.get("switch_candidate")) and item.get("pet_id")
    ]
    if not candidates:
        return None
    for pet_id in candidates:
        if pet_id != current_pet_id:
            return pet_id
    return None
