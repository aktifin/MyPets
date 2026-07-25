"""Administrator-only visual identity and asset-rights governance APIs.

The governance lifecycle is deliberately separate from package production and deployment:
- editors may maintain visual identity records and declare rights evidence;
- reviewers independently verify pending rights declarations;
- publishers may revoke rights and stop further private package distribution;
- every mutation is recorded in the administrator audit log.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import _audit, require_admin
from .api import get_session
from .asset_deployment_models import PetPersonalAssetRelease
from .asset_production_models import PetAssetProductionArtifact
from .governance_models import PetAssetRight, PetVisualIdentity
from .models import AccountPetRelation
from .security import Principal
from .services import append_event

governance_api_router = APIRouter(prefix="/api/v1/admin/governance", tags=["admin-governance"])

RightStatus = Literal["pending", "verified", "revoked"]


class IdentityUpsertRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    identity_version: str = Field(default="v1", min_length=1, max_length=32)
    hair_style: str = Field(default="", max_length=64)
    eye_style: str = Field(default="", max_length=64)
    color_palette: dict[str, Any] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list, max_length=100)
    reference_images: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("template_id", "identity_version", "hair_style", "eye_style")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("features", "reference_images")
    @classmethod
    def _normalize_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 240 for item in normalized):
            raise ValueError("视觉身份列表项不能超过 240 个字符")
        return list(dict.fromkeys(normalized))


class VisualIdentityView(BaseModel):
    identity_id: str
    template_id: str
    identity_version: str
    hair_style: str
    eye_style: str
    color_palette: dict[str, Any]
    features: list[str]
    reference_images: list[str]
    created_at: datetime
    updated_at: datetime


class RightDeclareRequest(BaseModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    rights_type: str = Field(min_length=1, max_length=64)
    source_declaration: str = Field(min_length=3, max_length=4000)

    @field_validator("artifact_id", "rights_type", "source_declaration")
    @classmethod
    def _strip_rights_text(cls, value: str) -> str:
        return value.strip()


class RightVerifyRequest(BaseModel):
    comment: str = Field(default="权利材料复核通过。", min_length=3, max_length=1000)

    @field_validator("comment")
    @classmethod
    def _strip_comment(cls, value: str) -> str:
        return value.strip()


class RightRevokeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return value.strip()


class LegacyRightRevokeRequest(RightRevokeRequest):
    right_id: str = Field(min_length=36, max_length=36)


class AssetRightView(BaseModel):
    right_id: str
    artifact_id: str
    rights_type: str
    source_declaration: str
    status: RightStatus
    declared_by_account_id: str
    verified_by_account_id: str | None
    revoked_reason: str | None
    created_at: datetime
    updated_at: datetime


class RightRevocationView(BaseModel):
    right: AssetRightView
    affected_release_ids: list[str]
    notified_account_ids: list[str]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json_dict(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _identity_view(identity: PetVisualIdentity) -> VisualIdentityView:
    return VisualIdentityView(
        identity_id=identity.id,
        template_id=identity.template_id,
        identity_version=identity.identity_version,
        hair_style=identity.hair_style,
        eye_style=identity.eye_style,
        color_palette=_json_dict(identity.color_palette_json),
        features=_json_list(identity.features_json),
        reference_images=_json_list(identity.reference_images_json),
        created_at=_aware(identity.created_at),
        updated_at=_aware(identity.updated_at),
    )


def _right_view(right: PetAssetRight) -> AssetRightView:
    current_status = right.status if right.status in {"pending", "verified", "revoked"} else "pending"
    return AssetRightView(
        right_id=right.id,
        artifact_id=right.artifact_id,
        rights_type=right.rights_type,
        source_declaration=right.source_declaration,
        status=current_status,  # type: ignore[arg-type]
        declared_by_account_id=right.declared_by_account_id,
        verified_by_account_id=right.verified_by_account_id,
        revoked_reason=right.revoked_reason,
        created_at=_aware(right.created_at),
        updated_at=_aware(right.updated_at),
    )


def _right_or_404(session: Session, right_id: str) -> PetAssetRight:
    right = session.get(PetAssetRight, right_id)
    if right is None:
        raise HTTPException(status_code=404, detail="版权存证记录不存在")
    return right


def _artifact_or_404(session: Session, artifact_id: str) -> PetAssetProductionArtifact:
    artifact = session.get(PetAssetProductionArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="制作产物不存在，不能登记权利存证")
    return artifact


def _latest_right(session: Session, artifact_id: str) -> PetAssetRight | None:
    return session.scalar(
        select(PetAssetRight)
        .where(PetAssetRight.artifact_id == artifact_id)
        .order_by(PetAssetRight.updated_at.desc(), PetAssetRight.created_at.desc(), PetAssetRight.id.desc())
        .limit(1)
    )


def _revoke_right(
    *,
    right: PetAssetRight,
    reason: str,
    principal: Principal,
    session: Session,
) -> RightRevocationView:
    if right.status == "revoked":
        raise HTTPException(status_code=409, detail="版权存证已经撤销")

    now = datetime.now(UTC)
    right.status = "revoked"
    right.revoked_reason = reason
    right.updated_at = now

    releases = list(
        session.scalars(
            select(PetPersonalAssetRelease).where(
                PetPersonalAssetRelease.artifact_id == right.artifact_id
            )
        )
    )
    notified: set[str] = set()
    for release in releases:
        account_ids = list(
            session.scalars(
                select(AccountPetRelation.account_id).where(
                    AccountPetRelation.pet_id == release.pet_id
                )
            )
        )
        for account_id in account_ids:
            append_event(
                session,
                account_id=account_id,
                event_type="asset_revoked",
                idempotency_key=f"asset-right-revoked:{right.id}:{release.id}:{account_id}",
                payload={
                    "cause": "asset_right_revoked",
                    "right_id": right.id,
                    "artifact_id": right.artifact_id,
                    "pet_id": release.pet_id,
                    "release_id": release.id,
                    "reason": reason,
                    "action": "evict_cache_and_fallback",
                },
            )
            notified.add(account_id)

    _audit(
        session,
        principal=principal,
        action="pet_asset_right.revoked",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={
            "artifact_id": right.artifact_id,
            "reason": reason,
            "affected_release_ids": [release.id for release in releases],
            "notified_account_ids": sorted(notified),
        },
    )
    session.commit()
    return RightRevocationView(
        right=_right_view(right),
        affected_release_ids=[release.id for release in releases],
        notified_account_ids=sorted(notified),
    )


@governance_api_router.post(
    "/identities",
    response_model=VisualIdentityView,
    status_code=status.HTTP_200_OK,
)
def upsert_visual_identity(
    body: IdentityUpsertRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> VisualIdentityView:
    identity = session.scalar(
        select(PetVisualIdentity).where(
            PetVisualIdentity.template_id == body.template_id,
            PetVisualIdentity.identity_version == body.identity_version,
        )
    )
    created = identity is None
    if identity is None:
        identity = PetVisualIdentity(
            id=str(uuid4()),
            template_id=body.template_id,
            identity_version=body.identity_version,
        )
        session.add(identity)

    identity.hair_style = body.hair_style
    identity.eye_style = body.eye_style
    identity.color_palette_json = json.dumps(
        body.color_palette, ensure_ascii=False, separators=(",", ":")
    )
    identity.features_json = json.dumps(
        body.features, ensure_ascii=False, separators=(",", ":")
    )
    identity.reference_images_json = json.dumps(
        body.reference_images, ensure_ascii=False, separators=(",", ":")
    )
    identity.updated_at = datetime.now(UTC)
    session.flush()
    _audit(
        session,
        principal=principal,
        action=("pet_visual_identity.created" if created else "pet_visual_identity.updated"),
        resource_type="pet_visual_identity",
        resource_id=identity.id,
        details={
            "template_id": identity.template_id,
            "identity_version": identity.identity_version,
        },
    )
    session.commit()
    return _identity_view(identity)


@governance_api_router.get(
    "/identities/{template_id}",
    response_model=list[VisualIdentityView],
)
def list_visual_identities(
    template_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    identity_version: str | None = Query(default=None, max_length=32),
) -> list[VisualIdentityView]:
    statement = select(PetVisualIdentity).where(PetVisualIdentity.template_id == template_id)
    if identity_version:
        statement = statement.where(PetVisualIdentity.identity_version == identity_version.strip())
    rows = list(
        session.scalars(
            statement.order_by(PetVisualIdentity.identity_version, PetVisualIdentity.created_at)
        )
    )
    if not rows:
        raise HTTPException(status_code=404, detail="视觉身份档案不存在")
    return [_identity_view(row) for row in rows]


@governance_api_router.get("/rights", response_model=list[AssetRightView])
def list_asset_rights(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    artifact_id: str | None = Query(default=None, max_length=36),
    status_filter: RightStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[AssetRightView]:
    statement = select(PetAssetRight)
    if artifact_id:
        statement = statement.where(PetAssetRight.artifact_id == artifact_id)
    if status_filter:
        statement = statement.where(PetAssetRight.status == status_filter)
    rows = list(
        session.scalars(
            statement.order_by(PetAssetRight.updated_at.desc(), PetAssetRight.id).limit(limit)
        )
    )
    return [_right_view(row) for row in rows]


@governance_api_router.post(
    "/rights",
    response_model=AssetRightView,
    status_code=status.HTTP_201_CREATED,
)
def declare_asset_right(
    body: RightDeclareRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> AssetRightView:
    _artifact_or_404(session, body.artifact_id)
    latest = _latest_right(session, body.artifact_id)
    if latest is not None and latest.status in {"pending", "verified"}:
        raise HTTPException(status_code=409, detail="该制作产物已有有效或待复核的版权存证")

    right = PetAssetRight(
        id=str(uuid4()),
        artifact_id=body.artifact_id,
        rights_type=body.rights_type,
        source_declaration=body.source_declaration,
        status="pending",
        declared_by_account_id=principal.account_id,
        verified_by_account_id=None,
    )
    session.add(right)
    session.flush()
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.declared",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={
            "artifact_id": right.artifact_id,
            "rights_type": right.rights_type,
        },
    )
    session.commit()
    return _right_view(right)


@governance_api_router.post(
    "/rights/{right_id}/verify",
    response_model=AssetRightView,
)
def verify_asset_right(
    right_id: str,
    body: RightVerifyRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> AssetRightView:
    right = _right_or_404(session, right_id)
    if right.status != "pending":
        raise HTTPException(status_code=409, detail="只有待复核版权存证可以核验")
    if right.declared_by_account_id == principal.account_id:
        raise HTTPException(status_code=409, detail="版权声明人不能复核自己的存证")

    right.status = "verified"
    right.verified_by_account_id = principal.account_id
    right.revoked_reason = None
    right.updated_at = datetime.now(UTC)
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.verified",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={
            "artifact_id": right.artifact_id,
            "comment": body.comment,
        },
    )
    session.commit()
    return _right_view(right)


@governance_api_router.post(
    "/rights/{right_id}/revoke",
    response_model=RightRevocationView,
)
def revoke_asset_right(
    right_id: str,
    body: RightRevokeRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> RightRevocationView:
    return _revoke_right(
        right=_right_or_404(session, right_id),
        reason=body.reason,
        principal=principal,
        session=session,
    )


@governance_api_router.post(
    "/rights/revoke",
    response_model=RightRevocationView,
    deprecated=True,
)
def revoke_asset_right_legacy(
    body: LegacyRightRevokeRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> RightRevocationView:
    """Backward-compatible path retained for older administrator clients."""

    return _revoke_right(
        right=_right_or_404(session, body.right_id),
        reason=body.reason,
        principal=principal,
        session=session,
    )
