"""User and administrator APIs for controlled pet asset production work orders."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import require_admin
from .api import get_session, get_settings, require_account
from .asset_packages import validate_asset_package
from .asset_production_models import (
    PetAssetProductionArtifact,
    PetAssetProductionJob,
    PetAssetProductionJobLog,
    PetAssetProductionReferenceImage,
)
from .asset_production_service import append_job_log, ensure_production_job, publish_job_event
from .asset_submission_images import sanitize_submission_image
from .asset_submission_models import UserPetAssetSubmission
from .config import Settings
from .models import Account, AdminAuditLog, Pet, PetTemplate, PetTemplateVersion, SyncEvent
from .object_store import FileObjectStore
from .security import Principal, normalize_username
from .services import append_event, find_event_by_idempotency

asset_production_router = APIRouter(prefix="/api/v1", tags=["pet-asset-production"])
admin_asset_production_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin-pet-asset-production"]
)

JobStatus = Literal["queued", "processing", "needs_input", "ready", "failed", "cancelled"]
MutableJobStatus = Literal["queued", "processing", "needs_input", "failed", "cancelled"]
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"processing", "needs_input", "failed", "cancelled"},
    "processing": {"processing", "needs_input", "failed", "cancelled"},
    "needs_input": {"processing", "needs_input", "failed", "cancelled"},
    "failed": {"queued", "processing", "failed", "cancelled"},
    "ready": set(),
    "cancelled": set(),
}


class ProductionArtifactView(BaseModel):
    artifact_id: str
    target_template_version_id: str
    template_code: str
    template_version: str
    identity_version: str
    asset_version: str
    package_sha256: str
    package_size: int
    manifest: dict[str, Any]
    package_url: str | None
    uploaded_by_account_id: str
    created_at: datetime


class ProductionReferenceImageView(BaseModel):
    reference_id: str
    original_filename: str
    image_media_type: str
    image_sha256: str
    image_size: int
    image_width: int
    image_height: int
    note: str
    image_url: str
    created_at: datetime


class ProductionJobLogView(BaseModel):
    log_id: str
    action: str
    actor_account_id: str | None
    from_status: str | None
    to_status: str
    progress: int
    message: str
    details: dict[str, Any]
    created_at: datetime


class ProductionJobView(BaseModel):
    job_id: str
    submission_id: str
    account_id: str
    account_username: str
    account_display_name: str
    pet_id: str
    pet_name: str
    status: JobStatus
    progress: int
    status_note: str
    assignee_account_id: str | None
    assignee_username: str | None
    assignee_display_name: str | None
    target_template_version_id: str | None
    can_cancel: bool
    can_add_reference: bool
    artifact: ProductionArtifactView | None
    references: list[ProductionReferenceImageView]
    logs: list[ProductionJobLogView]
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssignJobRequest(BaseModel):
    assignee_username: str = Field(min_length=3, max_length=64)
    note: str = Field(default="", max_length=1000)

    @field_validator("assignee_username", "note")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class UpdateJobRequest(BaseModel):
    status: MutableJobStatus
    progress: int | None = Field(default=None, ge=0, le=99)
    note: str = Field(default="", max_length=1000)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str) -> str:
        return value.strip()


class CancelJobRequest(BaseModel):
    note: str = Field(default="用户在制作开始前撤回工单。", max_length=1000)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str) -> str:
        return value.strip()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _safe_filename(value: str | None) -> str:
    raw = (value or "reference-image").replace("\\", "/")
    name = PurePath(raw).name.strip()
    return name[:255] or "reference-image"


def _object_store(request: Request) -> FileObjectStore:
    return request.app.state.asset_object_store


def _job_or_404(session: Session, job_id: str) -> PetAssetProductionJob:
    item = session.get(PetAssetProductionJob, job_id)
    if item is None:
        raise HTTPException(status_code=404, detail="宠物素材制作工单不存在")
    return item


def _owned_job(session: Session, account_id: str, job_id: str) -> PetAssetProductionJob:
    item = _job_or_404(session, job_id)
    if item.account_id != account_id:
        raise HTTPException(status_code=404, detail="宠物素材制作工单不存在")
    return item


def _json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _event_payload(event: SyncEvent) -> dict[str, Any]:
    return _json(event.payload_json)


def _artifact_view(
    session: Session,
    artifact: PetAssetProductionArtifact,
    *,
    admin: bool,
) -> ProductionArtifactView:
    version = session.get(PetTemplateVersion, artifact.template_version_id)
    template = session.get(PetTemplate, version.template_id) if version is not None else None
    if version is None or template is None:
        raise RuntimeError("制作产物引用的模板版本不存在")
    return ProductionArtifactView(
        artifact_id=artifact.id,
        target_template_version_id=version.id,
        template_code=template.template_code,
        template_version=version.template_version,
        identity_version=version.identity_version,
        asset_version=version.asset_version,
        package_sha256=artifact.package_sha256,
        package_size=artifact.package_size,
        manifest=_json(artifact.manifest_json),
        package_url=(
            f"/api/v1/admin/pet-asset-production-jobs/{artifact.job_id}/artifact/package"
            if admin
            else None
        ),
        uploaded_by_account_id=artifact.uploaded_by_account_id,
        created_at=_aware(artifact.created_at),
    )


def _reference_view(
    item: PetAssetProductionReferenceImage,
    *,
    admin: bool,
) -> ProductionReferenceImageView:
    prefix = "/api/v1/admin" if admin else "/api/v1"
    return ProductionReferenceImageView(
        reference_id=item.id,
        original_filename=item.original_filename,
        image_media_type=item.image_media_type,
        image_sha256=item.image_sha256,
        image_size=item.image_size,
        image_width=item.image_width,
        image_height=item.image_height,
        note=item.note,
        image_url=(
            f"{prefix}/pet-asset-production-jobs/{item.job_id}/reference-images/{item.id}/image"
        ),
        created_at=_aware(item.created_at),
    )


def _log_view(item: PetAssetProductionJobLog, *, admin: bool) -> ProductionJobLogView:
    return ProductionJobLogView(
        log_id=item.id,
        action=item.action,
        actor_account_id=item.actor_account_id if admin else None,
        from_status=item.from_status,
        to_status=item.to_status,
        progress=item.progress,
        message=item.message,
        details=_json(item.details_json) if admin else {},
        created_at=_aware(item.created_at),
    )


def _job_view(session: Session, job: PetAssetProductionJob, *, admin: bool) -> ProductionJobView:
    account = session.get(Account, job.account_id)
    pet = session.get(Pet, job.pet_id)
    assignee = session.get(Account, job.assignee_account_id) if job.assignee_account_id else None
    if account is None or pet is None:
        raise RuntimeError("制作工单引用的账户或宠物不存在")
    artifact = session.scalar(
        select(PetAssetProductionArtifact).where(PetAssetProductionArtifact.job_id == job.id)
    )
    references = list(
        session.scalars(
            select(PetAssetProductionReferenceImage)
            .where(PetAssetProductionReferenceImage.job_id == job.id)
            .order_by(PetAssetProductionReferenceImage.created_at, PetAssetProductionReferenceImage.id)
        )
    )
    logs = list(
        session.scalars(
            select(PetAssetProductionJobLog)
            .where(PetAssetProductionJobLog.job_id == job.id)
            .order_by(PetAssetProductionJobLog.created_at, PetAssetProductionJobLog.id)
        )
    )
    return ProductionJobView(
        job_id=job.id,
        submission_id=job.submission_id,
        account_id=job.account_id,
        account_username=account.username,
        account_display_name=account.display_name,
        pet_id=job.pet_id,
        pet_name=pet.name,
        status=job.status,  # type: ignore[arg-type]
        progress=job.progress,
        status_note=job.status_note,
        assignee_account_id=job.assignee_account_id,
        assignee_username=assignee.username if assignee else None,
        assignee_display_name=assignee.display_name if assignee else None,
        target_template_version_id=job.target_template_version_id,
        can_cancel=job.status == "queued",
        can_add_reference=job.status in {"queued", "processing", "needs_input"},
        artifact=_artifact_view(session, artifact, admin=admin) if artifact else None,
        references=[_reference_view(item, admin=admin) for item in references],
        logs=[_log_view(item, admin=admin) for item in logs],
        started_at=_aware(job.started_at),
        completed_at=_aware(job.completed_at),
        cancelled_at=_aware(job.cancelled_at),
        created_at=_aware(job.created_at),
        updated_at=_aware(job.updated_at),
    )


def _audit(
    session: Session,
    *,
    principal: Principal,
    action: str,
    job: PetAssetProductionJob,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AdminAuditLog(
            id=str(uuid4()),
            admin_account_id=principal.account_id,
            action=action,
            resource_type="pet_asset_production_job",
            resource_id=job.id,
            details_json=json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
        )
    )


def _materialize_approved_jobs(
    session: Session,
    *,
    account_id: str | None = None,
) -> int:
    statement = select(UserPetAssetSubmission).where(UserPetAssetSubmission.status == "approved")
    if account_id:
        statement = statement.where(UserPetAssetSubmission.account_id == account_id)
    created = 0
    for submission in session.scalars(statement):
        existing = session.scalar(
            select(PetAssetProductionJob.id).where(
                PetAssetProductionJob.submission_id == submission.id
            )
        )
        if existing is None:
            ensure_production_job(
                session,
                submission,
                actor_account_id=submission.reviewed_by_account_id,
            )
            created += 1
    return created


def _download_image(
    request: Request,
    item: PetAssetProductionReferenceImage,
) -> FileResponse:
    try:
        path = _object_store(request).path(item.image_object_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="补充参考图对象不存在") from exc
    extension = "png" if item.image_media_type == "image/png" else "jpg"
    return FileResponse(
        path,
        media_type=item.image_media_type,
        filename=f"pet-production-reference-{item.id}.{extension}",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@asset_production_router.get(
    "/pet-asset-production-jobs", response_model=list[ProductionJobView]
)
def list_my_production_jobs(
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ProductionJobView]:
    if _materialize_approved_jobs(session, account_id=principal.account_id):
        session.commit()
    statement = select(PetAssetProductionJob).where(
        PetAssetProductionJob.account_id == principal.account_id
    )
    if status_filter:
        statement = statement.where(PetAssetProductionJob.status == status_filter)
    rows = list(
        session.scalars(
            statement.order_by(PetAssetProductionJob.created_at.desc(), PetAssetProductionJob.id)
            .limit(limit)
        )
    )
    return [_job_view(session, item, admin=False) for item in rows]


@asset_production_router.get(
    "/pet-asset-production-jobs/{job_id}", response_model=ProductionJobView
)
def get_my_production_job(
    job_id: str,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductionJobView:
    return _job_view(session, _owned_job(session, principal.account_id, job_id), admin=False)


@asset_production_router.post(
    "/pet-asset-production-jobs/{job_id}/cancel", response_model=ProductionJobView
)
def cancel_my_production_job(
    job_id: str,
    body: CancelJobRequest,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductionJobView:
    job = _owned_job(session, principal.account_id, job_id)
    if job.status != "queued":
        raise HTTPException(status_code=409, detail="只有尚未开始的制作工单可以撤回")
    now = datetime.now(UTC)
    previous = job.status
    job.status = "cancelled"
    job.status_note = body.note or "用户在制作开始前撤回工单。"
    job.cancelled_at = now
    job.updated_at = now
    append_job_log(
        session,
        job,
        actor_account_id=principal.account_id,
        action="job.cancelled_by_user",
        from_status=previous,
        message=job.status_note,
    )
    publish_job_event(
        session,
        job,
        cause="production_job_cancelled",
        idempotency_key=f"pet-asset-production-job:{job.id}:cancelled:{uuid4()}",
    )
    session.commit()
    return _job_view(session, job, admin=False)


@asset_production_router.post(
    "/pet-asset-production-jobs/{job_id}/reference-images",
    response_model=ProductionReferenceImageView,
    status_code=status.HTTP_201_CREATED,
)
async def add_production_reference_image(
    job_id: str,
    request: Request,
    image: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    note: Annotated[str, Form(max_length=240)] = "",
) -> ProductionReferenceImageView:
    prior = find_event_by_idempotency(session, principal.account_id, idempotency_key)
    if prior is not None:
        payload = _event_payload(prior)
        reference_id = payload.get("reference_id")
        item = session.get(PetAssetProductionReferenceImage, reference_id) if reference_id else None
        if (
            prior.event_type != "pet_asset_production_job_updated"
            or payload.get("cause") != "production_reference_added"
            or item is None
            or item.job_id != job_id
        ):
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        return _reference_view(item, admin=False)

    job = _owned_job(session, principal.account_id, job_id)
    if job.status not in {"queued", "processing", "needs_input"}:
        raise HTTPException(status_code=409, detail="当前工单状态不允许补充参考图")
    raw = await image.read(settings.max_pet_submission_bytes + 1)
    if len(raw) > settings.max_pet_submission_bytes:
        raise HTTPException(status_code=413, detail="补充参考图大小超过限制")
    try:
        sanitized = sanitize_submission_image(
            raw,
            declared_media_type=image.content_type or "",
            max_input_bytes=settings.max_pet_submission_bytes,
            max_pixels=settings.max_pet_submission_pixels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    duplicate = session.scalar(
        select(PetAssetProductionReferenceImage).where(
            PetAssetProductionReferenceImage.job_id == job.id,
            PetAssetProductionReferenceImage.image_sha256 == sanitized.sha256,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="相同补充参考图已经存在")

    reference_id = str(uuid4())
    object_key = (
        f"production/{job.account_id}/{job.id}/references/{reference_id}/"
        f"image.{sanitized.extension}"
    )
    store = _object_store(request)
    try:
        store.write(object_key, sanitized.data)
    except (FileExistsError, OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="补充参考图暂存失败") from exc
    item = PetAssetProductionReferenceImage(
        id=reference_id,
        job_id=job.id,
        account_id=principal.account_id,
        original_filename=_safe_filename(image.filename),
        image_media_type=sanitized.media_type,
        image_object_key=object_key,
        image_sha256=sanitized.sha256,
        image_size=sanitized.size,
        image_width=sanitized.width,
        image_height=sanitized.height,
        note=note.strip(),
    )
    try:
        session.add(item)
        append_job_log(
            session,
            job,
            actor_account_id=principal.account_id,
            action="reference.added",
            from_status=job.status,
            message=item.note or "用户补充了参考图。",
            details={"reference_id": item.id, "sha256": item.image_sha256},
        )
        append_event(
            session,
            account_id=job.account_id,
            event_type="pet_asset_production_job_updated",
            idempotency_key=idempotency_key,
            payload={
                "cause": "production_reference_added",
                "reference_id": item.id,
                "job_id": job.id,
                "pet_id": job.pet_id,
                "status": job.status,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        store.delete(object_key)
        raise
    return _reference_view(item, admin=False)


@asset_production_router.get(
    "/pet-asset-production-jobs/{job_id}/reference-images/{reference_id}/image"
)
def download_my_production_reference_image(
    job_id: str,
    reference_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    _owned_job(session, principal.account_id, job_id)
    item = session.get(PetAssetProductionReferenceImage, reference_id)
    if item is None or item.job_id != job_id:
        raise HTTPException(status_code=404, detail="补充参考图不存在")
    return _download_image(request, item)


@admin_asset_production_router.get(
    "/pet-asset-production-jobs", response_model=list[ProductionJobView]
)
def list_admin_production_jobs(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    assignee_account_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ProductionJobView]:
    if _materialize_approved_jobs(session):
        session.commit()
    statement = select(PetAssetProductionJob)
    if status_filter:
        statement = statement.where(PetAssetProductionJob.status == status_filter)
    if assignee_account_id:
        statement = statement.where(
            PetAssetProductionJob.assignee_account_id == assignee_account_id
        )
    rows = list(
        session.scalars(
            statement.order_by(PetAssetProductionJob.updated_at.desc(), PetAssetProductionJob.id)
            .limit(limit)
        )
    )
    return [_job_view(session, item, admin=True) for item in rows]


@admin_asset_production_router.get(
    "/pet-asset-production-jobs/{job_id}", response_model=ProductionJobView
)
def get_admin_production_job(
    job_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductionJobView:
    return _job_view(session, _job_or_404(session, job_id), admin=True)


@admin_asset_production_router.post(
    "/pet-asset-production-jobs/{job_id}/assign", response_model=ProductionJobView
)
def assign_admin_production_job(
    job_id: str,
    body: AssignJobRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductionJobView:
    job = _job_or_404(session, job_id)
    if job.status in {"ready", "cancelled"}:
        raise HTTPException(status_code=409, detail="终态工单不能重新分配")
    username = normalize_username(body.assignee_username)
    assignee = session.scalar(select(Account).where(Account.username == username))
    if assignee is None:
        raise HTTPException(status_code=404, detail="负责人账户不存在")
    roles = set(settings.roles_for_username(assignee.username))
    if not roles.intersection({"editor", "superadmin"}):
        raise HTTPException(status_code=422, detail="负责人必须具有编辑或超级管理员角色")
    previous_assignee = job.assignee_account_id
    job.assignee_account_id = assignee.id
    job.status_note = body.note or f"已分配给 {assignee.display_name}。"
    job.updated_at = datetime.now(UTC)
    append_job_log(
        session,
        job,
        actor_account_id=principal.account_id,
        action="job.assigned",
        from_status=job.status,
        message=job.status_note,
        details={
            "previous_assignee_account_id": previous_assignee,
            "assignee_account_id": assignee.id,
        },
    )
    publish_job_event(
        session,
        job,
        cause="production_job_assigned",
        idempotency_key=f"pet-asset-production-job:{job.id}:assigned:{uuid4()}",
    )
    _audit(
        session,
        principal=principal,
        action="pet_asset_production_job.assigned",
        job=job,
        details={"assignee_account_id": assignee.id, "note": job.status_note},
    )
    session.commit()
    return _job_view(session, job, admin=True)


@admin_asset_production_router.post(
    "/pet-asset-production-jobs/{job_id}/update", response_model=ProductionJobView
)
def update_admin_production_job(
    job_id: str,
    body: UpdateJobRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductionJobView:
    job = _job_or_404(session, job_id)
    target = body.status
    if target not in _ALLOWED_TRANSITIONS.get(job.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"工单不能从 {job.status} 变更为 {target}",
        )
    if target in {"needs_input", "failed", "cancelled"} and len(body.note) < 3:
        raise HTTPException(status_code=422, detail="该状态必须填写至少 3 个字符的说明")
    previous = job.status
    now = datetime.now(UTC)
    if previous == "failed" and target == "queued":
        progress = 0
    else:
        progress = job.progress if body.progress is None else body.progress
        if progress < job.progress:
            raise HTTPException(status_code=422, detail="制作进度不能倒退")
    job.status = target
    job.progress = progress
    job.status_note = body.note or job.status_note
    job.updated_at = now
    if target == "processing" and job.started_at is None:
        job.started_at = now
    if target == "cancelled":
        job.cancelled_at = now
    if target == "queued":
        job.started_at = None
        job.cancelled_at = None
        job.completed_at = None
    append_job_log(
        session,
        job,
        actor_account_id=principal.account_id,
        action="job.status_updated",
        from_status=previous,
        message=job.status_note,
        details={"requested_progress": body.progress},
    )
    publish_job_event(
        session,
        job,
        cause="production_job_status_updated",
        idempotency_key=f"pet-asset-production-job:{job.id}:{job.status}:{uuid4()}",
    )
    _audit(
        session,
        principal=principal,
        action="pet_asset_production_job.status_updated",
        job=job,
        details={
            "from_status": previous,
            "to_status": job.status,
            "progress": job.progress,
            "note": job.status_note,
        },
    )
    session.commit()
    return _job_view(session, job, admin=True)


@admin_asset_production_router.post(
    "/pet-asset-production-jobs/{job_id}/artifact",
    response_model=ProductionJobView,
)
async def upload_admin_production_artifact(
    job_id: str,
    request: Request,
    target_template_version_id: Annotated[str, Form(min_length=1, max_length=36)],
    package: Annotated[UploadFile, File(description="制作完成的声明式宠物素材 ZIP 包")],
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> ProductionJobView:
    job = _job_or_404(session, job_id)
    if job.status not in {"processing", "needs_input"}:
        raise HTTPException(status_code=409, detail="只有制作中或等待补充资料的工单可以上传产物")
    if job.assignee_account_id is None:
        raise HTTPException(status_code=409, detail="必须先为工单分配负责人")
    principal_account = session.get(Account, principal.account_id)
    principal_roles = set(
        settings.roles_for_username(principal_account.username if principal_account else "")
    )
    if job.assignee_account_id != principal.account_id and "superadmin" not in principal_roles:
        raise HTTPException(status_code=403, detail="只有当前负责人或超级管理员可以上传工单产物")
    existing = session.scalar(
        select(PetAssetProductionArtifact).where(PetAssetProductionArtifact.job_id == job.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="工单已经存在不可变制作产物")

    version = session.get(PetTemplateVersion, target_template_version_id)
    template = session.get(PetTemplate, version.template_id) if version is not None else None
    pet = session.get(Pet, job.pet_id)
    if version is None or template is None:
        raise HTTPException(status_code=404, detail="目标宠物模板版本不存在")
    if pet is None:
        raise HTTPException(status_code=404, detail="目标宠物不存在")
    if template.template_code != pet.template_id:
        raise HTTPException(status_code=409, detail="目标模板与工单宠物当前模板不一致")
    if version.status not in {"draft", "changes_required"}:
        raise HTTPException(status_code=409, detail="目标模板版本必须处于草稿或需修改状态")

    data = await package.read(settings.max_asset_package_bytes + 1)
    try:
        validated = validate_asset_package(
            data,
            expected_template_id=template.template_code,
            expected_identity_version=version.identity_version,
            expected_asset_version=version.asset_version,
            max_package_bytes=settings.max_asset_package_bytes,
            max_uncompressed_bytes=settings.max_asset_uncompressed_bytes,
            max_files=settings.max_asset_files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    artifact_id = str(uuid4())
    object_key = (
        f"production/{job.account_id}/{job.id}/artifacts/{artifact_id}/"
        f"{validated.package_sha256}.zip"
    )
    store = _object_store(request)
    try:
        store.write(object_key, data)
    except (FileExistsError, OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="制作产物暂存失败") from exc

    artifact = PetAssetProductionArtifact(
        id=artifact_id,
        job_id=job.id,
        submission_id=job.submission_id,
        pet_id=job.pet_id,
        template_version_id=version.id,
        object_key=object_key,
        package_sha256=validated.package_sha256,
        package_size=validated.package_size,
        manifest_json=validated.manifest_json,
        uploaded_by_account_id=principal.account_id,
    )
    previous = job.status
    now = datetime.now(UTC)
    job.status = "ready"
    job.progress = 100
    job.status_note = "素材包已通过安全与 13 种动作校验，等待后续发布审核。"
    job.target_template_version_id = version.id
    job.completed_at = now
    job.updated_at = now
    try:
        session.add(artifact)
        session.flush()
        append_job_log(
            session,
            job,
            actor_account_id=principal.account_id,
            action="artifact.validated",
            from_status=previous,
            message=job.status_note,
            details={
                "artifact_id": artifact.id,
                "template_version_id": version.id,
                "sha256": artifact.package_sha256,
                "size": artifact.package_size,
            },
        )
        publish_job_event(
            session,
            job,
            cause="production_artifact_ready",
            idempotency_key=f"pet-asset-production-job:{job.id}:artifact:{artifact.id}",
        )
        _audit(
            session,
            principal=principal,
            action="pet_asset_production_job.artifact_uploaded",
            job=job,
            details={
                "artifact_id": artifact.id,
                "template_version_id": version.id,
                "sha256": artifact.package_sha256,
                "size": artifact.package_size,
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        store.delete(object_key)
        raise
    return _job_view(session, job, admin=True)


@admin_asset_production_router.get(
    "/pet-asset-production-jobs/{job_id}/artifact/package"
)
def download_admin_production_artifact(
    job_id: str,
    request: Request,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    _job_or_404(session, job_id)
    artifact = session.scalar(
        select(PetAssetProductionArtifact).where(PetAssetProductionArtifact.job_id == job_id)
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="制作产物不存在")
    try:
        path = _object_store(request).path(artifact.object_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="制作产物对象不存在") from exc
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"pet-production-artifact-{artifact.id}.zip",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@admin_asset_production_router.get(
    "/pet-asset-production-jobs/{job_id}/reference-images/{reference_id}/image"
)
def download_admin_production_reference_image(
    job_id: str,
    reference_id: str,
    request: Request,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    _job_or_404(session, job_id)
    item = session.get(PetAssetProductionReferenceImage, reference_id)
    if item is None or item.job_id != job_id:
        raise HTTPException(status_code=404, detail="补充参考图不存在")
    return _download_image(request, item)
