"""Deterministic lazy settlement for elapsed pet state.

Settlement is invoked by authenticated reads and care operations instead of a per-second
background job. The pet's server-side ``updated_at`` timestamp is the settlement anchor,
so the existing schema remains compatible with development databases created before this
feature. Values are clamped and health never drops below a protected floor; MyPets does
not implement pet death.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .models import Pet

MAX_SETTLEMENT_HOURS = 24 * 30
HEALTH_FLOOR = 50


@dataclass(frozen=True)
class SettlementMutation:
    settled_from: datetime
    settled_to: datetime
    elapsed_hours: int
    deltas: dict[str, int]

    @property
    def changed(self) -> bool:
        return any(value != 0 for value in self.deltas.values())


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _clamp(value: int) -> int:
    return min(100, max(0, int(value)))


STAGE_TRANSITIONS = (
    ("newborn", "child", 1, 100),
    ("child", "juvenile", 3, 300),
    ("juvenile", "adult", 7, 700),
    ("adult", "bond", 14, 1500),
)


def evaluate_growth_stage_transition(pet: Pet, age_days: int) -> str | None:
    """按陪伴天数与成长经验计算阶段晋升目标。"""

    current_stage = (pet.growth_stage or "newborn").lower()
    exp = int(pet.growth_exp or 0)
    for from_stage, to_stage, min_days, min_exp in STAGE_TRANSITIONS:
        if current_stage == from_stage:
            if age_days >= min_days and exp >= min_exp:
                return to_stage
            break
    return None


def settle_pet_state(pet: Pet, now: datetime) -> SettlementMutation:
    """Apply whole-hour elapsed state changes once and advance the settlement anchor."""

    current_time = _aware(now)
    created_anchor = _aware(pet.created_at or current_time)
    anchor = pet.updated_at or pet.created_at or current_time
    settled_from = _aware(anchor)
    if current_time <= settled_from:
        return SettlementMutation(settled_from, settled_from, 0, {})

    elapsed_hours = min(
        MAX_SETTLEMENT_HOURS,
        int((current_time - settled_from).total_seconds() // 3600),
    )
    if elapsed_hours <= 0:
        return SettlementMutation(settled_from, settled_from, 0, {})

    before = {
        "hunger": int(pet.hunger if pet.hunger is not None else 100),
        "energy": int(pet.energy if pet.energy is not None else 100),
        "mood": int(pet.mood if pet.mood is not None else 80),
        "cleanliness": int(pet.cleanliness if pet.cleanliness is not None else 100),
        "health": int(pet.health if pet.health is not None else 100),
        "boredom": int(pet.boredom if pet.boredom is not None else 0),
    }
    for field, value in before.items():
        setattr(pet, field, value)

    for _hour in range(elapsed_hours):
        pet.hunger = _clamp(int(pet.hunger) - 2)
        if pet.presence == "resting":
            pet.energy = _clamp(int(pet.energy) + 2)
        else:
            pet.energy = _clamp(int(pet.energy) - 1)
        pet.mood = _clamp(int(pet.mood) - 1)
        pet.cleanliness = _clamp(int(pet.cleanliness) - 1)
        pet.boredom = _clamp(int(pet.boredom) + 2)
        if int(pet.hunger) <= 10 or int(pet.cleanliness) <= 10:
            pet.health = max(HEALTH_FLOOR, int(pet.health) - 1)

    age_days = max(0, int((current_time - created_anchor).total_seconds() // 86400))
    next_stage = evaluate_growth_stage_transition(pet, age_days)
    if next_stage:
        pet.growth_stage = next_stage

    deltas = {
        field: int(getattr(pet, field)) - value
        for field, value in before.items()
    }
    if any(value != 0 for value in deltas.values()) or next_stage:
        pet.state_version = max(1, int(pet.state_version or 1) + 1)
    pet.updated_at = current_time
    return SettlementMutation(
        settled_from=settled_from,
        settled_to=current_time,
        elapsed_hours=elapsed_hours,
        deltas=deltas,
    )

