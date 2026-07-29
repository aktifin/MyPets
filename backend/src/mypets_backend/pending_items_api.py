"""Unified customer pending-items projection and direct-action API.

This module does not create another workflow system. It projects existing friendship,
shared-care, visit, party invitation and reminder records into one customer-facing queue,
then delegates mutations to the authoritative feature endpoints so their permission and
lifecycle rules remain the single source of truth. Party invitations are intentionally
read-only here because accepting one requires choosing an eligible managed pet in the
party experience.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import Account, Pet
from .party_models import PetParty, PetPartyMember
from .party_service import settle_due_parties
from .reminder_api import (
    ReminderSnoozeRequest,
    complete_occurrence,
    dismiss_occurrence,
    snooze_occurrence,
)
from .reminder_models import ReminderOccurrence
from .security import Principal
from .social_api import (
    accept_caregiver_invitation,
    accept_friend_request,
    reject_caregiver_invitation,
    reject_friend_request,
)
from .social_models import CaregiverInvitation, FriendRequest
from .visit_api import accept_visit, reject_visit
from .visit_models import PetVisit
from .visit_service import settle_due_visits

pending_items_router = APIRouter(prefix="/api/v1/pending-items", tags=["pending-items"])

PendingKind = Literal[
    "friend_request",
    "caregiver_invitation",
    "visit_request",
    "party_invitation",
    "reminder_due",
]
PendingAction = Literal["accept", "reject", "complete", "snooze", "dismiss"]


class PendingItemView(BaseModel):
    item_id: str
    kind: PendingKind
    title: str
    detail: str
    actor_display_name: str | None = None
    pet_id: str | None = None
    pet_name: str | None = None
    occurred_at: datetime
    due_at: datetime | None = None
    priority: Literal["urgent", "normal"] = "normal"
    actions: list[PendingAction]


class PendingItemsResponse(BaseModel):
    count: int
    urgent_count: int
    items: list[PendingItemView]


class PendingItemActionRequest(BaseModel):
    snooze_minutes: Literal[5, 10, 30] = 10


class PendingItemActionResponse(BaseModel):
    item_id: str
    kind: PendingKind
    action: PendingAction
    message: str


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _account_name(session: Session, account_id: str) -> str:
    account = session.get(Account, account_id)
    return account.display_name if account is not None else "一位用户"


def _pet(session: Session, pet_id: str) -> Pet | None:
    return session.get(Pet, pet_id)


def _friend_items(session: Session, account_id: str) -> list[PendingItemView]:
    rows = list(
        session.scalars(
            select(FriendRequest)
            .where(
                FriendRequest.recipient_account_id == account_id,
                FriendRequest.status == "pending",
            )
            .order_by(FriendRequest.created_at)
            .limit(200)
        )
    )
    return [
        PendingItemView(
            item_id=row.id,
            kind="friend_request",
            title=f"{_account_name(session, row.sender_account_id)} 想添加你为好友",
            detail="接受后可以查看对方开放的宠物、发起共同照料和串门。",
            actor_display_name=_account_name(session, row.sender_account_id),
            occurred_at=_aware(row.created_at),
            actions=["accept", "reject"],
        )
        for row in rows
    ]


def _caregiver_items(session: Session, account_id: str) -> list[PendingItemView]:
    rows = list(
        session.scalars(
            select(CaregiverInvitation)
            .where(
                CaregiverInvitation.invited_account_id == account_id,
                CaregiverInvitation.status == "pending",
            )
            .order_by(CaregiverInvitation.created_at)
            .limit(200)
        )
    )
    items: list[PendingItemView] = []
    for row in rows:
        pet = _pet(session, row.pet_id)
        pet_name = pet.name if pet is not None else "这只宠物"
        role_label = "共同照料者" if row.role == "caregiver" else "观察者"
        inviter_name = _account_name(session, row.invited_by_account_id)
        items.append(
            PendingItemView(
                item_id=row.id,
                kind="caregiver_invitation",
                title=f"邀请你共同照料 {pet_name}",
                detail=f"{inviter_name} 邀请你成为{role_label}。接受后会出现在你的宠物列表中。",
                actor_display_name=inviter_name,
                pet_id=row.pet_id,
                pet_name=pet_name,
                occurred_at=_aware(row.created_at),
                actions=["accept", "reject"],
            )
        )
    return items


def _visit_items(session: Session, account_id: str) -> list[PendingItemView]:
    rows = list(
        session.scalars(
            select(PetVisit)
            .where(
                PetVisit.host_account_id == account_id,
                PetVisit.status == "pending",
            )
            .order_by(PetVisit.created_at)
            .limit(200)
        )
    )
    items: list[PendingItemView] = []
    for row in rows:
        visitor = _pet(session, row.visitor_pet_id)
        host = _pet(session, row.host_pet_id)
        visitor_name = visitor.name if visitor is not None else "好友宠物"
        host_name = host.name if host is not None else "你的宠物"
        requester_name = _account_name(session, row.requester_account_id)
        note = f" 留言：{row.note}" if row.note else ""
        items.append(
            PendingItemView(
                item_id=row.id,
                kind="visit_request",
                title=f"{visitor_name} 想来找 {host_name} 串门",
                detail=f"来自 {requester_name}，计划停留 {row.duration_minutes} 分钟。{note}".strip(),
                actor_display_name=requester_name,
                pet_id=row.host_pet_id,
                pet_name=host_name,
                occurred_at=_aware(row.created_at),
                actions=["accept", "reject"],
            )
        )
    return items


def _party_items(session: Session, account_id: str) -> list[PendingItemView]:
    rows = list(
        session.execute(
            select(PetPartyMember, PetParty)
            .join(PetParty, PetParty.id == PetPartyMember.party_id)
            .where(
                PetPartyMember.account_id == account_id,
                PetPartyMember.status == "invited",
                PetParty.status == "open",
            )
            .order_by(PetPartyMember.created_at, PetPartyMember.id)
            .limit(200)
        ).all()
    )
    items: list[PendingItemView] = []
    for member, party in rows:
        host_name = _account_name(session, party.host_account_id)
        host_pet = _pet(session, party.host_pet_id)
        host_pet_name = host_pet.name if host_pet is not None else "发起人的宠物"
        note = f" 说明：{party.note}" if party.note else ""
        items.append(
            PendingItemView(
                item_id=party.id,
                kind="party_invitation",
                title=f"{host_name} 邀请你参加“{party.title}”",
                detail=(
                    f"请进入聚会选择一只自己管理且当前在家的宠物后回应。"
                    f"本场最多 {party.max_members} 只，约 {party.duration_minutes} 分钟。{note}"
                ).strip(),
                actor_display_name=host_name,
                pet_id=party.host_pet_id,
                pet_name=host_pet_name,
                occurred_at=_aware(member.created_at),
                actions=[],
            )
        )
    return items


def _reminder_items(
    session: Session,
    account_id: str,
    *,
    now: datetime,
) -> list[PendingItemView]:
    rows = list(
        session.scalars(
            select(ReminderOccurrence)
            .where(
                ReminderOccurrence.account_id == account_id,
                ReminderOccurrence.state.in_({"pending", "delivered", "seen", "snoozed"}),
                ReminderOccurrence.scheduled_at <= now,
            )
            .order_by(ReminderOccurrence.scheduled_at, ReminderOccurrence.id)
            .limit(200)
        )
    )
    items: list[PendingItemView] = []
    for row in rows:
        urgent = row.priority in {"urgent", "high"}
        content = row.content.strip() if row.content else "到时间了，可直接完成、稍后提醒或忽略。"
        items.append(
            PendingItemView(
                item_id=row.id,
                kind="reminder_due",
                title=row.title,
                detail=content,
                occurred_at=_aware(row.updated_at),
                due_at=_aware(row.scheduled_at),
                priority="urgent" if urgent else "normal",
                actions=["complete", "snooze", "dismiss"],
            )
        )
    return items


def build_pending_items(
    session: Session,
    *,
    account_id: str,
    limit: int,
) -> PendingItemsResponse:
    now = datetime.now(UTC)
    settle_due_visits(session, now=now)
    settle_due_parties(session, now=now)
    session.flush()
    items = [
        *_friend_items(session, account_id),
        *_caregiver_items(session, account_id),
        *_visit_items(session, account_id),
        *_party_items(session, account_id),
        *_reminder_items(session, account_id, now=now),
    ]
    items.sort(
        key=lambda item: (
            0 if item.priority == "urgent" else 1,
            _aware(item.due_at or item.occurred_at),
            item.kind,
            item.item_id,
        )
    )
    values = items[:limit]
    return PendingItemsResponse(
        count=len(items),
        urgent_count=sum(item.priority == "urgent" for item in items),
        items=values,
    )


@pending_items_router.get("", response_model=PendingItemsResponse)
def list_pending_items(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=100, ge=1, le=300),
) -> PendingItemsResponse:
    result = build_pending_items(
        session,
        account_id=principal.account_id,
        limit=limit,
    )
    session.commit()
    return result


@pending_items_router.post(
    "/{kind}/{item_id}/{action}",
    response_model=PendingItemActionResponse,
)
def act_on_pending_item(
    kind: PendingKind,
    item_id: str,
    action: PendingAction,
    body: PendingItemActionRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> PendingItemActionResponse:
    allowed: dict[PendingKind, set[PendingAction]] = {
        "friend_request": {"accept", "reject"},
        "caregiver_invitation": {"accept", "reject"},
        "visit_request": {"accept", "reject"},
        "party_invitation": set(),
        "reminder_due": {"complete", "snooze", "dismiss"},
    }
    if action not in allowed[kind]:
        raise HTTPException(status_code=422, detail="当前待处理事项不支持该操作")

    if kind == "friend_request":
        if action == "accept":
            accept_friend_request(item_id, principal, session)
            message = "好友申请已接受。"
        else:
            reject_friend_request(item_id, principal, session)
            message = "好友申请已拒绝。"
    elif kind == "caregiver_invitation":
        if action == "accept":
            result = accept_caregiver_invitation(item_id, principal, session)
            message = f"已接受 {result.pet.name} 的共同照料邀请。"
        else:
            reject_caregiver_invitation(item_id, principal, session)
            message = "共同照料邀请已拒绝。"
    elif kind == "visit_request":
        if action == "accept":
            result = accept_visit(item_id, principal, session)
            message = f"已接受 {result.visitor_pet.name} 的串门申请。"
        else:
            reject_visit(item_id, principal, session)
            message = "串门申请已拒绝。"
    elif action == "complete":
        complete_occurrence(item_id, idempotency_key, principal, session)
        message = "提醒已完成。"
    elif action == "snooze":
        snooze_occurrence(
            item_id,
            ReminderSnoozeRequest(minutes=body.snooze_minutes),
            idempotency_key,
            principal,
            session,
        )
        message = f"将在 {body.snooze_minutes} 分钟后再次提醒。"
    else:
        dismiss_occurrence(item_id, idempotency_key, principal, session)
        message = "提醒已忽略。"

    return PendingItemActionResponse(
        item_id=item_id,
        kind=kind,
        action=action,
        message=message,
    )
