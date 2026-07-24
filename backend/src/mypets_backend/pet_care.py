"""Deterministic server-authoritative pet care rules.

This module contains no HTTP or Qt dependencies. It mutates a Pet and the actor's
AccountPetRelation inside the caller's database transaction, then returns an explicit
summary suitable for API responses, synchronization events, and tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import AccountPetRelation, Pet

CareAction = Literal["feed", "play", "clean", "pet", "rest"]


@dataclass(frozen=True)
class CareRule:
    stat_deltas: dict[str, int]
    growth_exp: int
    bond_exp: int
    affinity: int
    contribution: int


CARE_RULES: dict[CareAction, CareRule] = {
    "feed": CareRule(
        stat_deltas={"hunger": 18, "mood": 2, "boredom": -1},
        growth_exp=4,
        bond_exp=2,
        affinity=2,
        contribution=2,
    ),
    "play": CareRule(
        stat_deltas={"energy": -12, "mood": 10, "boredom": -18, "hunger": -3},
        growth_exp=7,
        bond_exp=4,
        affinity=4,
        contribution=4,
    ),
    "clean": CareRule(
        stat_deltas={"cleanliness": 25, "mood": 3},
        growth_exp=3,
        bond_exp=2,
        affinity=2,
        contribution=3,
    ),
    "pet": CareRule(
        stat_deltas={"mood": 6, "boredom": -4},
        growth_exp=2,
        bond_exp=3,
        affinity=3,
        contribution=1,
    ),
    "rest": CareRule(
        stat_deltas={"energy": 20, "mood": 1, "boredom": 2},
        growth_exp=1,
        bond_exp=1,
        affinity=1,
        contribution=1,
    ),
}


@dataclass(frozen=True)
class CareMutation:
    action: CareAction
    deltas: dict[str, int]
    previous_growth_level: int
    growth_level: int
    previous_bond_level: int
    bond_level: int
    previous_growth_stage: str
    growth_stage: str

    @property
    def growth_level_changed(self) -> bool:
        return self.growth_level != self.previous_growth_level

    @property
    def bond_level_changed(self) -> bool:
        return self.bond_level != self.previous_bond_level

    @property
    def growth_stage_changed(self) -> bool:
        return self.growth_stage != self.previous_growth_stage


def _clamp_stat(value: int) -> int:
    return min(100, max(0, int(value)))


def _growth_stage(level: int) -> str:
    if level >= 7:
        return "adult"
    if level >= 3:
        return "child"
    return "newborn"


def apply_care_action(
    pet: Pet,
    relation: AccountPetRelation,
    action: CareAction,
) -> CareMutation:
    """Apply one care action and return the effective, post-clamp mutation."""

    rule = CARE_RULES[action]
    effective: dict[str, int] = {}
    for field, requested_delta in rule.stat_deltas.items():
        before = int(getattr(pet, field))
        after = _clamp_stat(before + requested_delta)
        setattr(pet, field, after)
        effective[field] = after - before

    old_growth_level = int(pet.growth_level)
    old_bond_level = int(pet.bond_level)
    old_stage = str(pet.growth_stage)

    pet.growth_exp = max(0, int(pet.growth_exp) + rule.growth_exp)
    pet.bond_exp = max(0, int(pet.bond_exp) + rule.bond_exp)
    pet.growth_level = max(1, 1 + pet.growth_exp // 100)
    pet.bond_level = max(1, 1 + pet.bond_exp // 80)
    pet.growth_stage = _growth_stage(pet.growth_level)
    pet.state_version = max(1, int(pet.state_version) + 1)

    relation.affinity = min(100, max(0, int(relation.affinity) + rule.affinity))
    relation.care_contribution = max(
        0, int(relation.care_contribution) + rule.contribution
    )

    effective.update(
        {
            "growth_exp": rule.growth_exp,
            "bond_exp": rule.bond_exp,
            "affinity": rule.affinity,
            "care_contribution": rule.contribution,
        }
    )
    return CareMutation(
        action=action,
        deltas=effective,
        previous_growth_level=old_growth_level,
        growth_level=int(pet.growth_level),
        previous_bond_level=old_bond_level,
        bond_level=int(pet.bond_level),
        previous_growth_stage=old_stage,
        growth_stage=str(pet.growth_stage),
    )
