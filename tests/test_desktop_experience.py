from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

import pytest
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.bubble_menu import PetBubbleMenu
from onepic_desktop_pet.desktop_experience import (
    apply_local_demo_care,
    build_local_daily_care_summary,
    daily_care_progress,
    format_care_result,
    plain_status_summary,
    recommend_care,
    snapshot_stats,
)
from onepic_desktop_pet.domain import PetIdentity, PetProfile, PetStats, PresenceStatus
from onepic_desktop_pet.first_run_dialog import FirstRunDialog
from onepic_desktop_pet.pet_registry import LOCAL_ACCOUNT_ID


@pytest.fixture(scope="module", autouse=True)
def _qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


def _pet(**stats) -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id="pet-1",
            name="团子",
            template_id="official.cat.white",
            template_version="1.0.0",
            identity_version="1.0.0",
            primary_owner_account_id=LOCAL_ACCOUNT_ID,
        ),
        stats=PetStats(**stats),
        presence=PresenceStatus.HOME,
    )


def test_recommendation_uses_the_most_urgent_plain_language_action() -> None:
    pet = _pet(hunger=32, energy=77, cleanliness=85, mood=80, boredom=15)

    recommendation = recommend_care(pet)

    assert recommendation.action == "feed"
    assert recommendation.title == "该投喂了"
    assert "饱食状态最低" in recommendation.detail
    assert plain_status_summary(pet) == "有点饿"


def test_away_pet_disables_care_and_explains_what_to_do() -> None:
    pet = _pet()
    pet.presence = PresenceStatus.VISITING

    recommendation = recommend_care(pet)

    assert recommendation.action is None
    assert "串门" in recommendation.title
    assert "召回" in recommendation.detail
    assert "暂时不能" in plain_status_summary(pet)


def test_local_demo_care_updates_state_without_mutating_original() -> None:
    original = _pet(hunger=40, mood=60, boredom=30, growth_exp=3, bond_exp=4)

    updated = apply_local_demo_care(original, "feed")

    assert original.stats.hunger == 40
    assert updated.stats.hunger == 58
    assert updated.stats.mood == 62
    assert updated.stats.boredom == 28
    assert updated.stats.growth_exp == 5
    assert updated.stats.bond_exp == 5
    assert updated.stats.state_version == original.stats.state_version + 1


def test_care_result_lists_real_state_and_growth_changes() -> None:
    before = snapshot_stats(_pet(hunger=40, growth_exp=8, bond_exp=3))
    after_pet = _pet(hunger=58, mood=82, growth_exp=10, bond_exp=4)
    after = snapshot_stats(after_pet)

    result = format_care_result("团子", "feed", before, after)

    assert result.title == "团子 · 投喂完成"
    assert "饱食 +18" in result.detail
    assert "成长经验 +2" in result.detail
    assert "羁绊经验 +1" in result.detail


def test_daily_progress_counts_only_today_care_actions() -> None:
    now = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)
    records = [
        {"action_type": "feed", "created_at": now.isoformat()},
        {"action_type": "play", "created_at": (now - timedelta(hours=2)).isoformat()},
        {"action_type": "chat", "created_at": now.isoformat()},
        {"action_type": "clean", "created_at": (now - timedelta(days=1)).isoformat()},
    ]

    assert daily_care_progress(records, now=now) == (2, 3)


def test_local_daily_summary_matches_three_task_model_and_streak() -> None:
    now = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)
    records: list[dict[str, str]] = []
    for days_ago in (0, 1, 2):
        created = now - timedelta(days=days_ago)
        for action in ("feed", "play", "clean"):
            records.append({"action_type": action, "created_at": created.isoformat()})

    summary = build_local_daily_care_summary(records, now=now)

    assert summary["completed_tasks"] == 3
    assert summary["all_tasks_completed"] is True
    assert summary["streak_days"] == 3
    assert summary["reward_title"] == "今日陪伴徽章"
    actions = {item["action"]: item for item in summary["actions"]}
    assert actions["feed"]["available"] is False
    assert "秒后" in actions["feed"]["reason"]
    assert actions["pet"]["available"] is True


def test_quick_panel_exposes_tasks_streak_and_action_cooldown() -> None:
    panel = PetBubbleMenu()
    emitted: list[str] = []
    panel.action_triggered.connect(emitted.append)

    panel.set_context(
        pet_name="团子",
        level_text="Lv.3 · 幼年期 · 羁绊 Lv.2",
        presence_text="在家",
        status_text="有点饿",
        recommendation_action="feed",
        recommendation_text="该投喂了",
        recommendation_detail="饱食状态最低。",
        daily_count=2,
        daily_goal=3,
        can_care=True,
        streak_days=4,
        task_text="✓ 3 次照料 · 1/2 2 种方式 · ✓ 1 次陪伴",
        reward_text="还剩 1 项任务。",
        action_states={
            "feed": (False, "投喂刚刚完成，3 秒后可再次操作。"),
            "play": (True, "现在可以操作。"),
        },
    )

    assert panel.name_label.text() == "团子"
    assert panel.daily_label.text() == "今日任务 2 / 3 · 连续 4 天"
    assert "1/2 2 种方式" in panel.task_label.text()
    assert panel.recommendation_button.isEnabled() is False
    assert panel.recommendation_button.text() == "投喂刚刚完成，3 秒后可再次操作。"
    assert panel.action_buttons["feed"].isEnabled() is False
    assert panel.action_buttons["play"].isEnabled() is True
    panel.action_buttons["play"].click()
    assert emitted == ["play"]
    panel.close()


def test_first_run_dialog_has_three_steps_and_emits_completion() -> None:
    dialog = FirstRunDialog()
    completed: list[bool] = []
    dialog.completed.connect(lambda: completed.append(True))
    dialog.set_pet_name("团子")

    assert dialog.pages.count() == 3
    assert "团子" in dialog.pet_label.text()
    dialog.pages.setCurrentIndex(2)
    dialog._complete()

    assert completed == [True]
    dialog.close()
