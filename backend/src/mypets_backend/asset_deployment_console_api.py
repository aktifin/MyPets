"""Read-oriented administrator API for current per-pet personal asset deployments."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import require_admin
from .api import get_session
from .asset_deployment_api import PersonalAssetDeploymentView, _deployment_view
from .asset_deployment_models import PetPersonalAssetDeployment
from .security import Principal

admin_asset_deployment_console_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-pet-personal-assets"],
)


@admin_asset_deployment_console_router.get(
    "/pet-personal-asset-deployments",
    response_model=list[PersonalAssetDeploymentView],
)
def list_personal_asset_deployments(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=200, ge=1, le=500),
) -> list[PersonalAssetDeploymentView]:
    rows = session.scalars(
        select(PetPersonalAssetDeployment)
        .order_by(PetPersonalAssetDeployment.updated_at.desc(), PetPersonalAssetDeployment.pet_id)
        .limit(limit)
    )
    return [_deployment_view(session, row) for row in rows]
