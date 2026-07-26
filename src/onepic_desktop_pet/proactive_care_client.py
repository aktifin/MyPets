"""Isolated desktop client for proactive care evaluation and preferences."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_api import CloudApiClient


class ProactiveCareCloudClient(QObject):
    preferences_received = Signal(object)
    evaluation_received = Signal(object)
    acknowledgement_received = Signal(object)
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

    def fetch_preferences(self) -> bool:
        return self._request("preferences", "GET", "/api/v1/portal/proactive-care/preferences")

    def update_preferences(self, values: Mapping[str, object]) -> bool:
        return self._request(
            "preferences_update",
            "PATCH",
            "/api/v1/portal/proactive-care/preferences",
            values,
        )

    def evaluate(self, *, pet_id: str | None, timezone_offset_minutes: int) -> bool:
        return self._request(
            "evaluate",
            "POST",
            "/api/v1/portal/proactive-care/evaluate",
            {
                "surface": "desktop",
                "pet_id": pet_id,
                "timezone_offset_minutes": max(-840, min(840, int(timezone_offset_minutes))),
            },
        )

    def acknowledge(
        self,
        notice_key: str,
        outcome: str,
        *,
        timezone_offset_minutes: int,
        snooze_minutes: int = 120,
    ) -> bool:
        if not notice_key.strip():
            return False
        return self._request(
            "acknowledge",
            "POST",
            "/api/v1/portal/proactive-care/acknowledge",
            {
                "notice_key": notice_key.strip(),
                "outcome": outcome,
                "timezone_offset_minutes": max(-840, min(840, int(timezone_offset_minutes))),
                "snooze_minutes": max(15, min(1440, int(snooze_minutes))),
            },
        )

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
    ) -> bool:
        token = getattr(self.api, "_device_token", None)
        if not isinstance(token, str) or not token:
            self.request_failed.emit(operation, "云端尚未连接")
            return False
        request = QNetworkRequest(QUrl(f"{self.api.base_url}{path}"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
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
        elif method == "PATCH":
            reply = self._manager.sendCustomRequest(request, b"PATCH", body)
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
            detail = fallback or "主动关怀请求失败"
            if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
                detail = str(payload["detail"])
            self.request_failed.emit(operation, detail)
            return
        if not isinstance(payload, dict):
            self.request_failed.emit(operation, "主动关怀响应无效")
            return
        if operation in {"preferences", "preferences_update"}:
            self.preferences_received.emit(payload)
        elif operation == "evaluate":
            self.evaluation_received.emit(payload)
        elif operation == "acknowledge":
            self.acknowledgement_received.emit(payload)
