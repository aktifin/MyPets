"""Read-oriented API used by the administrator web console."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import (
    _release_view,
    _version_or_404,
    _version_view,
    get_object_store,
    require_admin,
)
from .api import get_session
from .asset_preview import render_preview_png, summarize_actions
from .models import PetAssetRelease, PetTemplateVersion
from .object_store import FileObjectStore
from .schemas import PetAssetReleaseView, PetTemplateVersionView
from .security import Principal

admin_console_api_router = APIRouter(prefix="/api/v1/admin", tags=["admin-console"])
_ALLOWED_STATUSES = {"draft", "in_review", "changes_required", "approved", "published"}


class PetActionPreviewView(BaseModel):
    name: str
    source_action: str
    frame_count: int
    fallback_to: str | None


class PetTemplateVersionPreviewView(BaseModel):
    version: PetTemplateVersionView
    renderer_kind: str
    manifest: dict[str, Any]
    actions: list[PetActionPreviewView]
    preview_image_url: str


def _package_path(
    version: PetTemplateVersion,
    store: FileObjectStore,
    session: Session,
):
    if version.staging_object_key:
        try:
            return store.path(version.staging_object_key)
        except (FileNotFoundError, ValueError):
            pass
    release = session.scalar(
        select(PetAssetRelease).where(PetAssetRelease.template_version_id == version.id)
    )
    if release is None:
        raise HTTPException(status_code=409, detail="该版本没有可预览的素材包")
    try:
        return store.path(release.object_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="素材包文件不存在") from exc


@admin_console_api_router.get(
    "/pet-template-versions", response_model=list[PetTemplateVersionView]
)
def list_all_template_versions(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    template_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[PetTemplateVersionView]:
    if status_filter and status_filter not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="模板版本状态无效")
    query = select(PetTemplateVersion)
    if status_filter:
        query = query.where(PetTemplateVersion.status == status_filter)
    if template_id:
        query = query.where(PetTemplateVersion.template_id == template_id)
    rows = session.scalars(
        query.order_by(PetTemplateVersion.created_at.desc(), PetTemplateVersion.id).limit(limit)
    )
    return [_version_view(item) for item in rows]


@admin_console_api_router.get(
    "/pet-template-versions/{version_id}/preview",
    response_model=PetTemplateVersionPreviewView,
)
def get_template_version_preview(
    version_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    store: Annotated[FileObjectStore, Depends(get_object_store)],
    session: Annotated[Session, Depends(get_session)],
) -> PetTemplateVersionPreviewView:
    version = _version_or_404(session, version_id)
    if not version.manifest_json:
        raise HTTPException(status_code=409, detail="必须先上传并校验素材包")
    _package_path(version, store, session)
    try:
        manifest = dict(json.loads(version.manifest_json))
        actions = summarize_actions(manifest)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail="素材 Manifest 无法生成预览") from exc
    renderer = manifest.get("renderer")
    renderer_kind = "frames"
    if isinstance(renderer, dict):
        renderer_kind = str(renderer.get("kind", "frames"))
    return PetTemplateVersionPreviewView(
        version=_version_view(version),
        renderer_kind=renderer_kind,
        manifest=manifest,
        actions=[PetActionPreviewView(**item.__dict__) for item in actions],
        preview_image_url=(
            f"/api/v1/admin/pet-template-versions/{version.id}/preview-image"
        ),
    )


@admin_console_api_router.get(
    "/pet-template-versions/{version_id}/preview-image",
    response_class=Response,
)
def get_template_version_preview_image(
    version_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    store: Annotated[FileObjectStore, Depends(get_object_store)],
    session: Annotated[Session, Depends(get_session)],
    action: str = Query(default="idle", min_length=1, max_length=80),
    frame_index: int = Query(default=0, ge=0, le=10000),
) -> Response:
    version = _version_or_404(session, version_id)
    if not version.manifest_json:
        raise HTTPException(status_code=409, detail="必须先上传并校验素材包")
    package_path = _package_path(version, store, session)
    try:
        manifest = dict(json.loads(version.manifest_json))
        payload = render_preview_png(
            package_path,
            manifest,
            action=action,
            frame_index=frame_index,
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@admin_console_api_router.get(
    "/pet-asset-releases", response_model=list[PetAssetReleaseView]
)
def list_asset_releases(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    template_id: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[PetAssetReleaseView]:
    query = select(PetAssetRelease)
    if template_id:
        query = query.where(PetAssetRelease.template_code == template_id)
    rows = session.scalars(
        query.order_by(PetAssetRelease.created_at.desc(), PetAssetRelease.id).limit(limit)
    )
    return [_release_view(item) for item in rows]
