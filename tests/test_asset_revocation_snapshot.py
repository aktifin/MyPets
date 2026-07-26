from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ONEPIC_USE_DEMO_ASSETS", "1")

from PySide6.QtCore import QObject, Signal

from onepic_desktop_pet import asset_download as _asset_download  # noqa: F401
from onepic_desktop_pet.asset_revocation import _KNOWN_CACHE_ROOTS, is_identity_revoked
from onepic_desktop_pet.cloud_session import CloudConnectionState, CloudSessionController
from onepic_desktop_pet.cloud_types import CloudIdentity, normalize_base_url
from onepic_desktop_pet.config import PetSettings
from onepic_desktop_pet.credential_store import MemoryCredentialStore
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.pet_assets import PetAssetIdentity
from onepic_desktop_pet.pet_registry import PetRegistry


class _Timeout:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _Timer:
    def __init__(self) -> None:
        self.timeout = _Timeout()
        self.active = False

    def setInterval(self, _value: int) -> None:
        return None

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


class _Api(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self) -> None:
        super().__init__()
        self.base_url = normalize_base_url("https://pets.example.com")
        self.calls: list[tuple] = []
        self.device_token = "device-token"

    def set_base_url(self, value: str) -> None:
        self.base_url = normalize_base_url(value)

    def clear_tokens(self) -> None:
        self.device_token = None

    def set_account_token(self, _token) -> None:
        return None

    def set_device_token(self, token) -> None:
        self.device_token = token

    def bootstrap(self) -> None:
        self.calls.append(("bootstrap",))

    def fetch_events(self, after_sequence: int, limit: int = 100) -> None:
        self.calls.append(("events", after_sequence, limit))

    def list_conversations(self) -> None:
        self.calls.append(("conversations",))

    def fetch_asset_revocations(self) -> None:
        self.calls.append(("asset_revocations",))

    def acknowledge_asset_revocation(self, task) -> None:
        self.calls.append(("asset_revocation_ack", task.right_id, task.release_id, task.status))

    def heartbeat(self) -> None:
        self.calls.append(("heartbeat",))

    def set_active_pet(self, device_id: str, pet_id: str | None) -> None:
        self.calls.append(("active_pet", device_id, pet_id))

    def list_conversations(self) -> None:
        self.calls.append(("conversations",))


def _bootstrap_payload(pet_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "server_time": "2026-07-26T04:00:00+00:00",
        "account": {
            "id": "account-1",
            "username": "snapshot-user",
            "display_name": "新设备用户",
            "created_at": "2026-07-26T03:00:00+00:00",
        },
        "device": {
            "id": "device-1",
            "public_id": "snapshot-device",
            "name": "PC",
            "platform": "windows",
            "active_pet_id": pet_id,
            "last_seen_at": "2026-07-26T04:00:00+00:00",
            "revoked_at": None,
            "created_at": "2026-07-26T03:00:00+00:00",
        },
        "pets": [
            {
                "pet_id": pet_id,
                "name": "已撤销专属宠物",
                "template_id": "custom.snapshot.cat",
                "template_version": "2.0.0",
                "identity_version": "2.0.0",
                "primary_owner_account_id": "account-1",
                "presence": "home",
                "personality_type": "balanced",
                "asset_version": "2.0.0",
                "stats": {
                    "growth_stage": "child",
                    "growth_level": 2,
                    "growth_exp": 10,
                    "bond_level": 1,
                    "bond_exp": 2,
                    "hunger": 90,
                    "energy": 80,
                    "mood": 88,
                    "cleanliness": 75,
                    "health": 100,
                    "boredom": 10,
                    "state_version": 3,
                },
                "updated_at": "2026-07-26T04:00:00+00:00",
            }
        ],
        "relations": [
            {
                "account_id": "account-1",
                "pet_id": pet_id,
                "role": "owner",
                "affinity": 20,
                "care_contribution": 5,
            }
        ],
        "cursor": 42,
    }


def test_bootstrap_fetches_current_revocations_and_acknowledges_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "onepic_desktop_pet.cloud_session.save_settings",
        lambda settings: tmp_path / "settings.json",
    )
    cache_root = tmp_path / "pet-assets"
    _KNOWN_CACHE_ROOTS.clear()
    _KNOWN_CACHE_ROOTS.add(cache_root)
    store = LocalStateStore(tmp_path / "state.sqlite3")
    registry = PetRegistry(store)
    registry.bootstrap_local_pet()
    api = _Api()
    controller = CloudSessionController(
        api,
        store,
        registry,
        MemoryCredentialStore(),
        PetSettings(
            cloud_base_url="https://pets.example.com",
            device_public_id="snapshot-device",
        ),
        poll_timer=_Timer(),
    )
    controller.identity = CloudIdentity("account-1", "device-1", "新设备用户")
    controller.state = CloudConnectionState.SYNCING
    pet_id = str(uuid4())

    api.operation_succeeded.emit("bootstrap", _bootstrap_payload(pet_id))
    assert api.calls[-1] == ("asset_revocations",)

    right_id, release_id, artifact_id = str(uuid4()), str(uuid4()), str(uuid4())
    api.operation_succeeded.emit(
        "asset_revocations",
        [
            {
                "right_id": right_id,
                "artifact_id": artifact_id,
                "release_id": release_id,
                "pet_id": pet_id,
                "reason": "新设备也必须执行历史撤销。",
                "action": "evict_cache_and_fallback",
                "asset_identity": {
                    "template_id": "custom.snapshot.cat",
                    "identity_version": "2.0.0",
                    "asset_version": "2.0.0",
                },
                "revoked_at": "2026-07-26T04:01:00+00:00",
            }
        ],
    )

    identity = PetAssetIdentity("custom.snapshot.cat", "2.0.0", "2.0.0")
    assert is_identity_revoked(cache_root, identity)
    task = controller.asset_revocation_tasks.get(right_id, release_id)
    assert task.status == "completed"
    assert ("asset_revocation_ack", right_id, release_id, "completed") in api.calls

    api.operation_succeeded.emit(
        f"asset_revocation_ack:{right_id}:{release_id}",
        {"status": "completed"},
    )
    assert controller.asset_revocation_tasks.list_unacknowledged() == []
    controller.stop()
    store.close()
