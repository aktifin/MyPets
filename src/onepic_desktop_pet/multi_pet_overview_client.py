"""Read-only desktop client for the account-level multi-pet overview."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QObject, QUrl, QUrlQuery, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .cloud_api import CloudApiClient


class MultiPetOverviewCloudClient(QObject):
    overview_received = Signal(object)
    request_failed = Signal(str)

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
        self._replies: set[QNetworkReply] = set()

    def refresh(self, timezone_offset_minutes: int) -> bool:
        token = getattr(self.api, "_device_token", None)
        if not isinstance(token, str) or not token:
            self.request_failed.emit("云端尚未连接")
            return False
        url = QUrl(f"{self.api.base_url}/api/v1/multi-pet-overview")
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
        self._replies.add(reply)
        reply.finished.connect(lambda reply=reply: self._finish(reply))
        return True

    def _finish(self, reply: QNetworkReply) -> None:
        self._replies.discard(reply)
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
            detail = fallback or "多宠状态读取失败"
            if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
                detail = str(payload["detail"])
            self.request_failed.emit(detail)
            return
        if not isinstance(payload, dict):
            self.request_failed.emit("多宠状态响应无效")
            return
        self.overview_received.emit(payload)
