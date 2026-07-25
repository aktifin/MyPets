"""视觉身份档案与版权治理 API 端点模块。

本模块提供管理员创建/查询宠物视觉身份档案、登记/复核版权授权存证，
以及执行版权撤销并向客户端广播防扩散事件的接口。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import get_principal, get_session, require_account
from .asset_deployment_models import PetPersonalAssetRelease
from .governance_models import PetAssetRight, PetVisualIdentity
from .models import AccountPetRelation
from .security import Principal
from .services import append_event

governance_api_router = APIRouter(prefix="/api/v1/admin/governance", tags=["admin-governance"])


class IdentityCreateRequest(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    identity_version: str = Field(default="v1", max_length=32)
    hair_style: str = Field(default="")
    eye_style: str = Field(default="")
    features: List[str] = Field(default_factory=list)


class RightCreateRequest(BaseModel):
    artifact_id: str = Field(min_length=36, max_length=36)
    rights_type: str = Field(default="MIT", max_length=64)
    source_declaration: str = Field(default="")


class RightRevokeRequest(BaseModel):
    right_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=1, max_length=512)


@governance_api_router.post("/identities")
def create_visual_identity(
    req: IdentityCreateRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    """创建或更新宠物的稳定视觉身份档案。"""
    require_account(principal)

    existing = session.scalar(
        select(PetVisualIdentity).where(
            PetVisualIdentity.template_id == req.template_id,
            PetVisualIdentity.identity_version == req.identity_version,
        )
    )
    if existing:
        existing.hair_style = req.hair_style
        existing.eye_style = req.eye_style
        existing.features_json = json.dumps(req.features)
        session.commit()
        return {"status": "updated", "id": existing.id}

    identity = PetVisualIdentity(
        id=str(uuid4()),
        template_id=req.template_id,
        identity_version=req.identity_version,
        hair_style=req.hair_style,
        eye_style=req.eye_style,
        features_json=json.dumps(req.features),
    )
    session.add(identity)
    session.commit()
    return {"status": "created", "id": identity.id}


@governance_api_router.get("/identities/{template_id}")
def get_visual_identity(
    template_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    """查询宠物的视觉身份档案。"""
    require_account(principal)
    identity = session.scalar(
        select(PetVisualIdentity).where(PetVisualIdentity.template_id == template_id)
    )
    if not identity:
        raise HTTPException(status_code=404, detail="视觉身份档案不存在")
    return {
        "id": identity.id,
        "template_id": identity.template_id,
        "identity_version": identity.identity_version,
        "hair_style": identity.hair_style,
        "eye_style": identity.eye_style,
        "features": json.loads(identity.features_json),
    }


@governance_api_router.post("/rights")
def register_asset_right(
    req: RightCreateRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    """登记版权授权存证。"""
    require_account(principal)
    right = PetAssetRight(
        id=str(uuid4()),
        artifact_id=req.artifact_id,
        rights_type=req.rights_type,
        source_declaration=req.source_declaration,
        status="verified",
        declared_by_account_id=principal.account_id,
        verified_by_account_id=principal.account_id,
    )
    session.add(right)
    session.commit()
    return {"status": "registered", "right_id": right.id}


@governance_api_router.post("/rights/revoke")
def revoke_asset_right(
    req: RightRevokeRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_session)],
):
    """撤销版权授权，终止 Release 分发并向关联账号广播 asset_revoked 事件。"""
    require_account(principal)
    right = session.get(PetAssetRight, req.right_id)
    if not right:
        raise HTTPException(status_code=404, detail="版权存证记录不存在")

    right.status = "revoked"
    right.revoked_reason = req.reason

    # 查关联 release
    releases = list(
        session.scalars(
            select(PetPersonalAssetRelease).where(
                PetPersonalAssetRelease.artifact_id == right.artifact_id
            )
        )
    )

    for release in releases:
        # 向持有该宠物的账号发送撤销事件
        relations = list(
            session.scalars(
                select(AccountPetRelation).where(AccountPetRelation.pet_id == release.pet_id)
            )
        )
        for relation in relations:
            append_event(
                session,
                account_id=relation.account_id,
                event_type="asset_revoked",
                idempotency_key=f"revoke:{right.id}:{release.id}:{relation.account_id}",
                payload={
                    "pet_id": release.pet_id,
                    "release_id": release.id,
                    "reason": req.reason,
                    "action": "evict_cache_and_fallback",
                },
            )

    session.commit()
    return {
        "status": "revoked",
        "right_id": right.id,
        "affected_releases": len(releases),
    }
