"""Authoritative asynchronous visit transitions and lazy automatic return."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import AccountPetRelation, Pet
from .services import append_event, pet_view
from .visit_models import PetVisit


_TERMINAL = {"rejected", "cancelled", "completed", "recalled", "expired"}
_VISIT_REQUEST_TTL = timedelta(hours=24)


def _visit_payload(visit: PetVisit, cause: str) -> dict[str, object]:
    return {
        "cause": cause,
        "visit_id": visit.id,
        "status": visit.status,
        "requester_account_id": visit.requester_account_id,
        "host_account_id": visit.host_account_id,
        "visitor_pet_id": visit.visitor_pet_id,
        "host_pet_id": visit.host_pet_id,
        "duration_minutes": visit.duration_minutes,
        "completion_reason": visit.completion_reason,
        "started_at": visit.started_at.isoformat() if visit.started_at else None,
        "scheduled_end_at": visit.scheduled_end_at.isoformat() if visit.scheduled_end_at else None,
        "completed_at": visit.completed_at.isoformat() if visit.completed_at else None,
    }


def publish_visit_update(session: Session, visit: PetVisit, *, cause: str) -> None:
    payload = {"visit": _visit_payload(visit, cause)}
    for account_id in {visit.requester_account_id, visit.host_account_id}:
        append_event(
            session,
            account_id=account_id,
            event_type="pet_visit_updated",
            idempotency_key=f"pet-visit:{visit.id}:{visit.status}:{cause}:account:{account_id}",
            payload=payload,
        )


def publish_visitor_pet(session: Session, visit: PetVisit, pet: Pet, *, cause: str) -> None:
    relations = list(
        session.scalars(
            select(AccountPetRelation).where(AccountPetRelation.pet_id == pet.id)
        )
    )
    snapshot = pet_view(pet).model_dump(mode="json")
    for relation in relations:
        append_event(
            session,
            account_id=relation.account_id,
            event_type="pet_updated",
            idempotency_key=(
                f"pet-visit:{visit.id}:{visit.status}:{cause}:pet:{pet.id}:"
                f"account:{relation.account_id}"
            ),
            payload={"cause": cause, "visit_id": visit.id, "pet": snapshot},
        )


def finish_visit(
    session: Session,
    visit: PetVisit,
    *,
    now: datetime,
    status: str,
    reason: str,
) -> bool:
    if visit.status != "active":
        return False
    visit.status = status
    visit.completion_reason = reason
    visit.completed_at = now
    visitor = session.get(Pet, visit.visitor_pet_id)
    if visitor is not None:
        if visitor.presence == "visiting":
            visitor.presence = "home"
        visitor.state_version += 1
        visitor.updated_at = now
        session.flush()
        publish_visitor_pet(session, visit, visitor, cause=reason)
    publish_visit_update(session, visit, cause=reason)
    return True


def settle_due_visits(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[PetVisit]:
    effective_now = now or datetime.now(UTC)
    active_values = list(
        session.scalars(
            select(PetVisit).where(
                PetVisit.status == "active",
                PetVisit.scheduled_end_at.is_not(None),
                PetVisit.scheduled_end_at <= effective_now,
            )
        )
    )
    pending_values = list(
        session.scalars(
            select(PetVisit).where(
                PetVisit.status == "pending",
                PetVisit.created_at <= effective_now - _VISIT_REQUEST_TTL,
            )
        )
    )
    changed: list[PetVisit] = []
    for visit in active_values:
        if finish_visit(
            session,
            visit,
            now=effective_now,
            status="completed",
            reason="visit_auto_returned",
        ):
            changed.append(visit)
    for visit in pending_values:
        visit.status = "expired"
        visit.completion_reason = "visit_request_expired"
        visit.responded_at = effective_now
        visit.completed_at = effective_now
        publish_visit_update(session, visit, cause="visit_request_expired")
        changed.append(visit)
    return changed


def terminate_visits_between(
    session: Session,
    left_account_id: str,
    right_account_id: str,
    *,
    now: datetime | None = None,
    reason: str = "account_blocked",
) -> list[PetVisit]:
    effective_now = now or datetime.now(UTC)
    values = list(
        session.scalars(
            select(PetVisit).where(
                PetVisit.status.in_({"pending", "active"}),
                or_(
                    (
                        (PetVisit.requester_account_id == left_account_id)
                        & (PetVisit.host_account_id == right_account_id)
                    ),
                    (
                        (PetVisit.requester_account_id == right_account_id)
                        & (PetVisit.host_account_id == left_account_id)
                    ),
                ),
            )
        )
    )
    changed: list[PetVisit] = []
    for visit in values:
        if visit.status == "active":
            finish_visit(
                session,
                visit,
                now=effective_now,
                status="recalled",
                reason=reason,
            )
        else:
            visit.status = "cancelled"
            visit.completion_reason = reason
            visit.responded_at = effective_now
            visit.completed_at = effective_now
            publish_visit_update(session, visit, cause=reason)
        changed.append(visit)
    return changed


def has_open_visit_for_pet(session: Session, pet_id: str, *, exclude_id: str | None = None) -> bool:
    statement = select(PetVisit.id).where(
        PetVisit.visitor_pet_id == pet_id,
        PetVisit.status.in_({"pending", "active"}),
    )
    if exclude_id:
        statement = statement.where(PetVisit.id != exclude_id)
    return session.scalar(statement.limit(1)) is not None


def is_terminal(status: str) -> bool:
    return status in _TERMINAL
