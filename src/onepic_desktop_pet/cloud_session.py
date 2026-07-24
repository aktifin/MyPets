"""Desktop cloud authentication, device binding, pet care, and synchronization orchestration."""

from __future__ import annotations

import os
import platform
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from PySide6.QtCore import QObject, QTimer, Signal

from .cloud_api import CloudApiClient
from .cloud_types import CloudIdentity, DeviceCredentials, normalize_base_url
from .config import PetSettings, save_settings
from .credential_store import CredentialStore
from .local_store import LocalStateStore
from .pet_registry import PetRegistry
from .sync_apply import (
    apply_bootstrap,
    apply_events,
    parse_pet,
    parse_relation,
    stream_name,
)


class CloudConnectionState(str, Enum):
    DISABLED = "disabled"
    OFFLINE = "offline"
    AUTHENTICATING = "authenticating"
    BINDING = "binding"
    SYNCING = "syncing"
    CONNECTED = "connected"
    ERROR = "error"


class CloudSessionController(QObject):
    """Coordinate account login, device credentials, care actions, and cache synchronization."""

    state_changed = Signal(str)
    status_message = Signal(str)
    login_succeeded = Signal(str)
    login_failed = Signal(str)
    pets_changed = Signal()
    pet_care_succeeded = Signal(str, object)
    pet_care_failed = Signal(str, str)

    def __init__(
        self,
        api: CloudApiClient,
        store: LocalStateStore,
        registry: PetRegistry,
        credential_store: CredentialStore,
        settings: PetSettings,
        *,
        poll_timer: QTimer | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.api = api
        self.store = store
        self.registry = registry
        self.credential_store = credential_store
        self.settings = settings
        self.state = CloudConnectionState.DISABLED
        self.identity: CloudIdentity | None = None
        self._credentials: DeviceCredentials | None = None
        self._pending_display_name = ""
        self._pending_account_id = ""
        self._refresh_attempted = False

        self._poll_timer = poll_timer or QTimer(self)
        self._poll_timer.setInterval(self.settings.cloud_sync_interval_ms)
        self._poll_timer.timeout.connect(self.sync_now)
        self.api.operation_succeeded.connect(self._on_success)
        self.api.operation_failed.connect(self._on_failure)

    @property
    def connected(self) -> bool:
        return self.state is CloudConnectionState.CONNECTED and self.identity is not None

    def start(self) -> None:
        if not self.settings.cloud_sync_enabled:
            self._set_state(CloudConnectionState.DISABLED, "云端同步未启用")
            return
        try:
            self.api.set_base_url(self.settings.cloud_base_url)
            self._credentials = self.credential_store.load(self.settings.cloud_base_url)
        except (RuntimeError, OSError, ValueError) as exc:
            self._set_state(CloudConnectionState.ERROR, str(exc))
            return
        if self._credentials is None:
            self._set_state(CloudConnectionState.OFFLINE, "需要登录并绑定当前设备")
            return
        self._exchange_device_token()

    def configure_server(self, base_url: str) -> None:
        normalized = normalize_base_url(base_url)
        if normalized == self.settings.cloud_base_url:
            return
        self.stop()
        self.settings.cloud_base_url = normalized
        self.settings.cloud_sync_enabled = False
        self.api.set_base_url(normalized)
        self._credentials = None
        self.identity = None
        save_settings(self.settings)
        self._set_state(CloudConnectionState.OFFLINE, "服务地址已更新，请重新登录")

    def login(
        self,
        username: str,
        password: str,
        *,
        register: bool = False,
        display_name: str = "",
    ) -> None:
        username = username.strip()
        if not username or not password:
            self.login_failed.emit("用户名和密码不能为空")
            return
        self._pending_display_name = display_name.strip()
        if register and not self._pending_display_name:
            self.login_failed.emit("注册时必须填写显示名称")
            return
        self.api.clear_tokens()
        self.identity = None
        self._set_state(CloudConnectionState.AUTHENTICATING, "正在验证账户")
        if register:
            self.api.register(username, self._pending_display_name, password)
        else:
            self.api.login(username, password)

    def sync_now(self) -> None:
        if not self.connected or self.identity is None:
            if self._credentials is not None and self.state in {
                CloudConnectionState.OFFLINE,
                CloudConnectionState.ERROR,
            }:
                self._exchange_device_token()
            return
        cursor = self.store.get_cursor(
            stream_name(self.identity.account_id, self.identity.device_id)
        )
        self._set_state(CloudConnectionState.SYNCING, "正在同步宠物状态")
        self.api.fetch_events(cursor)

    def switch_active_pet(self, pet_id: str) -> None:
        if self.connected and self.identity is not None:
            self.api.set_active_pet(self.identity.device_id, pet_id)
            return
        self.registry.switch_active_pet(pet_id)
        self.pets_changed.emit()
        self.status_message.emit("当前处于离线模式，切换仅保存在本机")

    def care_for_pet(self, pet_id: str, action: str) -> None:
        """Submit one care action; visible success is emitted only after server confirmation."""

        normalized_action = action.strip().lower()
        if not self.connected or self.identity is None:
            self.pet_care_failed.emit(normalized_action, "云端未连接，无法更新宠物状态")
            return
        try:
            self.api.care_for_pet(
                pet_id,
                normalized_action,
                device_id=self.identity.device_id,
                client_time=datetime.now().astimezone(),
            )
        except (RuntimeError, ValueError) as exc:
            self.pet_care_failed.emit(normalized_action, str(exc))

    def sign_out(self, *, clear_cache: bool = False) -> None:
        base_url = self.settings.cloud_base_url
        self.stop()
        try:
            self.credential_store.delete(base_url)
        except (OSError, RuntimeError) as exc:
            self.status_message.emit(f"删除设备凭据失败：{exc}")
        self._credentials = None
        self.identity = None
        self.settings.cloud_sync_enabled = False
        save_settings(self.settings)
        if clear_cache:
            self.status_message.emit("当前版本不会自动删除本地宠物缓存")
        self._set_state(CloudConnectionState.OFFLINE, "已退出云端账户")

    def stop(self) -> None:
        self._poll_timer.stop()
        self.api.clear_tokens()
        self._refresh_attempted = False

    def _exchange_device_token(self) -> None:
        if self._credentials is None:
            self._set_state(CloudConnectionState.OFFLINE, "没有可用设备凭据")
            return
        self.api.set_base_url(self._credentials.base_url)
        self._set_state(CloudConnectionState.AUTHENTICATING, "正在验证设备")
        self.api.exchange_device_token(
            self._credentials.device_id,
            self._credentials.device_secret,
        )

    def _on_success(self, operation: str, payload: object) -> None:
        data = self._payload(payload)
        try:
            if operation in {"login", "register"}:
                token = self._required_string(data, "access_token")
                account = self._mapping(data.get("account"), "account")
                self.api.set_account_token(token)
                self._pending_account_id = self._required_string(account, "id")
                self._pending_display_name = str(account.get("display_name") or "").strip()
                self._set_state(CloudConnectionState.BINDING, "正在绑定当前电脑")
                self.api.bind_device(
                    self.settings.device_public_id,
                    self._device_name(),
                    "windows" if os.name == "nt" else "linux",
                )
                return

            if operation == "bind_device":
                device = self._mapping(data.get("device"), "device")
                account_id = self._pending_account_id
                if not account_id:
                    raise ValueError("绑定设备时账户标识不存在")
                credentials = DeviceCredentials(
                    base_url=self.api.base_url,
                    account_id=account_id,
                    device_id=self._required_string(device, "id"),
                    device_secret=self._required_string(data, "device_secret"),
                )
                self._credentials = credentials
                self._exchange_device_token()
                return

            if operation == "device_token":
                token = self._required_string(data, "access_token")
                account = self._mapping(data.get("account"), "account")
                device_id = self._required_string(data, "device_id")
                account_id = self._required_string(account, "id")
                display_name = self._required_string(account, "display_name")
                self.api.set_device_token(token)
                self.identity = CloudIdentity(account_id, device_id, display_name)
                if self._credentials is not None and self._credentials.account_id != account_id:
                    raise ValueError("设备凭据所属账户与令牌不一致")
                if self._credentials is not None:
                    self.credential_store.save(self._credentials)
                    self.settings.cloud_sync_enabled = True
                    self.settings.cloud_base_url = self._credentials.base_url
                    save_settings(self.settings)
                self._set_state(CloudConnectionState.SYNCING, "正在下载宠物资料")
                self.api.bootstrap()
                return

            if operation == "bootstrap":
                result = apply_bootstrap(self.store, data)
                self.identity = CloudIdentity(
                    result.account_id,
                    result.device_id,
                    self.identity.display_name if self.identity else "MyPets",
                )
                self._refresh_attempted = False
                self._poll_timer.start()
                self._set_state(CloudConnectionState.CONNECTED, "云端同步已连接")
                self.pets_changed.emit()
                self.login_succeeded.emit(self.identity.display_name)
                return

            if operation == "events":
                if self.identity is None:
                    raise ValueError("收到事件时设备身份不存在")
                apply_events(
                    self.store,
                    data,
                    account_id=self.identity.account_id,
                    device_id=self.identity.device_id,
                )
                self.pets_changed.emit()
                if bool(data.get("has_more")):
                    cursor = self.store.get_cursor(
                        stream_name(self.identity.account_id, self.identity.device_id)
                    )
                    self.api.fetch_events(cursor)
                else:
                    self._set_state(CloudConnectionState.CONNECTED, "同步完成")
                return

            if operation == "active_pet":
                pet_id = data.get("active_pet_id")
                if pet_id is None:
                    self.store.set_active_pet_id(None)
                else:
                    self.registry.switch_active_pet(self._required_string(data, "active_pet_id"))
                self.pets_changed.emit()
                self._set_state(CloudConnectionState.CONNECTED, "已切换当前宠物")
                return

            if operation.startswith("pet_care:"):
                parts = operation.split(":", 2)
                action = parts[1] if len(parts) > 1 else "care"
                pet = parse_pet(data.get("pet"))
                relation = parse_relation(data.get("relation"))
                if self.identity is None or relation.account_id != self.identity.account_id:
                    raise ValueError("照料结果关系不属于当前账户")
                self.store.upsert_pet(pet)
                self.store.upsert_relation(relation)
                self._refresh_attempted = False
                self.pets_changed.emit()
                self.pet_care_succeeded.emit(action, dict(data))
                self._set_state(CloudConnectionState.CONNECTED, "照料结果已同步")
                return

            if operation == "heartbeat":
                return
        except (KeyError, RuntimeError, OSError, ValueError) as exc:
            self._set_state(CloudConnectionState.ERROR, f"云端响应无效：{exc}")
            if operation.startswith("pet_care:"):
                action = operation.split(":", 2)[1]
                self.pet_care_failed.emit(action, str(exc))
            else:
                self.login_failed.emit(str(exc))

    def _on_failure(self, operation: str, status: int, detail: str) -> None:
        care_operation = operation.startswith("pet_care:")
        protected_operation = care_operation or operation in {
            "bootstrap",
            "events",
            "active_pet",
            "heartbeat",
        }
        if status == 401 and protected_operation:
            if care_operation:
                self.pet_care_failed.emit(
                    operation.split(":", 2)[1],
                    "设备会话已过期，正在刷新，请稍后重试",
                )
            if not self._refresh_attempted and self._credentials is not None:
                self._refresh_attempted = True
                self.api.set_device_token(None)
                self._exchange_device_token()
                return
        if status == 401 and operation == "device_token" and self._credentials is not None:
            try:
                self.credential_store.delete(self._credentials.base_url)
            except (OSError, RuntimeError):
                pass
            self._credentials = None
            self.settings.cloud_sync_enabled = False
            save_settings(self.settings)
            detail = "设备凭据已失效，请重新登录"
        if care_operation:
            action = operation.split(":", 2)[1]
            self.pet_care_failed.emit(action, detail)
            if status not in {0, 401, 503}:
                self.status_message.emit(detail)
                return
        if operation in {"login", "register", "bind_device", "device_token"}:
            self.login_failed.emit(detail)
        self._set_state(
            CloudConnectionState.OFFLINE if status in {0, 401, 503} else CloudConnectionState.ERROR,
            detail,
        )

    def _set_state(self, state: CloudConnectionState, message: str) -> None:
        self.state = state
        self.state_changed.emit(state.value)
        if message:
            self.status_message.emit(message)

    @staticmethod
    def _payload(payload: object) -> Mapping[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("响应必须是 JSON 对象")
        return payload

    @staticmethod
    def _mapping(value: object, field: str) -> Mapping[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"{field} 必须是 JSON 对象")
        return value

    @staticmethod
    def _required_string(data: Mapping[str, Any], field: str) -> str:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} 必须是非空字符串")
        return value.strip()

    @staticmethod
    def _device_name() -> str:
        return (
            os.environ.get("COMPUTERNAME")
            or platform.node()
            or "MyPets Desktop"
        )[:120]
