"""Server-authoritative pet care and activity endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import AccountPetRelation, Pet, SyncEvent
from .pet_care import CARE_RULES, CareAction, apply_care_action
from .schemas import PetView, RelationView
from .security import Principal
from .services import (
    append_event,
    find_event_by_idempotency,
    pet_view,
    relation_view,
)

pet_care_router = APIRouter(prefix="/api/v1", tags=["pet-care"])

CARE_ROLES = {"owner", "co_owner", "caregiver"}
CARE_COOLDOWN_SECONDS = 5
DAILY_CARE_LIMIT = 50


class PetCareRequest(BaseModel):
    client_time: datetime | None = None
    device_id: str | None = Field(default=None, max_length=36)

    @field_validator("client_time")
    @classmethod
    def _require_aware_client_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("client_time 必须包含时区")
        return value


class PetCareInteractionView(BaseModel):
    interaction_id: str
    pet_id: str
    action: CareAction
    actor_account_id: str
    actor_role: str
    device_id: str | None
    client_time: datetime | None
    deltas: dict[str, int]
    growth_level_changed: bool
    bond_level_changed: bool
    growth_stage_changed: bool
    created_at: datetime


class PetCareResponse(BaseModel):
    interaction: PetCareInteractionView
    pet: PetView
    relation: RelationView
    idempotency_key: str


class PetActivityResponse(BaseModel):
    items: list[PetCareInteractionView]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _event_payload(event: SyncEvent) -> dict[str, Any]:
    try:
        payload = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _interaction_from_event(event: SyncEvent) -> PetCareInteractionView | None:
    payload = _event_payload(event)
    interaction = payload.get("interaction")
    if not isinstance(interaction, dict):
        return None
    try:
        return PetCareInteractionView.model_validate(interaction)
    except ValueError:
        return None


def _recent_interactions(
    session: Session,
    *,
    account_id: str,
    pet_id: str,
    now: datetime,
) -> list[PetCareInteractionView]:
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = session.scalars(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == account_id,
            SyncEvent.event_type == "pet_updated",
            SyncEvent.created_at >= day_start,
        )
        .order_by(SyncEvent.sequence.desc())
        .limit(200)
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


def _relation_for_actor(
    session: Session,
    *,
    account_id: str,
    pet_id: str,
) -> AccountPetRelation:
    relation = session.get(AccountPetRelation, (account_id, pet_id))
    if relation is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    if relation.role not in CARE_ROLES:
        raise HTTPException(status_code=403, detail="当前角色没有照料宠物的权限")
    return relation


@pet_care_router.post(
    "/pets/{pet_id}/interactions/{action}",
    response_model=PetCareResponse,
)
def care_for_pet(
    pet_id: str,
    action: CareAction,
    body: PetCareRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PetCareResponse:
    if action not in CARE_RULES:
        raise HTTPException(status_code=404, detail="不支持的照料动作")
    if principal.kind == "device" and body.device_id not in {None, principal.device_id}:
        raise HTTPException(status_code=403, detail="设备令牌不能代表其他设备操作")

    existing = find_event_by_idempotency(
        session, principal.account_id, idempotency_key
    )
    if existing is not None:
        payload = _event_payload(existing)
        if existing.event_type != "pet_updated" or payload.get("cause") != "pet_care":
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise HTTPException(status_code=409, detail="幂等记录缺少原始操作结果")
        return PetCareResponse.model_validate(result)

    pet = session.get(Pet, pet_id)
    relation = _relation_for_actor(
        session,
        account_id=principal.account_id,
        pet_id=pet_id,
    )
    if pet is None:
        raise HTTPException(status_code=404, detail="宠物不存在")
    if pet.presence not in {"home", "resting"}:
        raise HTTPException(status_code=409, detail="宠物外出期间不能执行该照料动作")

    now = datetime.now(UTC)
    recent = _recent_interactions(
        session,
        account_id=principal.account_id,
        pet_id=pet_id,
        now=now,
    )
    if len(recent) >= DAILY_CARE_LIMIT:
        raise HTTPException(status_code=429, detail="今天的照料次数已经达到上限")
    for item in recent:
        if item.action != action:
            continue
        elapsed = (now - _aware(item.created_at)).total_seconds()
        if elapsed < CARE_COOLDOWN_SECONDS:
            retry_after = max(1, int(CARE_COOLDOWN_SECONDS - elapsed + 0.999))
            raise HTTPException(
                status_code=429,
                detail="照料动作冷却中",
                headers={"Retry-After": str(retry_after)},
            )
        break

    mutation = apply_care_action(pet, relation, action)
    pet.updated_at = now
    session.flush()

    interaction = PetCareInteractionView(
        interaction_id=str(uuid4()),
        pet_id=pet.id,
        action=action,
        actor_account_id=principal.account_id,
        actor_role=relation.role,
        device_id=principal.device_id or body.device_id,
        client_time=body.client_time,
        deltas=mutation.deltas,
        growth_level_changed=mutation.growth_level_changed,
        bond_level_changed=mutation.bond_level_changed,
        growth_stage_changed=mutation.growth_stage_changed,
        created_at=now,
    )
    response = PetCareResponse(
        interaction=interaction,
        pet=pet_view(pet),
        relation=relation_view(relation),
        idempotency_key=idempotency_key,
    )

    relations = list(
        session.scalars(
            select(AccountPetRelation).where(AccountPetRelation.pet_id == pet.id)
        )
    )
    for recipient_relation in relations:
        recipient_account_id = recipient_relation.account_id
        recipient_payload: dict[str, Any] = {
            "cause": "pet_care",
            "pet": pet_view(pet).model_dump(mode="json"),
            "relation": relation_view(recipient_relation).model_dump(mode="json"),
            "interaction": interaction.model_dump(mode="json"),
        }
        event_key = (
            idempotency_key
            if recipient_account_id == principal.account_id
            else f"{idempotency_key}:account:{recipient_account_id}"
        )
        if recipient_account_id == principal.account_id:
            recipient_payload["result"] = response.model_dump(mode="json")
        append_event(
            session,
            account_id=recipient_account_id,
            event_type="pet_updated",
            idempotency_key=event_key,
            payload=recipient_payload,
        )

    session.commit()
    return response


@pet_care_router.get(
    "/pets/{pet_id}/activity",
    response_model=PetActivityResponse,
)
def pet_activity(
    pet_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=30, ge=1, le=100),
) -> PetActivityResponse:
    if session.get(AccountPetRelation, (principal.account_id, pet_id)) is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    rows = session.scalars(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == principal.account_id,
            SyncEvent.event_type == "pet_updated",
        )
        .order_by(SyncEvent.sequence.desc())
        .limit(max(limit * 4, 40))
    )
    items: list[PetCareInteractionView] = []
    for row in rows:
        interaction = _interaction_from_event(row)
        if interaction is None or interaction.pet_id != pet_id:
            continue
        items.append(interaction)
        if len(items) >= limit:
            break
    return PetActivityResponse(items=items)
