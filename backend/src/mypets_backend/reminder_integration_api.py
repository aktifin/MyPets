"""Authenticated MyReminder rule synchronization into server-authoritative occurrences."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .config import Settings
from .models import Account
from .myreminder_provider import MyReminderHttpProvider
from .reminder_models import ReminderOccurrence
from .reminder_provider import ReminderProvider
from .security import Principal
from .services import append_event

reminder_integration_router = APIRouter(
    prefix="/api/v1/reminder-providers",
    tags=["reminder-providers"],
)

_NON_TERMINAL_STATES = {"pending", "delivered", "seen", "snoozed"}


class MyReminderProviderStatus(BaseModel):
    provider: str = "myreminder"
    configured: bool
    base_url: str | None
    lookback_days: int
    horizon_days: int


class MyReminderSyncResponse(BaseModel):
    provider: str = "myreminder"
    account_id: str
    external_username: str
    window_start: datetime
    window_end: datetime
    pulled: int
    created: int
    updated: int
    unchanged: int
    terminal_preserved: int
    expired: int


def _settings(request: Request) -> Settings:
    value = request.app.state.settings
    if not isinstance(value, Settings):
        raise RuntimeError("应用配置类型无效")
    return value


def _provider(request: Request, settings: Settings) -> ReminderProvider:
    factory: Callable[[Settings], ReminderProvider] | None = getattr(
        request.app.state,
        "myreminder_provider_factory",
        None,
    )
    if factory is not None:
        return factory(settings)
    if not settings.myreminder_configured:
        raise HTTPException(status_code=503, detail="MyReminder Provider 尚未配置")
    return MyReminderHttpProvider(
        base_url=settings.myreminder_base_url,
        integration_secret=settings.myreminder_integration_secret,
        timeout_seconds=settings.myreminder_timeout_seconds,
    )


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _payload(occurrence: ReminderOccurrence) -> dict[str, object]:
    return {
        "occurrence_id": occurrence.id,
        "account_id": occurrence.account_id,
        "source": occurrence.source,
        "source_reminder_id": occurrence.source_reminder_id,
        "title": occurrence.title,
        "content": occurrence.content,
        "scheduled_at": _aware(occurrence.scheduled_at).isoformat(),
        "timezone": occurrence.timezone,
        "state": occurrence.state,
        "priority": occurrence.priority,
        "category": occurrence.category,
        "version": occurrence.version,
        "snooze_count": occurrence.snooze_count,
        "last_delivered_at": (
            _aware(occurrence.last_delivered_at).isoformat()
            if occurrence.last_delivered_at
            else None
        ),
        "completed_at": (
            _aware(occurrence.completed_at).isoformat() if occurrence.completed_at else None
        ),
        "dismissed_at": (
            _aware(occurrence.dismissed_at).isoformat() if occurrence.dismissed_at else None
        ),
        "updated_at": _aware(occurrence.updated_at).isoformat(),
    }


def _same_source_values(current: ReminderOccurrence, incoming) -> bool:
    return (
        current.title == incoming.title
        and current.content == incoming.content
        and _aware(current.scheduled_at) == incoming.scheduled_at.astimezone(UTC)
        and current.timezone == incoming.timezone
        and current.priority == incoming.priority
        and current.category == incoming.category
    )


@reminder_integration_router.get(
    "/myreminder/status",
    response_model=MyReminderProviderStatus,
)
def myreminder_status(
    request: Request,
    _principal: Annotated[Principal, Depends(get_principal)],
) -> MyReminderProviderStatus:
    settings = _settings(request)
    return MyReminderProviderStatus(
        configured=settings.myreminder_configured,
        base_url=settings.myreminder_base_url or None,
        lookback_days=settings.myreminder_lookback_days,
        horizon_days=settings.myreminder_horizon_days,
    )


@reminder_integration_router.post(
    "/myreminder/sync",
    response_model=MyReminderSyncResponse,
)
def sync_myreminder(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> MyReminderSyncResponse:
    settings = _settings(request)
    account = session.get(Account, principal.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")

    now = datetime.now(UTC)
    window_start = now - timedelta(days=settings.myreminder_lookback_days)
    window_end = now + timedelta(days=settings.myreminder_horizon_days)
    provider = _provider(request, settings)
    try:
        pulled_values = list(
            provider.pull_occurrences(
                account_external_id=account.username,
                window_start=window_start,
                window_end=window_end,
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    source_ids: set[str] = set()
    created = updated = unchanged = terminal_preserved = 0
    for incoming in pulled_values:
        source_id = incoming.source_reminder_id.strip()
        if not source_id or source_id in source_ids:
            raise HTTPException(status_code=502, detail="MyReminder 返回重复或空 occurrence 标识")
        source_ids.add(source_id)
        current = session.scalar(
            select(ReminderOccurrence).where(
                ReminderOccurrence.account_id == account.id,
                ReminderOccurrence.source == provider.provider_id,
                ReminderOccurrence.source_reminder_id == source_id,
            )
        )
        if current is None:
            current = ReminderOccurrence(
                id=str(uuid4()),
                account_id=account.id,
                source=provider.provider_id,
                source_reminder_id=source_id,
                title=incoming.title,
                content=incoming.content,
                scheduled_at=incoming.scheduled_at.astimezone(UTC),
                timezone=incoming.timezone,
                state="pending",
                priority=incoming.priority,
                category=incoming.category,
                version=max(1, incoming.version),
                created_at=now,
                updated_at=now,
            )
            session.add(current)
            session.flush()
            created += 1
        elif current.state not in _NON_TERMINAL_STATES:
            terminal_preserved += 1
            continue
        elif current.snooze_count > 0:
            unchanged += 1
            continue
        elif _same_source_values(current, incoming):
            unchanged += 1
            continue
        else:
            current.title = incoming.title
            current.content = incoming.content
            current.scheduled_at = incoming.scheduled_at.astimezone(UTC)
            current.timezone = incoming.timezone
            current.priority = incoming.priority
            current.category = incoming.category
            current.version = max(current.version + 1, incoming.version)
            current.state = "pending"
            current.last_delivered_at = None
            current.updated_at = now
            session.flush()
            updated += 1

        append_event(
            session,
            account_id=account.id,
            event_type="reminder_occurrence_upserted",
            idempotency_key=(
                f"myreminder-sync:{current.id}:version:{current.version}"
            ),
            payload={
                "cause": "provider_created" if current.created_at == now else "provider_updated",
                "provider": provider.provider_id,
                "occurrence": _payload(current),
            },
        )

    existing_window = list(
        session.scalars(
            select(ReminderOccurrence).where(
                ReminderOccurrence.account_id == account.id,
                ReminderOccurrence.source == provider.provider_id,
                ReminderOccurrence.scheduled_at >= window_start,
                ReminderOccurrence.scheduled_at < window_end,
            )
        )
    )
    expired = 0
    for current in existing_window:
        if current.source_reminder_id in source_ids or current.state not in _NON_TERMINAL_STATES:
            continue
        current.state = "expired"
        current.version += 1
        current.updated_at = now
        session.flush()
        expired += 1
        append_event(
            session,
            account_id=account.id,
            event_type="reminder_expired",
            idempotency_key=f"myreminder-expire:{current.id}:version:{current.version}",
            payload={
                "cause": "provider_rule_absent_or_disabled",
                "provider": provider.provider_id,
                "occurrence": _payload(current),
            },
        )

    session.commit()
    return MyReminderSyncResponse(
        account_id=account.id,
        external_username=account.username,
        window_start=window_start,
        window_end=window_end,
        pulled=len(pulled_values),
        created=created,
        updated=updated,
        unchanged=unchanged,
        terminal_preserved=terminal_preserved,
        expired=expired,
    )
