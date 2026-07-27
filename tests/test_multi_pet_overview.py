from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from onepic_desktop_pet.desktop_experience import build_local_daily_care_summary
from onepic_desktop_pet.domain import PetIdentity, PetProfile, PetStats, PresenceStatus
from onepic_desktop_pet.multi_pet_overview import (
    build_local_overview_item,
    merge_overview_items,
    next_rotation_pet_id,
)
from onepic_desktop_pet.multi_pet_overview_dialog import MultiPetOverviewDialog
from onepic_desktop_pet.pet_registry import LOCAL_ACCOUNT_ID


@pytest.fixture(scope="module", autouse=True)
def _qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


def _pet(
    pet_id: str,
    name: str,
    *,
    hunger: int = 80,
    energy: int = 80,
    mood: int = 80,
    cleanliness: int = 80,
    health: int = 90,
    boredom: int = 20,
    presence: PresenceStatus = PresenceStatus.HOME,
) -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id=pet_id,
            name=name,
            template_id="local.test",
            template_version="1.0.0",
            identity_version="1.0.0",
            primary_owner_account_id=LOCAL_ACCOUNT_ID,
        ),
        stats=PetStats(
            hunger=hunger,
            energy=energy,
            mood=mood,
            cleanliness=cleanliness,
            health=health,
            boredom=boredom,
        ),
        presence=presence,
        updated_at=datetime.now().astimezone(),
    )


def test_local_multi_pet_overview_prioritizes_state_then_daily_rotation() -> None:
    hungry = _pet("local-hungry", "饿饿", hunger=20)
    stable = _pet("local-stable", "安稳", hunger=95, energy=95, mood=95, cleanliness=95)
    visiting = _pet("local-visiting", "串串", presence=PresenceStatus.VISITING)

    hungry_item = build_local_overview_item(
        hungry,
        build_local_daily_care_summary([]),
        current=False,
    )
    stable_item = build_local_overview_item(
        stable,
        build_local_daily_care_summary([]),
        current=True,
    )
    visiting_item = build_local_overview_item(
        visiting,
        build_local_daily_care_summary([]),
        current=False,
    )
    items = merge_overview_items(
        [stable_item, visiting_item, hungry_item],
        [],
        current_pet_id="local-stable",
    )

    assert [item["pet_id"] for item in items] == [
        "local-hungry",
        "local-stable",
        "local-visiting",
    ]
    assert items[0]["priority"] == "urgent"
    assert items[0]["recommended_action"] == "feed"
    assert items[0]["switch_candidate"] is True
    assert items[1]["priority"] == "routine"
    assert items[1]["current"] is True
    assert items[2]["priority"] == "unavailable"
    assert next_rotation_pet_id(items, current_pet_id="local-stable") == "local-hungry"


def test_health_attention_rotates_for_review_but_never_auto_cares() -> None:
    health_item = build_local_overview_item(
        _pet(
            "local-health",
            "康康",
            hunger=95,
            energy=95,
            mood=95,
            cleanliness=95,
            health=25,
            boredom=5,
        ),
        build_local_daily_care_summary([]),
        current=False,
    )

    assert health_item["priority"] == "urgent"
    assert health_item["recommended_action"] is None
    assert health_item["action_available"] is False
    assert health_item["switch_candidate"] is True
    assert health_item["recommended_action_label"] == "查看状态"
    assert "不会自动执行照料" in health_item["action_reason"]
    assert next_rotation_pet_id([health_item], current_pet_id="other") == "local-health"


def test_merge_prefers_local_snapshot_for_same_pet_and_keeps_cloud_pets() -> None:
    local_item = build_local_overview_item(
        _pet("same-pet", "本机名称", hunger=30),
        build_local_daily_care_summary([]),
        current=True,
    )
    cloud_item = {
        **local_item,
        "name": "云端旧名称",
        "priority": "stable",
        "state_score": 90,
        "source": "cloud",
    }
    second_cloud = {
        **cloud_item,
        "pet_id": "cloud-only",
        "name": "云端宠物",
        "priority": "routine",
        "switch_candidate": True,
    }

    merged = merge_overview_items(
        [local_item],
        [cloud_item, second_cloud],
        current_pet_id="same-pet",
    )

    by_id = {item["pet_id"]: item for item in merged}
    assert by_id["same-pet"]["name"] == "本机名称"
    assert by_id["same-pet"]["priority"] == "urgent"
    assert by_id["same-pet"]["current"] is True
    assert by_id["cloud-only"]["current"] is False


def test_multi_pet_dialog_exposes_next_switch_and_care_actions() -> None:
    dialog = MultiPetOverviewDialog()
    next_calls: list[bool] = []
    switches: list[str] = []
    cares: list[tuple[str, str]] = []
    dialog.next_requested.connect(lambda: next_calls.append(True))
    dialog.switch_requested.connect(switches.append)
    dialog.care_requested.connect(lambda pet_id, action: cares.append((pet_id, action)))

    item = build_local_overview_item(
        _pet("dialog-pet", "团子", hunger=20),
        build_local_daily_care_summary([]),
        current=False,
    )
    dialog.set_items(
        [item],
        total_count=2,
        needs_attention_count=1,
        urgent_count=1,
        next_pet_id="dialog-pet",
    )

    assert dialog.summary_label.text() == "共 2 只，其中 1 只需要关注，1 只优先处理"
    assert dialog.next_button.isEnabled()
    dialog.next_button.click()
    buttons = dialog.findChildren(QPushButton)
    next(button for button in buttons if button.text() == "切换到它").click()
    next(button for button in buttons if button.text() == "投喂").click()

    assert next_calls == [True]
    assert switches == ["dialog-pet"]
    assert cares == [("dialog-pet", "feed")]
    dialog.close()
