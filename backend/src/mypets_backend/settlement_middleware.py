"""Lazy pet and visit settlement middleware for authoritative snapshots.

Only read paths that return a complete pet snapshot and pet-care mutation paths are
intercepted. Invalid, expired, or revoked credentials are ignored here and remain the
responsibility of the normal API authentication dependency; the middleware never turns an
authentication failure into a successful response.
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
from .visit_service import settle_due_visits

_SETTLEMENT_PATHS = {
    "/api/v1/pets",
    "/api/v1/sync/bootstrap",
    "/api/v1/portal/dashboard",
}


class PetSettlementMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        should_settle = request.method == "GET" and request.url.path in _SETTLEMENT_PATHS
        should_settle = should_settle or (
            request.method == "POST"
            and request.url.path.startswith("/api/v1/pets/")
            and "/interactions/" in request.url.path
        )
        if should_settle:
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
            now = datetime.now(UTC)
            settle_due_visits(session, now=now)
            trigger = "pet_care" if request.method == "POST" else "pet_list"
            if request.url.path.endswith("bootstrap"):
                trigger = "bootstrap"
            elif request.url.path.endswith("dashboard"):
                trigger = "portal_dashboard"
            settle_pets_for_account(
                session,
                account_id=principal.account_id,
                now=now,
                trigger=trigger,
            )
            session.commit()
