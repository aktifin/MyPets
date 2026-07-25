"""Governance-enforced wrappers for personal asset approval, publishing, and download.

These routes are registered before the compatibility deployment routes. They reuse the
existing D3 state machine while adding two missing invariants:
- the latest rights record for an artifact must be independently verified before approval
  or publishing;
- a revoked or newly pending rights record stops subsequent package distribution.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import require_admin
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
        .order_by(PetAssetRight.updated_at.desc(), PetAssetRight.created_at.desc(), PetAssetRight.id.desc())
        .limit(1)
    )


def _require_verified_right(session: Session, artifact_id: str) -> PetAssetRight:
    right = _latest_right(session, artifact_id)
    if right is None:
        raise HTTPException(status_code=409, detail="制作产物尚未登记版权存证")
    if right.status != "verified":
        detail = "版权存证已撤销，禁止审核、发布或继续分发"
        if right.status == "pending":
            detail = "版权存证尚未完成独立复核"
        raise HTTPException(status_code=409, detail=detail)
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
    _require_verified_right(session, review.artifact_id)
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
    _require_verified_right(session, review.artifact_id)

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
        # A repeated publish request is an idempotent read of the current deployment.
        # It must not increment pet.state_version or emit duplicate events/audit rows.
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
    # Run the original authorization and object-existence checks first so an unrelated
    # account cannot use governance status to discover private release identifiers.
    response = download_personal_asset_release(
        release_id=release_id,
        request=request,
        principal=principal,
        session=session,
    )
    release = session.get(PetPersonalAssetRelease, release_id)
    assert release is not None
    right = _latest_right(session, release.artifact_id)
    if right is not None and right.status != "verified":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="该专属素材的权利状态已失效，服务端已停止分发",
        )
    return response
