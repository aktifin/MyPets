"""Administrator pet-template review/publishing routes and public asset catalog."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .api import get_session, get_settings, require_account
from .asset_packages import validate_asset_package
from .config import Settings
from .models import (
    Account,
    AdminAuditLog,
    PetAssetRelease,
    PetTemplate,
    PetTemplateVersion,
)
from .object_store import FileObjectStore
from .schemas import (
    AdminAuditLogView,
    PetAssetReleaseView,
    PetTemplateCreateRequest,
    PetTemplateVersionCreateRequest,
    PetTemplateVersionView,
    PetTemplateView,
    ReviewDecisionRequest,
)
from .security import Principal

admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin-pets"])
catalog_router = APIRouter(prefix="/api/v1", tags=["pet-assets"])


def get_object_store(request: Request) -> FileObjectStore:
    return request.app.state.asset_object_store


def require_admin(
    principal: Annotated[Principal, Depends(require_account)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> Principal:
    account = session.get(Account, principal.account_id)
    if account is None or account.username.lower() not in settings.admin_usernames:
        raise HTTPException(status_code=403, detail="此操作需要宠物内容管理员权限")
    return principal


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _template_view(item: PetTemplate) -> PetTemplateView:
    return PetTemplateView(
        id=item.id,
        template_code=item.template_code,
        display_name=item.display_name,
        species=item.species,
        description=item.description,
        status=item.status,
        created_by_account_id=item.created_by_account_id,
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def _version_view(item: PetTemplateVersion) -> PetTemplateVersionView:
    return PetTemplateVersionView(
        id=item.id,
        template_id=item.template_id,
        template_version=item.template_version,
        identity_version=item.identity_version,
        asset_version=item.asset_version,
        status=item.status,
        package_sha256=item.package_sha256,
        package_size=item.package_size,
        created_by_account_id=item.created_by_account_id,
        reviewed_by_account_id=item.reviewed_by_account_id,
        review_comment=item.review_comment,
        approved_at=_aware(item.approved_at),
        published_at=_aware(item.published_at),
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def _release_view(item: PetAssetRelease) -> PetAssetReleaseView:
    return PetAssetReleaseView(
        release_id=item.id,
        template_id=item.template_code,
        template_version=item.template_version,
        identity_version=item.identity_version,
        asset_version=item.asset_version,
        package_sha256=item.package_sha256,
        package_size=item.package_size,
        download_url=f"/api/v1/assets/releases/{item.id}/package",
        manifest=json.loads(item.manifest_json),
        published_at=_aware(item.created_at),
    )


def _audit_view(item: AdminAuditLog) -> AdminAuditLogView:
    return AdminAuditLogView(
        id=item.id,
        admin_account_id=item.admin_account_id,
        action=item.action,
        resource_type=item.resource_type,
        resource_id=item.resource_id,
        details=json.loads(item.details_json),
        created_at=_aware(item.created_at),
    )


def _audit(
    session: Session,
    *,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict | None = None,
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


def _template_or_404(session: Session, template_id: str) -> PetTemplate:
    item = session.get(PetTemplate, template_id)
    if item is None:
        raise HTTPException(status_code=404, detail="宠物模板不存在")
    return item


def _version_or_404(session: Session, version_id: str) -> PetTemplateVersion:
    item = session.get(PetTemplateVersion, version_id)
    if item is None:
        raise HTTPException(status_code=404, detail="宠物模板版本不存在")
    return item


@admin_router.post("/pet-templates", response_model=PetTemplateView, status_code=201)
def create_template(
    body: PetTemplateCreateRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateView:
    item = PetTemplate(
        id=str(uuid4()),
        template_code=body.template_code,
        display_name=body.display_name,
        species=body.species,
        description=body.description,
        status="draft",
        created_by_account_id=principal.account_id,
    )
    session.add(item)
    _audit(
        session,
        principal=principal,
        action="pet_template.created",
        resource_type="pet_template",
        resource_id=item.id,
        details={"template_code": item.template_code},
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="宠物模板编码已存在") from exc
    return _template_view(item)


@admin_router.get("/pet-templates", response_model=list[PetTemplateView])
def list_templates(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> list[PetTemplateView]:
    return [
        _template_view(item)
        for item in session.scalars(select(PetTemplate).order_by(PetTemplate.created_at))
    ]


@admin_router.post(
    "/pet-templates/{template_id}/versions",
    response_model=PetTemplateVersionView,
    status_code=201,
)
def create_template_version(
    template_id: str,
    body: PetTemplateVersionCreateRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateVersionView:
    template = _template_or_404(session, template_id)
    item = PetTemplateVersion(
        id=str(uuid4()),
        template_id=template.id,
        template_version=body.template_version,
        identity_version=body.identity_version,
        asset_version=body.asset_version,
        status="draft",
        created_by_account_id=principal.account_id,
    )
    session.add(item)
    _audit(
        session,
        principal=principal,
        action="pet_template_version.created",
        resource_type="pet_template_version",
        resource_id=item.id,
        details={
            "template_version": item.template_version,
            "identity_version": item.identity_version,
            "asset_version": item.asset_version,
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="相同宠物模板版本已存在") from exc
    return _version_view(item)


@admin_router.get(
    "/pet-templates/{template_id}/versions",
    response_model=list[PetTemplateVersionView],
)
def list_template_versions(
    template_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> list[PetTemplateVersionView]:
    _template_or_404(session, template_id)
    rows = session.scalars(
        select(PetTemplateVersion)
        .where(PetTemplateVersion.template_id == template_id)
        .order_by(PetTemplateVersion.created_at, PetTemplateVersion.id)
    )
    return [_version_view(item) for item in rows]


@admin_router.get(
    "/pet-template-versions/{version_id}",
    response_model=PetTemplateVersionView,
)
def get_template_version(
    version_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateVersionView:
    return _version_view(_version_or_404(session, version_id))


@admin_router.post(
    "/pet-template-versions/{version_id}/package",
    response_model=PetTemplateVersionView,
)
async def upload_package(
    version_id: str,
    package: Annotated[UploadFile, File(description="宠物形象 ZIP 包")],
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[FileObjectStore, Depends(get_object_store)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateVersionView:
    version = _version_or_404(session, version_id)
    if version.status not in {"draft", "changes_required"}:
        raise HTTPException(status_code=409, detail="当前状态不允许替换素材包")
    template = _template_or_404(session, version.template_id)
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
    key = f"staging/{version.id}/{validated.package_sha256}.zip"
    store.write(key, data, replace=True)
    version.manifest_json = validated.manifest_json
    version.package_sha256 = validated.package_sha256
    version.package_size = validated.package_size
    version.staging_object_key = key
    version.status = "draft"
    version.reviewed_by_account_id = None
    version.review_comment = ""
    version.approved_at = None
    _audit(
        session,
        principal=principal,
        action="pet_asset_package.uploaded",
        resource_type="pet_template_version",
        resource_id=version.id,
        details={"sha256": validated.package_sha256, "size": validated.package_size},
    )
    session.commit()
    return _version_view(version)


@admin_router.post(
    "/pet-template-versions/{version_id}/submit-review",
    response_model=PetTemplateVersionView,
)
def submit_review(
    version_id: str,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateVersionView:
    version = _version_or_404(session, version_id)
    if version.status not in {"draft", "changes_required"}:
        raise HTTPException(status_code=409, detail="当前状态不能提交审核")
    if not version.manifest_json or not version.staging_object_key:
        raise HTTPException(status_code=409, detail="必须先上传并校验素材包")
    version.status = "in_review"
    _audit(
        session,
        principal=principal,
        action="pet_template_version.submitted",
        resource_type="pet_template_version",
        resource_id=version.id,
    )
    session.commit()
    return _version_view(version)


@admin_router.post(
    "/pet-template-versions/{version_id}/approve",
    response_model=PetTemplateVersionView,
)
def approve_version(
    version_id: str,
    body: ReviewDecisionRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateVersionView:
    version = _version_or_404(session, version_id)
    if version.status != "in_review":
        raise HTTPException(status_code=409, detail="只有审核中的版本可以批准")
    if version.created_by_account_id == principal.account_id:
        raise HTTPException(status_code=409, detail="创建者不能审核自己的宠物版本")
    version.status = "approved"
    version.reviewed_by_account_id = principal.account_id
    version.review_comment = body.comment.strip()
    version.approved_at = datetime.now(UTC)
    _audit(
        session,
        principal=principal,
        action="pet_template_version.approved",
        resource_type="pet_template_version",
        resource_id=version.id,
        details={"comment": version.review_comment},
    )
    session.commit()
    return _version_view(version)


@admin_router.post(
    "/pet-template-versions/{version_id}/reject",
    response_model=PetTemplateVersionView,
)
def reject_version(
    version_id: str,
    body: ReviewDecisionRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateVersionView:
    version = _version_or_404(session, version_id)
    if version.status != "in_review":
        raise HTTPException(status_code=409, detail="只有审核中的版本可以退回")
    version.status = "changes_required"
    version.reviewed_by_account_id = principal.account_id
    version.review_comment = body.comment.strip()
    _audit(
        session,
        principal=principal,
        action="pet_template_version.rejected",
        resource_type="pet_template_version",
        resource_id=version.id,
        details={"comment": version.review_comment},
    )
    session.commit()
    return _version_view(version)


@admin_router.post(
    "/pet-template-versions/{version_id}/publish",
    response_model=PetAssetReleaseView,
    status_code=201,
)
def publish_version(
    version_id: str,
    principal: Annotated[Principal, Depends(require_admin)],
    store: Annotated[FileObjectStore, Depends(get_object_store)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetReleaseView:
    version = _version_or_404(session, version_id)
    if version.status != "approved":
        raise HTTPException(status_code=409, detail="只有已批准版本可以发布")
    if not all(
        [
            version.manifest_json,
            version.package_sha256,
            version.package_size,
            version.staging_object_key,
        ]
    ):
        raise HTTPException(status_code=409, detail="素材包发布信息不完整")
    template = _template_or_404(session, version.template_id)
    existing = session.scalar(
        select(PetAssetRelease).where(PetAssetRelease.template_version_id == version.id)
    )
    if existing is not None:
        return _release_view(existing)
    release_id = str(uuid4())
    object_key = f"releases/{template.template_code}/{version.identity_version}/{version.asset_version}/{release_id}.zip"
    try:
        store.promote(version.staging_object_key, object_key)
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    release = PetAssetRelease(
        id=release_id,
        template_version_id=version.id,
        template_code=template.template_code,
        template_version=version.template_version,
        identity_version=version.identity_version,
        asset_version=version.asset_version,
        object_key=object_key,
        package_sha256=version.package_sha256,
        package_size=version.package_size,
        manifest_json=version.manifest_json,
        published_by_account_id=principal.account_id,
    )
    session.add(release)
    version.status = "published"
    version.published_at = datetime.now(UTC)
    template.status = "published"
    _audit(
        session,
        principal=principal,
        action="pet_template_version.published",
        resource_type="pet_template_version",
        resource_id=version.id,
        details={"release_id": release.id, "object_key": object_key},
    )
    session.commit()
    return _release_view(release)


@admin_router.get("/audit-logs", response_model=list[AdminAuditLogView])
def list_audit_logs(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    resource_type: str | None = Query(default=None, max_length=80),
    resource_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AdminAuditLogView]:
    query = select(AdminAuditLog)
    if resource_type:
        query = query.where(AdminAuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AdminAuditLog.resource_id == resource_id)
    rows = session.scalars(query.order_by(AdminAuditLog.created_at.desc()).limit(limit))
    return [_audit_view(item) for item in rows]


@catalog_router.get("/catalog/pet-assets", response_model=PetAssetReleaseView)
def get_asset_release(
    template_id: Annotated[str, Query(min_length=1, max_length=160)],
    identity_version: Annotated[str, Query(min_length=1, max_length=32)],
    asset_version: Annotated[str, Query(min_length=1, max_length=32)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetReleaseView:
    release = session.scalar(
        select(PetAssetRelease).where(
            PetAssetRelease.template_code == template_id,
            PetAssetRelease.identity_version == identity_version,
            PetAssetRelease.asset_version == asset_version,
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="未找到匹配的已发布宠物形象包")
    return _release_view(release)


@catalog_router.get("/assets/releases/{release_id}/package")
def download_asset_release(
    release_id: str,
    store: Annotated[FileObjectStore, Depends(get_object_store)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    release = session.get(PetAssetRelease, release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="宠物形象发布版本不存在")
    try:
        path = store.path(release.object_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="宠物形象包文件不存在") from exc
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{release.template_code}-{release.asset_version}.zip",
        headers={
            "ETag": f'"{release.package_sha256}"',
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
