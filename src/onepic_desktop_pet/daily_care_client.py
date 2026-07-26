"""Isolated read-only client for cross-device daily care summaries."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_api import CloudApiClient


class DailyCareCloudClient(QObject):
    """Read daily progress without coupling a non-critical request to session state."""

    summary_received = Signal(str, object)
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
        self._replies: dict[QNetworkReply, str] = {}

    def refresh(self, pet_id: str, timezone_offset_minutes: int) -> bool:
        normalized_pet_id = pet_id.strip()
        if not normalized_pet_id:
            return False
        # CloudApiClient intentionally owns token lifecycle. This read-only companion
        # uses the current in-memory device token but never stores or logs it.
        token = getattr(self.api, "_device_token", None)
        if not isinstance(token, str) or not token:
            self.request_failed.emit(normalized_pet_id, "云端尚未连接，暂时使用本机照料进度。")
            return False

        url = QUrl(f"{self.api.base_url}/api/v1/pets/{normalized_pet_id}/daily-care")
        query = QUrlQuery()
        query.addQueryItem(
            "timezone_offset_minutes",
            str(max(-840, min(840, int(timezone_offset_minutes)))),
        )
        url.setQuery(query)
        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        reply = self._manager.get(request)
        self._replies[reply] = normalized_pet_id
        reply.finished.connect(lambda reply=reply: self._finish(reply))
        return True

    def _finish(self, reply: QNetworkReply) -> None:
        pet_id = self._replies.pop(reply, "")
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
            detail = fallback or "今日进度读取失败"
            if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
                detail = str(payload["detail"])
            self.request_failed.emit(pet_id, detail)
            return
        if not isinstance(payload, dict):
            self.request_failed.emit(pet_id, "今日进度响应无效")
            return
        self.summary_received.emit(pet_id, payload)
