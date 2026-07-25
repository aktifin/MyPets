"""Compatibility endpoints that must precede dynamic governance routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .admin_api import require_admin
from .api import get_session
from .governance_api import (
    LegacyRightRevokeRequest,
    RightRevocationView,
    _revoke_right,
    _right_or_404,
)
from .security import Principal

governance_compat_router = APIRouter(
    prefix="/api/v1/admin/governance",
    tags=["admin-governance"],
)


@governance_compat_router.post(
    "/rights/revoke",
    response_model=RightRevocationView,
    deprecated=True,
)
def revoke_asset_right_legacy_compat(
    body: LegacyRightRevokeRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> RightRevocationView:
    return _revoke_right(
        right=_right_or_404(session, body.right_id),
        reason=body.reason,
        principal=principal,
        session=session,
    )
