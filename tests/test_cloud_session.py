from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from onepic_desktop_pet.cloud_session import CloudConnectionState, CloudSessionController
from onepic_desktop_pet.cloud_types import DeviceCredentials, normalize_base_url
from onepic_desktop_pet.config import PetSettings
from onepic_desktop_pet.credential_store import MemoryCredentialStore
from onepic_desktop_pet.local_store import LocalStateStore
from onepic_desktop_pet.pet_registry import PetRegistry


class FakeTimeout:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class FakeTimer:
    def __init__(self) -> None:
        self.timeout = FakeTimeout()
        self.interval = 0
        self.active = False

    def setInterval(self, value: int) -> None:
        self.interval = value

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


class FakeApi(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = normalize_base_url(base_url)
        self.calls: list[tuple] = []
        self.account_token: str | None = None
        self.device_token: str | None = None

    def set_base_url(self, value: str) -> None:
        self.base_url = normalize_base_url(value)

    def clear_tokens(self) -> None:
        self.account_token = None
        self.device_token = None

    def set_account_token(self, token: str | None) -> None:
        self.account_token = token

    def set_device_token(self, token: str | None) -> None:
        self.device_token = token

    def login(self, username: str, password: str) -> None:
        self.calls.append(("login", username, password))

    def register(self, username: str, display_name: str, password: str) -> None:
        self.calls.append(("register", username, display_name, password))

    def bind_device(self, public_id: str, name: str, platform: str) -> None:
        self.calls.append(("bind_device", public_id, name, platform))

    def exchange_device_token(self, device_id: str, device_secret: str) -> None:
        self.calls.append(("device_token", device_id, device_secret))

    def bootstrap(self) -> None:
        self.calls.append(("bootstrap",))

    def fetch_events(self, after_sequence: int, limit: int = 100) -> None:
        self.calls.append(("events", after_sequence, limit))

    def heartbeat(self) -> None:
        self.calls.append(("heartbeat",))

    def set_active_pet(self, device_id: str, pet_id: str | None) -> None:
        self.calls.append(("active_pet", device_id, pet_id))


def _bootstrap_payload() -> dict:
    return {
        "schema_version": "1.0",
        "server_time": "2026-07-24T04:00:00+00:00",
        "account": {
            "id": "account-1",
            "username": "tester",
            "display_name": "测试用户",
            "created_at": "2026-07-24T03:00:00+00:00",
        },
        "device": {
            "id": "device-1",
            "public_id": "desktop-public-id",
            "name": "PC",
            "platform": "windows",
            "active_pet_id": "pet-1",
            "last_seen_at": "2026-07-24T04:00:00+00:00",
            "revoked_at": None,
            "created_at": "2026-07-24T03:00:00+00:00",
        },
        "pets": [
            {
                "pet_id": "pet-1",
                "name": "小白",
                "template_id": "official.cat",
                "template_version": "1.0.0",
                "identity_version": "1.0.0",
                "primary_owner_account_id": "account-1",
                "presence": "home",
                "personality_type": "balanced",
                "asset_version": "1.0.0",
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
                "updated_at": "2026-07-24T04:00:00+00:00",
            }
        ],
        "relations": [
            {
                "account_id": "account-1",
                "pet_id": "pet-1",
                "role": "owner",
                "affinity": 20,
                "care_contribution": 5,
            }
        ],
        "cursor": 7,
    }


def _controller(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "onepic_desktop_pet.cloud_session.save_settings",
        lambda settings: tmp_path / "settings.json",
    )
    settings = PetSettings(
        cloud_base_url="https://pets.example.com",
        device_public_id="desktop-public-id",
    )
    store = LocalStateStore(tmp_path / "state.sqlite3")
    registry = PetRegistry(store)
    registry.bootstrap_local_pet()
    credentials = MemoryCredentialStore()
    api = FakeApi(settings.cloud_base_url)
    controller = CloudSessionController(
        api,
        store,
        registry,
        credentials,
        settings,
        poll_timer=FakeTimer(),
    )
    return controller, api, store, credentials


def test_login_binds_device_then_persists_credentials_after_device_auth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    controller, api, store, credentials = _controller(tmp_path, monkeypatch)
    controller.login("tester", "long-password")
    assert api.calls[-1][:2] == ("login", "tester")

    api.operation_succeeded.emit(
        "login",
        {
            "access_token": "account-token",
            "device_id": None,
            "account": {"id": "account-1", "display_name": "测试用户"},
        },
    )
    assert api.account_token == "account-token"
    assert api.calls[-1][0] == "bind_device"

    api.operation_succeeded.emit(
        "bind_device",
        {"device": {"id": "device-1"}, "device_secret": "s" * 32},
    )
    server_url = "https://pets.example.com"
    assert credentials.load(server_url) is None
    assert api.calls[-1] == ("device_token", "device-1", "s" * 32)

    api.operation_succeeded.emit(
        "device_token",
        {
            "access_token": "device-token",
            "device_id": "device-1",
            "account": {"id": "account-1", "display_name": "测试用户"},
        },
    )
    assert api.device_token == "device-token"
    assert credentials.load(server_url) == DeviceCredentials(
        server_url,
        "account-1",
        "device-1",
        "s" * 32,
    )
    assert api.calls[-1] == ("bootstrap",)

    api.operation_succeeded.emit("bootstrap", _bootstrap_payload())
    assert controller.state is CloudConnectionState.CONNECTED
    assert controller.registry.active_pet().identity.name == "小白"
    controller.stop()
    store.close()


def test_auto_connect_uses_saved_device_credentials(tmp_path: Path, monkeypatch) -> None:
    controller, api, store, credentials = _controller(tmp_path, monkeypatch)
    credentials.save(
        DeviceCredentials(
            "https://pets.example.com",
            "account-1",
            "device-1",
            "q" * 32,
        )
    )
    controller.settings.cloud_sync_enabled = True
    controller.start()
    assert api.calls[-1] == ("device_token", "device-1", "q" * 32)
    store.close()


def test_offline_pet_switch_stays_local(tmp_path: Path, monkeypatch) -> None:
    controller, _api, store, _credentials = _controller(tmp_path, monkeypatch)
    current = controller.registry.active_pet()
    assert current is not None
    controller.switch_active_pet(current.identity.pet_id)
    assert store.get_active_pet_id() == current.identity.pet_id
    store.close()
