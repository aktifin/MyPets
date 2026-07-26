"""Shared helpers for immutable copyright-rights history and validity checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from .governance_models import PetAssetRight, PetAssetRightHistory
from .security import Principal


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def validity_state(right: PetAssetRight, now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    valid_from = aware(right.valid_from)
    valid_until = aware(right.valid_until)
    if valid_from is not None and current < valid_from:
        return "scheduled"
    if valid_until is not None and current >= valid_until:
        return "expired"
    return "active"


def require_validity_window(
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    start = aware(valid_from)
    end = aware(valid_until)
    if start is not None and end is not None and end <= start:
        raise ValueError("授权有效期结束时间必须晚于开始时间")
    return start, end


def record_right_history(
    session: Session,
    *,
    right: PetAssetRight,
    principal: Principal,
    event_type: str,
    comment: str = "",
    details: dict[str, Any] | None = None,
) -> PetAssetRightHistory:
    item = PetAssetRightHistory(
        id=str(uuid4()),
        right_id=right.id,
        event_type=event_type,
        status_snapshot=right.status,
        actor_account_id=principal.account_id,
        comment=comment.strip(),
        details_json=json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
    )
    session.add(item)
    return item
