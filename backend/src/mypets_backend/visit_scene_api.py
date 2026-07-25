"""Read-only desktop visit scene metadata and server-authoritative dual-pet actions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import Account, Pet
from .security import Principal
from .services import append_event, find_event_by_idempotency
from .visit_models import PetVisit
from .visit_service import settle_due_visits

visit_scene_router = APIRouter(prefix="/api/v1/visits", tags=["pet-visit-scenes"])
VisitInteractionAction = Literal["greet", "wave", "play", "sit_together"]


class VisitSceneAccount(BaseModel):
    account_id: str
    username: str
    display_name: str


class VisitScenePet(BaseModel):
    pet_id: str
    name: str
    presence: str
    growth_stage: str
    growth_level: int
    mood: int
    template_id: str
    template_version: str
    identity_version: str
    asset_version: str
    personality_type: str


class VisitSceneView(BaseModel):
    visit_id: str
    status: str
    requester: VisitSceneAccount
    host: VisitSceneAccount
    visitor_pet: VisitScenePet
    host_pet: VisitScenePet
    note: str
    started_at: datetime | None
    scheduled_end_at: datetime | None
    can_send_home: bool
    can_interact: bool


class VisitInteractionRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class VisitInteractionView(BaseModel):
    interaction_id: str
    visit_id: str
    action: VisitInteractionAction
    actor_account_id: str
    visitor_pet_id: str
    host_pet_id: str
    created_at: datetime


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _visit(session: Session, visit_id: str) -> PetVisit:
    value = session.get(PetVisit, visit_id)
    if value is None:
        raise HTTPException(status_code=404, detail="串门记录不存在")
    return value


def _participant(value: PetVisit, account_id: str) -> None:
    if account_id not in {value.requester_account_id, value.host_account_id}:
        raise HTTPException(status_code=403, detail="当前账户不能查看该串门场景")


def _account(session: Session, account_id: str) -> Account:
    value = session.get(Account, account_id)
    if value is None:
        raise RuntimeError("串门记录引用了不存在的账户")
    return value


def _pet(session: Session, pet_id: str) -> Pet:
    value = session.get(Pet, pet_id)
    if value is None:
        raise RuntimeError("串门记录引用了不存在的宠物")
    return value


def _account_view(value: Account) -> VisitSceneAccount:
    return VisitSceneAccount(
        account_id=value.id,
        username=value.username,
        display_name=value.display_name,
    )


def _pet_view(value: Pet) -> VisitScenePet:
    return VisitScenePet(
        pet_id=value.id,
        name=value.name,
        presence=value.presence,
        growth_stage=value.growth_stage,
        growth_level=value.growth_level,
        mood=value.mood,
        template_id=value.template_id,
        template_version=value.template_version,
        identity_version=value.identity_version,
        asset_version=value.asset_version,
        personality_type=value.personality_type,
    )


def _scene(session: Session, value: PetVisit, principal: Principal) -> VisitSceneView:
    requester = _account(session, value.requester_account_id)
    host = _account(session, value.host_account_id)
    visitor_pet = _pet(session, value.visitor_pet_id)
    host_pet = _pet(session, value.host_pet_id)
    is_host = principal.account_id == value.host_account_id
    return VisitSceneView(
        visit_id=value.id,
        status=value.status,
        requester=_account_view(requester),
        host=_account_view(host),
        visitor_pet=_pet_view(visitor_pet),
        host_pet=_pet_view(host_pet),
        note=value.note,
        started_at=_aware(value.started_at),
        scheduled_end_at=_aware(value.scheduled_end_at),
        can_send_home=is_host and value.status == "active",
        can_interact=is_host and value.status == "active",
    )


@visit_scene_router.get("/{visit_id}/scene", response_model=VisitSceneView)
def get_visit_scene(
    visit_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitSceneView:
    settle_due_visits(session)
    value = _visit(session, visit_id)
    _participant(value, principal.account_id)
    result = _scene(session, value, principal)
    session.commit()
    return result


@visit_scene_router.post(
    "/{visit_id}/interactions/{action}",
    response_model=VisitInteractionView,
)
def interact_during_visit(
    visit_id: str,
    action: VisitInteractionAction,
    body: VisitInteractionRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitInteractionView:
    settle_due_visits(session)
    value = _visit(session, visit_id)
    _participant(value, principal.account_id)
    if principal.account_id != value.host_account_id:
        raise HTTPException(status_code=403, detail="只有接待方可以触发桌面双宠互动")
    if value.status != "active":
        raise HTTPException(status_code=409, detail="只有进行中的串门可以互动")

    scoped_key = f"visit-interaction:{visit_id}:{body.idempotency_key}"
    existing = find_event_by_idempotency(session, principal.account_id, scoped_key)
    if existing is not None:
        if existing.event_type != "pet_visit_interaction":
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        payload = json.loads(existing.payload_json)
        interaction = payload.get("interaction")
        if not isinstance(interaction, dict):
            raise HTTPException(status_code=409, detail="幂等记录缺少互动结果")
        return VisitInteractionView.model_validate(interaction)

    now = datetime.now(UTC)
    result = VisitInteractionView(
        interaction_id=str(uuid4()),
        visit_id=value.id,
        action=action,
        actor_account_id=principal.account_id,
        visitor_pet_id=value.visitor_pet_id,
        host_pet_id=value.host_pet_id,
        created_at=now,
    )
    payload = {
        "cause": "visit_desktop_interaction",
        "interaction": result.model_dump(mode="json"),
    }
    append_event(
        session,
        account_id=value.host_account_id,
        event_type="pet_visit_interaction",
        idempotency_key=scoped_key,
        payload=payload,
    )
    append_event(
        session,
        account_id=value.requester_account_id,
        event_type="pet_visit_interaction",
        idempotency_key=scoped_key,
        payload=payload,
    )
    session.commit()
    return result
