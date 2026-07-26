"""Server-authoritative proactive care preferences and gentle notice evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .models import AccountPetRelation, Pet, SyncEvent
from .proactive_care import (
    DEFAULT_PREFERENCES,
    build_proactive_candidates,
    in_quiet_hours,
    next_quiet_end,
    normalize_preferences,
)
from .reminder_models import ReminderOccurrence
from .security import Principal
from .services import append_event, pets_for_account, relations_for_account


proactive_care_router = APIRouter(prefix="/api/v1/portal/proactive-care", tags=["user-portal"])

PREFERENCE_EVENT = "proactive_care_preferences_updated"
DELIVERED_EVENT = "proactive_care_notice_delivered"
ACK_EVENT = "proactive_care_notice_acknowledged"


class ProactiveCarePreferenceView(BaseModel):
    enabled: bool
    low_state_enabled: bool
    inactivity_enabled: bool
    reminder_enabled: bool
    quiet_hours_enabled: bool
    quiet_start: str
    quiet_end: str
    min_interval_minutes: int
    max_daily_notices: int


class ProactiveCarePreferenceUpdate(BaseModel):
    enabled: bool | None = None
    low_state_enabled: bool | None = None
    inactivity_enabled: bool | None = None
    reminder_enabled: bool | None = None
    quiet_hours_enabled: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    min_interval_minutes: int | None = Field(default=None, ge=15, le=1440)
    max_daily_notices: int | None = Field(default=None, ge=1, le=12)

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def _clock(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.strip().split(":")
        if len(parts) != 2:
            raise ValueError("免打扰时间必须使用 HH:MM 格式")
        try:
            hour, minute = (int(part) for part in parts)
        except ValueError as exc:
            raise ValueError("免打扰时间必须使用 HH:MM 格式") from exc
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("免打扰时间超出有效范围")
        return f"{hour:02d}:{minute:02d}"

    @model_validator(mode="after")
    def _not_empty(self) -> "ProactiveCarePreferenceUpdate":
        if not self.model_dump(exclude_none=True):
            raise ValueError("至少需要修改一项主动关怀设置")
        return self


class ProactiveCareNoticeView(BaseModel):
    notice_key: str
    kind: Literal["low_state", "inactivity", "reminder_due"]
    priority: int
    pet_id: str | None
    title: str
    detail: str
    action_label: str
    care_action: Literal["feed", "play", "clean", "pet", "rest"] | None
    target_section: str
    delivered_at: datetime


class ProactiveCareEvaluateRequest(BaseModel):
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    surface: Literal["web", "desktop"] = "web"
    pet_id: str | None = Field(default=None, max_length=36)


class ProactiveCareEvaluateResponse(BaseModel):
    preferences: ProactiveCarePreferenceView
    notice: ProactiveCareNoticeView | None
    suppression_reason: str
    next_check_at: datetime
    server_time: datetime


class ProactiveCareAcknowledgeRequest(BaseModel):
    notice_key: str = Field(min_length=3, max_length=200)
    outcome: Literal["opened", "acted", "snoozed", "dismissed_today"]
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    snooze_minutes: int = Field(default=120, ge=15, le=1440)


class ProactiveCareAcknowledgeResponse(BaseModel):
    notice_key: str
    outcome: str
    suppress_until: datetime


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _payload(event: SyncEvent) -> dict[str, object]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _preferences(session: Session, account_id: str) -> dict[str, object]:
    row = session.scalar(
        select(SyncEvent)
        .where(
            SyncEvent.account_id == account_id,
            SyncEvent.event_type == PREFERENCE_EVENT,
        )
        .order_by(SyncEvent.sequence.desc())
        .limit(1)
    )
    raw = _payload(row).get("preferences") if row is not None else None
    return normalize_preferences(raw if isinstance(raw, dict) else DEFAULT_PREFERENCES)


def _preference_view(value: dict[str, object]) -> ProactiveCarePreferenceView:
    return ProactiveCarePreferenceView.model_validate(value)


def _last_care_by_pet(
    session: Session,
    *,
    account_id: str,
    now: datetime,
) -> dict[str, datetime]:
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
    values: dict[str, datetime] = {}
    for row in rows:
        payload = _payload(row)
        if payload.get("cause") != "pet_care":
            continue
        interaction = payload.get("interaction")
        if not isinstance(interaction, dict):
            continue
        if interaction.get("actor_account_id") != account_id:
            continue
        pet_id = str(interaction.get("pet_id") or "")
        if not pet_id or pet_id in values:
            continue
        raw = interaction.get("created_at")
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            parsed = _aware(row.created_at)
        values[pet_id] = _aware(parsed)
    return values


def _recent_notice_events(
    session: Session,
    *,
    account_id: str,
    now: datetime,
) -> list[SyncEvent]:
    return list(
        session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.account_id == account_id,
                SyncEvent.event_type.in_((DELIVERED_EVENT, ACK_EVENT)),
                SyncEvent.created_at >= now - timedelta(days=8),
            )
            .order_by(SyncEvent.sequence.desc())
            .limit(2000)
        )
    )


def _local_date(now: datetime, offset_minutes: int) -> str:
    return (now - timedelta(minutes=offset_minutes)).date().isoformat()


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed).astimezone(UTC)


def _eligible_candidate(
    candidates: list[dict[str, object]],
    events: list[SyncEvent],
    *,
    now: datetime,
    preferred_pet_id: str | None,
) -> dict[str, object] | None:
    suppressed_until: dict[str, datetime] = {}
    latest_delivery_by_key: dict[str, datetime] = {}
    for event in events:
        payload = _payload(event)
        key = str(payload.get("notice_key") or "")
        if not key:
            continue
        if event.event_type == ACK_EVENT:
            until = _parse_datetime(payload.get("suppress_until"))
            if until is not None and until > suppressed_until.get(key, datetime.min.replace(tzinfo=UTC)):
                suppressed_until[key] = until
        elif event.event_type == DELIVERED_EVENT and key not in latest_delivery_by_key:
            latest_delivery_by_key[key] = _aware(event.created_at).astimezone(UTC)

    adjusted: list[dict[str, object]] = []
    for candidate in candidates:
        key = str(candidate["notice_key"])
        if suppressed_until.get(key, datetime.min.replace(tzinfo=UTC)) > now:
            continue
        latest = latest_delivery_by_key.get(key)
        if latest is not None and now - latest < timedelta(hours=6):
            continue
        value = dict(candidate)
        if preferred_pet_id and value.get("pet_id") == preferred_pet_id:
            value["priority"] = int(value["priority"]) + 60
        adjusted.append(value)
    return max(adjusted, key=lambda item: int(item["priority"])) if adjusted else None


@proactive_care_router.get("/preferences", response_model=ProactiveCarePreferenceView)
def get_proactive_care_preferences(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ProactiveCarePreferenceView:
    return _preference_view(_preferences(session, principal.account_id))


@proactive_care_router.patch("/preferences", response_model=ProactiveCarePreferenceView)
def update_proactive_care_preferences(
    body: ProactiveCarePreferenceUpdate,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ProactiveCarePreferenceView:
    current = _preferences(session, principal.account_id)
    current.update(body.model_dump(exclude_none=True))
    normalized = normalize_preferences(current)
    append_event(
        session,
        account_id=principal.account_id,
        event_type=PREFERENCE_EVENT,
        idempotency_key=f"proactive-pref:{principal.account_id}:{uuid4()}",
        payload={"preferences": normalized, "updated_by": principal.kind},
    )
    session.commit()
    return _preference_view(normalized)


@proactive_care_router.post("/evaluate", response_model=ProactiveCareEvaluateResponse)
def evaluate_proactive_care(
    body: ProactiveCareEvaluateRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ProactiveCareEvaluateResponse:
    now = datetime.now(UTC)
    prefs = _preferences(session, principal.account_id)
    view = _preference_view(prefs)
    default_next = now + timedelta(minutes=max(15, int(prefs["min_interval_minutes"])))
    if not bool(prefs["enabled"]):
        return ProactiveCareEvaluateResponse(
            preferences=view,
            notice=None,
            suppression_reason="主动关怀已关闭",
            next_check_at=default_next,
            server_time=now,
        )
    if bool(prefs["quiet_hours_enabled"]) and in_quiet_hours(
        now=now,
        timezone_offset_minutes=body.timezone_offset_minutes,
        quiet_start=str(prefs["quiet_start"]),
        quiet_end=str(prefs["quiet_end"]),
    ):
        quiet_end_at = next_quiet_end(
            now=now,
            timezone_offset_minutes=body.timezone_offset_minutes,
            quiet_start=str(prefs["quiet_start"]),
            quiet_end=str(prefs["quiet_end"]),
        )
        return ProactiveCareEvaluateResponse(
            preferences=view,
            notice=None,
            suppression_reason="当前处于免打扰时段",
            next_check_at=quiet_end_at,
            server_time=now,
        )

    pets = pets_for_account(session, principal.account_id)
    relations_list = relations_for_account(session, principal.account_id)
    relations = {relation.pet_id: relation for relation in relations_list}
    if body.pet_id is not None and body.pet_id not in relations:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    reminders = list(
        session.scalars(
            select(ReminderOccurrence)
            .where(ReminderOccurrence.account_id == principal.account_id)
            .order_by(ReminderOccurrence.scheduled_at)
            .limit(500)
        )
    )
    candidates = build_proactive_candidates(
        pets=pets,
        relations=relations,
        last_interactions=_last_care_by_pet(session, account_id=principal.account_id, now=now),
        reminders=reminders,
        preferences=prefs,
        now=now,
    )
    events = _recent_notice_events(session, account_id=principal.account_id, now=now)
    delivered = [event for event in events if event.event_type == DELIVERED_EVENT]
    local_day = _local_date(now, body.timezone_offset_minutes)
    daily_count = sum(_payload(event).get("local_date") == local_day for event in delivered)
    if daily_count >= int(prefs["max_daily_notices"]):
        return ProactiveCareEvaluateResponse(
            preferences=view,
            notice=None,
            suppression_reason="今天的主动提示次数已达到设置上限",
            next_check_at=default_next,
            server_time=now,
        )
    if delivered:
        latest = max(_aware(event.created_at).astimezone(UTC) for event in delivered)
        interval = timedelta(minutes=int(prefs["min_interval_minutes"]))
        if now - latest < interval:
            return ProactiveCareEvaluateResponse(
                preferences=view,
                notice=None,
                suppression_reason="距离上一条主动提示还很近",
                next_check_at=latest + interval,
                server_time=now,
            )

    candidate = _eligible_candidate(
        candidates,
        events,
        now=now,
        preferred_pet_id=body.pet_id,
    )
    if candidate is None:
        return ProactiveCareEvaluateResponse(
            preferences=view,
            notice=None,
            suppression_reason="暂无新的关怀提示",
            next_check_at=default_next,
            server_time=now,
        )

    delivered_at = now
    notice_data = {**candidate, "delivered_at": delivered_at.isoformat()}
    append_event(
        session,
        account_id=principal.account_id,
        event_type=DELIVERED_EVENT,
        idempotency_key=f"proactive-delivery:{principal.account_id}:{uuid4()}",
        payload={
            "notice_key": candidate["notice_key"],
            "kind": candidate["kind"],
            "surface": body.surface,
            "local_date": local_day,
            "notice": notice_data,
        },
    )
    session.commit()
    return ProactiveCareEvaluateResponse(
        preferences=view,
        notice=ProactiveCareNoticeView.model_validate(notice_data),
        suppression_reason="",
        next_check_at=default_next,
        server_time=now,
    )


@proactive_care_router.post("/acknowledge", response_model=ProactiveCareAcknowledgeResponse)
def acknowledge_proactive_care(
    body: ProactiveCareAcknowledgeRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> ProactiveCareAcknowledgeResponse:
    now = datetime.now(UTC)
    if body.outcome == "dismissed_today":
        local_now = now - timedelta(minutes=body.timezone_offset_minutes)
        local_midnight = datetime.combine(local_now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
        suppress_until = local_midnight + timedelta(minutes=body.timezone_offset_minutes)
    elif body.outcome == "snoozed":
        suppress_until = now + timedelta(minutes=body.snooze_minutes)
    elif body.outcome == "acted":
        suppress_until = now + timedelta(hours=6)
    else:
        suppress_until = now + timedelta(minutes=30)
    append_event(
        session,
        account_id=principal.account_id,
        event_type=ACK_EVENT,
        idempotency_key=f"proactive-ack:{principal.account_id}:{uuid4()}",
        payload={
            "notice_key": body.notice_key,
            "outcome": body.outcome,
            "suppress_until": suppress_until.isoformat(),
            "local_date": _local_date(now, body.timezone_offset_minutes),
        },
    )
    session.commit()
    return ProactiveCareAcknowledgeResponse(
        notice_key=body.notice_key,
        outcome=body.outcome,
        suppress_until=suppress_until,
    )
