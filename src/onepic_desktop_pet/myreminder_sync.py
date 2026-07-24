"""Desktop trigger for server-side MyReminder provider synchronization."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_api import CloudApiClient
from .cloud_session import CloudSessionController


class MyReminderSyncTransport(QObject):
    operation_succeeded = Signal(object)
    operation_failed = Signal(int, str)

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
        self._reply: QNetworkReply | None = None

    def sync(self) -> None:
        if self._reply is not None:
            raise RuntimeError("MyReminder 同步已在进行")
        token = self.api._require_device_token()
        request = QNetworkRequest(
            QUrl(f"{self.api.base_url}/api/v1/reminder-providers/myreminder/sync")
        )
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"Content-Type", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        self._reply = self._manager.post(request, QByteArray(b"{}"))
        self._reply.finished.connect(self._finish)

    def _finish(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
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
            self.operation_failed.emit(status, self._detail(payload, fallback))
            return
        self.operation_succeeded.emit(payload if isinstance(payload, dict) else {})

    @staticmethod
    def _detail(payload: object, fallback: str) -> str:
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        return fallback or "MyReminder 同步失败"


class MyReminderSyncController(QObject):
    sync_started = Signal()
    sync_succeeded = Signal(object)
    sync_failed = Signal(str)

    def __init__(
        self,
        session: CloudSessionController,
        api: CloudApiClient,
        *,
        transport: MyReminderSyncTransport | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.transport = transport or MyReminderSyncTransport(api, parent=self)
        self._busy = False
        self.transport.operation_succeeded.connect(self._on_success)
        self.transport.operation_failed.connect(self._on_failure)

    @property
    def busy(self) -> bool:
        return self._busy

    def sync(self) -> bool:
        if self._busy:
            self.sync_failed.emit("MyReminder 同步已在进行")
            return False
        if not self.session.connected:
            self.sync_failed.emit("云端未连接，无法同步 MyReminder")
            return False
        try:
            self._busy = True
            self.transport.sync()
        except (RuntimeError, ValueError) as exc:
            self._busy = False
            self.sync_failed.emit(str(exc))
            return False
        self.sync_started.emit()
        return True

    def _on_success(self, payload: object) -> None:
        self._busy = False
        if not isinstance(payload, dict):
            self.sync_failed.emit("MyReminder 同步响应必须是对象")
            return
        required = ("pulled", "created", "updated", "unchanged", "expired")
        if any(not isinstance(payload.get(field), int) for field in required):
            self.sync_failed.emit("MyReminder 同步响应缺少统计字段")
            return
        self.sync_succeeded.emit(dict(payload))

    def _on_failure(self, _status: int, detail: str) -> None:
        self._busy = False
        self.sync_failed.emit(detail)
