"""Short-lived ticket issuance and account-scoped WebSocket cursor notifications."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .api import get_principal
from .config import Settings
from .models import Account, Device
from .security import Principal, create_realtime_ticket, decode_realtime_ticket
from .services import current_cursor

realtime_router = APIRouter(prefix="/api/v1/realtime", tags=["realtime"])
REALTIME_PROTOCOL = "mypets.realtime.v1"
_TICKET_PREFIX = "mypets.ticket."


class RealtimeTicketResponse(BaseModel):
    ticket: str
    expires_at: datetime
    protocol: str = REALTIME_PROTOCOL


@realtime_router.post("/ticket", response_model=RealtimeTicketResponse)
def issue_realtime_ticket(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> RealtimeTicketResponse:
    settings: Settings = request.app.state.settings
    ticket, expires_at = create_realtime_ticket(settings, principal)
    return RealtimeTicketResponse(ticket=ticket, expires_at=expires_at)


def _offered_protocols(websocket: WebSocket) -> list[str]:
    raw = websocket.headers.get("sec-websocket-protocol", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _ticket_from_protocols(protocols: list[str]) -> str | None:
    for value in protocols:
        if value.startswith(_TICKET_PREFIX):
            ticket = value[len(_TICKET_PREFIX) :].strip()
            if ticket:
                return ticket
    return None


def _validate_principal(session: Session, principal: Principal) -> bool:
    account = session.get(Account, principal.account_id)
    if account is None:
        return False
    if principal.kind != "device":
        return True
    device = session.get(Device, principal.device_id)
    return bool(
        device is not None
        and device.account_id == principal.account_id
        and device.revoked_at is None
        and device.credential_version == principal.device_version
    )


def _safe_after_sequence(websocket: WebSocket) -> int:
    raw = websocket.query_params.get("after_sequence", "0")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


@realtime_router.websocket("/ws")
async def realtime_websocket(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    protocols = _offered_protocols(websocket)
    ticket = _ticket_from_protocols(protocols)
    if REALTIME_PROTOCOL not in protocols or ticket is None:
        await websocket.close(code=4401, reason="缺少实时连接协议或票据")
        return
    try:
        principal = decode_realtime_ticket(ticket, settings)
    except jwt.PyJWTError:
        await websocket.close(code=4401, reason="实时连接票据无效或已过期")
        return

    with websocket.app.state.session_factory() as session:
        if not _validate_principal(session, principal):
            await websocket.close(code=4401, reason="账户或设备已失效")
            return
        server_cursor = current_cursor(session, principal.account_id)

    await websocket.accept(subprotocol=REALTIME_PROTOCOL)
    client_cursor = min(_safe_after_sequence(websocket), server_cursor)
    last_announced_cursor = client_cursor
    await websocket.send_json(
        {
            "type": "hello",
            "cursor": server_cursor,
            "server_time": datetime.now(UTC).isoformat(),
            "source_kind": principal.kind,
        }
    )
    last_heartbeat = asyncio.get_running_loop().time()

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=settings.realtime_poll_interval_seconds,
                )
                if isinstance(message, dict):
                    message_type = message.get("type")
                    if message_type == "ack":
                        try:
                            acknowledged = int(message.get("cursor", 0))
                        except (TypeError, ValueError):
                            acknowledged = 0
                        last_announced_cursor = max(last_announced_cursor, acknowledged)
                    elif message_type == "ping":
                        await websocket.send_json(
                            {
                                "type": "pong",
                                "server_time": datetime.now(UTC).isoformat(),
                            }
                        )
            except TimeoutError:
                pass

            with websocket.app.state.session_factory() as session:
                if not _validate_principal(session, principal):
                    await websocket.close(code=4401, reason="账户或设备已失效")
                    return
                latest_cursor = current_cursor(session, principal.account_id)

            if latest_cursor > last_announced_cursor:
                await websocket.send_json(
                    {
                        "type": "events_available",
                        "cursor": latest_cursor,
                        "server_time": datetime.now(UTC).isoformat(),
                    }
                )
                last_announced_cursor = latest_cursor

            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= settings.realtime_heartbeat_seconds:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "cursor": latest_cursor,
                        "server_time": datetime.now(UTC).isoformat(),
                    }
                )
                last_heartbeat = now
    except WebSocketDisconnect:
        return
