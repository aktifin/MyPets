"""Customer-facing navigation projections for visits and categorized messages.

The endpoints in this module are read-only views over existing visit, message and sync-event
records. They deliberately avoid a second workflow table: visit lifecycle timestamps remain
owned by ``PetVisit`` and desktop interaction entries remain owned by ``SyncEvent``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import (
    Account,
    Conversation,
    ConversationMember,
    Message,
    Pet,
    SyncEvent,
)
from .security import Principal
from .visit_models import PetVisit
from .visit_service import settle_due_visits


customer_navigation_router = APIRouter(prefix="/api/v1", tags=["customer-navigation"])

TimelineKind = Literal[
    "requested",
    "accepted",
    "arrived",
    "interaction",
    "rejected",
    "cancelled",
    "returned",
    "expired",
]
NavigationKind = Literal["friend", "pet", "visit", "none"]

_INTERACTION_LABELS = {
    "greet": ("打了招呼", "两只宠物友好地打了招呼。"),
    "wave": ("挥了挥爪", "两只宠物互相挥爪回应。"),
    "play": ("一起玩耍", "两只宠物完成了一次共同玩耍。"),
    "sit_together": ("并排坐下", "两只宠物安静地并排坐了一会儿。"),
}
_RETURN_LABELS = {
    "visit_auto_returned": ("按时返家", "串门时间结束，来访宠物已自动返家。"),
    "visit_recalled": ("主人召回", "来访宠物已由主人主动召回。"),
    "guest_sent_home": ("接待方送返", "接待方已让来访宠物提前返家。"),
    "account_blocked": ("串门提前结束", "账户关系变化，来访宠物已安全返家。"),
    "friend_removed": ("串门提前结束", "好友关系变化，来访宠物已安全返家。"),
}


class VisitTimelineEntryView(BaseModel):
    event_id: str
    kind: TimelineKind
    title: str
    detail: str
    occurred_at: datetime
    actor_account_id: str | None = None
    actor_display_name: str | None = None
    interaction_action: str | None = None


class VisitTimelineView(BaseModel):
    visit_id: str
    status: str
    visitor_pet_id: str
    visitor_pet_name: str
    host_pet_id: str
    host_pet_name: str
    entries: list[VisitTimelineEntryView]


class ConversationTargetView(BaseModel):
    conversation_id: str
    kind: NavigationKind
    target_id: str | None = None
    label: str


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _payload(event: SyncEvent) -> dict[str, object]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _account(session: Session, account_id: str) -> Account | None:
    return session.get(Account, account_id)


def _account_name(session: Session, account_id: str | None) -> str | None:
    if not account_id:
        return None
    account = _account(session, account_id)
    return account.display_name if account is not None else None


def _participant(visit: PetVisit, account_id: str) -> None:
    if account_id not in {visit.requester_account_id, visit.host_account_id}:
        raise HTTPException(status_code=403, detail="当前账户不能查看该串门时间线")


def _entry(
    *,
    event_id: str,
    kind: TimelineKind,
    title: str,
    detail: str,
    occurred_at: datetime | None,
    actor_account_id: str | None,
    actor_display_name: str | None,
    interaction_action: str | None = None,
) -> VisitTimelineEntryView | None:
    timestamp = _aware(occurred_at)
    if timestamp is None:
        return None
    return VisitTimelineEntryView(
        event_id=event_id,
        kind=kind,
        title=title,
        detail=detail,
        occurred_at=timestamp,
        actor_account_id=actor_account_id,
        actor_display_name=actor_display_name,
        interaction_action=interaction_action,
    )


def _interaction_entries(
    session: Session,
    *,
    account_id: str,
    visit: PetVisit,
) -> list[VisitTimelineEntryView]:
    rows = list(
        session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.account_id == account_id,
                SyncEvent.event_type == "pet_visit_interaction",
            )
            .order_by(SyncEvent.created_at, SyncEvent.sequence)
            .limit(2000)
        )
    )
    seen: set[str] = set()
    values: list[VisitTimelineEntryView] = []
    for row in rows:
        interaction = _payload(row).get("interaction")
        if not isinstance(interaction, dict):
            continue
        if str(interaction.get("visit_id") or "") != visit.id:
            continue
        interaction_id = str(interaction.get("interaction_id") or row.event_id)
        if interaction_id in seen:
            continue
        seen.add(interaction_id)
        action = str(interaction.get("action") or "")
        title, detail = _INTERACTION_LABELS.get(
            action,
            ("完成了一次互动", "两只宠物完成了一次串门互动。"),
        )
        actor_id = str(interaction.get("actor_account_id") or "") or None
        raw_time = interaction.get("created_at")
        try:
            occurred_at = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except ValueError:
            occurred_at = row.created_at
        entry = _entry(
            event_id=f"interaction:{interaction_id}",
            kind="interaction",
            title=title,
            detail=detail,
            occurred_at=occurred_at,
            actor_account_id=actor_id,
            actor_display_name=_account_name(session, actor_id),
            interaction_action=action or None,
        )
        if entry is not None:
            values.append(entry)
    return values


def _visit_timeline(session: Session, visit: PetVisit, principal: Principal) -> VisitTimelineView:
    _participant(visit, principal.account_id)
    requester_name = _account_name(session, visit.requester_account_id)
    host_name = _account_name(session, visit.host_account_id)
    visitor = session.get(Pet, visit.visitor_pet_id)
    host_pet = session.get(Pet, visit.host_pet_id)
    if visitor is None or host_pet is None:
        raise RuntimeError("串门记录引用了不存在的宠物")

    entries: list[tuple[int, VisitTimelineEntryView]] = []

    requested = _entry(
        event_id=f"visit:{visit.id}:requested",
        kind="requested",
        title="已发送串门申请",
        detail=(
            f"{visitor.name} 申请拜访 {host_pet.name}，计划停留 {visit.duration_minutes} 分钟。"
            + (f" 留言：{visit.note}" if visit.note else "")
        ),
        occurred_at=visit.created_at,
        actor_account_id=visit.requester_account_id,
        actor_display_name=requester_name,
    )
    if requested is not None:
        entries.append((10, requested))

    if visit.status in {"active", "completed", "recalled"}:
        accepted = _entry(
            event_id=f"visit:{visit.id}:accepted",
            kind="accepted",
            title="接待方已接受",
            detail=f"{host_name or '接待方'} 接受了串门申请。",
            occurred_at=visit.responded_at or visit.started_at,
            actor_account_id=visit.host_account_id,
            actor_display_name=host_name,
        )
        arrived = _entry(
            event_id=f"visit:{visit.id}:arrived",
            kind="arrived",
            title="来访宠物已到达",
            detail=f"{visitor.name} 已到达 {host_pet.name} 身边，串门正式开始。",
            occurred_at=visit.started_at,
            actor_account_id=None,
            actor_display_name=None,
        )
        if accepted is not None:
            entries.append((20, accepted))
        if arrived is not None:
            entries.append((30, arrived))
    elif visit.status == "rejected":
        rejected = _entry(
            event_id=f"visit:{visit.id}:rejected",
            kind="rejected",
            title="串门申请已拒绝",
            detail="接待方拒绝了本次串门申请。",
            occurred_at=visit.responded_at or visit.completed_at,
            actor_account_id=visit.host_account_id,
            actor_display_name=host_name,
        )
        if rejected is not None:
            entries.append((50, rejected))
    elif visit.status == "cancelled":
        cancelled = _entry(
            event_id=f"visit:{visit.id}:cancelled",
            kind="cancelled",
            title="串门申请已取消",
            detail="申请方取消了本次串门申请。",
            occurred_at=visit.responded_at or visit.completed_at,
            actor_account_id=visit.requester_account_id,
            actor_display_name=requester_name,
        )
        if cancelled is not None:
            entries.append((50, cancelled))
    elif visit.status == "expired":
        expired = _entry(
            event_id=f"visit:{visit.id}:expired",
            kind="expired",
            title="串门申请已过期",
            detail="申请在 24 小时内未处理，系统已自动关闭。",
            occurred_at=visit.completed_at or visit.responded_at,
            actor_account_id=None,
            actor_display_name=None,
        )
        if expired is not None:
            entries.append((50, expired))

    entries.extend((40, item) for item in _interaction_entries(
        session,
        account_id=principal.account_id,
        visit=visit,
    ))

    if visit.status in {"completed", "recalled"}:
        title, detail = _RETURN_LABELS.get(
            visit.completion_reason,
            ("串门已经结束", "来访宠物已安全返家。"),
        )
        actor_id: str | None
        if visit.completion_reason == "visit_recalled":
            actor_id = visit.requester_account_id
        elif visit.completion_reason == "guest_sent_home":
            actor_id = visit.host_account_id
        else:
            actor_id = None
        returned = _entry(
            event_id=f"visit:{visit.id}:returned",
            kind="returned",
            title=title,
            detail=detail,
            occurred_at=visit.completed_at,
            actor_account_id=actor_id,
            actor_display_name=_account_name(session, actor_id),
        )
        if returned is not None:
            entries.append((60, returned))

    entries.sort(key=lambda item: (item[1].occurred_at, item[0], item[1].event_id))
    return VisitTimelineView(
        visit_id=visit.id,
        status=visit.status,
        visitor_pet_id=visitor.id,
        visitor_pet_name=visitor.name,
        host_pet_id=host_pet.id,
        host_pet_name=host_pet.name,
        entries=[item for _order, item in entries],
    )


def _conversation_members(session: Session, conversation_id: str) -> list[str]:
    return list(
        session.scalars(
            select(ConversationMember.account_id).where(
                ConversationMember.conversation_id == conversation_id
            )
        )
    )


def _visit_target(
    session: Session,
    *,
    account_ids: list[str],
    sender_pet_id: str | None,
) -> PetVisit | None:
    if len(account_ids) != 2:
        return None
    left, right = account_ids
    statement = select(PetVisit).where(
        or_(
            (
                (PetVisit.requester_account_id == left)
                & (PetVisit.host_account_id == right)
            ),
            (
                (PetVisit.requester_account_id == right)
                & (PetVisit.host_account_id == left)
            ),
        )
    )
    if sender_pet_id:
        statement = statement.where(PetVisit.visitor_pet_id == sender_pet_id)
    return session.scalar(statement.order_by(PetVisit.created_at.desc()).limit(1))


@customer_navigation_router.get(
    "/visits/{visit_id}/timeline",
    response_model=VisitTimelineView,
)
def get_visit_timeline(
    visit_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> VisitTimelineView:
    settle_due_visits(session)
    visit = session.get(PetVisit, visit_id)
    if visit is None:
        raise HTTPException(status_code=404, detail="串门记录不存在")
    result = _visit_timeline(session, visit, principal)
    session.commit()
    return result


@customer_navigation_router.get(
    "/conversations/{conversation_id}/target",
    response_model=ConversationTargetView,
)
def get_conversation_target(
    conversation_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ConversationTargetView:
    conversation = session.get(Conversation, conversation_id)
    member = session.get(ConversationMember, (conversation_id, principal.account_id))
    if conversation is None or member is None:
        raise HTTPException(status_code=404, detail="会话不存在或无访问权限")

    members = _conversation_members(session, conversation_id)
    messages = list(
        session.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                or_(
                    Message.message_type.in_(("visit_message", "care_event", "growth_notice")),
                    Message.sender_pet_id.is_not(None),
                ),
            )
            .order_by(Message.sequence.desc())
            .limit(50)
        )
    )
    for message in messages:
        if message.message_type == "visit_message":
            visit = _visit_target(
                session,
                account_ids=members,
                sender_pet_id=message.sender_pet_id,
            )
            if visit is not None:
                visitor = session.get(Pet, visit.visitor_pet_id)
                host_pet = session.get(Pet, visit.host_pet_id)
                label = (
                    f"查看 {visitor.name} → {host_pet.name} 的串门"
                    if visitor is not None and host_pet is not None
                    else "查看相关串门"
                )
                return ConversationTargetView(
                    conversation_id=conversation_id,
                    kind="visit",
                    target_id=visit.id,
                    label=label,
                )
        if message.sender_pet_id:
            pet = session.get(Pet, message.sender_pet_id)
            if pet is not None:
                return ConversationTargetView(
                    conversation_id=conversation_id,
                    kind="pet",
                    target_id=pet.id,
                    label=f"查看宠物 {pet.name}",
                )

    peer_id = next((account_id for account_id in members if account_id != principal.account_id), None)
    peer = session.get(Account, peer_id) if peer_id else None
    if peer is not None:
        return ConversationTargetView(
            conversation_id=conversation_id,
            kind="friend",
            target_id=peer.id,
            label=f"查看好友 {peer.display_name}",
        )
    return ConversationTargetView(
        conversation_id=conversation_id,
        kind="none",
        target_id=None,
        label="暂无关联详情",
    )
