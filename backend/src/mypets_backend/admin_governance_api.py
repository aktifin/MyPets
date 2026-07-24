"""Administrator role, visual comparison, deployment, and rollback APIs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import _audit, _release_view, _version_or_404, require_admin
from .admin_rbac import permissions_for_roles
from .api import get_session, get_settings
from .asset_preview import summarize_actions
from .config import Settings
from .models import Account, PetAssetDeployment, PetAssetRelease
from .schemas import PetAssetReleaseView
from .security import Principal

admin_governance_router = APIRouter(prefix="/api/v1/admin", tags=["admin-governance"])
governance_catalog_router = APIRouter(prefix="/api/v1", tags=["pet-assets"])


class AdminIdentityView(BaseModel):
    account_id: str
    username: str
    display_name: str
    roles: list[str]
    permissions: list[str]


class ActionComparisonView(BaseModel):
    name: str
    change: str
    left: dict[str, Any] | None
    right: dict[str, Any] | None


class VersionComparisonView(BaseModel):
    left_version_id: str
    right_version_id: str
    template_changed: bool
    renderer_changed: bool
    identity_version_changed: bool
    asset_version_changed: bool
    package_hash_changed: bool
    action_changes: list[ActionComparisonView]


class DeploymentView(BaseModel):
    template_id: str
    channel: str
    active_release: PetAssetReleaseView
    previous_release: PetAssetReleaseView | None
    reason: str
    updated_by_account_id: str
    updated_at: datetime


class RollbackRequest(BaseModel):
    release_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=3, max_length=1000)


def _manifest(version) -> dict[str, Any]:
    if not version.manifest_json:
        raise HTTPException(status_code=409, detail="版本尚未上传可比较的素材包")
    try:
        value = json.loads(version.manifest_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail="素材 Manifest 无法解析") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=409, detail="素材 Manifest 格式无效")
    return value


def _action_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.name: {
            "source_action": item.source_action,
            "frame_count": item.frame_count,
            "fallback_to": item.fallback_to,
        }
        for item in summarize_actions(manifest)
    }


def _release_or_none(session: Session, release_id: str | None) -> PetAssetRelease | None:
    if not release_id:
        return None
    return session.get(PetAssetRelease, release_id)


def _deployment_view(session: Session, deployment: PetAssetDeployment) -> DeploymentView:
    active = _release_or_none(session, deployment.active_release_id)
    if active is None:
        raise HTTPException(status_code=409, detail="当前部署引用了不存在的发布版本")
    previous = _release_or_none(session, deployment.previous_release_id)
    updated_at = deployment.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return DeploymentView(
        template_id=deployment.template_code,
        channel=deployment.channel,
        active_release=_release_view(active),
        previous_release=_release_view(previous) if previous else None,
        reason=deployment.reason,
        updated_by_account_id=deployment.updated_by_account_id,
        updated_at=updated_at,
    )


@admin_governance_router.get("/me", response_model=AdminIdentityView)
def administrator_identity(
    principal: Annotated[Principal, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
) -> AdminIdentityView:
    account = session.get(Account, principal.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="管理员账户不存在")
    roles = settings.roles_for_username(account.username)
    return AdminIdentityView(
        account_id=account.id,
        username=account.username,
        display_name=account.display_name,
        roles=list(roles),
        permissions=list(permissions_for_roles(roles)),
    )


@admin_governance_router.get(
    "/pet-template-versions/compare", response_model=VersionComparisonView
)
def compare_template_versions(
    left_id: Annotated[str, Query(min_length=1, max_length=36)],
    right_id: Annotated[str, Query(min_length=1, max_length=36)],
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> VersionComparisonView:
    if left_id == right_id:
        raise HTTPException(status_code=422, detail="请选择两个不同的模板版本")
    left = _version_or_404(session, left_id)
    right = _version_or_404(session, right_id)
    left_manifest = _manifest(left)
    right_manifest = _manifest(right)
    left_actions = _action_map(left_manifest)
    right_actions = _action_map(right_manifest)
    changes: list[ActionComparisonView] = []
    for name in sorted(set(left_actions) | set(right_actions)):
        left_value = left_actions.get(name)
        right_value = right_actions.get(name)
        if left_value == right_value:
            continue
        if left_value is None:
            change = "added"
        elif right_value is None:
            change = "removed"
        else:
            change = "changed"
        changes.append(
            ActionComparisonView(
                name=name,
                change=change,
                left=left_value,
                right=right_value,
            )
        )
    left_renderer = left_manifest.get("renderer", {"kind": "frames"})
    right_renderer = right_manifest.get("renderer", {"kind": "frames"})
    return VersionComparisonView(
        left_version_id=left.id,
        right_version_id=right.id,
        template_changed=left.template_id != right.template_id,
        renderer_changed=left_renderer != right_renderer,
        identity_version_changed=left.identity_version != right.identity_version,
        asset_version_changed=left.asset_version != right.asset_version,
        package_hash_changed=left.package_sha256 != right.package_sha256,
        action_changes=changes,
    )


@admin_governance_router.get(
    "/pet-asset-deployments", response_model=list[DeploymentView]
)
def list_asset_deployments(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    template_id: str | None = Query(default=None, max_length=160),
) -> list[DeploymentView]:
    query = select(PetAssetDeployment)
    if template_id:
        query = query.where(PetAssetDeployment.template_code == template_id)
    rows = session.scalars(
        query.order_by(PetAssetDeployment.template_code, PetAssetDeployment.channel)
    )
    return [_deployment_view(session, item) for item in rows]


@admin_governance_router.post(
    "/pet-asset-deployments/{template_code}/rollback",
    response_model=DeploymentView,
)
def rollback_asset_deployment(
    template_code: str,
    body: RollbackRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> DeploymentView:
    deployment = session.get(PetAssetDeployment, (template_code, "stable"))
    if deployment is None:
        raise HTTPException(status_code=404, detail="该宠物模板尚未建立稳定发布通道")
    target = session.get(PetAssetRelease, body.release_id)
    if target is None or target.template_code != template_code:
        raise HTTPException(status_code=404, detail="回滚目标不是该模板的已发布版本")
    if target.id == deployment.active_release_id:
        raise HTTPException(status_code=409, detail="目标版本已经是当前稳定版本")

    old_release_id = deployment.active_release_id
    deployment.previous_release_id = old_release_id
    deployment.active_release_id = target.id
    deployment.updated_by_account_id = principal.account_id
    deployment.reason = body.reason.strip()
    deployment.updated_at = datetime.now(UTC)
    _audit(
        session,
        principal=principal,
        action="pet_asset_deployment.rolled_back",
        resource_type="pet_asset_deployment",
        resource_id=target.id,
        details={
            "template_code": template_code,
            "channel": "stable",
            "from_release_id": old_release_id,
            "to_release_id": target.id,
            "reason": deployment.reason,
        },
    )
    session.commit()
    return _deployment_view(session, deployment)


@governance_catalog_router.get(
    "/catalog/pet-assets/latest", response_model=PetAssetReleaseView
)
def latest_asset_release(
    template_id: Annotated[str, Query(min_length=1, max_length=160)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetReleaseView:
    deployment = session.get(PetAssetDeployment, (template_id, "stable"))
    if deployment is None:
        raise HTTPException(status_code=404, detail="该宠物模板没有稳定发布版本")
    release = session.get(PetAssetRelease, deployment.active_release_id)
    if release is None:
        raise HTTPException(status_code=404, detail="稳定发布版本不存在")
    return _release_view(release)
