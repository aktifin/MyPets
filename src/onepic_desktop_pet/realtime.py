"""Qt WebSocket cursor notifications layered over the existing REST sync protocol."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket, QWebSocketHandshakeOptions

from .cloud_api import CloudApiClient

REALTIME_PROTOCOL = "mypets.realtime.v1"
_TICKET_PREFIX = "mypets.ticket."


def websocket_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.startswith("https://"):
        return f"wss://{normalized[len('https://'):]}/api/v1/realtime/ws"
    if normalized.startswith("http://"):
        return f"ws://{normalized[len('http://'):]}/api/v1/realtime/ws"
    raise ValueError("实时连接要求 http 或 https 服务地址")


class RealtimeTicketTransport(QObject):
    ticket_ready = Signal(str)
    failed = Signal(str)

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

    @property
    def busy(self) -> bool:
        return self._reply is not None

    def request_ticket(self) -> bool:
        if self._reply is not None:
            return False
        try:
            token = self.api._require_device_token()
        except RuntimeError as exc:
            self.failed.emit(str(exc))
            return False
        request = QNetworkRequest(QUrl(f"{self.api.base_url}/api/v1/realtime/ticket"))
        request.setRawHeader(b"Accept", b"application/json")
        request.setRawHeader(b"Content-Type", b"application/json")
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        self._reply = self._manager.post(request, QByteArray(b"{}"))
        self._reply.finished.connect(self._finish)
        return True

    def abort(self) -> None:
        if self._reply is not None:
            self._reply.abort()

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
            detail = payload.get("detail") if isinstance(payload, dict) else None
            self.failed.emit(str(detail or fallback or "实时连接票据请求失败"))
            return
        if not isinstance(payload, dict):
            self.failed.emit("实时连接票据响应必须是对象")
            return
        ticket = payload.get("ticket")
        protocol = payload.get("protocol")
        if not isinstance(ticket, str) or not ticket or protocol != REALTIME_PROTOCOL:
            self.failed.emit("实时连接票据响应无效")
            return
        self.ticket_ready.emit(ticket)


class RealtimeSocket(QObject):
    cursor_available = Signal(int)
    status_message = Signal(str)
    disconnected_unexpectedly = Signal()

    def __init__(
        self,
        *,
        socket: QWebSocket | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._socket = socket or QWebSocket()
        self._stopping = False
        self._connected = False
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.errorOccurred.connect(self._on_error)

    @property
    def connected(self) -> bool:
        return self._connected

    def open(self, base_url: str, ticket: str) -> None:
        self._stopping = False
        options = QWebSocketHandshakeOptions()
        options.setSubprotocols([REALTIME_PROTOCOL, f"{_TICKET_PREFIX}{ticket}"])
        request = QNetworkRequest(QUrl(websocket_url(base_url)))
        request.setRawHeader(b"User-Agent", b"MyPets-Desktop/0.2-alpha")
        self._socket.open(request, options)
        self.status_message.emit("正在建立实时通知连接")

    def stop(self) -> None:
        self._stopping = True
        self._connected = False
        self._socket.close()

    def _on_connected(self) -> None:
        self._connected = True
        self.status_message.emit("实时通知已连接")

    def _on_disconnected(self) -> None:
        was_stopping = self._stopping
        self._connected = False
        self.status_message.emit("实时通知已断开")
        if not was_stopping:
            self.disconnected_unexpectedly.emit()

    def _on_error(self, _error: object) -> None:
        self.status_message.emit(f"实时通知异常：{self._socket.errorString()}")

    def _on_text_message(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        event_type = payload.get("type")
        if event_type in {"hello", "events_available"}:
            cursor = payload.get("cursor")
            if isinstance(cursor, int) and cursor >= 0:
                self.cursor_available.emit(cursor)
                self._socket.sendTextMessage(
                    json.dumps({"type": "ack", "cursor": cursor}, separators=(",", ":"))
                )
        elif event_type == "heartbeat":
            cursor = payload.get("cursor")
            self._socket.sendTextMessage(
                json.dumps(
                    {"type": "ack", "cursor": cursor if isinstance(cursor, int) else 0},
                    separators=(",", ":"),
                )
            )


class RealtimeClient(QObject):
    cursor_available = Signal(int)
    status_message = Signal(str)

    def __init__(
        self,
        api: CloudApiClient,
        *,
        ticket_transport: RealtimeTicketTransport | None = None,
        realtime_socket: RealtimeSocket | None = None,
        reconnect_timer: QTimer | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.api = api
        self.ticket_transport = ticket_transport or RealtimeTicketTransport(api, parent=self)
        self.socket = realtime_socket or RealtimeSocket(parent=self)
        self._timer = reconnect_timer or QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._request_ticket)
        self._stopped = True
        self._connecting = False
        self._reconnect_delay_ms = 1000

        self.ticket_transport.ticket_ready.connect(self._open_ticket)
        self.ticket_transport.failed.connect(self._failed)
        self.socket.cursor_available.connect(self.cursor_available)
        self.socket.status_message.connect(self.status_message)
        self.socket.disconnected_unexpectedly.connect(self._schedule_reconnect)

    def start(self) -> None:
        self._stopped = False
        if self.socket.connected or self._connecting or self.ticket_transport.busy:
            return
        self._request_ticket()

    def stop(self) -> None:
        self._stopped = True
        self._connecting = False
        self._timer.stop()
        self.ticket_transport.abort()
        self.socket.stop()

    def _request_ticket(self) -> None:
        if self._stopped or self._connecting or self.socket.connected:
            return
        self._connecting = self.ticket_transport.request_ticket()

    def _open_ticket(self, ticket: str) -> None:
        self._connecting = False
        if self._stopped:
            return
        try:
            self.socket.open(self.api.base_url, ticket)
        except ValueError as exc:
            self._failed(str(exc))
            return
        self._reconnect_delay_ms = 1000

    def _failed(self, message: str) -> None:
        self._connecting = False
        self.status_message.emit(f"实时通知不可用：{message}；保留定时轮询")
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._stopped or self._timer.isActive():
            return
        self._timer.start(self._reconnect_delay_ms)
        self._reconnect_delay_ms = min(self._reconnect_delay_ms * 2, 30000)
