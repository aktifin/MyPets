"""云养宠领域模型的边界与状态测试。"""

from datetime import UTC, datetime

import pytest

from onepic_desktop_pet.domain import (
    CloudEvent,
    GrowthStage,
    PetStats,
    ReminderOccurrence,
    ReminderOccurrenceState,
)


def test_pet_stats_clamps_daily_and_growth_values() -> None:
    stats = PetStats(
        growth_stage=GrowthStage.JUVENILE,
        growth_level=0,
        growth_exp=-3,
        hunger=120,
        energy=-4,
        boredom=200,
    )

    stats.clamp()

    assert stats.growth_level == 1
    assert stats.growth_exp == 0
    assert stats.hunger == 100
    assert stats.energy == 0
    assert stats.boredom == 100


def test_reminder_occurrence_requires_timezone() -> None:
    with pytest.raises(ValueError, match="时区"):
        ReminderOccurrence(
            occurrence_id="source:1:2026-07-24T12:00",
            source="myreminder",
            source_reminder_id="1",
            account_id="account-1",
            title="午餐",
            content="该吃饭了",
            scheduled_at=datetime(2026, 7, 24, 12, 0),
            timezone="Asia/Shanghai",
        )


def test_completed_reminder_is_terminal() -> None:
    reminder = ReminderOccurrence(
        occurrence_id="source:1:2026-07-24T12:00+08:00",
        source="myreminder",
        source_reminder_id="1",
        account_id="account-1",
        title="午餐",
        content="该吃饭了",
        scheduled_at=datetime.now(UTC),
        timezone="Asia/Shanghai",
        state=ReminderOccurrenceState.COMPLETED,
    )

    assert reminder.terminal


def test_cloud_event_requires_idempotency_key() -> None:
    with pytest.raises(ValueError, match="幂等键"):
        CloudEvent(
            event_id="event-1",
            event_type="pet_stats_changed",
            sequence_number=1,
            idempotency_key="",
            created_at=datetime.now(UTC),
            payload={},
            target_account_id="account-1",
        )
