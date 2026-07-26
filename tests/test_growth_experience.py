from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.domain import GrowthStage, PetIdentity, PetProfile, PetStats
from onepic_desktop_pet.growth_experience import (
    apply_growth_levels,
    build_growth_milestones,
    build_growth_progress,
    build_local_memories,
)
from onepic_desktop_pet.pet_care_panel import PetCarePanel


@pytest.fixture(scope="module", autouse=True)
def _qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


def _pet(*, growth_exp: int = 0, bond_exp: int = 0) -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id="local-growth-pet",
            name="团子",
            template_id="official.cat.local",
            template_version="1.0.0",
            identity_version="1.0.0",
            primary_owner_account_id="local",
        ),
        stats=PetStats(growth_exp=growth_exp, bond_exp=bond_exp),
        updated_at=datetime.now(timezone.utc),
    )


def test_local_growth_levels_match_server_thresholds() -> None:
    pet = apply_growth_levels(_pet(growth_exp=203, bond_exp=83))
    assert pet.stats.growth_level == 3
    assert pet.stats.bond_level == 2
    assert pet.stats.growth_stage is GrowthStage.CHILD

    progress = build_growth_progress(pet)
    assert progress["current_stage_label"] == "幼年期"
    assert progress["next_stage_label"] == "成熟期"
    assert progress["next_stage_target_level"] == 7
    assert progress["next_stage_exp_remaining"] == 397
    assert progress["growth_level_current"] == 3
    assert progress["growth_exp_remaining"] == 97
    assert progress["bond_level_current"] == 3
    assert progress["bond_exp_remaining"] == 77
    assert progress["estimated_actions"] == 57


def test_growth_milestones_and_local_memory_timeline() -> None:
    milestones = build_growth_milestones(
        pet_name="团子",
        before={"growth_level": 2, "bond_level": 1},
        after={"growth_level": 3, "bond_level": 2},
        previous_stage="newborn",
        current_stage="child",
    )
    assert [item["memory_type"] for item in milestones] == [
        "growth_level",
        "bond_level",
        "growth_stage",
    ]
    records = [
        {
            "action_type": item["memory_type"],
            "action_name": item["title"],
            "detail": item["detail"],
            "created_at": "2026-07-27T08:00:00+00:00",
        }
        for item in milestones
    ]
    memories = build_local_memories(records, pet_name="团子")
    assert [item["memory_type"] for item in memories[:3]] == [
        "growth_level",
        "bond_level",
        "growth_stage",
    ]
    assert memories[-1]["memory_type"] == "adoption"
    assert memories[-1]["title"] == "团子 开始陪伴"


def test_pet_care_panel_shows_goal_progress_and_recent_memories() -> None:
    panel = PetCarePanel()
    pet = apply_growth_levels(_pet(growth_exp=203, bond_exp=83))
    panel.set_pet(pet)
    progress = build_growth_progress(pet)
    memories = build_local_memories([], pet_name="团子")
    panel.set_growth_experience(progress, memories)

    assert "下一阶段：成熟期" in panel.growth_goal_label.text()
    assert panel.growth_progress.value() == 3
    assert panel.growth_progress.maximum() == 100
    assert panel.bond_progress.value() == 3
    assert panel.bond_progress.maximum() == 80
    assert len(panel._memory_widgets) == 1
    panel.close()
