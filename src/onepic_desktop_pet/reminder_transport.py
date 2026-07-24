"""Isolated reminder HTTP transport using the active desktop device token."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_api import CloudApiClient
from .reminder_cache import ReminderCommand


class ReminderTransport(QObject):
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

    def refresh(self) -> None:
        self._request(
            "reminders",
            "GET",
            "/api/v1/reminders/snapshot",
            query={"limit": 500},
        )

    def submit(self, command: ReminderCommand) -> None:
        path_suffix = {
            "delivered": "delivered",
            "completed": "complete",
            "snoozed": "snooze",
            "dismissed": "dismiss",
        }.get(command.action)
        if path_suffix is None:
            raise ValueError("不支持的提醒命令")
        payload: dict[str, Any] = {}
        if command.action == "snoozed":
            payload["minutes"] = command.snooze_minutes
        self._request(
            f"reminder_command:{command.command_id}:{command.action}:{command.occurrence_id}",
            "POST",
            f"/api/v1/reminders/occurrences/{command.occurrence_id}/{path_suffix}",
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
            headers={"Idempotency-Key": command.idempotency_key},
        )

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> None:
        token = self.api._require_device_token()
        url = QUrl(f"{self.api.base_url}{path}")
        if query:
            url_query = QUrlQuery()
            for key, value in query.items():
                url_query.addQueryItem(str(key), str(value))
            url.setQuery(url_query)
        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        if content_type:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, content_type)
        for key, value in (headers or {}).items():
            request.setRawHeader(key.encode("utf-8"), value.encode("utf-8"))

        payload = QByteArray(body or b"")
        if method == "GET":
            reply = self._manager.get(request)
        else:
            reply = self._manager.post(request, payload)
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

        data: Any = None
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = None
        if network_error != QNetworkReply.NetworkError.NoError or not 200 <= status < 300:
            self.operation_failed.emit(operation, status, self._error_detail(data, fallback))
            return
        self.operation_succeeded.emit(operation, data if data is not None else {})

    @staticmethod
    def _error_detail(data: Any, fallback: str) -> str:
        if isinstance(data, dict):
            detail = data.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            if isinstance(detail, list):
                messages = [
                    str(item.get("msg", "")).strip()
                    for item in detail
                    if isinstance(item, dict)
                ]
                messages = [message for message in messages if message]
                if messages:
                    return "；".join(messages)
        return fallback or "提醒网络请求失败"
