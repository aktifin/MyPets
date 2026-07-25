"""Independent review and per-pet deployment for validated personal asset packages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import require_admin
from .api import get_session, require_account
from .asset_deployment_models import (
    PetAssetDeploymentReview,
    PetPersonalAssetDeployment,
    PetPersonalAssetRelease,
)
from .asset_production_models import PetAssetProductionArtifact, PetAssetProductionJob
from .models import AccountPetRelation, AdminAuditLog, Pet, PetTemplate, PetTemplateVersion
from .object_store import FileObjectStore
from .security import Principal
from .services import append_event, pet_view

asset_deployment_router = APIRouter(prefix="/api/v1", tags=["pet-personal-assets"])
admin_asset_deployment_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin-pet-personal-assets"]
)

ReviewStatus = Literal["pending", "approved", "rejected", "published"]


class DeploymentReviewDecision(BaseModel):
    comment: str = Field(min_length=3, max_length=1000)
    rights_verified: bool = False
    visual_identity_verified: bool = False

    @field_validator("comment")
    @classmethod
    def _strip_comment(cls, value: str) -> str:
        return value.strip()


class DeploymentPublishRequest(BaseModel):
    reason: str = Field(default="专属素材审核通过并部署。", min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return value.strip()


class DeploymentRollbackRequest(BaseModel):
    reason: str = Field(default="回退到上一专属素材版本。", min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        return value.strip()


class PersonalAssetReleaseView(BaseModel):
    release_id: str
    review_id: str
    artifact_id: str
    pet_id: str
    template_version_id: str
    template_code: str
    template_version: str
    identity_version: str
    asset_version: str
    package_sha256: str
    package_size: int
    manifest: dict[str, Any]
    download_url: str
    published_by_account_id: str
    published_at: datetime


class DeploymentReviewView(BaseModel):
    review_id: str
    artifact_id: str
    job_id: str
    pet_id: str
    pet_name: str
    status: ReviewStatus
    submitted_by_account_id: str
    reviewed_by_account_id: str | None
    review_comment: str
    rights_verified: bool
    visual_identity_verified: bool
    compatibility: dict[str, Any]
    submitted_at: datetime
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    release: PersonalAssetReleaseView | None


class PersonalAssetDeploymentView(BaseModel):
    pet_id: str
    active_release: PersonalAssetReleaseView
    previous_release: PersonalAssetReleaseView | None
    updated_by_account_id: str
    reason: str
    created_at: datetime
    updated_at: datetime


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _store(request: Request) -> FileObjectStore:
    return request.app.state.asset_object_store


def _review_or_404(session: Session, review_id: str) -> PetAssetDeploymentReview:
    review = session.get(PetAssetDeploymentReview, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="专属素材部署审核不存在")
    return review


def _artifact_for_review(
    session: Session, review: PetAssetDeploymentReview
) -> PetAssetProductionArtifact:
    artifact = session.get(PetAssetProductionArtifact, review.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=409, detail="审核引用的制作产物不存在")
    return artifact


def _release_view(session: Session, release: PetPersonalAssetRelease) -> PersonalAssetReleaseView:
    version = session.get(PetTemplateVersion, release.template_version_id)
    template = session.get(PetTemplate, version.template_id) if version is not None else None
    if version is None or template is None:
        raise RuntimeError("专属 Release 引用的模板版本不存在")
    return PersonalAssetReleaseView(
        release_id=release.id,
        review_id=release.review_id,
        artifact_id=release.artifact_id,
        pet_id=release.pet_id,
        template_version_id=version.id,
        template_code=template.template_code,
        template_version=version.template_version,
        identity_version=version.identity_version,
        asset_version=version.asset_version,
        package_sha256=release.package_sha256,
        package_size=release.package_size,
        manifest=_json(release.manifest_json),
        download_url=f"/api/v1/personal-asset-releases/{release.id}/package",
        published_by_account_id=release.published_by_account_id,
        published_at=_aware(release.created_at),
    )


def _review_view(session: Session, review: PetAssetDeploymentReview) -> DeploymentReviewView:
    pet = session.get(Pet, review.pet_id)
    if pet is None:
        raise RuntimeError("专属素材审核引用的宠物不存在")
    release = session.scalar(
        select(PetPersonalAssetRelease).where(PetPersonalAssetRelease.review_id == review.id)
    )
    return DeploymentReviewView(
        review_id=review.id,
        artifact_id=review.artifact_id,
        job_id=review.job_id,
        pet_id=review.pet_id,
        pet_name=pet.name,
        status=review.status,  # type: ignore[arg-type]
        submitted_by_account_id=review.submitted_by_account_id,
        reviewed_by_account_id=review.reviewed_by_account_id,
        review_comment=review.review_comment,
        rights_verified=review.rights_verified,
        visual_identity_verified=review.visual_identity_verified,
        compatibility=_json(review.compatibility_json),
        submitted_at=_aware(review.submitted_at),
        reviewed_at=_aware(review.reviewed_at),
        created_at=_aware(review.created_at),
        updated_at=_aware(review.updated_at),
        release=_release_view(session, release) if release else None,
    )


def _deployment_view(
    session: Session, deployment: PetPersonalAssetDeployment
) -> PersonalAssetDeploymentView:
    active = session.get(PetPersonalAssetRelease, deployment.active_release_id)
    previous = (
        session.get(PetPersonalAssetRelease, deployment.previous_release_id)
        if deployment.previous_release_id
        else None
    )
    if active is None:
        raise RuntimeError("单宠部署引用的当前 Release 不存在")
    return PersonalAssetDeploymentView(
        pet_id=deployment.pet_id,
        active_release=_release_view(session, active),
        previous_release=_release_view(session, previous) if previous else None,
        updated_by_account_id=deployment.updated_by_account_id,
        reason=deployment.reason,
        created_at=_aware(deployment.created_at),
        updated_at=_aware(deployment.updated_at),
    )


def _audit(
    session: Session,
    *,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AdminAuditLog(
            id=str(uuid4()),
            admin_account_id=principal.account_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details_json=json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
        )
    )


def _compatibility_report(
    session: Session,
    *,
    review: PetAssetDeploymentReview,
    artifact: PetAssetProductionArtifact,
) -> dict[str, Any]:
    job = session.get(PetAssetProductionJob, review.job_id)
    pet = session.get(Pet, review.pet_id)
    version = session.get(PetTemplateVersion, artifact.template_version_id)
    template = session.get(PetTemplate, version.template_id) if version is not None else None
    manifest = _json(artifact.manifest_json)
    checks = {
        "job_ready": job is not None and job.status == "ready",
        "artifact_matches_job": job is not None and artifact.job_id == job.id,
        "artifact_matches_pet": artifact.pet_id == review.pet_id,
        "target_version_matches_job": (
            job is not None and job.target_template_version_id == artifact.template_version_id
        ),
        "template_matches_pet": (
            pet is not None and template is not None and template.template_code == pet.template_id
        ),
        "schema_version_supported": manifest.get("schema_version") in {"2.0", "2.1"},
        "manifest_template_matches": (
            template is not None and manifest.get("template_id") == template.template_code
        ),
        "manifest_identity_matches": (
            version is not None and manifest.get("identity_version") == version.identity_version
        ),
        "manifest_asset_matches": (
            version is not None and manifest.get("asset_version") == version.asset_version
        ),
    }
    return {"compatible": all(checks.values()), "checks": checks}


def _publish_review_event(
    session: Session,
    *,
    review: PetAssetDeploymentReview,
    cause: str,
) -> None:
    job = session.get(PetAssetProductionJob, review.job_id)
    if job is None:
        return
    append_event(
        session,
        account_id=job.account_id,
        event_type="pet_asset_deployment_review_updated",
        idempotency_key=f"pet-asset-deployment-review:{review.id}:{cause}:{review.updated_at.isoformat()}",
        payload={
            "cause": cause,
            "review_id": review.id,
            "job_id": review.job_id,
            "pet_id": review.pet_id,
            "status": review.status,
        },
    )


def _publish_deployment_events(
    session: Session,
    *,
    pet: Pet,
    release: PetPersonalAssetRelease,
    cause: str,
) -> None:
    relation_accounts = list(
        session.scalars(
            select(AccountPetRelation.account_id).where(AccountPetRelation.pet_id == pet.id)
        )
    )
    payload = {
        "cause": cause,
        "pet_id": pet.id,
        "release_id": release.id,
        "pet": pet_view(pet).model_dump(mode="json"),
    }
    for account_id in relation_accounts:
        append_event(
            session,
            account_id=account_id,
            event_type="pet_asset_version_changed",
            idempotency_key=f"pet-personal-asset:{pet.id}:{release.id}:{cause}",
            payload=payload,
        )


def _apply_release_to_pet(
    session: Session,
    *,
    pet: Pet,
    release: PetPersonalAssetRelease,
) -> None:
    version = session.get(PetTemplateVersion, release.template_version_id)
    template = session.get(PetTemplate, version.template_id) if version is not None else None
    if version is None or template is None or template.template_code != pet.template_id:
        raise HTTPException(status_code=409, detail="专属 Release 与宠物当前模板不兼容")
    pet.template_version = version.template_version
    pet.identity_version = version.identity_version
    pet.asset_version = version.asset_version
    pet.state_version += 1
    pet.updated_at = datetime.now(UTC)


@admin_asset_deployment_router.get(
    "/pet-asset-deployment-reviews", response_model=list[DeploymentReviewView]
)
def list_deployment_reviews(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: ReviewStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[DeploymentReviewView]:
    statement = select(PetAssetDeploymentReview)
    if status_filter:
        statement = statement.where(PetAssetDeploymentReview.status == status_filter)
    rows = session.scalars(
        statement.order_by(PetAssetDeploymentReview.updated_at.desc()).limit(limit)
    )
    return [_review_view(session, row) for row in rows]


@admin_asset_deployment_router.get(
    "/pet-asset-deployment-reviews/{review_id}", response_model=DeploymentReviewView
)
def get_deployment_review(
    review_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> DeploymentReviewView:
    return _review_view(session, _review_or_404(session, review_id))


@admin_asset_deployment_router.post(
    "/pet-asset-production-jobs/{job_id}/submit-deployment-review",
    response_model=DeploymentReviewView,
    status_code=status.HTTP_201_CREATED,
)
def submit_deployment_review(
    job_id: str,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> DeploymentReviewView:
    job = session.get(PetAssetProductionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="宠物素材制作工单不存在")
    if job.status != "ready":
        raise HTTPException(status_code=409, detail="只有产物校验完成的工单可以提交部署审核")
    artifact = session.scalar(
        select(PetAssetProductionArtifact).where(PetAssetProductionArtifact.job_id == job.id)
    )
    if artifact is None:
        raise HTTPException(status_code=409, detail="工单尚无可审核的制作产物")
    existing = session.scalar(
        select(PetAssetDeploymentReview).where(
            PetAssetDeploymentReview.artifact_id == artifact.id
        )
    )
    if existing is not None:
        return _review_view(session, existing)
    review = PetAssetDeploymentReview(
        id=str(uuid4()),
        artifact_id=artifact.id,
        job_id=job.id,
        pet_id=job.pet_id,
        status="pending",
        submitted_by_account_id=principal.account_id,
    )
    session.add(review)
    session.flush()
    _publish_review_event(session, review=review, cause="submitted")
    _audit(
        session,
        principal=principal,
        action="pet_asset_deployment_review.submitted",
        resource_type="pet_asset_deployment_review",
        resource_id=review.id,
        details={"artifact_id": artifact.id, "job_id": job.id, "pet_id": job.pet_id},
    )
    session.commit()
    return _review_view(session, review)


@admin_asset_deployment_router.post(
    "/pet-asset-deployment-reviews/{review_id}/approve",
    response_model=DeploymentReviewView,
)
def approve_deployment_review(
    review_id: str,
    body: DeploymentReviewDecision,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> DeploymentReviewView:
    review = _review_or_404(session, review_id)
    if review.status != "pending":
        raise HTTPException(status_code=409, detail="只有待审核产物可以批准")
    artifact = _artifact_for_review(session, review)
    if artifact.uploaded_by_account_id == principal.account_id:
        raise HTTPException(status_code=409, detail="制作产物上传者不能审核自己的产物")
    if not body.rights_verified or not body.visual_identity_verified:
        raise HTTPException(status_code=422, detail="权利状态和视觉身份必须全部核验通过")
    report = _compatibility_report(session, review=review, artifact=artifact)
    if not report["compatible"]:
        raise HTTPException(status_code=409, detail={"message": "专属素材兼容性检查未通过", **report})
    now = datetime.now(UTC)
    review.status = "approved"
    review.reviewed_by_account_id = principal.account_id
    review.review_comment = body.comment
    review.rights_verified = True
    review.visual_identity_verified = True
    review.compatibility_json = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    review.reviewed_at = now
    review.updated_at = now
    _publish_review_event(session, review=review, cause="approved")
    _audit(
        session,
        principal=principal,
        action="pet_asset_deployment_review.approved",
        resource_type="pet_asset_deployment_review",
        resource_id=review.id,
        details={"comment": body.comment, **report},
    )
    session.commit()
    return _review_view(session, review)


@admin_asset_deployment_router.post(
    "/pet-asset-deployment-reviews/{review_id}/reject",
    response_model=DeploymentReviewView,
)
def reject_deployment_review(
    review_id: str,
    body: DeploymentReviewDecision,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> DeploymentReviewView:
    review = _review_or_404(session, review_id)
    if review.status != "pending":
        raise HTTPException(status_code=409, detail="只有待审核产物可以退回")
    artifact = _artifact_for_review(session, review)
    if artifact.uploaded_by_account_id == principal.account_id:
        raise HTTPException(status_code=409, detail="制作产物上传者不能审核自己的产物")
    now = datetime.now(UTC)
    review.status = "rejected"
    review.reviewed_by_account_id = principal.account_id
    review.review_comment = body.comment
    review.rights_verified = body.rights_verified
    review.visual_identity_verified = body.visual_identity_verified
    review.compatibility_json = json.dumps(
        _compatibility_report(session, review=review, artifact=artifact),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    review.reviewed_at = now
    review.updated_at = now
    _publish_review_event(session, review=review, cause="rejected")
    _audit(
        session,
        principal=principal,
        action="pet_asset_deployment_review.rejected",
        resource_type="pet_asset_deployment_review",
        resource_id=review.id,
        details={"comment": body.comment},
    )
    session.commit()
    return _review_view(session, review)


@admin_asset_deployment_router.post(
    "/pet-asset-deployment-reviews/{review_id}/publish",
    response_model=PersonalAssetDeploymentView,
    status_code=status.HTTP_201_CREATED,
)
def publish_personal_asset_release(
    review_id: str,
    body: DeploymentPublishRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PersonalAssetDeploymentView:
    review = _review_or_404(session, review_id)
    if review.status not in {"approved", "published"}:
        raise HTTPException(status_code=409, detail="只有已批准的专属素材可以发布")
    if not review.rights_verified or not review.visual_identity_verified:
        raise HTTPException(status_code=409, detail="权利状态或视觉身份尚未核验通过")
    artifact = _artifact_for_review(session, review)
    report = _compatibility_report(session, review=review, artifact=artifact)
    if not report["compatible"]:
        raise HTTPException(status_code=409, detail={"message": "发布前兼容性复核未通过", **report})
    pet = session.get(Pet, review.pet_id)
    if pet is None:
        raise HTTPException(status_code=404, detail="目标宠物不存在")

    release = session.scalar(
        select(PetPersonalAssetRelease).where(PetPersonalAssetRelease.review_id == review.id)
    )
    object_key: str | None = None
    if release is None:
        release_id = str(uuid4())
        object_key = f"personal-releases/{pet.id}/{release_id}/{artifact.package_sha256}.zip"
        try:
            _store(request).promote(artifact.object_key, object_key)
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        release = PetPersonalAssetRelease(
            id=release_id,
            review_id=review.id,
            artifact_id=artifact.id,
            pet_id=pet.id,
            template_version_id=artifact.template_version_id,
            object_key=object_key,
            package_sha256=artifact.package_sha256,
            package_size=artifact.package_size,
            manifest_json=artifact.manifest_json,
            published_by_account_id=principal.account_id,
        )
        session.add(release)
        session.flush()

    deployment = session.get(PetPersonalAssetDeployment, pet.id)
    if deployment is None:
        deployment = PetPersonalAssetDeployment(
            pet_id=pet.id,
            active_release_id=release.id,
            previous_release_id=None,
            updated_by_account_id=principal.account_id,
            reason=body.reason,
        )
        session.add(deployment)
    elif deployment.active_release_id != release.id:
        deployment.previous_release_id = deployment.active_release_id
        deployment.active_release_id = release.id
        deployment.updated_by_account_id = principal.account_id
        deployment.reason = body.reason
        deployment.updated_at = datetime.now(UTC)

    _apply_release_to_pet(session, pet=pet, release=release)
    review.status = "published"
    review.updated_at = datetime.now(UTC)
    _publish_review_event(session, review=review, cause="published")
    _publish_deployment_events(session, pet=pet, release=release, cause="personal_asset_published")
    _audit(
        session,
        principal=principal,
        action="pet_personal_asset_release.published",
        resource_type="pet_personal_asset_release",
        resource_id=release.id,
        details={
            "review_id": review.id,
            "artifact_id": artifact.id,
            "pet_id": pet.id,
            "previous_release_id": deployment.previous_release_id,
            "reason": body.reason,
        },
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        if object_key is not None:
            _store(request).delete(object_key)
        raise
    return _deployment_view(session, deployment)


@admin_asset_deployment_router.post(
    "/pet-personal-asset-deployments/{pet_id}/rollback",
    response_model=PersonalAssetDeploymentView,
)
def rollback_personal_asset_deployment(
    pet_id: str,
    body: DeploymentRollbackRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PersonalAssetDeploymentView:
    deployment = session.get(PetPersonalAssetDeployment, pet_id)
    pet = session.get(Pet, pet_id)
    if deployment is None or pet is None:
        raise HTTPException(status_code=404, detail="宠物专属素材部署不存在")
    if deployment.previous_release_id is None:
        raise HTTPException(status_code=409, detail="当前部署没有可回退的上一版本")
    previous = session.get(PetPersonalAssetRelease, deployment.previous_release_id)
    if previous is None or previous.pet_id != pet.id:
        raise HTTPException(status_code=409, detail="上一专属 Release 不存在或不属于该宠物")
    current_release_id = deployment.active_release_id
    deployment.active_release_id = previous.id
    deployment.previous_release_id = current_release_id
    deployment.updated_by_account_id = principal.account_id
    deployment.reason = body.reason
    deployment.updated_at = datetime.now(UTC)
    _apply_release_to_pet(session, pet=pet, release=previous)
    _publish_deployment_events(session, pet=pet, release=previous, cause="personal_asset_rolled_back")
    _audit(
        session,
        principal=principal,
        action="pet_personal_asset_deployment.rolled_back",
        resource_type="pet_personal_asset_deployment",
        resource_id=pet.id,
        details={
            "from_release_id": current_release_id,
            "to_release_id": previous.id,
            "reason": body.reason,
        },
    )
    session.commit()
    return _deployment_view(session, deployment)


@asset_deployment_router.get(
    "/pets/{pet_id}/personal-asset-deployment",
    response_model=PersonalAssetDeploymentView,
)
def get_my_personal_asset_deployment(
    pet_id: str,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> PersonalAssetDeploymentView:
    relation = session.get(AccountPetRelation, (principal.account_id, pet_id))
    if relation is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    deployment = session.get(PetPersonalAssetDeployment, pet_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="宠物尚未部署专属素材")
    return _deployment_view(session, deployment)


@asset_deployment_router.get("/personal-asset-releases/{release_id}/package")
def download_personal_asset_release(
    release_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    release = session.get(PetPersonalAssetRelease, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="专属素材 Release 不存在")
    relation = session.get(AccountPetRelation, (principal.account_id, release.pet_id))
    if relation is None:
        raise HTTPException(status_code=404, detail="专属素材 Release 不存在")
    try:
        path = _store(request).path(release.object_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="专属素材包文件不存在") from exc
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"pet-{release.pet_id}-personal-{release.id}.zip",
        headers={
            "ETag": f'"{release.package_sha256}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
