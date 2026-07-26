"""Governance-enforced wrappers for personal asset approval, publishing, and download.

The latest rights record must be independently verified and inside its validity window.
Revoked, pending, scheduled, or expired authorization stops approval, publishing, and
subsequent private package distribution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import _audit, require_admin
from .api import get_session, require_account
from .asset_deployment_api import (
    DeploymentPublishRequest,
    DeploymentReviewDecision,
    DeploymentReviewView,
    PersonalAssetDeploymentView,
    _deployment_view,
    approve_deployment_review,
    download_personal_asset_release,
    publish_personal_asset_release,
)
from .asset_deployment_models import (
    PetAssetDeploymentReview,
    PetPersonalAssetDeployment,
    PetPersonalAssetRelease,
)
from .asset_production_models import PetAssetProductionArtifact
from .asset_submission_models import UserPetAssetSubmission
from .governance_history import validity_state
from .governance_models import PetAssetRight
from .security import Principal

admin_governed_asset_deployment_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-pet-personal-assets"],
)
governed_asset_deployment_router = APIRouter(
    prefix="/api/v1",
    tags=["pet-personal-assets"],
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


def _materialize_legacy_verified_right(
    session: Session,
    *,
    artifact_id: str,
    principal: Principal,
) -> PetAssetRight | None:
    """Convert pre-ledger approved submission evidence into an explicit ledger row."""

    artifact = session.get(PetAssetProductionArtifact, artifact_id)
    if artifact is None:
        return None
    submission = session.get(UserPetAssetSubmission, artifact.submission_id)
    if (
        submission is None
        or submission.status != "approved"
        or submission.rights_confirmed_at is None
        or submission.reviewed_by_account_id is None
        or submission.reviewed_by_account_id == submission.account_id
    ):
        return None

    now = datetime.now(UTC)
    right = PetAssetRight(
        id=str(uuid4()),
        artifact_id=artifact.id,
        rights_type=submission.rights_basis,
        source_declaration=(
            "由历史已审核宠物原图投稿自动迁移；"
            f"submission_id={submission.id}；review_comment={submission.review_comment}"
        ),
        status="verified",
        declared_by_account_id=submission.account_id,
        verified_by_account_id=submission.reviewed_by_account_id,
        review_comment=submission.review_comment,
        verified_at=now,
    )
    session.add(right)
    session.flush()
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.migrated_from_submission",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={
            "artifact_id": artifact.id,
            "submission_id": submission.id,
            "declared_by_account_id": submission.account_id,
            "verified_by_account_id": submission.reviewed_by_account_id,
        },
    )
    return right


def _require_verified_right(
    session: Session,
    artifact_id: str,
    *,
    principal: Principal,
) -> PetAssetRight:
    right = _latest_right(session, artifact_id)
    if right is None:
        right = _materialize_legacy_verified_right(
            session,
            artifact_id=artifact_id,
            principal=principal,
        )
    if right is None:
        raise HTTPException(status_code=409, detail="制作产物尚未登记版权存证")
    if right.status != "verified":
        detail = "版权存证已撤销，禁止审核、发布或继续分发"
        if right.status == "pending":
            detail = "版权存证尚未完成独立复核"
        raise HTTPException(status_code=409, detail=detail)
    current_validity = validity_state(right)
    if current_validity == "scheduled":
        raise HTTPException(status_code=409, detail="版权授权尚未到生效时间")
    if current_validity == "expired":
        raise HTTPException(status_code=409, detail="版权授权有效期已经结束")
    return right


@admin_governed_asset_deployment_router.post(
    "/pet-asset-deployment-reviews/{review_id}/approve",
    response_model=DeploymentReviewView,
)
def approve_governed_deployment_review(
    review_id: str,
    body: DeploymentReviewDecision,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> DeploymentReviewView:
    review = session.get(PetAssetDeploymentReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="专属素材部署审核不存在")
    if not body.rights_verified or not body.visual_identity_verified:
        raise HTTPException(status_code=422, detail="权利状态和视觉身份必须全部核验通过")
    _require_verified_right(
        session,
        review.artifact_id,
        principal=principal,
    )
    return approve_deployment_review(
        review_id=review_id,
        body=body,
        principal=principal,
        session=session,
    )


@admin_governed_asset_deployment_router.post(
    "/pet-asset-deployment-reviews/{review_id}/publish",
    response_model=PersonalAssetDeploymentView,
    status_code=status.HTTP_201_CREATED,
)
def publish_governed_personal_asset_release(
    review_id: str,
    body: DeploymentPublishRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PersonalAssetDeploymentView:
    review = session.get(PetAssetDeploymentReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="专属素材部署审核不存在")
    _require_verified_right(
        session,
        review.artifact_id,
        principal=principal,
    )

    release = session.scalar(
        select(PetPersonalAssetRelease).where(
            PetPersonalAssetRelease.review_id == review.id
        )
    )
    deployment = session.get(PetPersonalAssetDeployment, review.pet_id)
    if (
        review.status == "published"
        and release is not None
        and deployment is not None
        and deployment.active_release_id == release.id
    ):
        return _deployment_view(session, deployment)

    return publish_personal_asset_release(
        review_id=review_id,
        body=body,
        request=request,
        principal=principal,
        session=session,
    )


@governed_asset_deployment_router.get(
    "/personal-asset-releases/{release_id}/package"
)
def download_governed_personal_asset_release(
    release_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    response = download_personal_asset_release(
        release_id=release_id,
        request=request,
        principal=principal,
        session=session,
    )
    release = session.get(PetPersonalAssetRelease, release_id)
    assert release is not None
    right = _latest_right(session, release.artifact_id)
    if right is not None and (
        right.status != "verified" or validity_state(right) != "active"
    ):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="该专属素材的权利状态或授权有效期已失效，服务端已停止分发",
        )
    return response
