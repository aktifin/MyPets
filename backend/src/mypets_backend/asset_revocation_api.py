"""Device and administrator APIs for revoked personal asset cleanup acknowledgements."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import require_admin
from .api import get_session, get_principal, require_device
from .asset_deployment_api import _release_view
from .asset_deployment_models import PetPersonalAssetRelease
from .asset_revocation_models import PetAssetRevocationAcknowledgement
from .governance_models import PetAssetRight
from .models import AccountPetRelation
from .security import Principal

asset_revocation_router = APIRouter(prefix="/api/v1", tags=["asset-revocations"])
admin_asset_revocation_router = APIRouter(
    prefix="/api/v1/admin/governance", tags=["admin-governance"]
)

AckStatus = Literal["completed", "failed"]


class RevokedAssetIdentityView(BaseModel):
    template_id: str
    identity_version: str
    asset_version: str


class AssetRevocationNoticeView(BaseModel):
    right_id: str
    artifact_id: str
    release_id: str
    pet_id: str
    reason: str
    action: Literal["evict_cache_and_fallback"] = "evict_cache_and_fallback"
    asset_identity: RevokedAssetIdentityView
    revoked_at: datetime


class AssetRevocationAcknowledgeRequest(BaseModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    release_id: str = Field(min_length=36, max_length=36)
    pet_id: str = Field(min_length=36, max_length=36)
    status: AckStatus
    cache_cleared: bool
    fallback_applied: bool
    message: str = Field(default="", max_length=1000)
    processed_at: datetime

    @field_validator("artifact_id", "release_id", "pet_id", "message")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("processed_at")
    @classmethod
    def _require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("processed_at 必须包含时区")
        return value.astimezone(UTC)


class AssetRevocationAcknowledgementView(BaseModel):
    acknowledgement_id: str
    right_id: str
    artifact_id: str
    release_id: str
    pet_id: str
    account_id: str
    device_id: str
    status: AckStatus
    cache_cleared: bool
    fallback_applied: bool
    message: str
    attempt_count: int
    client_processed_at: datetime
    created_at: datetime
    updated_at: datetime


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _view(item: PetAssetRevocationAcknowledgement) -> AssetRevocationAcknowledgementView:
    status_value = item.status if item.status in {"completed", "failed"} else "failed"
    return AssetRevocationAcknowledgementView(
        acknowledgement_id=item.id,
        right_id=item.right_id,
        artifact_id=item.artifact_id,
        release_id=item.release_id,
        pet_id=item.pet_id,
        account_id=item.account_id,
        device_id=item.device_id,
        status=status_value,  # type: ignore[arg-type]
        cache_cleared=item.cache_cleared,
        fallback_applied=item.fallback_applied,
        message=item.message,
        attempt_count=item.attempt_count,
        client_processed_at=_aware(item.client_processed_at),
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def _latest_right(session: Session, artifact_id: str) -> PetAssetRight | None:
    return session.scalar(
        select(PetAssetRight)
        .where(PetAssetRight.artifact_id == artifact_id)
        .order_by(
            PetAssetRight.updated_at.desc(),
            PetAssetRight.created_at.desc(),
            PetAssetRight.id.desc(),
        )
        .limit(1)
    )


def _validate_scope(
    session: Session,
    *,
    principal: Principal,
    right_id: str,
    body: AssetRevocationAcknowledgeRequest,
) -> tuple[PetAssetRight, PetPersonalAssetRelease]:
    right = session.get(PetAssetRight, right_id)
    if right is None or right.status != "revoked":
        raise HTTPException(status_code=404, detail="已撤销版权存证不存在")
    release = session.get(PetPersonalAssetRelease, body.release_id)
    if (
        release is None
        or release.artifact_id != right.artifact_id
        or release.artifact_id != body.artifact_id
        or release.pet_id != body.pet_id
    ):
        raise HTTPException(status_code=409, detail="撤销回执与版权存证或专属 Release 不匹配")
    relation = session.get(AccountPetRelation, (principal.account_id, body.pet_id))
    if relation is None:
        raise HTTPException(status_code=404, detail="撤销回执目标宠物不存在")
    return right, release


@asset_revocation_router.get(
    "/asset-revocations",
    response_model=list[AssetRevocationNoticeView],
)
def list_current_asset_revocations(
    principal: Annotated[Principal, Depends(require_device)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=200, ge=1, le=500),
) -> list[AssetRevocationNoticeView]:
    pet_ids = list(
        session.scalars(
            select(AccountPetRelation.pet_id).where(
                AccountPetRelation.account_id == principal.account_id
            )
        )
    )
    if not pet_ids:
        return []
    releases = list(
        session.scalars(
            select(PetPersonalAssetRelease)
            .where(PetPersonalAssetRelease.pet_id.in_(pet_ids))
            .order_by(PetPersonalAssetRelease.created_at.desc(), PetPersonalAssetRelease.id)
            .limit(limit)
        )
    )
    notices: list[AssetRevocationNoticeView] = []
    for release in releases:
        right = _latest_right(session, release.artifact_id)
        if right is None or right.status != "revoked":
            continue
        release_data = _release_view(session, release)
        notices.append(
            AssetRevocationNoticeView(
                right_id=right.id,
                artifact_id=release.artifact_id,
                release_id=release.id,
                pet_id=release.pet_id,
                reason=right.revoked_reason or "版权授权已撤销，停止使用该专属素材。",
                asset_identity=RevokedAssetIdentityView(
                    template_id=release_data.template_code,
                    identity_version=release_data.identity_version,
                    asset_version=release_data.asset_version,
                ),
                revoked_at=_aware(right.updated_at),
            )
        )
    return notices


@asset_revocation_router.post(
    "/asset-revocations/{right_id}/acknowledgements",
    response_model=AssetRevocationAcknowledgementView,
)
def acknowledge_asset_revocation(
    right_id: str,
    body: AssetRevocationAcknowledgeRequest,
    principal: Annotated[Principal, Depends(require_device)],
    session: Annotated[Session, Depends(get_session)],
) -> AssetRevocationAcknowledgementView:
    _validate_scope(session, principal=principal, right_id=right_id, body=body)
    assert principal.device_id is not None
    existing = session.scalar(
        select(PetAssetRevocationAcknowledgement).where(
            PetAssetRevocationAcknowledgement.right_id == right_id,
            PetAssetRevocationAcknowledgement.release_id == body.release_id,
            PetAssetRevocationAcknowledgement.device_id == principal.device_id,
        )
    )
    now = datetime.now(UTC)
    if existing is None:
        existing = PetAssetRevocationAcknowledgement(
            id=str(uuid4()),
            right_id=right_id,
            artifact_id=body.artifact_id,
            release_id=body.release_id,
            pet_id=body.pet_id,
            account_id=principal.account_id,
            device_id=principal.device_id,
            attempt_count=1,
            client_processed_at=body.processed_at,
        )
        session.add(existing)
    else:
        if existing.account_id != principal.account_id or existing.pet_id != body.pet_id:
            raise HTTPException(status_code=409, detail="撤销回执设备范围不一致")
        existing.attempt_count += 1
    existing.status = body.status
    existing.cache_cleared = body.cache_cleared
    existing.fallback_applied = body.fallback_applied
    existing.message = body.message
    existing.client_processed_at = body.processed_at
    existing.updated_at = now
    session.commit()
    return _view(existing)


@asset_revocation_router.get(
    "/asset-revocations/acknowledgements",
    response_model=list[AssetRevocationAcknowledgementView],
)
def list_my_asset_revocation_acknowledgements(
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
    pet_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[AssetRevocationAcknowledgementView]:
    statement = select(PetAssetRevocationAcknowledgement).where(
        PetAssetRevocationAcknowledgement.account_id == principal.account_id
    )
    if principal.kind == "device" and principal.device_id:
        statement = statement.where(
            PetAssetRevocationAcknowledgement.device_id == principal.device_id
        )
    if pet_id:
        statement = statement.where(PetAssetRevocationAcknowledgement.pet_id == pet_id)
    rows = session.scalars(
        statement.order_by(
            PetAssetRevocationAcknowledgement.updated_at.desc(),
            PetAssetRevocationAcknowledgement.id,
        ).limit(limit)
    )
    return [_view(item) for item in rows]


@admin_asset_revocation_router.get(
    "/revocation-acknowledgements",
    response_model=list[AssetRevocationAcknowledgementView],
)
def list_admin_asset_revocation_acknowledgements(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    right_id: str | None = Query(default=None, max_length=36),
    status_filter: AckStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[AssetRevocationAcknowledgementView]:
    statement = select(PetAssetRevocationAcknowledgement)
    if right_id:
        statement = statement.where(PetAssetRevocationAcknowledgement.right_id == right_id)
    if status_filter:
        statement = statement.where(PetAssetRevocationAcknowledgement.status == status_filter)
    rows = session.scalars(
        statement.order_by(
            PetAssetRevocationAcknowledgement.updated_at.desc(),
            PetAssetRevocationAcknowledgement.id,
        ).limit(limit)
    )
    return [_view(item) for item in rows]
