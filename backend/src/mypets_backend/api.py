"""FastAPI routes for account authentication, device binding, pets, and sync."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .models import Account, AccountPetRelation, Device, Pet
from .schemas import (
    AccountView,
    ActivePetRequest,
    BootstrapResponse,
    DeviceBindingResponse,
    DeviceBindRequest,
    DeviceTokenRequest,
    DeviceView,
    EventsResponse,
    HeartbeatResponse,
    PetCreateRequest,
    PetView,
    RegisterRequest,
    TokenResponse,
)
from .security import (
    Principal,
    create_access_token,
    decode_access_token,
    generate_device_secret,
    hash_device_secret,
    hash_password,
    normalize_username,
    verify_device_secret,
    verify_password,
)
from .services import (
    account_view,
    append_event,
    current_cursor,
    device_view,
    event_view,
    events_after,
    find_event_by_idempotency,
    pet_for_account,
    pet_view,
    pets_for_account,
    relation_view,
    relations_for_account,
)

router = APIRouter(prefix="/api/v1")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request):
    with request.app.state.session_factory() as session:
        yield session


def _unauthorized(detail: str = "认证失败") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_principal(
    token: Annotated[str, Depends(oauth2_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    try:
        principal = decode_access_token(token, settings)
    except jwt.PyJWTError as exc:
        raise _unauthorized("访问令牌无效或已过期") from exc
    account = session.get(Account, principal.account_id)
    if account is None:
        raise _unauthorized("账户不存在")
    if principal.kind == "device":
        device = session.get(Device, principal.device_id)
        if (
            device is None
            or device.account_id != principal.account_id
            or device.revoked_at is not None
            or device.credential_version != principal.device_version
        ):
            raise _unauthorized("设备已失效")
    return principal


def require_account(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    if principal.kind != "account":
        raise HTTPException(status_code=403, detail="此操作需要账户访问令牌")
    return principal


def require_device(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    if principal.kind != "device" or principal.device_id is None:
        raise HTTPException(status_code=403, detail="此操作需要设备访问令牌")
    return principal


def _token_response(
    settings: Settings,
    account: Account,
    *,
    kind: str,
    device_id: str | None = None,
    device_version: int | None = None,
) -> TokenResponse:
    token, expires_at = create_access_token(
        settings,
        account_id=account.id,
        kind=kind,  # type: ignore[arg-type]
        device_id=device_id,
        device_version=device_version,
    )
    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        account=account_view(account),
        device_id=device_id,
    )


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(
    body: RegisterRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> TokenResponse:
    username = normalize_username(body.username)
    if session.scalar(select(Account.id).where(Account.username == username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    account = Account(
        id=str(uuid4()),
        username=username,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    return _token_response(settings, account, kind="account")


@router.post("/auth/token", response_model=TokenResponse)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> TokenResponse:
    account = session.scalar(
        select(Account).where(Account.username == normalize_username(form.username))
    )
    if account is None or not verify_password(form.password, account.password_hash):
        raise _unauthorized("用户名或密码错误")
    return _token_response(settings, account, kind="account")


@router.post("/auth/device-token", response_model=TokenResponse)
def exchange_device_token(
    body: DeviceTokenRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> TokenResponse:
    device = session.get(Device, body.device_id)
    if (
        device is None
        or device.revoked_at is not None
        or not verify_device_secret(body.device_secret, device.secret_hash, settings)
    ):
        raise _unauthorized("设备凭据无效")
    account = session.get(Account, device.account_id)
    if account is None:
        raise _unauthorized("账户不存在")
    device.last_seen_at = datetime.now(UTC)
    session.commit()
    return _token_response(
        settings,
        account,
        kind="device",
        device_id=device.id,
        device_version=device.credential_version,
    )


@router.get("/accounts/me", response_model=AccountView)
def me(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> AccountView:
    account = session.get(Account, principal.account_id)
    assert account is not None
    return account_view(account)


@router.post("/devices/bind", response_model=DeviceBindingResponse, status_code=201)
def bind_device(
    body: DeviceBindRequest,
    principal: Annotated[Principal, Depends(require_account)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> DeviceBindingResponse:
    device = session.scalar(
        select(Device).where(
            Device.account_id == principal.account_id,
            Device.public_id == body.public_id,
        )
    )
    secret = generate_device_secret()
    if device is None:
        device = Device(
            id=str(uuid4()),
            account_id=principal.account_id,
            public_id=body.public_id,
            name=body.name.strip(),
            platform=body.platform,
            secret_hash=hash_device_secret(secret, settings),
            credential_version=1,
        )
        session.add(device)
    else:
        device.name = body.name.strip()
        device.platform = body.platform
        device.secret_hash = hash_device_secret(secret, settings)
        device.credential_version += 1
        device.revoked_at = None
    session.flush()
    append_event(
        session,
        account_id=principal.account_id,
        event_type="device_bound",
        idempotency_key=f"device-bind:{device.id}:{uuid4()}",
        payload={"device": device_view(device).model_dump(mode="json")},
        target_device_id=device.id,
    )
    session.commit()
    return DeviceBindingResponse(device=device_view(device), device_secret=secret)


@router.get("/devices", response_model=list[DeviceView])
def list_devices(
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> list[DeviceView]:
    devices = session.scalars(
        select(Device)
        .where(Device.account_id == principal.account_id)
        .order_by(Device.created_at, Device.id)
    )
    return [device_view(device) for device in devices]


@router.delete("/devices/{device_id}", status_code=204)
def revoke_device(
    device_id: str,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    device = session.get(Device, device_id)
    if device is None or device.account_id != principal.account_id:
        raise HTTPException(status_code=404, detail="设备不存在")
    if device.revoked_at is None:
        device.revoked_at = datetime.now(UTC)
        device.credential_version += 1
        append_event(
            session,
            account_id=principal.account_id,
            event_type="device_revoked",
            idempotency_key=f"device-revoke:{device.id}",
            payload={"device_id": device.id},
        )
        session.commit()


@router.patch("/devices/{device_id}/active-pet", response_model=DeviceView)
def set_active_pet(
    device_id: str,
    body: ActivePetRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> DeviceView:
    if principal.kind == "device" and principal.device_id != device_id:
        raise HTTPException(status_code=403, detail="设备只能修改自己的当前宠物")
    device = session.get(Device, device_id)
    if device is None or device.account_id != principal.account_id:
        raise HTTPException(status_code=404, detail="设备不存在")
    existing = find_event_by_idempotency(
        session, principal.account_id, idempotency_key
    )
    if existing is not None:
        if existing.event_type != "active_pet_changed":
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        return device_view(device)
    if body.pet_id is not None and pet_for_account(
        session, principal.account_id, body.pet_id
    ) is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    device.active_pet_id = body.pet_id
    device.last_seen_at = datetime.now(UTC)
    append_event(
        session,
        account_id=principal.account_id,
        event_type="active_pet_changed",
        idempotency_key=idempotency_key,
        payload={"device_id": device.id, "pet_id": body.pet_id},
        target_device_id=device.id,
    )
    session.commit()
    return device_view(device)


@router.post("/pets", response_model=PetView, status_code=201)
def create_pet(
    body: PetCreateRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> PetView:
    existing = find_event_by_idempotency(
        session, principal.account_id, idempotency_key
    )
    if existing is not None:
        if existing.event_type != "pet_created":
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        pet_id = event_view(existing).payload.get("pet", {}).get("pet_id")
        pet = session.get(Pet, pet_id) if pet_id else None
        if pet is None:
            raise HTTPException(status_code=409, detail="幂等记录对应资源不存在")
        return pet_view(pet)

    pet = Pet(
        id=str(uuid4()),
        name=body.name,
        template_id=body.template_id,
        template_version=body.template_version,
        identity_version=body.identity_version,
        asset_version=body.asset_version,
        primary_owner_account_id=principal.account_id,
    )
    relation = AccountPetRelation(
        account_id=principal.account_id,
        pet_id=pet.id,
        role="owner",
        affinity=0,
        care_contribution=0,
    )
    session.add(pet)
    session.flush()
    session.add(relation)
    session.flush()
    append_event(
        session,
        account_id=principal.account_id,
        event_type="pet_created",
        idempotency_key=idempotency_key,
        payload={
            "pet": pet_view(pet).model_dump(mode="json"),
            "relation": relation_view(relation).model_dump(mode="json"),
        },
    )
    session.commit()
    return pet_view(pet)


@router.get("/pets", response_model=list[PetView])
def list_pets(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> list[PetView]:
    return [pet_view(pet) for pet in pets_for_account(session, principal.account_id)]


@router.get("/sync/bootstrap", response_model=BootstrapResponse)
def bootstrap(
    principal: Annotated[Principal, Depends(require_device)],
    session: Annotated[Session, Depends(get_session)],
) -> BootstrapResponse:
    account = session.get(Account, principal.account_id)
    device = session.get(Device, principal.device_id)
    assert account is not None and device is not None
    device.last_seen_at = datetime.now(UTC)
    session.commit()
    return BootstrapResponse(
        server_time=datetime.now(UTC),
        account=account_view(account),
        device=device_view(device),
        pets=[pet_view(pet) for pet in pets_for_account(session, principal.account_id)],
        relations=[
            relation_view(relation)
            for relation in relations_for_account(session, principal.account_id)
        ],
        cursor=current_cursor(session, principal.account_id),
    )


@router.get("/sync/events", response_model=EventsResponse)
def get_events(
    principal: Annotated[Principal, Depends(require_device)],
    session: Annotated[Session, Depends(get_session)],
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> EventsResponse:
    events, has_more = events_after(
        session,
        account_id=principal.account_id,
        device_id=principal.device_id or "",
        after_sequence=after_sequence,
        limit=limit,
    )
    next_cursor = events[-1].sequence if events else after_sequence
    return EventsResponse(
        events=[event_view(event) for event in events],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post("/sync/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    principal: Annotated[Principal, Depends(require_device)],
    session: Annotated[Session, Depends(get_session)],
) -> HeartbeatResponse:
    device = session.get(Device, principal.device_id)
    assert device is not None
    device.last_seen_at = datetime.now(UTC)
    session.commit()
    return HeartbeatResponse(
        server_time=datetime.now(UTC),
        cursor=current_cursor(session, principal.account_id),
    )
