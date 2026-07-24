from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.sync_apply import apply_events


def _pet_payload(*, stage: str, level: int, state_version: int) -> dict:
    return {
        "pet_id": "pet-growth-1",
        "name": "米粒",
        "template_id": "official.cat.growth",
        "template_version": "1.0.0",
        "identity_version": "1.0.0",
        "primary_owner_account_id": "account-1",
        "presence": "home",
        "personality_type": "balanced",
        "asset_version": "1.0.0",
        "stats": {
            "growth_stage": stage,
            "growth_level": level,
            "growth_exp": 203,
            "bond_level": 2,
            "bond_exp": 81,
            "hunger": 90,
            "energy": 80,
            "mood": 88,
            "cleanliness": 75,
            "health": 100,
            "boredom": 10,
            "state_version": state_version,
        },
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _relation_payload() -> dict:
    return {
        "account_id": "account-1",
        "pet_id": "pet-growth-1",
        "role": "owner",
        "affinity": 20,
        "care_contribution": 5,
    }


def test_growth_stage_event_updates_cached_pet(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.sqlite3")
    payload = {
        "events": [
            {
                "sequence_number": 1,
                "event_id": "growth-event-1",
                "event_type": "growth_stage_changed",
                "idempotency_key": "growth-stage-key",
                "created_at": datetime.now(UTC).isoformat(),
                "target_account_id": "account-1",
                "target_device_id": None,
                "payload": {
                    "pet_id": "pet-growth-1",
                    "pet": _pet_payload(stage="child", level=3, state_version=5),
                    "relation": _relation_payload(),
                    "transition": {
                        "previous_value": "newborn",
                        "current_value": "child",
                        "source": "pet_care",
                    },
                },
            }
        ],
        "next_cursor": 1,
        "has_more": False,
    }

    result = apply_events(
        store,
        payload,
        account_id="account-1",
        device_id="device-1",
    )
    cached = store.get_pet("pet-growth-1")
    assert cached is not None
    assert cached.stats.growth_stage.value == "child"
    assert cached.stats.growth_level == 3
    assert cached.stats.state_version == 5
    assert result.events_applied == 1
    assert result.events_ignored == 0
    store.close()


def test_settlement_pet_updated_event_updates_cached_stats(tmp_path: Path) -> None:
    store = LocalStateStore(tmp_path / "state.sqlite3")
    pet = _pet_payload(stage="newborn", level=1, state_version=2)
    pet["stats"]["hunger"] = 72
    payload = {
        "events": [
            {
                "sequence_number": 1,
                "event_id": "settlement-event-1",
                "event_type": "pet_updated",
                "idempotency_key": "settlement-key",
                "created_at": datetime.now(UTC).isoformat(),
                "target_account_id": "account-1",
                "target_device_id": None,
                "payload": {
                    "cause": "state_settlement",
                    "pet": pet,
                    "relation": _relation_payload(),
                    "settlement": {
                        "elapsed_hours": 4,
                        "deltas": {"hunger": -8},
                    },
                },
            }
        ],
        "next_cursor": 1,
        "has_more": False,
    }

    apply_events(
        store,
        payload,
        account_id="account-1",
        device_id="device-1",
    )
    cached = store.get_pet("pet-growth-1")
    assert cached is not None
    assert cached.stats.hunger == 72
    store.close()
