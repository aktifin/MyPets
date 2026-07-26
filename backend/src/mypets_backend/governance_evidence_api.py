"""Evidence attachments, validity updates, and immutable rights-history APIs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .admin_api import _audit, require_admin
from .api import get_session
from .governance_history import aware, record_right_history, require_validity_window, validity_state
from .governance_models import PetAssetRight, PetAssetRightEvidence, PetAssetRightHistory
from .object_store import FileObjectStore
from .security import Principal

rights_evidence_router = APIRouter(prefix="/api/v1/admin/governance", tags=["admin-governance"])
_ALLOWED_MEDIA_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "text/plain": ".txt",
}
_MAX_EVIDENCE_BYTES = 8 * 1024 * 1024


class RightTermsRequest(BaseModel):
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def _validate_window(self) -> "RightTermsRequest":
        try:
            self.valid_from, self.valid_until = require_validity_window(
                self.valid_from, self.valid_until
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RightTermsView(BaseModel):
    right_id: str
    valid_from: datetime | None
    valid_until: datetime | None
    validity_state: Literal["scheduled", "active", "expired"]
    updated_at: datetime


class RightEvidenceView(BaseModel):
    evidence_id: str
    right_id: str
    original_filename: str
    media_type: str
    sha256: str
    size_bytes: int
    uploaded_by_account_id: str
    download_url: str
    created_at: datetime


class RightHistoryView(BaseModel):
    history_id: str
    right_id: str
    event_type: str
    status_snapshot: str
    actor_account_id: str
    comment: str
    details: dict[str, Any]
    created_at: datetime


def _right_or_404(session: Session, right_id: str) -> PetAssetRight:
    right = session.get(PetAssetRight, right_id)
    if right is None:
        raise HTTPException(status_code=404, detail="版权存证记录不存在")
    return right


def _store(request: Request) -> FileObjectStore:
    return request.app.state.asset_object_store


def _safe_name(value: str | None) -> str:
    raw = (value or "evidence").replace("\\", "/")
    name = PurePath(raw).name.strip()
    return name[:255] or "evidence"


def _evidence_view(item: PetAssetRightEvidence) -> RightEvidenceView:
    return RightEvidenceView(
        evidence_id=item.id,
        right_id=item.right_id,
        original_filename=item.original_filename,
        media_type=item.media_type,
        sha256=item.sha256,
        size_bytes=item.size_bytes,
        uploaded_by_account_id=item.uploaded_by_account_id,
        download_url=(
            f"/api/v1/admin/governance/rights/{item.right_id}/evidence/{item.id}/file"
        ),
        created_at=aware(item.created_at),  # type: ignore[arg-type]
    )


def _history_view(item: PetAssetRightHistory) -> RightHistoryView:
    try:
        details = json.loads(item.details_json)
    except json.JSONDecodeError:
        details = {}
    return RightHistoryView(
        history_id=item.id,
        right_id=item.right_id,
        event_type=item.event_type,
        status_snapshot=item.status_snapshot,
        actor_account_id=item.actor_account_id,
        comment=item.comment,
        details=details if isinstance(details, dict) else {},
        created_at=aware(item.created_at),  # type: ignore[arg-type]
    )


@rights_evidence_router.post("/rights/{right_id}/terms", response_model=RightTermsView)
def update_right_terms(
    right_id: str,
    body: RightTermsRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> RightTermsView:
    right = _right_or_404(session, right_id)
    if right.status != "pending":
        raise HTTPException(status_code=409, detail="只有待复核版权存证可以调整有效期")
    right.valid_from = body.valid_from
    right.valid_until = body.valid_until
    right.updated_at = datetime.now(UTC)
    record_right_history(
        session,
        right=right,
        principal=principal,
        event_type="terms_updated",
        details={
            "valid_from": aware(right.valid_from).isoformat() if right.valid_from else None,
            "valid_until": aware(right.valid_until).isoformat() if right.valid_until else None,
        },
    )
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.terms_updated",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={
            "valid_from": aware(right.valid_from).isoformat() if right.valid_from else None,
            "valid_until": aware(right.valid_until).isoformat() if right.valid_until else None,
        },
    )
    session.commit()
    return RightTermsView(
        right_id=right.id,
        valid_from=aware(right.valid_from),
        valid_until=aware(right.valid_until),
        validity_state=validity_state(right),  # type: ignore[arg-type]
        updated_at=aware(right.updated_at),  # type: ignore[arg-type]
    )


@rights_evidence_router.post(
    "/rights/{right_id}/evidence",
    response_model=RightEvidenceView,
    status_code=status.HTTP_201_CREATED,
)
async def upload_right_evidence(
    right_id: str,
    request: Request,
    evidence: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> RightEvidenceView:
    right = _right_or_404(session, right_id)
    if right.status != "pending":
        raise HTTPException(status_code=409, detail="只有待复核版权存证可以增加证据附件")
    media_type = (evidence.content_type or "").lower().strip()
    extension = _ALLOWED_MEDIA_TYPES.get(media_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="证据附件仅支持 PDF、PNG、JPEG 或纯文本")
    data = await evidence.read(_MAX_EVIDENCE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="证据附件不能为空")
    if len(data) > _MAX_EVIDENCE_BYTES:
        raise HTTPException(status_code=413, detail="单个证据附件不能超过 8 MB")
    digest = hashlib.sha256(data).hexdigest()
    item = PetAssetRightEvidence(
        id=str(uuid4()),
        right_id=right.id,
        original_filename=_safe_name(evidence.filename),
        media_type=media_type,
        object_key=f"governance/rights/{right.id}/{digest}{extension}",
        sha256=digest,
        size_bytes=len(data),
        uploaded_by_account_id=principal.account_id,
    )
    session.add(item)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(
            select(PetAssetRightEvidence).where(
                PetAssetRightEvidence.right_id == right.id,
                PetAssetRightEvidence.sha256 == digest,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="相同证据附件已经上传") from exc
        raise
    try:
        _store(request).write(item.object_key, data)
    except FileExistsError:
        session.rollback()
        raise HTTPException(status_code=409, detail="相同证据对象已经存在")
    record_right_history(
        session,
        right=right,
        principal=principal,
        event_type="evidence_added",
        comment=item.original_filename,
        details={
            "evidence_id": item.id,
            "media_type": item.media_type,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        },
    )
    _audit(
        session,
        principal=principal,
        action="pet_asset_right.evidence_added",
        resource_type="pet_asset_right",
        resource_id=right.id,
        details={"evidence_id": item.id, "sha256": item.sha256},
    )
    session.commit()
    return _evidence_view(item)


@rights_evidence_router.get(
    "/rights/{right_id}/evidence", response_model=list[RightEvidenceView]
)
def list_right_evidence(
    right_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> list[RightEvidenceView]:
    _right_or_404(session, right_id)
    rows = list(
        session.scalars(
            select(PetAssetRightEvidence)
            .where(PetAssetRightEvidence.right_id == right_id)
            .order_by(PetAssetRightEvidence.created_at, PetAssetRightEvidence.id)
        )
    )
    return [_evidence_view(row) for row in rows]


@rights_evidence_router.get("/rights/{right_id}/evidence/{evidence_id}/file")
def download_right_evidence(
    right_id: str,
    evidence_id: str,
    request: Request,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    item = session.get(PetAssetRightEvidence, evidence_id)
    if item is None or item.right_id != right_id:
        raise HTTPException(status_code=404, detail="版权证据附件不存在")
    try:
        path = _store(request).path(item.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail="版权证据附件正文已经丢失") from exc
    return FileResponse(
        path,
        media_type=item.media_type,
        filename=item.original_filename,
        headers={"Cache-Control": "private, no-store"},
    )


@rights_evidence_router.get(
    "/rights/{right_id}/history", response_model=list[RightHistoryView]
)
def list_right_history(
    right_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> list[RightHistoryView]:
    _right_or_404(session, right_id)
    rows = list(
        session.scalars(
            select(PetAssetRightHistory)
            .where(PetAssetRightHistory.right_id == right_id)
            .order_by(PetAssetRightHistory.created_at, PetAssetRightHistory.id)
        )
    )
    return [_history_view(row) for row in rows]
