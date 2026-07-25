"""Password hashing, device-secret hashing, and signed access tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import Settings

_password_hasher = PasswordHasher()
TokenKind = Literal["account", "device"]
_REALTIME_AUDIENCE = "mypets-realtime"


@dataclass(frozen=True)
class Principal:
    account_id: str
    kind: TokenKind
    device_id: str | None = None
    device_version: int | None = None


def normalize_username(username: str) -> str:
    return username.strip().lower()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _password_hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_device_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_device_secret(secret: str, settings: Settings) -> str:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        secret.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_device_secret(secret: str, encoded: str, settings: Settings) -> bool:
    return hmac.compare_digest(hash_device_secret(secret, settings), encoded)


def create_access_token(
    settings: Settings,
    *,
    account_id: str,
    kind: TokenKind,
    device_id: str | None = None,
    device_version: int | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if kind == "account"
        else timedelta(hours=settings.device_token_hours)
    )
    expires_at = now + lifetime
    payload = {
        "sub": account_id,
        "kind": kind,
        "device_id": device_id,
        "device_version": device_version,
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), expires_at


def decode_access_token(token: str, settings: Settings) -> Principal:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    return _principal_from_claims(payload)


def create_realtime_ticket(
    settings: Settings,
    principal: Principal,
) -> tuple[str, datetime]:
    """Create a short-lived ticket intended only for a WebSocket subprotocol header."""

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.realtime_ticket_seconds)
    payload = {
        "sub": principal.account_id,
        "kind": "realtime",
        "source_kind": principal.kind,
        "device_id": principal.device_id,
        "device_version": principal.device_version,
        "aud": _REALTIME_AUDIENCE,
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), expires_at


def decode_realtime_ticket(token: str, settings: Settings) -> Principal:
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=_REALTIME_AUDIENCE,
    )
    if payload.get("kind") != "realtime":
        raise jwt.InvalidTokenError("invalid realtime ticket kind")
    source_kind = payload.get("source_kind")
    claims = {
        "sub": payload.get("sub"),
        "kind": source_kind,
        "device_id": payload.get("device_id"),
        "device_version": payload.get("device_version"),
    }
    return _principal_from_claims(claims)


def _principal_from_claims(payload: dict) -> Principal:
    account_id = str(payload.get("sub", "")).strip()
    kind = payload.get("kind")
    device_id = payload.get("device_id")
    device_version = payload.get("device_version")
    if not account_id or kind not in {"account", "device"}:
        raise jwt.InvalidTokenError("invalid principal claims")
    if kind == "device" and (not device_id or not isinstance(device_version, int)):
        raise jwt.InvalidTokenError("device token missing device claims")
    return Principal(
        account_id=account_id,
        kind=kind,
        device_id=str(device_id) if device_id else None,
        device_version=device_version if isinstance(device_version, int) else None,
    )
