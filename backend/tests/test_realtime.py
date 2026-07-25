from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mypets_backend.realtime_api import REALTIME_PROTOCOL


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "display_name": username,
            "password": "a-strong-test-password",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _device_auth(client: TestClient, account_auth: dict[str, str]) -> dict[str, str]:
    bound = client.post(
        "/api/v1/devices/bind",
        headers=account_auth,
        json={
            "public_id": "realtime-test-device-0001",
            "name": "实时测试设备",
            "platform": "windows",
        },
    )
    assert bound.status_code == 201, bound.text
    token = client.post(
        "/api/v1/auth/device-token",
        json={
            "device_id": bound.json()["device"]["id"],
            "device_secret": bound.json()["device_secret"],
        },
    )
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _ticket(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post("/api/v1/realtime/ticket", headers=auth)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["protocol"] == REALTIME_PROTOCOL
    assert payload["ticket"]
    assert "expires_at" in payload
    return payload["ticket"]


def test_device_websocket_announces_new_cursor_without_event_payload(client: TestClient) -> None:
    owner = _register(client, "realtime_owner")
    sender = _register(client, "realtime_sender")
    device = _device_auth(client, owner)
    ticket = _ticket(client, device)

    with client.websocket_connect(
        "/api/v1/realtime/ws?after_sequence=0",
        subprotocols=[REALTIME_PROTOCOL, f"mypets.ticket.{ticket}"],
    ) as websocket:
        assert websocket.accepted_subprotocol == REALTIME_PROTOCOL
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        assert hello["source_kind"] == "device"
        initial_cursor = hello["cursor"]

        created = client.post(
            "/api/v1/friend-requests",
            headers=sender,
            json={"username": "realtime_owner"},
        )
        assert created.status_code == 201, created.text

        notice = websocket.receive_json()
        assert notice["type"] == "events_available"
        assert notice["cursor"] > initial_cursor
        assert set(notice) == {"type", "cursor", "server_time"}
        websocket.send_json({"type": "ack", "cursor": notice["cursor"]})
        websocket.send_json({"type": "ping"})
        pong = websocket.receive_json()
        assert pong["type"] == "pong"


def test_account_ticket_connects_for_portal_refresh_hints(client: TestClient) -> None:
    account = _register(client, "realtime_portal")
    ticket = _ticket(client, account)
    with client.websocket_connect(
        "/api/v1/realtime/ws",
        subprotocols=[REALTIME_PROTOCOL, f"mypets.ticket.{ticket}"],
    ) as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        assert hello["source_kind"] == "account"


def test_websocket_rejects_missing_or_invalid_ticket(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as missing:
        with client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[REALTIME_PROTOCOL],
        ):
            pass
    assert missing.value.code == 4401

    with pytest.raises(WebSocketDisconnect) as invalid:
        with client.websocket_connect(
            "/api/v1/realtime/ws",
            subprotocols=[REALTIME_PROTOCOL, "mypets.ticket.not-a-jwt"],
        ):
            pass
    assert invalid.value.code == 4401
