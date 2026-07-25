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
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .models import Account, Device
from .pet_state_service import settle_pets_for_account
from .security import Principal, decode_access_token
from .social_models import AccountBlock
from .visit_service import settle_due_visits, terminate_visits_between

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
        response = await call_next(request)
        if 200 <= response.status_code < 300:
            if request.method == "POST" and request.url.path == "/api/v1/blocks":
                self._terminate_newly_blocked_visits(request)
            elif request.method == "DELETE" and request.url.path.startswith(
                "/api/v1/friends/"
            ):
                friend_account_id = request.url.path.rsplit("/", 1)[-1].strip()
                if friend_account_id:
                    self._terminate_relationship_visits(
                        request,
                        friend_account_id,
                        reason="friend_removed",
                    )
        return response

    @staticmethod
    def _principal_if_valid(request: Request, session: Session) -> Principal | None:
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None
        try:
            principal = decode_access_token(token.strip(), request.app.state.settings)
        except jwt.PyJWTError:
            return None
        account = session.get(Account, principal.account_id)
        if account is None:
            return None
        if principal.kind == "device":
            device = session.get(Device, principal.device_id)
            if (
                device is None
                or device.account_id != principal.account_id
                or device.revoked_at is not None
                or device.credential_version != principal.device_version
            ):
                return None
        return principal

    @classmethod
    def _settle_if_authenticated(cls, request: Request) -> None:
        with request.app.state.session_factory() as session:
            principal = cls._principal_if_valid(request, session)
            if principal is None:
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

    @classmethod
    def _terminate_newly_blocked_visits(cls, request: Request) -> None:
        with request.app.state.session_factory() as session:
            principal = cls._principal_if_valid(request, session)
            if principal is None:
                return
            blocked_ids = list(
                session.scalars(
                    select(AccountBlock.blocked_account_id).where(
                        AccountBlock.blocker_account_id == principal.account_id
                    )
                )
            )
            now = datetime.now(UTC)
            for blocked_account_id in blocked_ids:
                terminate_visits_between(
                    session,
                    principal.account_id,
                    blocked_account_id,
                    now=now,
                    reason="account_blocked",
                )
            session.commit()

    @classmethod
    def _terminate_relationship_visits(
        cls,
        request: Request,
        other_account_id: str,
        *,
        reason: str,
    ) -> None:
        with request.app.state.session_factory() as session:
            principal = cls._principal_if_valid(request, session)
            if principal is None:
                return
            terminate_visits_between(
                session,
                principal.account_id,
                other_account_id,
                now=datetime.now(UTC),
                reason=reason,
            )
            session.commit()
