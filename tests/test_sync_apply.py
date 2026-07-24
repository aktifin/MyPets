from __future__ import annotations

from onepic_desktop_pet.sync_apply import apply_bootstrap, apply_events


class FakeStore:
    def __init__(self) -> None:
        self.pets = {}
        self.relations = {}
        self.active_pet_id = None
        self.cursors = {}

    def upsert_pet(self, pet) -> None:
        self.pets[pet.identity.pet_id] = pet

    def delete_pet(self, pet_id: str) -> None:
        self.pets.pop(pet_id, None)

    def upsert_relation(self, relation) -> None:
        self.relations[(relation.account_id, relation.pet_id)] = relation

    def set_active_pet_id(self, pet_id: str | None) -> None:
        if pet_id is not None and pet_id not in self.pets:
            raise KeyError(pet_id)
        self.active_pet_id = pet_id

    def set_cursor(self, stream: str, cursor: int) -> None:
        self.cursors[stream] = max(cursor, self.cursors.get(stream, 0))

    def get_cursor(self, stream: str) -> int:
        return self.cursors.get(stream, 0)


def pet_payload(pet_id: str = "pet-1") -> dict:
    return {
        "pet_id": pet_id,
        "name": "小白",
        "template_id": "official.cat.white",
        "template_version": "1.0.0",
        "identity_version": "1.0.0",
        "primary_owner_account_id": "account-1",
        "presence": "home",
        "personality_type": "balanced",
        "asset_version": "1.0.0",
        "updated_at": "2026-07-24T03:00:00Z",
        "stats": {
            "growth_stage": "newborn",
            "growth_level": 1,
            "growth_exp": 0,
            "bond_level": 1,
            "bond_exp": 0,
            "hunger": 100,
            "energy": 100,
            "mood": 80,
            "cleanliness": 100,
            "health": 100,
            "boredom": 0,
            "state_version": 1,
        },
    }


def relation_payload(pet_id: str = "pet-1") -> dict:
    return {
        "account_id": "account-1",
        "pet_id": pet_id,
        "role": "owner",
        "affinity": 0,
        "care_contribution": 0,
    }


def test_bootstrap_applies_validated_snapshot() -> None:
    store = FakeStore()
    result = apply_bootstrap(
        store,
        {
            "schema_version": "1.0",
            "cursor": 3,
            "account": {"id": "account-1"},
            "device": {"id": "device-1", "active_pet_id": "pet-1"},
            "pets": [pet_payload()],
            "relations": [relation_payload()],
        },
    )
    assert result.cursor == 3
    assert store.active_pet_id == "pet-1"
    assert store.pets["pet-1"].stats.growth_level == 1
    assert store.cursors["sync:account-1:device-1"] == 3


def test_bootstrap_rejects_cross_account_relation_before_mutation() -> None:
    store = FakeStore()
    relation = relation_payload()
    relation["account_id"] = "other"
    try:
        apply_bootstrap(
            store,
            {
                "schema_version": "1.0",
                "cursor": 1,
                "account": {"id": "account-1"},
                "device": {"id": "device-1", "active_pet_id": None},
                "pets": [pet_payload()],
                "relations": [relation],
            },
        )
    except ValueError as exc:
        assert "当前账户" in str(exc)
    else:
        raise AssertionError("cross-account relation must fail")
    assert store.pets == {}


def test_incremental_events_apply_known_and_advance_unknown() -> None:
    store = FakeStore()
    payload = {
        "next_cursor": 8,
        "events": [
            {
                "sequence_number": 7,
                "event_id": "e7",
                "event_type": "pet_created",
                "idempotency_key": "k7",
                "created_at": "2026-07-24T03:00:00Z",
                "target_account_id": "account-1",
                "target_device_id": None,
                "payload": {
                    "pet": pet_payload(),
                    "relation": relation_payload(),
                },
            },
            {
                "sequence_number": 8,
                "event_id": "e8",
                "event_type": "future_event",
                "idempotency_key": "k8",
                "created_at": "2026-07-24T03:01:00Z",
                "target_account_id": "account-1",
                "target_device_id": None,
                "payload": {},
            },
        ],
    }
    result = apply_events(
        store,
        payload,
        account_id="account-1",
        device_id="device-1",
    )
    assert result.events_applied == 1
    assert result.events_ignored == 1
    assert store.cursors["sync:account-1:device-1"] == 8


def test_device_target_mismatch_is_rejected() -> None:
    store = FakeStore()
    payload = {
        "next_cursor": 2,
        "events": [
            {
                "sequence_number": 2,
                "event_id": "e2",
                "event_type": "active_pet_changed",
                "idempotency_key": "k2",
                "created_at": "2026-07-24T03:00:00Z",
                "target_account_id": "account-1",
                "target_device_id": "device-other",
                "payload": {"device_id": "device-other", "pet_id": None},
            }
        ],
    }
    try:
        apply_events(
            store,
            payload,
            account_id="account-1",
            device_id="device-1",
        )
    except ValueError as exc:
        assert "其他设备" in str(exc)
    else:
        raise AssertionError("target mismatch must fail")
