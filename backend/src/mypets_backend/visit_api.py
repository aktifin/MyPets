"""Friend-gated asynchronous pet visit request and lifecycle APIs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import Account, AccountPetRelation, Pet
from .security import Principal, normalize_username
from .social_models import AccountBlock, Friendship, PetPrivacy
from .visit_models import PetVisit
from .visit_service import (
    finish_visit,
    has_open_visit_for_pet,
    publish_visit_update,
    publish_visitor_pet,
    settle_due_visits,
)

visit_router = APIRouter(prefix="/api/v1/visits", tags=["pet-visits"])

VisitStatus = Literal[
    "pending",
    "active",
    "rejected",
    "cancelled",
    "completed",
    "recalled",
    "expired",
]


class VisitCreateRequest(BaseModel):
    host_username: str = Field(min_length=3, max_length=64)
    visitor_pet_id: str = Field(min_length=1, max_length=36)
    host_pet_id: str = Field(min_length=1, max_length=36)
    duration_minutes: int = Field(default=60, ge=15, le=240)
    note: str = Field(default="", max_length=200)

    @field_validator("host_username")
    @classmethod
    def _normalize_username(cls, value: str) -> str:
        return normalize_username(value)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str) -> str:
        return value.strip()


class AccountSummary(BaseModel):
    account_id: str
    username: str
    display_name: str


class PetSummary(BaseModel):
    pet_id: str
    name: str
    presence: str
    growth_stage: str
    growth_level: int
    mood: int


class VisitView(BaseModel):
    visit_id: str
    requester: AccountSummary
    host: AccountSummary
    visitor_pet: PetSummary
    host_pet: PetSummary
    status: VisitStatus
    note: str
    duration_minutes: int
    completion_reason: str
    created_at: datetime
    responded_at: datetime | None
    started_at: datetime | None
    scheduled_end_at: datetime | None
    completed_at: datetime | None
    can_accept: bool
    can_reject: bool
    can_cancel: bool
    can_recall: bool


class VisitListResponse(BaseModel):
    incoming_requests: list[VisitView]
    outgoing_requests: list[VisitView]
    active: list[VisitView]
    history: list[VisitView]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _account_summary(value: Account) -> AccountSummary:
    return AccountSummary(
        account_id=value.id,
        username=value.username,
        display_name=value.display_name,
    )


def _pet_summary(value: Pet) -> PetSummary:
    return PetSummary(
        pet_id=value.id,
        name=value.name,
        presence=value.presence,
        growth_stage=value.growth_stage,
        growth_level=value.growth_level,
        mood=value.mood,
    )


def _friendship(session: Session, left: str, right: str) -> Friendship | None:
    low, high = (left, right) if left < right else (right, left)
    return session.scalar(
        select(Friendship).where(
            Friendship.account_low_id == low,
            Friendship.account_high_id == high,
        )
    )


def _blocked(session: Session, left: str, right: str) -> bool:
    return (
        session.get(AccountBlock, (left, right)) is not None
        or session.get(AccountBlock, (right, left)) is not None
    )


def _manager_relation(session: Session, account_id: str, pet_id: str) -> AccountPetRelation | None:
    relation = session.get(AccountPetRelation, (account_id, pet_id))
    return relation if relation is not None and relation.role in {"owner", "co_owner"} else None


def _require_manager(session: Session, account_id: str, pet_id: str) -> tuple[Pet, AccountPetRelation]:
    pet = session.get(Pet, pet_id)
    relation = _manager_relation(session, account_id, pet_id)
    if pet is None or relation is None:
        raise HTTPException(status_code=404, detail="宠物不存在或当前账户无管理权限")
    return pet, relation


def _host_pet_visible(session: Session, requester_account_id: str, host_pet: Pet) -> bool:
    relation = session.get(AccountPetRelation, (requester_account_id, host_pet.id))
    if relation is not None:
        return True
    privacy = session.get(PetPrivacy, host_pet.id)
    if privacy is None:
        return False
    return privacy.visibility in {"friends", "public"}


def _visit(session: Session, visit_id: str) -> PetVisit:
    value = session.get(PetVisit, visit_id)
    if value is None:
        raise HTTPException(status_code=404, detail="串门记录不存在")
    return value


def _has_active_host_visit(session: Session, host_pet_id: str, *, exclude_id: str | None = None) -> bool:
    statement = select(PetVisit.id).where(
        PetVisit.host_pet_id == host_pet_id,
        PetVisit.status == "active",
    )
    if exclude_id:
        statement = statement.where(PetVisit.id != exclude_id)
    return session.scalar(statement.limit(1)) is not None


def _view(session: Session, value: PetVisit, principal: Principal) -> VisitView:
    requester = session.get(Account, value.requester_account_id)
    host = session.get(Account, value.host_account_id)
    visitor_pet = session.get(Pet, value.visitor_pet_id)
    host_pet = session.get(Pet, value.host_pet_id)
    if requester is None or host is None or visitor_pet is None or host_pet is None:
        raise RuntimeError("串门记录引用了不存在的数据")
    can_recall = value.status == "active" and _manager_relation(
        session, principal.account_id, value.visitor_pet_id
    ) is not None
    return VisitView(
        visit_id=value.id,
        requester=_account_summary(requester),
        host=_account_summary(host),
        visitor_pet=_pet_summary(visitor_pet),
        host_pet=_pet_summary(host_pet),
        status=value.status,  # type: ignore[arg-type]
        note=value.note,
        duration_minutes=value.duration_minutes,
        completion_reason=value.completion_reason,
        created_at=_aware(value.created_at),  # type: ignore[arg-type]
        responded_at=_aware(value.responded_at),
        started_at=_aware(value.started_at),
        scheduled_end_at=_aware(value.scheduled_end_at),
        completed_at=_aware(value.completed_at),
        can_accept=value.status == "pending" and principal.account_id == value.host_account_id,
        can_reject=value.status == "pending" and principal.account_id == value.host_account_id,
        can_cancel=value.status == "pending" and principal.account_id == value.requester_account_id,
        can_recall=can_recall,
    )


def _require_participant(value: PetVisit, account_id: str) -> None:
    if account_id not in {value.requester_account_id, value.host_account_id}:
        raise HTTPException(status_code=403, detail="当前账户不能处理该串门记录")


@visit_router.post("", response_model=VisitView, status_code=201)
def create_visit_request(
    body: VisitCreateRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitView:
    settle_due_visits(session)
    host = session.scalar(select(Account).where(Account.username == body.host_username))
    if host is None:
        raise HTTPException(status_code=404, detail="好友账户不存在")
    if host.id == principal.account_id:
        raise HTTPException(status_code=400, detail="不能向自己发起串门")
    if _blocked(session, principal.account_id, host.id):
        raise HTTPException(status_code=403, detail="当前账户关系不允许串门")
    if _friendship(session, principal.account_id, host.id) is None:
        raise HTTPException(status_code=409, detail="只能向好友发起串门")

    visitor_pet, _ = _require_manager(session, principal.account_id, body.visitor_pet_id)
    host_pet, _ = _require_manager(session, host.id, body.host_pet_id)
    if not _host_pet_visible(session, principal.account_id, host_pet):
        raise HTTPException(status_code=404, detail="接待宠物不存在或当前不可见")
    if visitor_pet.id == host_pet.id:
        raise HTTPException(status_code=400, detail="来访宠物和接待宠物不能相同")
    if visitor_pet.presence not in {"home", "resting"}:
        raise HTTPException(status_code=409, detail="来访宠物当前不在家")
    if host_pet.presence not in {"home", "resting"}:
        raise HTTPException(status_code=409, detail="接待宠物当前不在家")
    if has_open_visit_for_pet(session, visitor_pet.id):
        raise HTTPException(status_code=409, detail="该宠物已有待处理或进行中的串门")

    value = PetVisit(
        id=str(uuid4()),
        requester_account_id=principal.account_id,
        host_account_id=host.id,
        visitor_pet_id=visitor_pet.id,
        host_pet_id=host_pet.id,
        status="pending",
        note=body.note,
        duration_minutes=body.duration_minutes,
    )
    session.add(value)
    session.flush()
    publish_visit_update(session, value, cause="visit_requested")
    result = _view(session, value, principal)
    session.commit()
    return result


@visit_router.get("", response_model=VisitListResponse)
def list_visits(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitListResponse:
    settle_due_visits(session)
    values = list(
        session.scalars(
            select(PetVisit)
            .where(
                or_(
                    PetVisit.requester_account_id == principal.account_id,
                    PetVisit.host_account_id == principal.account_id,
                )
            )
            .order_by(PetVisit.created_at.desc())
            .limit(300)
        )
    )
    incoming = [
        _view(session, item, principal)
        for item in values
        if item.status == "pending" and item.host_account_id == principal.account_id
    ]
    outgoing = [
        _view(session, item, principal)
        for item in values
        if item.status == "pending" and item.requester_account_id == principal.account_id
    ]
    active = [_view(session, item, principal) for item in values if item.status == "active"]
    history = [
        _view(session, item, principal)
        for item in values
        if item.status in {"rejected", "cancelled", "completed", "recalled", "expired"}
    ][:100]
    session.commit()
    return VisitListResponse(
        incoming_requests=incoming,
        outgoing_requests=outgoing,
        active=active,
        history=history,
    )


@visit_router.post("/{visit_id}/accept", response_model=VisitView)
def accept_visit(
    visit_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitView:
    settle_due_visits(session)
    value = _visit(session, visit_id)
    if value.host_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有接待方可以接受串门")
    if value.status != "pending":
        raise HTTPException(status_code=409, detail="串门申请已经处理")
    if _blocked(session, value.requester_account_id, value.host_account_id):
        raise HTTPException(status_code=403, detail="当前账户关系不允许接受串门")
    if _friendship(session, value.requester_account_id, value.host_account_id) is None:
        raise HTTPException(status_code=409, detail="好友关系已失效")
    visitor_pet = session.get(Pet, value.visitor_pet_id)
    host_pet, _ = _require_manager(session, principal.account_id, value.host_pet_id)
    if visitor_pet is None or _manager_relation(
        session, value.requester_account_id, value.visitor_pet_id
    ) is None:
        raise HTTPException(status_code=409, detail="来访宠物关系已失效")
    if not _host_pet_visible(session, value.requester_account_id, host_pet):
        raise HTTPException(status_code=409, detail="接待宠物已不再对申请方可见")
    if visitor_pet.presence not in {"home", "resting"}:
        raise HTTPException(status_code=409, detail="来访宠物当前不在家")
    if host_pet.presence not in {"home", "resting"}:
        raise HTTPException(status_code=409, detail="接待宠物当前不在家")
    if has_open_visit_for_pet(session, visitor_pet.id, exclude_id=value.id):
        raise HTTPException(status_code=409, detail="来访宠物已有其他串门")
    if _has_active_host_visit(session, host_pet.id, exclude_id=value.id):
        raise HTTPException(status_code=409, detail="接待宠物正在接待其他来访")

    now = datetime.now(UTC)
    value.status = "active"
    value.responded_at = now
    value.started_at = now
    value.scheduled_end_at = now + timedelta(minutes=value.duration_minutes)
    visitor_pet.presence = "visiting"
    visitor_pet.state_version += 1
    visitor_pet.updated_at = now
    session.flush()
    publish_visitor_pet(session, value, visitor_pet, cause="visit_started")
    publish_visit_update(session, value, cause="visit_started")
    result = _view(session, value, principal)
    session.commit()
    return result


def _close_pending(
    session: Session,
    principal: Principal,
    visit_id: str,
    *,
    action: Literal["rejected", "cancelled"],
) -> VisitView:
    value = _visit(session, visit_id)
    if value.status != "pending":
        raise HTTPException(status_code=409, detail="串门申请已经处理")
    if action == "rejected" and value.host_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有接待方可以拒绝串门")
    if action == "cancelled" and value.requester_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有申请方可以取消串门")
    now = datetime.now(UTC)
    value.status = action
    value.responded_at = now
    value.completed_at = now
    value.completion_reason = "visit_rejected" if action == "rejected" else "visit_cancelled"
    publish_visit_update(session, value, cause=value.completion_reason)
    result = _view(session, value, principal)
    session.commit()
    return result


@visit_router.post("/{visit_id}/reject", response_model=VisitView)
def reject_visit(
    visit_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitView:
    return _close_pending(session, principal, visit_id, action="rejected")


@visit_router.post("/{visit_id}/cancel", response_model=VisitView)
def cancel_visit(
    visit_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitView:
    return _close_pending(session, principal, visit_id, action="cancelled")


@visit_router.post("/{visit_id}/recall", response_model=VisitView)
def recall_visit(
    visit_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitView:
    settle_due_visits(session)
    value = _visit(session, visit_id)
    _require_participant(value, principal.account_id)
    if _manager_relation(session, principal.account_id, value.visitor_pet_id) is None:
        raise HTTPException(status_code=403, detail="只有来访宠物的主人可以召回")
    if value.status != "active":
        raise HTTPException(status_code=409, detail="该串门当前不能召回")
    finish_visit(
        session,
        value,
        now=datetime.now(UTC),
        status="recalled",
        reason="visit_recalled",
    )
    result = _view(session, value, principal)
    session.commit()
    return result


@visit_router.post("/{visit_id}/send-home", response_model=VisitView)
def send_home_visit(
    visit_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitView:
    settle_due_visits(session)
    value = _visit(session, visit_id)
    _require_participant(value, principal.account_id)
    if value.host_account_id != principal.account_id:
        raise HTTPException(status_code=403, detail="只有接待方可以发送来访宠物提前返家")
    if value.status != "active":
        raise HTTPException(status_code=409, detail="该串门当前不能发送返家")
    finish_visit(
        session,
        value,
        now=datetime.now(UTC),
        status="recalled",
        reason="guest_sent_home",
    )
    result = _view(session, value, principal)
    session.commit()
    return result

