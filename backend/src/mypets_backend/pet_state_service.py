"""Application service for lazy pet settlement and semantic synchronization events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AccountPetRelation, Pet
from .pet_settlement import SettlementMutation, settle_pet_state
from .services import append_event, pet_view, pets_for_account, relation_view


def settle_pet_and_publish(
    session: Session,
    pet: Pet,
    *,
    now: datetime,
    trigger: str,
) -> SettlementMutation:
    """Settle one pet and publish the resulting authoritative snapshot to every member."""

    mutation = settle_pet_state(pet, now)
    if mutation.elapsed_hours <= 0:
        return mutation
    session.flush()
    if not mutation.changed:
        return mutation

    relations = list(
        session.scalars(
            select(AccountPetRelation).where(AccountPetRelation.pet_id == pet.id)
        )
    )
    for relation in relations:
        payload: dict[str, Any] = {
            "cause": "state_settlement",
            "trigger": trigger,
            "pet": pet_view(pet).model_dump(mode="json"),
            "relation": relation_view(relation).model_dump(mode="json"),
            "settlement": {
                "settled_from": mutation.settled_from.isoformat(),
                "settled_to": mutation.settled_to.isoformat(),
                "elapsed_hours": mutation.elapsed_hours,
                "deltas": mutation.deltas,
            },
        }
        append_event(
            session,
            account_id=relation.account_id,
            event_type="pet_updated",
            idempotency_key=(
                f"pet-settlement:{pet.id}:{pet.state_version}:{relation.account_id}"
            ),
            payload=payload,
        )
    return mutation


def settle_pets_for_account(
    session: Session,
    *,
    account_id: str,
    now: datetime,
    trigger: str,
) -> tuple[list[Pet], list[SettlementMutation]]:
    """Settle every pet visible to an account and return the authoritative objects."""

    pets = pets_for_account(session, account_id)
    mutations = [
        settle_pet_and_publish(session, pet, now=now, trigger=trigger)
        for pet in pets
    ]
    return pets, mutations
