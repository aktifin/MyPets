"""Lazy pet settlement middleware for authoritative pet snapshots.

Only read paths that return a complete pet snapshot are intercepted. Invalid, expired, or
revoked credentials are ignored here and remain the responsibility of the normal API
authentication dependency; the middleware never turns an authentication failure into a
successful response.
"""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .models import Account, Device
from .pet_state_service import settle_pets_for_account
from .security import decode_access_token

_SETTLEMENT_PATHS = {"/api/v1/pets", "/api/v1/sync/bootstrap"}


class PetSettlementMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method == "GET" and request.url.path in _SETTLEMENT_PATHS:
            self._settle_if_authenticated(request)
        return await call_next(request)

    @staticmethod
    def _settle_if_authenticated(request: Request) -> None:
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return
        try:
            principal = decode_access_token(token.strip(), request.app.state.settings)
        except jwt.PyJWTError:
            return

        with request.app.state.session_factory() as session:
            account = session.get(Account, principal.account_id)
            if account is None:
                return
            if principal.kind == "device":
                device = session.get(Device, principal.device_id)
                if (
                    device is None
                    or device.account_id != principal.account_id
                    or device.revoked_at is not None
                    or device.credential_version != principal.device_version
                ):
                    return
            settle_pets_for_account(
                session,
                account_id=principal.account_id,
                now=datetime.now(UTC),
                trigger="bootstrap" if request.url.path.endswith("bootstrap") else "pet_list",
            )
            session.commit()
