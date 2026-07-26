"""Customer-facing growth goal and milestone timeline API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .growth_experience import build_growth_progress, stage_label
from .models import AccountPetRelation, Pet, SyncEvent
from .pet_state_service import settle_pet_and_publish
from .schemas import PetView
from .security import Principal
from .services import pet_view


growth_experience_router = APIRouter(prefix="/api/v1", tags=["pet-growth"])
_GROWTH_EVENT_TYPES = {"growth_level_up", "bond_level_up", "growth_stage_changed"}


class GrowthProgressView(BaseModel):
    current_stage: str
    current_stage_label: str
    current_stage_detail: str
    growth_level: int
    growth_exp: int
    growth_level_current: int
    growth_level_target: int
    growth_exp_remaining: int
    growth_level_percent: int
    bond_level: int
    bond_exp: int
    bond_level_current: int
    bond_level_target: int
    bond_exp_remaining: int
    bond_level_percent: int
    next_stage: str | None
    next_stage_label: str | None
    next_stage_target_level: int | None
    next_stage_exp_remaining: int
    stage_progress_percent: int
    headline: str
    detail: str
    suggested_action: str
    suggested_action_label: str
    estimated_actions: int
    final_stage: bool


class GrowthMemoryView(BaseModel):
    memory_id: str
    memory_type: Literal["adoption", "growth_level", "bond_level", "growth_stage"]
    icon: str
    title: str
    detail: str
    occurred_at: datetime
    source_label: str
    previous_value: str | None = None
    current_value: str | None = None


class GrowthExperienceResponse(BaseModel):
    pet: PetView
    progress: GrowthProgressView
    memories: list[GrowthMemoryView]
    settled_at: datetime


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _payload(event: SyncEvent) -> dict[str, object]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _transition_memory(event: SyncEvent, pet_name: str) -> GrowthMemoryView | None:
    payload = _payload(event)
    transition = payload.get("transition")
    if not isinstance(transition, dict):
        return None
    previous = str(transition.get("previous_value") or "")
    current = str(transition.get("current_value") or "")
    source = str(transition.get("source") or "pet_care")
    source_label = "日常照料" if source == "pet_care" else "成长结算"
    if event.event_type == "growth_level_up":
        return GrowthMemoryView(
            memory_id=event.event_id,
            memory_type="growth_level",
            icon="⭐",
            title=f"{pet_name} 升到成长 Lv.{current}",
            detail=f"从 Lv.{previous} 成长到 Lv.{current}，新的等级目标已经开启。",
            occurred_at=_aware(event.created_at),
            source_label=source_label,
            previous_value=previous,
            current_value=current,
        )
    if event.event_type == "bond_level_up":
        return GrowthMemoryView(
            memory_id=event.event_id,
            memory_type="bond_level",
            icon="🤝",
            title=f"羁绊提升到 Lv.{current}",
            detail=f"共同照料让羁绊从 Lv.{previous} 提升到 Lv.{current}。",
            occurred_at=_aware(event.created_at),
            source_label=source_label,
            previous_value=previous,
            current_value=current,
        )
    if event.event_type == "growth_stage_changed":
        previous_label = stage_label(previous)
        current_label = stage_label(current)
        return GrowthMemoryView(
            memory_id=event.event_id,
            memory_type="growth_stage",
            icon="🌱",
            title=f"进入{current_label}",
            detail=f"{pet_name} 从{previous_label}成长为{current_label}，这是值得记住的一天。",
            occurred_at=_aware(event.created_at),
            source_label=source_label,
            previous_value=previous,
            current_value=current,
        )
    return None


@growth_experience_router.get(
    "/pets/{pet_id}/growth-experience",
    response_model=GrowthExperienceResponse,
)
def get_growth_experience(
    pet_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=30, ge=1, le=100),
) -> GrowthExperienceResponse:
    relation = session.get(AccountPetRelation, (principal.account_id, pet_id))
    if relation is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    pet = session.get(Pet, pet_id)
    if pet is None:
        raise HTTPException(status_code=404, detail="宠物不存在")

    settle_pet_and_publish(session, pet, now=datetime.now(UTC), trigger="growth_experience")
    session.commit()

    rows = session.scalars(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == principal.account_id,
            SyncEvent.event_type.in_(_GROWTH_EVENT_TYPES),
        )
        .order_by(SyncEvent.sequence.desc())
        .limit(max(limit * 4, 100))
    )
    memories: list[GrowthMemoryView] = []
    for row in rows:
        payload = _payload(row)
        if payload.get("pet_id") != pet.id:
            continue
        memory = _transition_memory(row, pet.name)
        if memory is not None:
            memories.append(memory)
        if len(memories) >= max(0, limit - 1):
            break

    adoption = GrowthMemoryView(
        memory_id=f"adoption:{pet.id}",
        memory_type="adoption",
        icon="🏠",
        title=f"{pet.name} 成为家人",
        detail="从这一天开始，成长、照料和陪伴记录都会保存在这里。",
        occurred_at=_aware(pet.created_at),
        source_label="领养记录",
    )
    memories.append(adoption)
    memories.sort(key=lambda item: item.occurred_at, reverse=True)
    memories = memories[:limit]

    return GrowthExperienceResponse(
        pet=pet_view(pet),
        progress=GrowthProgressView.model_validate(build_growth_progress(pet).as_dict()),
        memories=memories,
        settled_at=_aware(pet.updated_at),
    )
