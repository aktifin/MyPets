"""Authoritative multi-pet party lifecycle, event publication, and lazy settlement."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AccountPetRelation, Pet
from .party_models import PetParty, PetPartyMember
from .services import append_event, pet_view


_PARTY_TERMINAL = {"completed", "cancelled"}
_ACTIVE_MEMBER_STATES = {"accepted", "joined"}
_RESTRICTED_INVITATION_STATES = {"declined", "expired"}


def party_members(session: Session, party_id: str) -> list[PetPartyMember]:
    return list(
        session.scalars(
            select(PetPartyMember)
            .where(PetPartyMember.party_id == party_id)
            .order_by(PetPartyMember.created_at, PetPartyMember.id)
        )
    )


def _party_payload(
    party: PetParty,
    members: list[PetPartyMember],
    *,
    cause: str,
    visibility: str = "participant",
) -> dict[str, object]:
    return {
        "cause": cause,
        "visibility": visibility,
        "party_id": party.id,
        "host_account_id": party.host_account_id,
        "host_pet_id": party.host_pet_id,
        "status": party.status,
        "title": party.title,
        "max_members": party.max_members,
        "duration_minutes": party.duration_minutes,
        "completion_reason": party.completion_reason,
        "created_at": party.created_at.isoformat() if party.created_at else None,
        "started_at": party.started_at.isoformat() if party.started_at else None,
        "scheduled_end_at": (
            party.scheduled_end_at.isoformat() if party.scheduled_end_at else None
        ),
        "ended_at": party.ended_at.isoformat() if party.ended_at else None,
        "members": [
            {
                "member_id": item.id,
                "account_id": item.account_id,
                "pet_id": item.pet_id,
                "role": item.role,
                "status": item.status,
                "joined_at": item.joined_at.isoformat() if item.joined_at else None,
                "left_at": item.left_at.isoformat() if item.left_at else None,
            }
            for item in members
        ],
    }


def _restricted_notice_is_relevant(
    party: PetParty,
    member: PetPartyMember,
    *,
    cause: str,
) -> bool:
    """Return whether a terminal invitee should receive one final lifecycle notice.

    Declined and expired invitees keep their own invitation record, but they must not continue
    receiving roster changes, interactions, departures, or completion updates that happen after
    their participation opportunity has ended.
    """

    if member.status == "declined":
        return cause == f"party_declined:{member.id}"
    if member.status != "expired":
        return True
    if cause == "party_started":
        return bool(
            member.responded_at
            and party.started_at
            and member.responded_at == party.started_at
        )
    if cause == "party_cancelled":
        return True
    return False


def _visible_members_for_recipient(
    values: list[PetPartyMember],
    recipient: PetPartyMember,
) -> tuple[list[PetPartyMember], str]:
    if recipient.status not in _RESTRICTED_INVITATION_STATES:
        return values, "participant"
    visible = [
        item
        for item in values
        if item.role == "host" or item.account_id == recipient.account_id
    ]
    return visible, "invitation_record"


def publish_party_update(
    session: Session,
    party: PetParty,
    *,
    cause: str,
    members: list[PetPartyMember] | None = None,
) -> None:
    values = members if members is not None else party_members(session, party.id)
    recipients = {item.account_id: item for item in values}
    for account_id, recipient in recipients.items():
        if recipient.status in _RESTRICTED_INVITATION_STATES and not _restricted_notice_is_relevant(
            party,
            recipient,
            cause=cause,
        ):
            continue
        visible_members, visibility = _visible_members_for_recipient(values, recipient)
        payload = {
            "party": _party_payload(
                party,
                visible_members,
                cause=cause,
                visibility=visibility,
            )
        }
        append_event(
            session,
            account_id=account_id,
            event_type="pet_party_updated",
            idempotency_key=(
                f"pet-party:{party.id}:{party.status}:{cause}:account:{account_id}"
            ),
            payload=payload,
        )


def publish_party_pet(
    session: Session,
    party: PetParty,
    pet: Pet,
    *,
    cause: str,
) -> None:
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
                f"pet-party:{party.id}:{party.status}:{cause}:pet:{pet.id}:"
                f"account:{relation.account_id}"
            ),
            payload={"cause": cause, "party_id": party.id, "pet": snapshot},
        )


def _restore_member_pet(
    session: Session,
    party: PetParty,
    member: PetPartyMember,
    *,
    now: datetime,
    cause: str,
) -> None:
    if not member.pet_id:
        return
    pet = session.get(Pet, member.pet_id)
    if pet is None:
        return
    if pet.presence == "gathering":
        pet.presence = "home"
    pet.state_version += 1
    pet.updated_at = now
    session.flush()
    publish_party_pet(session, party, pet, cause=cause)


def finish_party(
    session: Session,
    party: PetParty,
    *,
    now: datetime,
    reason: str,
    cancelled: bool = False,
) -> bool:
    if party.status in _PARTY_TERMINAL:
        return False
    values = party_members(session, party.id)
    party.status = "cancelled" if cancelled else "completed"
    party.completion_reason = reason
    party.ended_at = now
    for member in values:
        if member.status == "joined":
            member.status = "completed"
            member.left_at = now
            _restore_member_pet(session, party, member, now=now, cause=reason)
        elif cancelled and member.role == "host" and member.status == "accepted":
            member.status = "completed"
            member.left_at = now
        elif member.status in {"invited", "accepted"}:
            member.status = "expired"
            member.responded_at = member.responded_at or now
    session.flush()
    publish_party_update(session, party, cause=reason, members=values)
    return True


def settle_due_parties(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[PetParty]:
    effective_now = now or datetime.now(UTC)
    values = list(
        session.scalars(
            select(PetParty).where(
                PetParty.status == "active",
                PetParty.scheduled_end_at.is_not(None),
                PetParty.scheduled_end_at <= effective_now,
            )
        )
    )
    changed: list[PetParty] = []
    for party in values:
        if finish_party(
            session,
            party,
            now=effective_now,
            reason="party_auto_ended",
        ):
            changed.append(party)
    return changed


def has_open_party_for_pet(
    session: Session,
    pet_id: str,
    *,
    exclude_party_id: str | None = None,
) -> bool:
    statement = (
        select(PetPartyMember.id)
        .join(PetParty, PetParty.id == PetPartyMember.party_id)
        .where(
            PetPartyMember.pet_id == pet_id,
            PetPartyMember.status.in_(_ACTIVE_MEMBER_STATES),
            PetParty.status.in_({"open", "active"}),
        )
    )
    if exclude_party_id:
        statement = statement.where(PetParty.id != exclude_party_id)
    return session.scalar(statement.limit(1)) is not None
