"""Customer-facing daily care progress and action availability API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .daily_care import build_daily_care_summary
from .models import SyncEvent
from .pet_care_api import (
    CARE_COOLDOWN_SECONDS,
    DAILY_CARE_LIMIT,
    PetCareInteractionView,
    _interaction_from_event,
    _relation_for_actor,
)
from .security import Principal


daily_care_router = APIRouter(prefix="/api/v1", tags=["pet-care"])


class DailyCareTaskView(BaseModel):
    task_id: str
    title: str
    detail: str
    current: int
    target: int
    completed: bool


class CareActionAvailabilityView(BaseModel):
    action: Literal["feed", "play", "clean", "pet", "rest"]
    label: str
    available: bool
    remaining_seconds: int
    next_available_at: datetime | None
    reason: str


class DailyCareSummaryView(BaseModel):
    pet_id: str
    local_date: str
    timezone_offset_minutes: int
    server_time: datetime
    task_day_ends_at: datetime
    tasks: list[DailyCareTaskView]
    completed_tasks: int
    total_tasks: int
    all_tasks_completed: bool
    streak_days: int
    reward_title: str
    reward_detail: str
    care_count: int
    daily_limit: int
    daily_remaining: int
    daily_limit_reached: bool
    actions: list[CareActionAvailabilityView]


def _care_history(
    session: Session,
    *,
    account_id: str,
    pet_id: str,
    now: datetime,
    days: int = 90,
) -> list[PetCareInteractionView]:
    rows = session.scalars(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == account_id,
            SyncEvent.event_type == "pet_updated",
            SyncEvent.created_at >= now - timedelta(days=max(7, min(370, days))),
        )
        .order_by(SyncEvent.sequence.desc())
        .limit(5000)
    )
    interactions: list[PetCareInteractionView] = []
    for row in rows:
        interaction = _interaction_from_event(row)
        if (
            interaction is not None
            and interaction.pet_id == pet_id
            and interaction.actor_account_id == account_id
        ):
            interactions.append(interaction)
    return interactions


@daily_care_router.get(
    "/pets/{pet_id}/daily-care",
    response_model=DailyCareSummaryView,
)
def pet_daily_care(
    pet_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> DailyCareSummaryView:
    _relation_for_actor(
        session,
        account_id=principal.account_id,
        pet_id=pet_id,
        require_care=False,
    )
    now = datetime.now(UTC)
    interactions = _care_history(
        session,
        account_id=principal.account_id,
        pet_id=pet_id,
        now=now,
    )
    return DailyCareSummaryView.model_validate(
        build_daily_care_summary(
            interactions,
            pet_id=pet_id,
            now=now,
            timezone_offset_minutes=timezone_offset_minutes,
            cooldown_seconds=CARE_COOLDOWN_SECONDS,
            daily_limit=DAILY_CARE_LIMIT,
        )
    )
