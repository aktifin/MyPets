"""Account-level multi-pet status overview and rotation recommendation API."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .daily_care import build_daily_care_summary
from .models import Device, SyncEvent
from .multi_pet_overview import (
    build_pet_overview_item,
    next_rotation_pet_id,
    sort_overview_items,
)
from .pet_care_api import (
    CARE_COOLDOWN_SECONDS,
    DAILY_CARE_LIMIT,
    PetCareInteractionView,
    _interaction_from_event,
)
from .security import Principal
from .services import pets_for_account, relations_for_account
from .user_portal_models import AccountWebPreference

multi_pet_overview_router = APIRouter(prefix="/api/v1", tags=["customer-experience"])


class MultiPetOverviewItemView(BaseModel):
    pet_id: str
    name: str
    role: str
    presence: str
    growth_stage: str
    growth_level: int
    bond_level: int
    state_score: int
    priority: Literal["urgent", "attention", "routine", "stable", "unavailable"]
    status_summary: str
    recommendation_title: str
    recommendation_detail: str
    recommended_action: Literal["feed", "play", "clean", "pet", "rest"] | None
    recommended_action_label: str
    can_care: bool
    action_available: bool
    action_reason: str
    needs_attention: bool
    switch_candidate: bool
    current: bool
    daily_completed_tasks: int
    daily_total_tasks: int
    daily_all_completed: bool
    daily_remaining: int
    updated_at: datetime


class MultiPetOverviewView(BaseModel):
    current_pet_id: str | None
    next_pet_id: str | None
    total_count: int
    needs_attention_count: int
    urgent_count: int
    care_ready_count: int
    completed_today_count: int
    items: list[MultiPetOverviewItemView]


def _current_pet_id(
    session: Session,
    principal: Principal,
    available_ids: set[str],
    *,
    fallback_pet_id: str | None,
) -> str | None:
    selected: str | None = None
    if principal.kind == "device" and principal.device_id:
        device = session.get(Device, principal.device_id)
        selected = device.active_pet_id if device is not None else None
    else:
        preference = session.get(AccountWebPreference, principal.account_id)
        selected = preference.selected_pet_id if preference is not None else None
    if selected in available_ids:
        return selected
    return fallback_pet_id


def _interaction_history_by_pet(
    session: Session,
    *,
    account_id: str,
    now: datetime,
) -> dict[str, list[PetCareInteractionView]]:
    rows = session.scalars(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == account_id,
            SyncEvent.event_type == "pet_updated",
            SyncEvent.created_at >= now - timedelta(days=90),
        )
        .order_by(SyncEvent.sequence.desc())
        .limit(5000)
    )
    grouped: dict[str, list[PetCareInteractionView]] = defaultdict(list)
    for row in rows:
        interaction = _interaction_from_event(row)
        if interaction is None or interaction.actor_account_id != account_id:
            continue
        grouped[interaction.pet_id].append(interaction)
    return grouped


@multi_pet_overview_router.get(
    "/multi-pet-overview",
    response_model=MultiPetOverviewView,
)
def multi_pet_overview(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    timezone_offset_minutes: int = Query(default=0, ge=-840, le=840),
) -> MultiPetOverviewView:
    pets = pets_for_account(session, principal.account_id)
    relations = {
        relation.pet_id: relation
        for relation in relations_for_account(session, principal.account_id)
    }
    available_ids = {pet.id for pet in pets}
    current_pet_id = _current_pet_id(
        session,
        principal,
        available_ids,
        fallback_pet_id=pets[0].id if pets else None,
    )
    now = datetime.now(UTC)
    history_by_pet = _interaction_history_by_pet(
        session,
        account_id=principal.account_id,
        now=now,
    )

    items: list[dict[str, object]] = []
    for pet in pets:
        relation = relations.get(pet.id)
        if relation is None:
            continue
        daily = build_daily_care_summary(
            history_by_pet.get(pet.id, []),
            pet_id=pet.id,
            now=now,
            timezone_offset_minutes=timezone_offset_minutes,
            cooldown_seconds=CARE_COOLDOWN_SECONDS,
            daily_limit=DAILY_CARE_LIMIT,
        )
        items.append(
            build_pet_overview_item(
                pet=pet,
                role=relation.role,
                daily_summary=daily,
                current=pet.id == current_pet_id,
            )
        )

    ordered = sort_overview_items(items)
    next_pet_id = next_rotation_pet_id(ordered, current_pet_id=current_pet_id)
    return MultiPetOverviewView(
        current_pet_id=current_pet_id,
        next_pet_id=next_pet_id,
        total_count=len(ordered),
        needs_attention_count=sum(bool(item["needs_attention"]) for item in ordered),
        urgent_count=sum(item["priority"] == "urgent" for item in ordered),
        care_ready_count=sum(bool(item["switch_candidate"]) for item in ordered),
        completed_today_count=sum(bool(item["daily_all_completed"]) for item in ordered),
        items=[MultiPetOverviewItemView.model_validate(item) for item in ordered],
    )
