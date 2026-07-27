from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from onepic_desktop_pet.config import PetSettings
from onepic_desktop_pet.domain import PetIdentity, PetProfile, PetStats
from onepic_desktop_pet.multi_pet_layout import DualPetLayoutController
from onepic_desktop_pet.next_pet_prompt import NextPetPrompt
from onepic_desktop_pet.proactive_care import (
    aggregate_local_proactive_notices,
    build_local_proactive_notice,
)


@pytest.fixture(scope="module", autouse=True)
def _qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


def _pet(pet_id: str, name: str, *, hunger: int = 80) -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id=pet_id,
            name=name,
            template_id="local.test",
            template_version="1.0.0",
            identity_version="1.0.0",
            primary_owner_account_id="local-account",
        ),
        stats=PetStats(hunger=hunger),
        updated_at=datetime.now().astimezone(),
    )


def test_local_proactive_notices_are_aggregated_once_for_multiple_pets() -> None:
    first = build_local_proactive_notice(_pet("pet-a", "团子", hunger=20), [])
    second = build_local_proactive_notice(_pet("pet-b", "豆包", hunger=25), [])

    notice = aggregate_local_proactive_notices(
        [item for item in (first, second) if item is not None]
    )

    assert notice is not None
    assert str(notice["notice_key"]).startswith("multi-pet:")
    assert notice["title"] == "2 只宠物需要你留意"
    assert "团子" in str(notice["detail"])
    assert "豆包" in str(notice["detail"])
    assert notice["care_action"] is None
    assert notice["target_section"] == "multi_pet"


def test_single_local_notice_remains_directly_actionable() -> None:
    direct = build_local_proactive_notice(_pet("pet-only", "团子", hunger=20), [])

    notice = aggregate_local_proactive_notices([direct] if direct is not None else [])

    assert notice is not None
    assert notice["pet_id"] == "pet-only"
    assert notice["care_action"] == "feed"
    assert notice["action_label"] == "去投喂"


def test_next_pet_prompt_only_switches_after_explicit_click() -> None:
    prompt = NextPetPrompt()
    anchor = QWidget()
    anchor.resize(120, 120)
    anchor.move(300, 220)
    anchor.show()
    switched: list[str] = []
    prompt.switch_requested.connect(switched.append)

    prompt.show_for(
        anchor,
        pet_id="pet-next",
        pet_name="豆包",
        reason="今日任务还没有完成。",
    )

    assert switched == []
    assert "豆包" in prompt.title_label.text()
    assert prompt.switch_button.text() == "切换到 豆包"
    prompt.switch_button.click()
    assert switched == ["pet-next"]
    prompt.close()
    anchor.close()


def test_dual_pet_layout_keeps_one_companion_and_remembers_positions() -> None:
    primary = QWidget()
    primary.resize(160, 180)
    primary.move(120, 140)
    primary.show()
    settings = PetSettings(display_height=180)
    saves: list[bool] = []
    controller = DualPetLayoutController(
        primary_window=primary,
        settings=settings,
        save_callback=lambda: saves.append(True),
    )

    first = controller.show_companion(
        pet_id="pet-b",
        pet_name="豆包",
        manifest_path=None,
        display_height=180,
        use_saved_position=False,
    )
    assert controller.visible is True
    assert controller.companion_pet_id == "pet-b"
    assert settings.multi_pet_layout_enabled is True
    assert settings.multi_pet_companion_pet_id == "pet-b"
    assert settings.multi_pet_primary_x is not None
    assert settings.multi_pet_companion_x is not None

    desired_primary = QPoint(90, 110)
    desired_secondary = QPoint(310, 118)
    settings.multi_pet_primary_x = desired_primary.x()
    settings.multi_pet_primary_y = desired_primary.y()
    settings.multi_pet_companion_x = desired_secondary.x()
    settings.multi_pet_companion_y = desired_secondary.y()
    controller.restore_layout()
    assert primary.pos() == desired_primary
    assert first.pos() == desired_secondary

    first.move(QPoint(first.x() + 12, first.y() + 8))
    controller.remember_positions()
    assert settings.multi_pet_companion_x == first.x()
    assert settings.multi_pet_companion_y == first.y()

    second = controller.show_companion(
        pet_id="pet-c",
        pet_name="奶糖",
        manifest_path=None,
        display_height=180,
        use_saved_position=False,
    )
    assert second is not first
    assert controller.companion_pet_id == "pet-c"
    assert settings.multi_pet_companion_pet_id == "pet-c"

    controller.hide_companion()
    assert controller.visible is False
    assert settings.multi_pet_layout_enabled is False
    controller.close()
    primary.close()
