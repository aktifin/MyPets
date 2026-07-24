"""Asynchronous Qt HTTP transport for the MyPets backend API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from PySide6.QtCore import QByteArray, QObject, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_types import normalize_base_url


class CloudApiClient(QObject):
    """Non-blocking API client built on QNetworkAccessManager."""

    operation_succeeded = Signal(str, object)
    operation_failed = Signal(str, int, str)

    def __init__(
        self,
        base_url: str,
        *,
        manager: QNetworkAccessManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager or QNetworkAccessManager(self)
        self._base_url = normalize_base_url(base_url)
        self._account_token: str | None = None
        self._device_token: str | None = None
        self._operations: dict[QNetworkReply, str] = {}

    @property
    def base_url(self) -> str:
        return self._base_url

    def set_base_url(self, value: str) -> None:
        normalized = normalize_base_url(value)
        if normalized != self._base_url:
            self._base_url = normalized
            self.clear_tokens()

    def clear_tokens(self) -> None:
        self._account_token = None
        self._device_token = None

    def set_account_token(self, token: str | None) -> None:
        self._account_token = token.strip() if token else None

    def set_device_token(self, token: str | None) -> None:
        self._device_token = token.strip() if token else None

    def register(self, username: str, display_name: str, password: str) -> None:
        self._json_request(
            "register",
            "POST",
            "/api/v1/auth/register",
            {"username": username, "display_name": display_name, "password": password},
        )

    def login(self, username: str, password: str) -> None:
        body = urlencode(
            {
                "username": username,
                "password": password,
                "grant_type": "password",
                "scope": "",
                "client_id": "",
                "client_secret": "",
            }
        ).encode("utf-8")
        self._request(
            "login",
            "POST",
            "/api/v1/auth/token",
            body=body,
            content_type="application/x-www-form-urlencoded",
        )

    def bind_device(self, public_id: str, name: str, platform: str = "windows") -> None:
        self._json_request(
            "bind_device",
            "POST",
            "/api/v1/devices/bind",
            {"public_id": public_id, "name": name, "platform": platform},
            token=self._require_account_token(),
        )

    def exchange_device_token(self, device_id: str, device_secret: str) -> None:
        self._json_request(
            "device_token",
            "POST",
            "/api/v1/auth/device-token",
            {"device_id": device_id, "device_secret": device_secret},
        )

    def bootstrap(self) -> None:
        self._request(
            "bootstrap",
            "GET",
            "/api/v1/sync/bootstrap",
            token=self._require_device_token(),
        )

    def fetch_events(self, after_sequence: int, limit: int = 100) -> None:
        self._request(
            "events",
            "GET",
            "/api/v1/sync/events",
            token=self._require_device_token(),
            query={
                "after_sequence": max(0, int(after_sequence)),
                "limit": max(1, min(500, int(limit))),
            },
        )

    def heartbeat(self) -> None:
        self._request(
            "heartbeat",
            "POST",
            "/api/v1/sync/heartbeat",
            token=self._require_device_token(),
            body=b"{}",
            content_type="application/json",
        )

    def set_active_pet(self, device_id: str, pet_id: str | None) -> None:
        self._json_request(
            "active_pet",
            "PATCH",
            f"/api/v1/devices/{device_id}/active-pet",
            {"pet_id": pet_id},
            token=self._require_device_token(),
            headers={"Idempotency-Key": f"desktop-active-pet-{uuid4()}"},
        )

    def care_for_pet(
        self,
        pet_id: str,
        action: str,
        *,
        device_id: str,
        client_time: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Submit one deterministic care action using the current device identity."""

        normalized_action = action.strip().lower()
        if normalized_action not in {"feed", "play", "clean", "pet", "rest"}:
            raise ValueError("不支持的照料动作")
        key = idempotency_key or f"desktop-care-{normalized_action}-{uuid4()}"
        operation = f"pet_care:{normalized_action}:{pet_id}"
        payload: dict[str, Any] = {"device_id": device_id}
        if client_time is not None:
            if client_time.tzinfo is None:
                raise ValueError("client_time 必须包含时区")
            payload["client_time"] = client_time.isoformat()
        self._json_request(
            operation,
            "POST",
            f"/api/v1/pets/{pet_id}/interactions/{normalized_action}",
            payload,
            token=self._require_device_token(),
            headers={"Idempotency-Key": key},
        )

    def _require_account_token(self) -> str:
        if not self._account_token:
            raise RuntimeError("尚未取得账户访问令牌")
        return self._account_token

    def _require_device_token(self) -> str:
        if not self._device_token:
            raise RuntimeError("尚未取得设备访问令牌")
        return self._device_token

    def _json_request(
        self,
        operation: str,
        method: str,
        path: str,
        payload: Mapping[str, Any],
        *,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._request(
            operation,
            method,
            path,
            body=body,
            content_type="application/json",
            token=token,
            headers=headers,
        )

    def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        token: str | None = None,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, Any] | None = None,
    ) -> None:
        url = QUrl(f"{self._base_url}{path}")
        if query:
            url_query = QUrlQuery()
            for key, value in query.items():
                url_query.addQueryItem(str(key), str(value))
            url.setQuery(url_query)
        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        if content_type:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, content_type)
        if token:
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        for key, value in (headers or {}).items():
            request.setRawHeader(key.encode("utf-8"), value.encode("utf-8"))

        payload = QByteArray(body or b"")
        normalized_method = method.upper()
        if normalized_method == "GET":
            reply = self._manager.get(request)
        elif normalized_method == "POST":
            reply = self._manager.post(request, payload)
        elif normalized_method == "PATCH":
            reply = self._manager.sendCustomRequest(request, b"PATCH", payload)
        elif normalized_method == "DELETE":
            reply = self._manager.deleteResource(request)
        else:
            reply = self._manager.sendCustomRequest(
                request, normalized_method.encode("ascii"), payload
            )
        self._operations[reply] = operation
        reply.finished.connect(lambda reply=reply: self._finish(reply))

    def _finish(self, reply: QNetworkReply) -> None:
        operation = self._operations.pop(reply, "unknown")
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status_value) if status_value is not None else 0
        raw = bytes(reply.readAll())
        network_error = reply.error()
        error_text = reply.errorString()
        reply.deleteLater()

        data: Any = None
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = None

        if network_error != QNetworkReply.NetworkError.NoError or not 200 <= status < 300:
            detail = self._error_detail(data, error_text)
            self.operation_failed.emit(operation, status, detail)
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
        return fallback or "网络请求失败"
