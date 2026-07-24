"""Desktop social transport and state controller using the active device token."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController


class SocialTransport(QObject):
    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(
        self,
        api: CloudApiClient,
        *,
        manager: QNetworkAccessManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.api = api
        self._manager = manager or QNetworkAccessManager(self)
        self._operations: dict[QNetworkReply, str] = {}

    def request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> None:
        token = self.api._require_device_token()
        url = QUrl(f"{self.api.base_url}{path}")
        if query:
            values = QUrlQuery()
            for key, value in query.items():
                values.addQueryItem(str(key), str(value))
            url.setQuery(values)
        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        payload = QByteArray()
        if body is not None:
            request.setRawHeader(b"Content-Type", b"application/json")
            payload = QByteArray(
                json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        if method == "GET":
            reply = self._manager.get(request)
        elif method == "POST":
            reply = self._manager.post(request, payload)
        elif method == "PATCH":
            reply = self._manager.sendCustomRequest(request, b"PATCH", payload)
        elif method == "DELETE":
            reply = self._manager.sendCustomRequest(request, b"DELETE")
        else:
            raise ValueError("不支持的社交请求方法")
        self._operations[reply] = operation
        reply.finished.connect(lambda reply=reply: self._finish(reply))

    def _finish(self, reply: QNetworkReply) -> None:
        operation = self._operations.pop(reply, "unknown")
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status_value) if status_value is not None else 0
        raw = bytes(reply.readAll())
        network_error = reply.error()
        fallback = reply.errorString()
        reply.deleteLater()
        payload: Any = None
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        if network_error != QNetworkReply.NetworkError.NoError or not 200 <= status < 300:
            self.operation_failed.emit(operation, status, self._detail(payload, fallback))
            return
        self.operation_succeeded.emit(operation, payload if payload is not None else {})

    @staticmethod
    def _detail(payload: object, fallback: str) -> str:
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            if isinstance(detail, list):
                values = [
                    str(item.get("msg") or "").strip()
                    for item in detail
                    if isinstance(item, dict)
                ]
                values = [item for item in values if item]
                if values:
                    return "；".join(values)
        return fallback or "社交请求失败"


class SocialController(QObject):
    snapshot_changed = Signal(object)
    status_message = Signal(str)
    operation_failed = Signal(str)
    pets_sync_requested = Signal()

    def __init__(
        self,
        session: CloudSessionController,
        api: CloudApiClient,
        *,
        transport: SocialTransport | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.transport = transport or SocialTransport(api, parent=self)
        self.active_pet_id: str | None = None
        self.snapshot: dict[str, object] = {}
        self._pending_refresh: set[str] = set()
        self.transport.operation_succeeded.connect(self._on_success)
        self.transport.operation_failed.connect(self._on_failure)
        self.session.state_changed.connect(self._session_changed)

    def refresh(self, active_pet_id: str | None = None) -> bool:
        if active_pet_id is not None:
            self.active_pet_id = active_pet_id
        if not self.session.connected:
            self.operation_failed.emit("云端未连接，无法读取好友和共同照料数据")
            return False
        requests = {
            "friends": ("GET", "/api/v1/friends", None),
            "friend_requests": ("GET", "/api/v1/friend-requests", None),
            "blocks": ("GET", "/api/v1/blocks", None),
            "caregiver_invitations": ("GET", "/api/v1/caregiver-invitations", None),
        }
        if self.active_pet_id:
            requests["pet_privacy"] = (
                "GET",
                f"/api/v1/pets/{self.active_pet_id}/privacy",
                None,
            )
            requests["pet_caregivers"] = (
                "GET",
                f"/api/v1/pets/{self.active_pet_id}/caregivers",
                None,
            )
        self._pending_refresh = set(requests)
        try:
            for operation, (method, path, body) in requests.items():
                self.transport.request(operation, method, path, body=body)
        except (RuntimeError, ValueError) as exc:
            self._pending_refresh.clear()
            self.operation_failed.emit(str(exc))
            return False
        self.status_message.emit("正在刷新好友与共同照料数据…")
        return True

    def send_friend_request(self, username: str) -> None:
        self._mutate("send_friend_request", "POST", "/api/v1/friend-requests", {"username": username})

    def respond_friend_request(self, request_id: str, action: str) -> None:
        if action not in {"accept", "reject", "cancel"}:
            raise ValueError("不支持的好友申请操作")
        self._mutate(
            f"friend_request_{action}",
            "POST",
            f"/api/v1/friend-requests/{request_id}/{action}",
        )

    def remove_friend(self, account_id: str) -> None:
        self._mutate("remove_friend", "DELETE", f"/api/v1/friends/{account_id}")

    def block(self, username: str) -> None:
        self._mutate("block_account", "POST", "/api/v1/blocks", {"username": username})

    def unblock(self, account_id: str) -> None:
        self._mutate("unblock_account", "DELETE", f"/api/v1/blocks/{account_id}")

    def update_privacy(self, visibility: str, allow_remote_care: bool) -> None:
        if not self.active_pet_id:
            self.operation_failed.emit("没有可管理的当前宠物")
            return
        self._mutate(
            "update_privacy",
            "PATCH",
            f"/api/v1/pets/{self.active_pet_id}/privacy",
            {"visibility": visibility, "allow_remote_care": allow_remote_care},
        )

    def invite_caregiver(self, username: str, role: str) -> None:
        if not self.active_pet_id:
            self.operation_failed.emit("没有可管理的当前宠物")
            return
        self._mutate(
            "invite_caregiver",
            "POST",
            f"/api/v1/pets/{self.active_pet_id}/caregiver-invitations",
            {"username": username, "role": role},
        )

    def respond_caregiver_invitation(self, invitation_id: str, action: str) -> None:
        if action not in {"accept", "reject", "cancel"}:
            raise ValueError("不支持的共同照料邀请操作")
        self._mutate(
            f"caregiver_invitation_{action}",
            "POST",
            f"/api/v1/caregiver-invitations/{invitation_id}/{action}",
        )

    def remove_caregiver(self, pet_id: str, account_id: str) -> None:
        self._mutate(
            "remove_caregiver",
            "DELETE",
            f"/api/v1/pets/{pet_id}/caregivers/{account_id}",
        )

    def _mutate(
        self,
        operation: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.session.connected:
            self.operation_failed.emit("云端未连接，操作未提交")
            return
        try:
            self.transport.request(f"mutation:{operation}", method, path, body=body)
        except (RuntimeError, ValueError) as exc:
            self.operation_failed.emit(str(exc))

    def _on_success(self, operation: str, payload: object) -> None:
        if operation in self._pending_refresh:
            self.snapshot[operation] = payload
            self._pending_refresh.discard(operation)
            if not self._pending_refresh:
                self.snapshot_changed.emit(dict(self.snapshot))
                self.status_message.emit("好友与共同照料数据已刷新")
            return
        if not operation.startswith("mutation:"):
            return
        label = operation.removeprefix("mutation:")
        self.status_message.emit(
            {
                "send_friend_request": "好友申请已发送",
                "friend_request_accept": "好友申请已接受",
                "friend_request_reject": "好友申请已拒绝",
                "friend_request_cancel": "好友申请已取消",
                "remove_friend": "好友关系已解除",
                "block_account": "账户已屏蔽",
                "unblock_account": "账户已解除屏蔽",
                "update_privacy": "宠物隐私设置已保存",
                "invite_caregiver": "共同照料邀请已发送",
                "caregiver_invitation_accept": "共同照料邀请已接受",
                "caregiver_invitation_reject": "共同照料邀请已拒绝",
                "caregiver_invitation_cancel": "共同照料邀请已取消",
                "remove_caregiver": "共同照料关系已移除",
            }.get(label, "操作已完成")
        )
        if label in {
            "caregiver_invitation_accept",
            "remove_caregiver",
            "block_account",
        }:
            self.pets_sync_requested.emit()
        self.refresh()

    def _on_failure(self, operation: str, _status: int, detail: str) -> None:
        self._pending_refresh.discard(operation)
        self.operation_failed.emit(detail)

    def _session_changed(self, state: str) -> None:
        if state == "connected":
            self.refresh()
        elif state in {"offline", "disabled", "error"}:
            self._pending_refresh.clear()
