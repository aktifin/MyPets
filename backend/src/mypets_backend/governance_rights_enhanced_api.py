"""Enhanced copyright-rights lifecycle registered before compatibility routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .admin_api import _audit, require_admin
from .api import get_session
from .asset_deployment_models import PetPersonalAssetRelease
from .asset_production_models import PetAssetProductionArtifact
from .governance_history import aware, record_right_history, require_validity_window, validity_state
from .governance_models import PetAssetRight, PetAssetRightEvidence
from .models import AccountPetRelation
from .security import Principal
from .services import append_event

rights_enhanced_router = APIRouter(prefix="/api/v1/admin/governance", tags=["admin-governance"])
RightStatus = Literal["pending", "verified", "revoked"]


class EnhancedRightDeclareRequest(BaseModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    rights_type: str = Field(min_length=1, max_length=64)
    source_declaration: str = Field(min_length=3, max_length=4000)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @field_validator("artifact_id", "rights_type", "source_declaration")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _validate_window(self) -> "EnhancedRightDeclareRequest":
        try:
            self.valid_from, self.valid_until = require_validity_window(
                self.valid_from, self.valid_until
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class EnhancedRightVerifyRequest(BaseModel):
    comment: str = Field(min_length=3, max_length=1000)

    @field_validator("comment")
    @classmethod
    def _strip_comment(cls, value: str) -> str:
        return value.strip()


class EnhancedRightRevokeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return value.strip()


class EnhancedAssetRightView(BaseModel):
    right_id: str
    artifact_id: str
    rights_type: str
    source_declaration: str
    status: RightStatus
    validity_state: Literal["scheduled", "active", "expired"]
    valid_from: datetime | None
    valid_until: datetime | None
    review_comment: str
    declared_by_account_id: str
    verified_by_account_id: str | None
    verified_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None
    evidence_count: int
    created_at: datetime
    updated_at: datetime


class EnhancedRightRevocationView(BaseModel):
    right: EnhancedAssetRightView
    affected_release_ids: list[str]
    notified_account_ids: list[str]


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


def _evidence_count(session: Session, right_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(PetAssetRightEvidence.id)).where(
                PetAssetRightEvidence.right_id == right_id
            )
        )
        or 0
    )


def _view(session: Session, right: PetAssetRight) -> EnhancedAssetRightView:
    current_status = right.status if right.status in {"pending", "verified", "revoked"} else "pending"
    return EnhancedAssetRightView(
        right_id=right.id,
        artifact_id=right.artifact_id,
        rights_type=right.rights_type,
        source_declaration=right.source_declaration,
        status=current_status,  # type: ignore[arg-type]
        validity_state=validity_state(right),  # type: ignore[arg-type]
        valid_from=aware(right.valid_from),
        valid_until=aware(right.valid_until),
        review_comment=right.review_comment,
        declared_by_account_id=right.declared_by_account_id,
        verified_by_account_id=right.verified_by_account_id,
        verified_at=aware(right.verified_at),
        revoked_at=aware(right.revoked_at),
        revoked_reason=right.revoked_reason,
        evidence_count=_evidence_count(session, right.id),
        created_at=aware(right.created_at),  # type: ignore[arg-type]
        updated_at=aware(right.updated_at),  # type: ignore[arg-type]
    )


@rights_enhanced_router.get("/rights", response_model=list[EnhancedAssetRightView])
def list_asset_rights_enhanced(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    artifact_id: str | None = Query(default=None, max_length=36),
    status_filter: RightStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[EnhancedAssetRightView]:
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
    return [_view(session, row) for row in rows]


@rights_enhanced_router.post(
    "/rights",
    response_model=EnhancedAssetRightView,
    status_code=status.HTTP_201_CREATED,
)
def declare_asset_right_enhanced(
    body: EnhancedRightDeclareRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> EnhancedAssetRightView:
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
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        review_comment="",
        verified_at=None,
        revoked_at=None,
    )
    session.add(right)
    session.flush()
    record_right_history(
        session,
        right=right,
        principal=principal,
        event_type="declared",
        comment=body.source_declaration,
        details={
            "artifact_id": right.artifact_id,
            "rights_type": right.rights_type,
            "valid_from": aware(right.valid_from).isoformat() if right.valid_from else None,
            "valid_until": aware(right.valid_until).isoformat() if right.valid_until else None,
        },
    )
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.declared",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={"artifact_id": right.artifact_id, "rights_type": right.rights_type},
    )
    session.commit()
    return _view(session, right)


@rights_enhanced_router.post(
    "/rights/{right_id}/verify",
    response_model=EnhancedAssetRightView,
)
def verify_asset_right_enhanced(
    right_id: str,
    body: EnhancedRightVerifyRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> EnhancedAssetRightView:
    right = _right_or_404(session, right_id)
    if right.status != "pending":
        raise HTTPException(status_code=409, detail="只有待复核版权存证可以核验")
    if right.declared_by_account_id == principal.account_id:
        raise HTTPException(status_code=409, detail="版权声明人不能复核自己的存证")
    if _evidence_count(session, right.id) < 1:
        raise HTTPException(status_code=409, detail="版权存证至少需要一个证据附件才能复核")
    if validity_state(right) == "expired":
        raise HTTPException(status_code=409, detail="授权有效期已经结束，不能核验为有效")

    now = datetime.now(UTC)
    right.status = "verified"
    right.verified_by_account_id = principal.account_id
    right.review_comment = body.comment
    right.verified_at = now
    right.revoked_at = None
    right.revoked_reason = None
    right.updated_at = now
    record_right_history(
        session,
        right=right,
        principal=principal,
        event_type="verified",
        comment=body.comment,
        details={"artifact_id": right.artifact_id},
    )
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.verified",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={"artifact_id": right.artifact_id, "comment": body.comment},
    )
    session.commit()
    return _view(session, right)


@rights_enhanced_router.post(
    "/rights/{right_id}/revoke",
    response_model=EnhancedRightRevocationView,
)
def revoke_asset_right_enhanced(
    right_id: str,
    body: EnhancedRightRevokeRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> EnhancedRightRevocationView:
    right = _right_or_404(session, right_id)
    if right.status == "revoked":
        raise HTTPException(status_code=409, detail="版权存证已经撤销")

    now = datetime.now(UTC)
    right.status = "revoked"
    right.revoked_reason = body.reason
    right.revoked_at = now
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
                    "reason": body.reason,
                    "action": "evict_cache_and_fallback",
                },
            )
            notified.add(account_id)
    affected_release_ids = [release.id for release in releases]
    notified_account_ids = sorted(notified)
    record_right_history(
        session,
        right=right,
        principal=principal,
        event_type="revoked",
        comment=body.reason,
        details={
            "affected_release_ids": affected_release_ids,
            "notified_account_ids": notified_account_ids,
        },
    )
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.revoked",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={
            "artifact_id": right.artifact_id,
            "reason": body.reason,
            "affected_release_ids": affected_release_ids,
            "notified_account_ids": notified_account_ids,
        },
    )
    session.commit()
    return EnhancedRightRevocationView(
        right=_view(session, right),
        affected_release_ids=affected_release_ids,
        notified_account_ids=notified_account_ids,
    )
