"""Customer-facing processing history projected from existing authoritative records.

The history endpoint does not create another workflow or audit table. Social and visit results are
read from their lifecycle records, while reminder actions are reconstructed from account-scoped
``SyncEvent`` rows so repeated snoozes remain visible.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import Account, Pet, SyncEvent
from .reminder_models import ReminderOccurrence
from .security import Principal
from .social_models import CaregiverInvitation, FriendRequest
from .visit_models import PetVisit
from .visit_service import settle_due_visits

customer_history_router = APIRouter(prefix="/api/v1/customer-history", tags=["customer-history"])

HistoryKind = Literal["friend_request", "caregiver_invitation", "visit", "reminder"]
HistoryFilter = Literal["all", "friend_request", "caregiver_invitation", "visit", "reminder"]
HistoryAction = Literal[
    "accepted",
    "rejected",
    "cancelled",
    "completed",
    "snoozed",
    "dismissed",
    "returned",
    "expired",
]
HistoryDirection = Literal["incoming", "outgoing", "self", "system"]
HistoryTargetKind = Literal["friend", "shared_care", "visit", "reminder"]

_RETURN_LABELS = {
    "visit_auto_returned": ("按时返家", "串门时间结束，来访宠物已自动返家。"),
    "visit_recalled": ("主人召回", "来访宠物已由主人主动召回。"),
    "guest_sent_home": ("接待方送返", "接待方已让来访宠物提前返家。"),
    "account_blocked": ("串门提前结束", "账户关系变化，来访宠物已安全返家。"),
    "friend_removed": ("串门提前结束", "好友关系变化，来访宠物已安全返家。"),
}


class CustomerHistoryItemView(BaseModel):
    history_id: str
    kind: HistoryKind
    action: HistoryAction
    direction: HistoryDirection
    title: str
    detail: str
    occurred_at: datetime
    actor_display_name: str | None = None
    pet_id: str | None = None
    pet_name: str | None = None
    counterparty_account_id: str | None = None
    counterparty_display_name: str | None = None
    target_kind: HistoryTargetKind
    target_id: str
    target_label: str


class CustomerHistoryResponse(BaseModel):
    count: int
    items: list[CustomerHistoryItemView]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _account(session: Session, account_id: str | None) -> Account | None:
    return session.get(Account, account_id) if account_id else None


def _account_name(session: Session, account_id: str | None) -> str | None:
    value = _account(session, account_id)
    return value.display_name if value is not None else None


def _payload(event: SyncEvent) -> dict[str, object]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _in_range(value: datetime, start: datetime | None, end: datetime | None) -> bool:
    timestamp = _aware(value)
    if timestamp is None:
        return False
    if start is not None and timestamp < start:
        return False
    return end is None or timestamp < end


def _friend_history(
    session: Session,
    *,
    account_id: str,
    start: datetime | None,
    end: datetime | None,
) -> list[CustomerHistoryItemView]:
    rows = list(
        session.scalars(
            select(FriendRequest)
            .where(
                FriendRequest.status != "pending",
                or_(
                    FriendRequest.sender_account_id == account_id,
                    FriendRequest.recipient_account_id == account_id,
                ),
            )
            .order_by(FriendRequest.responded_at.desc(), FriendRequest.id)
            .limit(500)
        )
    )
    values: list[CustomerHistoryItemView] = []
    for row in rows:
        occurred_at = _aware(row.responded_at)
        if occurred_at is None or not _in_range(occurred_at, start, end):
            continue
        incoming = row.recipient_account_id == account_id
        other_id = row.sender_account_id if incoming else row.recipient_account_id
        other_name = _account_name(session, other_id) or "对方"
        actor_id = row.recipient_account_id if row.status in {"accepted", "rejected"} else row.sender_account_id
        actor_name = _account_name(session, actor_id)
        if row.status == "accepted":
            title = f"你接受了 {other_name} 的好友申请" if incoming else f"{other_name} 接受了你的好友申请"
            detail = "好友关系已经建立，可继续查看对方开放的宠物、消息和串门。"
        elif row.status == "rejected":
            title = f"你拒绝了 {other_name} 的好友申请" if incoming else f"{other_name} 拒绝了你的好友申请"
            detail = "本次好友申请已经结束。"
        else:
            title = f"{other_name} 取消了好友申请" if incoming else f"你取消了发给 {other_name} 的好友申请"
            detail = "本次好友申请已由发送方取消。"
        values.append(
            CustomerHistoryItemView(
                history_id=f"friend-request:{row.id}:{row.status}",
                kind="friend_request",
                action=row.status,
                direction="incoming" if incoming else "outgoing",
                title=title,
                detail=detail,
                occurred_at=occurred_at,
                actor_display_name=actor_name,
                counterparty_account_id=other_id,
                counterparty_display_name=other_name,
                target_kind="friend",
                target_id=other_id,
                target_label="查看好友与申请",
            )
        )
    return values


def _caregiver_history(
    session: Session,
    *,
    account_id: str,
    start: datetime | None,
    end: datetime | None,
) -> list[CustomerHistoryItemView]:
    rows = list(
        session.scalars(
            select(CaregiverInvitation)
            .where(
                CaregiverInvitation.status != "pending",
                or_(
                    CaregiverInvitation.invited_account_id == account_id,
                    CaregiverInvitation.invited_by_account_id == account_id,
                ),
            )
            .order_by(CaregiverInvitation.responded_at.desc(), CaregiverInvitation.id)
            .limit(500)
        )
    )
    values: list[CustomerHistoryItemView] = []
    for row in rows:
        occurred_at = _aware(row.responded_at)
        if occurred_at is None or not _in_range(occurred_at, start, end):
            continue
        incoming = row.invited_account_id == account_id
        other_id = row.invited_by_account_id if incoming else row.invited_account_id
        other_name = _account_name(session, other_id) or "对方"
        pet = session.get(Pet, row.pet_id)
        pet_name = pet.name if pet is not None else "这只宠物"
        actor_id = row.invited_account_id if row.status in {"accepted", "rejected"} else row.invited_by_account_id
        actor_name = _account_name(session, actor_id)
        role_label = "共同照料者" if row.role == "caregiver" else "观察者"
        if row.status == "accepted":
            title = f"你接受了照料 {pet_name} 的邀请" if incoming else f"{other_name} 接受了照料 {pet_name} 的邀请"
            detail = f"共同照料关系已经建立，角色为{role_label}。"
        elif row.status == "rejected":
            title = f"你拒绝了照料 {pet_name} 的邀请" if incoming else f"{other_name} 拒绝了照料 {pet_name} 的邀请"
            detail = "本次共同照料邀请已经结束。"
        else:
            title = f"{other_name} 取消了照料 {pet_name} 的邀请" if incoming else f"你取消了照料 {pet_name} 的邀请"
            detail = "本次共同照料邀请已由邀请方取消。"
        values.append(
            CustomerHistoryItemView(
                history_id=f"caregiver-invitation:{row.id}:{row.status}",
                kind="caregiver_invitation",
                action=row.status,
                direction="incoming" if incoming else "outgoing",
                title=title,
                detail=detail,
                occurred_at=occurred_at,
                actor_display_name=actor_name,
                pet_id=row.pet_id,
                pet_name=pet_name,
                counterparty_account_id=other_id,
                counterparty_display_name=other_name,
                target_kind="shared_care",
                target_id=row.pet_id,
                target_label="查看共同照料",
            )
        )
    return values


def _visit_history(
    session: Session,
    *,
    account_id: str,
    start: datetime | None,
    end: datetime | None,
) -> list[CustomerHistoryItemView]:
    rows = list(
        session.scalars(
            select(PetVisit)
            .where(
                or_(
                    PetVisit.requester_account_id == account_id,
                    PetVisit.host_account_id == account_id,
                )
            )
            .order_by(PetVisit.created_at.desc(), PetVisit.id)
            .limit(500)
        )
    )
    values: list[CustomerHistoryItemView] = []
    for row in rows:
        visitor = session.get(Pet, row.visitor_pet_id)
        host_pet = session.get(Pet, row.host_pet_id)
        visitor_name = visitor.name if visitor is not None else "来访宠物"
        host_pet_name = host_pet.name if host_pet is not None else "接待宠物"
        other_id = row.host_account_id if row.requester_account_id == account_id else row.requester_account_id
        other_name = _account_name(session, other_id) or "对方"
        direction: HistoryDirection = "outgoing" if row.requester_account_id == account_id else "incoming"

        def add(
            action: HistoryAction,
            title: str,
            detail: str,
            occurred_at: datetime | None,
            actor_id: str | None,
        ) -> None:
            timestamp = _aware(occurred_at)
            if timestamp is None or not _in_range(timestamp, start, end):
                return
            values.append(
                CustomerHistoryItemView(
                    history_id=f"visit:{row.id}:{action}:{timestamp.isoformat()}",
                    kind="visit",
                    action=action,
                    direction=direction,
                    title=title,
                    detail=detail,
                    occurred_at=timestamp,
                    actor_display_name=_account_name(session, actor_id),
                    pet_id=row.visitor_pet_id,
                    pet_name=visitor_name,
                    counterparty_account_id=other_id,
                    counterparty_display_name=other_name,
                    target_kind="visit",
                    target_id=row.id,
                    target_label=f"查看 {visitor_name} → {host_pet_name} 的串门时间线",
                )
            )

        if row.status in {"active", "completed", "recalled"}:
            add(
                "accepted",
                f"{host_pet_name} 接受了 {visitor_name} 的串门",
                f"接待方已接受申请，计划停留 {row.duration_minutes} 分钟。",
                row.responded_at or row.started_at,
                row.host_account_id,
            )
        elif row.status == "rejected":
            add(
                "rejected",
                f"{visitor_name} 的串门申请被拒绝",
                "接待方拒绝了本次串门申请。",
                row.responded_at or row.completed_at,
                row.host_account_id,
            )
        elif row.status == "cancelled":
            add(
                "cancelled",
                f"{visitor_name} 的串门申请已取消",
                "申请方取消了本次串门申请。",
                row.responded_at or row.completed_at,
                row.requester_account_id,
            )
        elif row.status == "expired":
            add(
                "expired",
                f"{visitor_name} 的串门申请已过期",
                "申请在规定时间内未处理，系统已自动关闭。",
                row.completed_at or row.responded_at,
                None,
            )

        if row.status in {"completed", "recalled"}:
            return_title, return_detail = _RETURN_LABELS.get(
                row.completion_reason,
                ("串门已经结束", "来访宠物已安全返家。"),
            )
            actor_id = None
            if row.completion_reason == "visit_recalled":
                actor_id = row.requester_account_id
            elif row.completion_reason == "guest_sent_home":
                actor_id = row.host_account_id
            add(
                "returned",
                f"{visitor_name} · {return_title}",
                return_detail,
                row.completed_at,
                actor_id,
            )
    return values


def _reminder_history(
    session: Session,
    *,
    account_id: str,
    start: datetime | None,
    end: datetime | None,
) -> list[CustomerHistoryItemView]:
    event_actions: dict[str, HistoryAction] = {
        "reminder_completed": "completed",
        "reminder_snoozed": "snoozed",
        "reminder_dismissed": "dismissed",
    }
    rows = list(
        session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.account_id == account_id,
                SyncEvent.event_type.in_(tuple(event_actions)),
            )
            .order_by(SyncEvent.created_at.desc(), SyncEvent.sequence.desc())
            .limit(2000)
        )
    )
    actor_name = _account_name(session, account_id)
    values: list[CustomerHistoryItemView] = []
    seen_terminal: set[tuple[str, str]] = set()
    seen_event_ids: set[str] = set()
    for row in rows:
        timestamp = _aware(row.created_at)
        if timestamp is None or not _in_range(timestamp, start, end):
            continue
        payload = _payload(row)
        occurrence = payload.get("occurrence")
        if not isinstance(occurrence, dict):
            continue
        occurrence_id = str(occurrence.get("occurrence_id") or "")
        if not occurrence_id or row.event_id in seen_event_ids:
            continue
        seen_event_ids.add(row.event_id)
        action = event_actions[row.event_type]
        title_text = str(occurrence.get("title") or "提醒")
        content = str(occurrence.get("content") or "").strip()
        if action == "completed":
            title = f"已完成提醒：{title_text}"
            detail = content or "该提醒已经完成。"
        elif action == "dismissed":
            title = f"已忽略提醒：{title_text}"
            detail = content or "该提醒已经忽略。"
        else:
            minutes = payload.get("snooze_minutes")
            title = f"已稍后提醒：{title_text}"
            detail = f"将在 {minutes} 分钟后再次提醒。" if minutes else "提醒时间已经推迟。"
        if action in {"completed", "dismissed"}:
            seen_terminal.add((occurrence_id, action))
        values.append(
            CustomerHistoryItemView(
                history_id=f"reminder-event:{row.event_id}",
                kind="reminder",
                action=action,
                direction="self",
                title=title,
                detail=detail,
                occurred_at=timestamp,
                actor_display_name=actor_name,
                target_kind="reminder",
                target_id=occurrence_id,
                target_label="查看提醒详情",
            )
        )

    terminal_rows = list(
        session.scalars(
            select(ReminderOccurrence)
            .where(
                ReminderOccurrence.account_id == account_id,
                ReminderOccurrence.state.in_(("completed", "dismissed")),
            )
            .order_by(ReminderOccurrence.updated_at.desc(), ReminderOccurrence.id)
            .limit(500)
        )
    )
    for row in terminal_rows:
        action: HistoryAction = "completed" if row.state == "completed" else "dismissed"
        if (row.id, action) in seen_terminal:
            continue
        timestamp = _aware(row.completed_at if action == "completed" else row.dismissed_at) or _aware(row.updated_at)
        if timestamp is None or not _in_range(timestamp, start, end):
            continue
        values.append(
            CustomerHistoryItemView(
                history_id=f"reminder-fallback:{row.id}:{action}",
                kind="reminder",
                action=action,
                direction="self",
                title=("已完成提醒：" if action == "completed" else "已忽略提醒：") + row.title,
                detail=row.content or ("该提醒已经完成。" if action == "completed" else "该提醒已经忽略。"),
                occurred_at=timestamp,
                actor_display_name=actor_name,
                target_kind="reminder",
                target_id=row.id,
                target_label="查看提醒详情",
            )
        )
    return values


@customer_history_router.get("", response_model=CustomerHistoryResponse)
def list_customer_history(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    kind: HistoryFilter = Query(default="all"),
    days: int | None = Query(default=30, ge=1, le=3650),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> CustomerHistoryResponse:
    if start is not None and start.tzinfo is None:
        raise HTTPException(status_code=422, detail="start 必须包含时区")
    if end is not None and end.tzinfo is None:
        raise HTTPException(status_code=422, detail="end 必须包含时区")
    resolved_start = start.astimezone(UTC) if start is not None else None
    resolved_end = end.astimezone(UTC) if end is not None else None
    if resolved_start is None and days is not None:
        resolved_start = datetime.now(UTC) - timedelta(days=days)
    if resolved_start is not None and resolved_end is not None and resolved_start >= resolved_end:
        raise HTTPException(status_code=422, detail="start 必须早于 end")

    settle_due_visits(session)
    items: list[CustomerHistoryItemView] = []
    if kind in {"all", "friend_request"}:
        items.extend(_friend_history(session, account_id=principal.account_id, start=resolved_start, end=resolved_end))
    if kind in {"all", "caregiver_invitation"}:
        items.extend(_caregiver_history(session, account_id=principal.account_id, start=resolved_start, end=resolved_end))
    if kind in {"all", "visit"}:
        items.extend(_visit_history(session, account_id=principal.account_id, start=resolved_start, end=resolved_end))
    if kind in {"all", "reminder"}:
        items.extend(_reminder_history(session, account_id=principal.account_id, start=resolved_start, end=resolved_end))

    items.sort(key=lambda item: (item.occurred_at, item.history_id), reverse=True)
    session.commit()
    return CustomerHistoryResponse(count=len(items), items=items[:limit])
