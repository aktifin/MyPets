"""Serialization, authorization queries, and append-only sync event helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import Account, AccountPetRelation, Device, Pet, SyncEvent
from .schemas import (
    AccountView,
    DeviceView,
    PetStatsView,
    PetView,
    RelationView,
    SyncEventView,
)


def account_view(account: Account) -> AccountView:
    return AccountView(
        id=account.id,
        username=account.username,
        display_name=account.display_name,
        created_at=_aware(account.created_at),
    )


def device_view(device: Device) -> DeviceView:
    return DeviceView(
        id=device.id,
        public_id=device.public_id,
        name=device.name,
        platform=device.platform,
        active_pet_id=device.active_pet_id,
        last_seen_at=_aware(device.last_seen_at) if device.last_seen_at else None,
        revoked_at=_aware(device.revoked_at) if device.revoked_at else None,
        created_at=_aware(device.created_at),
    )


def pet_view(pet: Pet) -> PetView:
    return PetView(
        pet_id=pet.id,
        name=pet.name,
        template_id=pet.template_id,
        template_version=pet.template_version,
        identity_version=pet.identity_version,
        primary_owner_account_id=pet.primary_owner_account_id,
        presence=pet.presence,
        personality_type=pet.personality_type,
        asset_version=pet.asset_version,
        stats=PetStatsView(
            growth_stage=pet.growth_stage,
            growth_level=pet.growth_level,
            growth_exp=pet.growth_exp,
            bond_level=pet.bond_level,
            bond_exp=pet.bond_exp,
            hunger=pet.hunger,
            energy=pet.energy,
            mood=pet.mood,
            cleanliness=pet.cleanliness,
            health=pet.health,
            boredom=pet.boredom,
            state_version=pet.state_version,
        ),
        updated_at=_aware(pet.updated_at),
    )


def relation_view(relation: AccountPetRelation) -> RelationView:
    return RelationView.model_validate(relation)


def event_view(event: SyncEvent) -> SyncEventView:
    return SyncEventView(
        sequence_number=event.sequence,
        event_id=event.event_id,
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        created_at=_aware(event.created_at),
        target_account_id=event.account_id,
        target_device_id=event.target_device_id,
        payload=json.loads(event.payload_json),
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def pet_for_account(session: Session, account_id: str, pet_id: str) -> Pet | None:
    return session.scalar(
        select(Pet)
        .join(AccountPetRelation, AccountPetRelation.pet_id == Pet.id)
        .where(
            AccountPetRelation.account_id == account_id,
            Pet.id == pet_id,
        )
    )


def pets_for_account(session: Session, account_id: str) -> list[Pet]:
    return list(
        session.scalars(
            select(Pet)
            .join(AccountPetRelation, AccountPetRelation.pet_id == Pet.id)
            .where(AccountPetRelation.account_id == account_id)
            .order_by(Pet.created_at, Pet.id)
        )
    )


def relations_for_account(
    session: Session, account_id: str
) -> list[AccountPetRelation]:
    return list(
        session.scalars(
            select(AccountPetRelation)
            .where(AccountPetRelation.account_id == account_id)
            .order_by(AccountPetRelation.pet_id)
        )
    )


def current_cursor(session: Session, account_id: str) -> int:
    return int(
        session.scalar(
            select(func.coalesce(func.max(SyncEvent.sequence), 0)).where(
                SyncEvent.account_id == account_id
            )
        )
        or 0
    )


def find_event_by_idempotency(
    session: Session, account_id: str, idempotency_key: str
) -> SyncEvent | None:
    return session.scalar(
        select(SyncEvent).where(
            SyncEvent.account_id == account_id,
            SyncEvent.idempotency_key == idempotency_key,
        )
    )


def append_event(
    session: Session,
    *,
    account_id: str,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    target_device_id: str | None = None,
) -> SyncEvent:
    existing = find_event_by_idempotency(session, account_id, idempotency_key)
    if existing is not None:
        return existing
    event = SyncEvent(
        event_id=str(uuid4()),
        account_id=account_id,
        target_device_id=target_device_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    session.add(event)
    session.flush()
    return event


def events_after(
    session: Session,
    *,
    account_id: str,
    device_id: str,
    after_sequence: int,
    limit: int,
) -> tuple[list[SyncEvent], bool]:
    rows = list(
        session.scalars(
            select(SyncEvent)
            .where(
                SyncEvent.account_id == account_id,
                SyncEvent.sequence > after_sequence,
                or_(
                    SyncEvent.target_device_id.is_(None),
                    SyncEvent.target_device_id == device_id,
                ),
            )
            .order_by(SyncEvent.sequence)
            .limit(limit + 1)
        )
    )
    return rows[:limit], len(rows) > limit
