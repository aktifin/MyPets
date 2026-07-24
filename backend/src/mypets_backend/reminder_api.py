"""Reminder provider import, delivery, snooze, completion, and synchronization events."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .reminder_models import ReminderOccurrence
from .security import Principal
from .services import append_event, find_event_by_idempotency

reminder_router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])

REMINDER_STATES = {
    "pending",
    "delivered",
    "seen",
    "snoozed",
    "completed",
    "dismissed",
    "expired",
}
TERMINAL_STATES = {"completed", "dismissed", "expired"}


class ReminderUpsertRequest(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    source_reminder_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(default="", max_length=4000)
    scheduled_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    priority: str = Field(default="normal", min_length=1, max_length=32)
    category: str = Field(default="general", min_length=1, max_length=64)
    version: int = Field(default=1, ge=1)

    @field_validator(
        "source",
        "source_reminder_id",
        "title",
        "content",
        "timezone",
        "priority",
        "category",
    )
    @classmethod
    def _strip_strings(cls, value: str) -> str:
        return value.strip()

    @field_validator("scheduled_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scheduled_at 必须包含时区")
        return value


class ReminderSnoozeRequest(BaseModel):
    minutes: Literal[5, 10, 30]


class ReminderOccurrenceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    occurrence_id: str
    account_id: str
    source: str
    source_reminder_id: str
    title: str
    content: str
    scheduled_at: datetime
    timezone: str
    state: str
    priority: str
    category: str
    version: int
    snooze_count: int
    last_delivered_at: datetime | None
    completed_at: datetime | None
    dismissed_at: datetime | None
    updated_at: datetime


class ReminderMutationResponse(BaseModel):
    action: str
    occurrence: ReminderOccurrenceView
    idempotency_key: str


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _view(occurrence: ReminderOccurrence) -> ReminderOccurrenceView:
    return ReminderOccurrenceView(
        occurrence_id=occurrence.id,
        account_id=occurrence.account_id,
        source=occurrence.source,
        source_reminder_id=occurrence.source_reminder_id,
        title=occurrence.title,
        content=occurrence.content,
        scheduled_at=_aware(occurrence.scheduled_at),
        timezone=occurrence.timezone,
        state=occurrence.state,
        priority=occurrence.priority,
        category=occurrence.category,
        version=occurrence.version,
        snooze_count=occurrence.snooze_count,
        last_delivered_at=_aware(occurrence.last_delivered_at),
        completed_at=_aware(occurrence.completed_at),
        dismissed_at=_aware(occurrence.dismissed_at),
        updated_at=_aware(occurrence.updated_at),
    )


def _event_payload(event_payload_json: str) -> dict[str, Any]:
    try:
        value = json.loads(event_payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _require_account_principal(principal: Principal) -> None:
    if principal.kind != "account":
        raise HTTPException(status_code=403, detail="提醒来源导入需要账户令牌")


def _require_device_principal(principal: Principal) -> None:
    if principal.kind != "device" or not principal.device_id:
        raise HTTPException(status_code=403, detail="提醒投递确认需要设备令牌")


def _owned_occurrence(
    session: Session,
    account_id: str,
    occurrence_id: str,
) -> ReminderOccurrence:
    occurrence = session.get(ReminderOccurrence, occurrence_id)
    if occurrence is None or occurrence.account_id != account_id:
        raise HTTPException(status_code=404, detail="提醒实例不存在")
    return occurrence


def _prior_occurrence(
    session: Session,
    *,
    account_id: str,
    idempotency_key: str,
    event_type: str,
) -> ReminderOccurrence | None:
    event = find_event_by_idempotency(session, account_id, idempotency_key)
    if event is None:
        return None
    payload = _event_payload(event.payload_json)
    occurrence_data = payload.get("occurrence")
    occurrence_id = (
        occurrence_data.get("occurrence_id")
        if isinstance(occurrence_data, dict)
        else None
    )
    occurrence = session.get(ReminderOccurrence, occurrence_id) if occurrence_id else None
    if event.event_type != event_type or occurrence is None:
        raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
    return occurrence


def _same_provider_payload(
    occurrence: ReminderOccurrence,
    body: ReminderUpsertRequest,
) -> bool:
    return (
        occurrence.source == body.source
        and occurrence.source_reminder_id == body.source_reminder_id
        and occurrence.title == body.title
        and occurrence.content == body.content
        and _aware(occurrence.scheduled_at) == body.scheduled_at.astimezone(UTC)
        and occurrence.timezone == body.timezone
        and occurrence.priority == body.priority
        and occurrence.category == body.category
    )


@reminder_router.post(
    "/occurrences",
    response_model=ReminderOccurrenceView,
    status_code=status.HTTP_201_CREATED,
)
def upsert_occurrence(
    body: ReminderUpsertRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ReminderOccurrenceView:
    _require_account_principal(principal)
    prior = _prior_occurrence(
        session,
        account_id=principal.account_id,
        idempotency_key=idempotency_key,
        event_type="reminder_occurrence_upserted",
    )
    if prior is not None:
        return _view(prior)

    occurrence = session.scalar(
        select(ReminderOccurrence).where(
            ReminderOccurrence.account_id == principal.account_id,
            ReminderOccurrence.source == body.source,
            ReminderOccurrence.source_reminder_id == body.source_reminder_id,
        )
    )
    created = occurrence is None
    now = datetime.now(UTC)
    if occurrence is None:
        occurrence = ReminderOccurrence(
            id=str(uuid4()),
            account_id=principal.account_id,
            source=body.source,
            source_reminder_id=body.source_reminder_id,
            title=body.title,
            content=body.content,
            scheduled_at=body.scheduled_at.astimezone(UTC),
            timezone=body.timezone,
            state="pending",
            priority=body.priority,
            category=body.category,
            version=body.version,
            created_at=now,
            updated_at=now,
        )
        session.add(occurrence)
    else:
        if body.version < occurrence.version:
            raise HTTPException(status_code=409, detail="提醒来源版本已过期")
        if body.version == occurrence.version:
            if not _same_provider_payload(occurrence, body):
                raise HTTPException(status_code=409, detail="同版本提醒内容不一致")
        else:
            if occurrence.state in TERMINAL_STATES:
                raise HTTPException(status_code=409, detail="终态提醒不能被来源更新复活")
            occurrence.title = body.title
            occurrence.content = body.content
            occurrence.scheduled_at = body.scheduled_at.astimezone(UTC)
            occurrence.timezone = body.timezone
            occurrence.priority = body.priority
            occurrence.category = body.category
            occurrence.version = body.version
            occurrence.state = "pending"
            occurrence.last_delivered_at = None
            occurrence.updated_at = now
    session.flush()
    view = _view(occurrence)
    append_event(
        session,
        account_id=principal.account_id,
        event_type="reminder_occurrence_upserted",
        idempotency_key=idempotency_key,
        payload={
            "cause": "provider_created" if created else "provider_updated",
            "occurrence": view.model_dump(mode="json"),
        },
    )
    session.commit()
    return _view(occurrence)


@reminder_router.get("/occurrences", response_model=list[ReminderOccurrenceView])
def list_occurrences(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    state: list[str] | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ReminderOccurrenceView]:
    if start is not None and start.tzinfo is None:
        raise HTTPException(status_code=422, detail="start 必须包含时区")
    if end is not None and end.tzinfo is None:
        raise HTTPException(status_code=422, detail="end 必须包含时区")
    requested_states = set(state or [])
    invalid = requested_states - REMINDER_STATES
    if invalid:
        raise HTTPException(status_code=422, detail=f"无效提醒状态：{sorted(invalid)}")

    statement = select(ReminderOccurrence).where(
        ReminderOccurrence.account_id == principal.account_id
    )
    if start is not None:
        statement = statement.where(ReminderOccurrence.scheduled_at >= start.astimezone(UTC))
    if end is not None:
        statement = statement.where(ReminderOccurrence.scheduled_at < end.astimezone(UTC))
    if requested_states:
        statement = statement.where(ReminderOccurrence.state.in_(requested_states))
    rows = list(
        session.scalars(
            statement.order_by(ReminderOccurrence.scheduled_at, ReminderOccurrence.id).limit(limit)
        )
    )
    return [_view(row) for row in rows]


def _mutate_occurrence(
    *,
    occurrence_id: str,
    action: Literal["delivered", "completed", "snoozed", "dismissed"],
    idempotency_key: str,
    principal: Principal,
    session: Session,
    snooze_minutes: int | None = None,
) -> ReminderMutationResponse:
    event_type = {
        "delivered": "reminder_delivered",
        "completed": "reminder_completed",
        "snoozed": "reminder_snoozed",
        "dismissed": "reminder_dismissed",
    }[action]
    prior = _prior_occurrence(
        session,
        account_id=principal.account_id,
        idempotency_key=idempotency_key,
        event_type=event_type,
    )
    if prior is not None:
        return ReminderMutationResponse(
            action=action,
            occurrence=_view(prior),
            idempotency_key=idempotency_key,
        )

    occurrence = _owned_occurrence(session, principal.account_id, occurrence_id)
    now = datetime.now(UTC)
    if occurrence.state in TERMINAL_STATES:
        if (
            (action == "completed" and occurrence.state == "completed")
            or (action == "dismissed" and occurrence.state == "dismissed")
        ):
            pass
        else:
            raise HTTPException(status_code=409, detail="终态提醒不能再次变更")
    elif action == "delivered":
        occurrence.state = "delivered"
        occurrence.last_delivered_at = now
    elif action == "completed":
        occurrence.state = "completed"
        occurrence.completed_at = now
    elif action == "dismissed":
        occurrence.state = "dismissed"
        occurrence.dismissed_at = now
    elif action == "snoozed":
        if snooze_minutes not in {5, 10, 30}:
            raise HTTPException(status_code=422, detail="只支持 5、10 或 30 分钟贪睡")
        occurrence.state = "pending"
        occurrence.scheduled_at = now + timedelta(minutes=snooze_minutes)
        occurrence.snooze_count += 1
        occurrence.version += 1
        occurrence.last_delivered_at = None
    occurrence.updated_at = now
    session.flush()
    view = _view(occurrence)
    append_event(
        session,
        account_id=principal.account_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload={
            "action": action,
            "device_id": principal.device_id,
            "snooze_minutes": snooze_minutes,
            "occurrence": view.model_dump(mode="json"),
        },
    )
    session.commit()
    return ReminderMutationResponse(
        action=action,
        occurrence=_view(occurrence),
        idempotency_key=idempotency_key,
    )


@reminder_router.post(
    "/occurrences/{occurrence_id}/delivered",
    response_model=ReminderMutationResponse,
)
def mark_delivered(
    occurrence_id: str,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ReminderMutationResponse:
    _require_device_principal(principal)
    return _mutate_occurrence(
        occurrence_id=occurrence_id,
        action="delivered",
        idempotency_key=idempotency_key,
        principal=principal,
        session=session,
    )


@reminder_router.post(
    "/occurrences/{occurrence_id}/complete",
    response_model=ReminderMutationResponse,
)
def complete_occurrence(
    occurrence_id: str,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ReminderMutationResponse:
    return _mutate_occurrence(
        occurrence_id=occurrence_id,
        action="completed",
        idempotency_key=idempotency_key,
        principal=principal,
        session=session,
    )


@reminder_router.post(
    "/occurrences/{occurrence_id}/snooze",
    response_model=ReminderMutationResponse,
)
def snooze_occurrence(
    occurrence_id: str,
    body: ReminderSnoozeRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ReminderMutationResponse:
    return _mutate_occurrence(
        occurrence_id=occurrence_id,
        action="snoozed",
        idempotency_key=idempotency_key,
        principal=principal,
        session=session,
        snooze_minutes=body.minutes,
    )


@reminder_router.post(
    "/occurrences/{occurrence_id}/dismiss",
    response_model=ReminderMutationResponse,
)
def dismiss_occurrence(
    occurrence_id: str,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ReminderMutationResponse:
    return _mutate_occurrence(
        occurrence_id=occurrence_id,
        action="dismissed",
        idempotency_key=idempotency_key,
        principal=principal,
        session=session,
    )
