"""Validated desktop reminder contracts shared by sync, cache, and scheduling."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .domain import ReminderOccurrence, ReminderOccurrenceState


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    return value


def _string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是字符串")
    value = value.strip()
    if not allow_empty and not value:
        raise ValueError(f"{field} 不能为空")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} 必须是整数")
    if value < minimum:
        raise ValueError(f"{field} 不能小于 {minimum}")
    return value


def _timestamp(value: Any, field: str) -> datetime:
    raw = _string(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 不是有效 ISO 8601 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")
    return parsed


def parse_reminder_occurrence(
    value: Any,
    *,
    account_id: str | None = None,
) -> ReminderOccurrence:
    data = _mapping(value, "reminder occurrence")
    parsed_account_id = _string(data.get("account_id"), "account_id")
    if account_id is not None and parsed_account_id != account_id:
        raise ValueError("提醒实例不属于当前账户")
    try:
        state = ReminderOccurrenceState(_string(data.get("state"), "state"))
    except ValueError as exc:
        raise ValueError(f"提醒状态无效：{exc}") from exc
    occurrence = ReminderOccurrence(
        occurrence_id=_string(data.get("occurrence_id"), "occurrence_id"),
        source=_string(data.get("source"), "source"),
        source_reminder_id=_string(
            data.get("source_reminder_id"), "source_reminder_id"
        ),
        account_id=parsed_account_id,
        title=_string(data.get("title"), "title"),
        content=_string(data.get("content", ""), "content", allow_empty=True),
        scheduled_at=_timestamp(data.get("scheduled_at"), "scheduled_at"),
        timezone=_string(data.get("timezone"), "timezone"),
        state=state,
        priority=_string(data.get("priority", "normal"), "priority"),
        category=_string(data.get("category", "general"), "category"),
        version=_integer(data.get("version", 1), "version", minimum=1),
    )
    return occurrence
