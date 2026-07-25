from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from onepic_desktop_pet.realtime import (
    REALTIME_PROTOCOL,
    RealtimeClient,
    RealtimeSocket,
    websocket_url,
)


class FakeSocket(QObject):
    connected = Signal()
    disconnected = Signal()
    textMessageReceived = Signal(str)
    errorOccurred = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.open_calls: list[tuple[str, list[str]]] = []
        self.sent: list[str] = []
        self.closed = False

    def open(self, request, options) -> None:
        self.open_calls.append((request.url().toString(), list(options.subprotocols())))

    def close(self) -> None:
        self.closed = True

    def sendTextMessage(self, text: str) -> int:
        self.sent.append(text)
        return len(text)

    def errorString(self) -> str:
        return "fake socket error"


class FakeTicketTransport(QObject):
    ticket_ready = Signal(str)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.aborted = False
        self.busy = False

    def request_ticket(self) -> bool:
        self.calls += 1
        self.busy = True
        return True

    def abort(self) -> None:
        self.aborted = True
        self.busy = False


class FakeRealtimeSocket(QObject):
    cursor_available = Signal(int)
    status_message = Signal(str)
    disconnected_unexpectedly = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.connected = False
        self.open_calls: list[tuple[str, str]] = []
        self.stopped = False

    def open(self, base_url: str, ticket: str) -> None:
        self.open_calls.append((base_url, ticket))
        self.connected = True

    def stop(self) -> None:
        self.stopped = True
        self.connected = False


class FakeApi:
    base_url = "https://pets.example.test"


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_websocket_url_requires_http_transport() -> None:
    assert websocket_url("http://127.0.0.1:8000/") == "ws://127.0.0.1:8000/api/v1/realtime/ws"
    assert websocket_url("https://pets.example.test") == "wss://pets.example.test/api/v1/realtime/ws"


def test_realtime_socket_uses_ticket_subprotocol_and_emits_cursor() -> None:
    app = _application()
    fake = FakeSocket()
    realtime = RealtimeSocket(socket=fake)
    cursors: list[int] = []
    realtime.cursor_available.connect(cursors.append)

    realtime.open("https://pets.example.test", "ticket-value")
    assert fake.open_calls == [
        (
            "wss://pets.example.test/api/v1/realtime/ws",
            [REALTIME_PROTOCOL, "mypets.ticket.ticket-value"],
        )
    ]

    fake.connected.emit()
    assert realtime.connected is True
    fake.textMessageReceived.emit(
        json.dumps({"type": "hello", "cursor": 16})
    )
    fake.textMessageReceived.emit(
        json.dumps({"type": "events_available", "cursor": 17})
    )
    assert cursors == [16, 17]
    assert json.loads(fake.sent[-1]) == {"type": "ack", "cursor": 17}

    fake.textMessageReceived.emit(json.dumps({"type": "heartbeat", "cursor": 17}))
    assert json.loads(fake.sent[-1]) == {"type": "ack", "cursor": 17}

    realtime.stop()
    assert fake.closed is True
    assert app is not None


def test_realtime_client_requests_ticket_forwards_cursor_and_stops() -> None:
    app = _application()
    tickets = FakeTicketTransport()
    socket = FakeRealtimeSocket()
    client = RealtimeClient(
        FakeApi(),
        ticket_transport=tickets,
        realtime_socket=socket,
    )
    cursors: list[int] = []
    client.cursor_available.connect(cursors.append)

    client.start()
    assert tickets.calls == 1
    tickets.busy = False
    tickets.ticket_ready.emit("signed-ticket")
    assert socket.open_calls == [("https://pets.example.test", "signed-ticket")]

    socket.cursor_available.emit(23)
    assert cursors == [23]

    client.stop()
    assert tickets.aborted is True
    assert socket.stopped is True
    assert app is not None
