from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.cloud_session import CloudConnectionState, CloudSessionController
from onepic_desktop_pet.cloud_types import CloudIdentity
from onepic_desktop_pet.config import PetSettings
from onepic_desktop_pet.credential_store import MemoryCredentialStore
from onepic_desktop_pet.domain import (
    AccountPetRelation,
    GrowthStage,
    PetIdentity,
    PetProfile,
    PetRole,
    PetStats,
)
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.pet_care_panel import PetCarePanel
from onepic_desktop_pet.pet_registry import PetRegistry


class FakeTimeout:
    def connect(self, callback) -> None:
        self.callback = callback


class FakeTimer:
    def __init__(self) -> None:
        self.timeout = FakeTimeout()
        self.active = False

    def setInterval(self, _value: int) -> None:
        pass

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


class FakeApi(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.base_url = "https://pets.example.com"
        self.calls: list[tuple] = []

    def care_for_pet(self, pet_id: str, action: str, **kwargs) -> None:
        self.calls.append((pet_id, action, kwargs))

    def clear_tokens(self) -> None:
        pass


def _profile(*, hunger: int = 70, state_version: int = 1) -> PetProfile:
    return PetProfile(
        identity=PetIdentity(
            pet_id="pet-care-1",
            name="团团",
            template_id="official.cat.care",
            template_version="1.0.0",
            identity_version="1.0.0",
            primary_owner_account_id="account-1",
        ),
        stats=PetStats(
            growth_stage=GrowthStage.NEWBORN,
            hunger=hunger,
            energy=80,
            mood=85,
            cleanliness=75,
            health=100,
            boredom=12,
            state_version=state_version,
        ),
        updated_at=datetime.now().astimezone(),
    )


def _pet_payload(*, hunger: int, state_version: int) -> dict:
    return {
        "pet_id": "pet-care-1",
        "name": "团团",
        "template_id": "official.cat.care",
        "template_version": "1.0.0",
        "identity_version": "1.0.0",
        "primary_owner_account_id": "account-1",
        "presence": "home",
        "personality_type": "balanced",
        "asset_version": "1.0.0",
        "stats": {
            "growth_stage": "newborn",
            "growth_level": 1,
            "growth_exp": 4,
            "bond_level": 1,
            "bond_exp": 2,
            "hunger": hunger,
            "energy": 80,
            "mood": 87,
            "cleanliness": 75,
            "health": 100,
            "boredom": 11,
            "state_version": state_version,
        },
        "updated_at": datetime.now().astimezone().isoformat(),
    }


def test_cloud_care_waits_for_confirmation_then_updates_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "onepic_desktop_pet.cloud_session.save_settings",
        lambda _settings: tmp_path / "settings.json",
    )
    store = LocalStateStore(tmp_path / "state.sqlite3")
    store.upsert_pet(_profile())
    store.upsert_relation(
        AccountPetRelation(
            account_id="account-1",
            pet_id="pet-care-1",
            role=PetRole.OWNER,
        )
    )
    store.set_active_pet_id("pet-care-1")
    registry = PetRegistry(store)
    api = FakeApi()
    controller = CloudSessionController(
        api,
        store,
        registry,
        MemoryCredentialStore(),
        PetSettings(cloud_base_url=api.base_url),
        poll_timer=FakeTimer(),
    )
    controller.identity = CloudIdentity("account-1", "device-1", "主人")
    controller.state = CloudConnectionState.CONNECTED

    succeeded: list[tuple[str, object]] = []
    controller.pet_care_succeeded.connect(
        lambda action, payload: succeeded.append((action, payload))
    )
    controller.care_for_pet("pet-care-1", "feed")
    assert api.calls[-1][0:2] == ("pet-care-1", "feed")
    assert store.get_pet("pet-care-1").stats.hunger == 70

    api.operation_succeeded.emit(
        "pet_care:feed:pet-care-1",
        {
            "interaction": {"action": "feed"},
            "pet": _pet_payload(hunger=88, state_version=2),
            "relation": {
                "account_id": "account-1",
                "pet_id": "pet-care-1",
                "role": "owner",
                "affinity": 2,
                "care_contribution": 2,
            },
            "idempotency_key": "care-key",
        },
    )
    cached = store.get_pet("pet-care-1")
    assert cached is not None
    assert cached.stats.hunger == 88
    assert cached.stats.state_version == 2
    assert succeeded and succeeded[-1][0] == "feed"
    store.close()


def test_pet_care_panel_displays_state_and_emits_action() -> None:
    app = QApplication.instance() or QApplication([])
    panel = PetCarePanel()
    panel.set_pet(_profile(hunger=64, state_version=4))
    assert panel.name_label.text() == "团团"
    assert panel.stat_bars["hunger"].value() == 64
    assert "等级 1" in panel.growth_label.text()

    actions: list[str] = []
    panel.action_requested.connect(actions.append)
    panel.action_buttons["play"].click()
    assert actions == ["play"]

    panel.set_busy(True, "正在提交玩耍…")
    assert not panel.action_buttons["feed"].isEnabled()
    panel.show_result("玩耍完成")
    assert panel.action_buttons["feed"].isEnabled()
    panel.close()
    app.processEvents()
