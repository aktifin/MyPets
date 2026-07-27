"""Desktop client for the unified actionable pending-items queue."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_api import CloudApiClient


class PendingItemsCloudClient(QObject):
    items_received = Signal(object)
    action_succeeded = Signal(object)
    request_failed = Signal(str, str)

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

    def refresh(self, *, limit: int = 100) -> bool:
        safe_limit = max(1, min(300, int(limit)))
        return self._request("list", "GET", f"/api/v1/pending-items?limit={safe_limit}")

    def act(
        self,
        *,
        kind: str,
        item_id: str,
        action: str,
        snooze_minutes: int = 10,
    ) -> bool:
        normalized = (kind.strip(), item_id.strip(), action.strip())
        if not all(normalized):
            self.request_failed.emit("action", "待处理事项参数不完整")
            return False
        path = "/api/v1/pending-items/{}/{}/{}".format(
            quote(normalized[0], safe=""),
            quote(normalized[1], safe=""),
            quote(normalized[2], safe=""),
        )
        return self._request(
            "action",
            "POST",
            path,
            {"snooze_minutes": max(5, min(30, int(snooze_minutes)))},
            idempotency_key=f"desktop-pending-{uuid4()}",
        )

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> bool:
        token = getattr(self.api, "_device_token", None)
        if not isinstance(token, str) or not token:
            self.request_failed.emit(operation, "云端尚未连接")
            return False
        request = QNetworkRequest(QUrl(f"{self.api.base_url}{path}"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        if idempotency_key:
            request.setRawHeader(b"Idempotency-Key", idempotency_key.encode("ascii"))
        body = QByteArray()
        if payload is not None:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
            body = QByteArray(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        if method == "GET":
            reply = self._manager.get(request)
        elif method == "POST":
            reply = self._manager.post(request, body)
        else:
            raise ValueError(f"不支持的请求方法：{method}")
        self._operations[reply] = operation
        reply.finished.connect(lambda reply=reply: self._finish(reply))
        return True

    def _finish(self, reply: QNetworkReply) -> None:
        operation = self._operations.pop(reply, "unknown")
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status_value) if status_value is not None else 0
        raw = bytes(reply.readAll())
        error = reply.error()
        fallback = reply.errorString()
        reply.deleteLater()

        payload: Any = None
        if raw:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        if error != QNetworkReply.NetworkError.NoError or not 200 <= status < 300:
            detail = fallback or "待处理事项请求失败"
            if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
                detail = str(payload["detail"])
            self.request_failed.emit(operation, detail)
            return
        if not isinstance(payload, dict):
            self.request_failed.emit(operation, "待处理事项响应无效")
            return
        if operation == "list":
            self.items_received.emit(payload)
        else:
            self.action_succeeded.emit(payload)
