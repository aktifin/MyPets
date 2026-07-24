"""Object-shaped reminder snapshot for shared desktop transport compatibility."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session
from .reminder_api import ReminderOccurrenceView, _view
from .reminder_models import ReminderOccurrence
from .security import Principal

reminder_snapshot_router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])


class ReminderSnapshotResponse(BaseModel):
    items: list[ReminderOccurrenceView]
    server_time: datetime
    count: int


@reminder_snapshot_router.get("/snapshot", response_model=ReminderSnapshotResponse)
def reminder_snapshot(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=500, ge=1, le=500),
) -> ReminderSnapshotResponse:
    rows = list(
        session.scalars(
            select(ReminderOccurrence)
            .where(ReminderOccurrence.account_id == principal.account_id)
            .order_by(ReminderOccurrence.scheduled_at, ReminderOccurrence.id)
            .limit(limit)
        )
    )
    items = [_view(row) for row in rows]
    return ReminderSnapshotResponse(
        items=items,
        server_time=datetime.now(UTC),
        count=len(items),
    )
