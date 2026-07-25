"""Safe user pet-image submission and administrator review endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import require_admin
from .api import get_session, get_settings, require_account
from .asset_submission_images import sanitize_submission_image
from .asset_submission_models import UserPetAssetSubmission
from .config import Settings
from .models import Account, AccountPetRelation, AdminAuditLog, Pet, SyncEvent
from .object_store import FileObjectStore
from .security import Principal
from .services import append_event, find_event_by_idempotency

asset_submission_router = APIRouter(prefix="/api/v1", tags=["pet-asset-submissions"])
admin_asset_submission_router = APIRouter(
    prefix="/api/v1/admin", tags=["admin-pet-asset-submissions"]
)

SubmissionStatus = Literal[
    "pending_processing",
    "in_review",
    "approved",
    "rejected",
]
StylePreference = Literal["original", "light_chibi", "full_chibi"]
RightsBasis = Literal["owner_photo", "authorized_use"]
_SUBMISSION_STATUSES = {
    "pending_processing",
    "in_review",
    "approved",
    "rejected",
}
_ACTIVE_DUPLICATE_STATUSES = {"pending_processing", "in_review", "approved"}


class PetAssetSubmissionView(BaseModel):
    submission_id: str
    account_id: str
    account_username: str
    account_display_name: str
    pet_id: str
    pet_name: str
    status: SubmissionStatus
    style_preference: StylePreference
    personality_hint: str
    rights_basis: RightsBasis
    rights_confirmed_at: datetime
    original_filename: str
    image_media_type: str
    image_sha256: str
    image_size: int
    image_width: int
    image_height: int
    image_url: str
    review_comment: str
    reviewed_by_account_id: str | None
    reviewed_at: datetime | None
    publication_ready: bool = False
    created_at: datetime
    updated_at: datetime


class SubmissionReviewRequest(BaseModel):
    comment: str = Field(default="", max_length=2000)

    @field_validator("comment")
    @classmethod
    def _strip_comment(cls, value: str) -> str:
        return value.strip()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _event_payload(event: SyncEvent) -> dict[str, Any]:
    try:
        value = json.loads(event.payload_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _object_store(request: Request) -> FileObjectStore:
    return request.app.state.asset_object_store


def _safe_original_filename(value: str | None) -> str:
    raw = (value or "pet-image").replace("\\", "/")
    name = PurePath(raw).name.strip()
    return name[:255] or "pet-image"


def _submission_or_404(session: Session, submission_id: str) -> UserPetAssetSubmission:
    item = session.get(UserPetAssetSubmission, submission_id)
    if item is None:
        raise HTTPException(status_code=404, detail="宠物形象提交不存在")
    return item


def _owned_submission(
    session: Session,
    *,
    account_id: str,
    submission_id: str,
) -> UserPetAssetSubmission:
    item = _submission_or_404(session, submission_id)
    if item.account_id != account_id:
        raise HTTPException(status_code=404, detail="宠物形象提交不存在")
    return item


def _view(
    session: Session,
    item: UserPetAssetSubmission,
    *,
    admin: bool = False,
) -> PetAssetSubmissionView:
    account = session.get(Account, item.account_id)
    pet = session.get(Pet, item.pet_id)
    if account is None or pet is None:
        raise RuntimeError("宠物形象提交引用的账户或宠物不存在")
    image_url = (
        f"/api/v1/admin/pet-asset-submissions/{item.id}/image"
        if admin
        else f"/api/v1/pet-asset-submissions/{item.id}/image"
    )
    return PetAssetSubmissionView(
        submission_id=item.id,
        account_id=item.account_id,
        account_username=account.username,
        account_display_name=account.display_name,
        pet_id=item.pet_id,
        pet_name=pet.name,
        status=item.status,  # type: ignore[arg-type]
        style_preference=item.style_preference,  # type: ignore[arg-type]
        personality_hint=item.personality_hint,
        rights_basis=item.rights_basis,  # type: ignore[arg-type]
        rights_confirmed_at=_aware(item.rights_confirmed_at),
        original_filename=item.original_filename,
        image_media_type=item.image_media_type,
        image_sha256=item.image_sha256,
        image_size=item.image_size,
        image_width=item.image_width,
        image_height=item.image_height,
        image_url=image_url,
        review_comment=item.review_comment,
        reviewed_by_account_id=item.reviewed_by_account_id,
        reviewed_at=_aware(item.reviewed_at),
        publication_ready=False,
        created_at=_aware(item.created_at),
        updated_at=_aware(item.updated_at),
    )


def _publish_submission_event(
    session: Session,
    item: UserPetAssetSubmission,
    *,
    cause: str,
    idempotency_key: str,
) -> None:
    append_event(
        session,
        account_id=item.account_id,
        event_type="pet_asset_submission_updated",
        idempotency_key=idempotency_key,
        payload={
            "cause": cause,
            "submission": _view(session, item).model_dump(mode="json"),
        },
    )


def _audit_submission(
    session: Session,
    *,
    principal: Principal,
    action: str,
    item: UserPetAssetSubmission,
    details: dict[str, Any] | None = None,
) -> None:
    session.add(
        AdminAuditLog(
            id=str(uuid4()),
            admin_account_id=principal.account_id,
            action=action,
            resource_type="pet_asset_submission",
            resource_id=item.id,
            details_json=json.dumps(
                details or {}, ensure_ascii=False, separators=(",", ":")
            ),
        )
    )


@asset_submission_router.post(
    "/pet-asset-submissions",
    response_model=PetAssetSubmissionView,
    status_code=status.HTTP_201_CREATED,
)
async def create_pet_asset_submission(
    request: Request,
    pet_id: Annotated[str, Form(min_length=1, max_length=36)],
    style_preference: Annotated[StylePreference, Form()],
    rights_basis: Annotated[RightsBasis, Form()],
    rights_confirmed: Annotated[bool, Form()],
    image: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    personality_hint: Annotated[str, Form(max_length=240)] = "",
) -> PetAssetSubmissionView:
    prior = find_event_by_idempotency(session, principal.account_id, idempotency_key)
    if prior is not None:
        payload = _event_payload(prior)
        submission_data = payload.get("submission")
        submission_id = (
            submission_data.get("submission_id")
            if isinstance(submission_data, dict)
            else None
        )
        item = session.get(UserPetAssetSubmission, submission_id) if submission_id else None
        if (
            prior.event_type != "pet_asset_submission_updated"
            or payload.get("cause") != "submission_created"
            or item is None
        ):
            raise HTTPException(status_code=409, detail="幂等键已用于其他操作")
        return _view(session, item)

    if not rights_confirmed:
        raise HTTPException(status_code=422, detail="必须确认拥有图片权利或已取得授权")
    personality_hint = personality_hint.strip()

    pet = session.get(Pet, pet_id)
    relation = session.get(AccountPetRelation, (principal.account_id, pet_id))
    if pet is None or relation is None:
        raise HTTPException(status_code=404, detail="宠物不存在或无访问权限")
    if relation.role not in {"owner", "co_owner"}:
        raise HTTPException(status_code=403, detail="只有主人或共同主人可以提交宠物形象")

    raw = await image.read(settings.max_pet_submission_bytes + 1)
    if len(raw) > settings.max_pet_submission_bytes:
        raise HTTPException(status_code=413, detail="宠物图片大小超过限制")
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
        select(UserPetAssetSubmission).where(
            UserPetAssetSubmission.account_id == principal.account_id,
            UserPetAssetSubmission.pet_id == pet_id,
            UserPetAssetSubmission.image_sha256 == sanitized.sha256,
            UserPetAssetSubmission.status.in_(_ACTIVE_DUPLICATE_STATUSES),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="相同图片已有待处理或已通过的提交")

    now = datetime.now(UTC)
    submission_id = str(uuid4())
    object_key = (
        f"submissions/{principal.account_id}/{submission_id}/"
        f"source.{sanitized.extension}"
    )
    store = _object_store(request)
    try:
        store.write(object_key, sanitized.data)
    except (FileExistsError, OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="宠物图片暂存失败") from exc

    item = UserPetAssetSubmission(
        id=submission_id,
        account_id=principal.account_id,
        pet_id=pet_id,
        status="pending_processing",
        style_preference=style_preference,
        personality_hint=personality_hint,
        rights_basis=rights_basis,
        rights_confirmed_at=now,
        original_filename=_safe_original_filename(image.filename),
        image_media_type=sanitized.media_type,
        image_object_key=object_key,
        image_sha256=sanitized.sha256,
        image_size=sanitized.size,
        image_width=sanitized.width,
        image_height=sanitized.height,
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(item)
        session.flush()
        _publish_submission_event(
            session,
            item,
            cause="submission_created",
            idempotency_key=idempotency_key,
        )
        session.commit()
    except Exception:
        session.rollback()
        store.delete(object_key)
        raise
    return _view(session, item)


@asset_submission_router.get(
    "/pet-asset-submissions", response_model=list[PetAssetSubmissionView]
)
def list_my_pet_asset_submissions(
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: SubmissionStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
) -> list[PetAssetSubmissionView]:
    statement = select(UserPetAssetSubmission).where(
        UserPetAssetSubmission.account_id == principal.account_id
    )
    if status_filter is not None:
        statement = statement.where(UserPetAssetSubmission.status == status_filter)
    rows = list(
        session.scalars(
            statement.order_by(
                UserPetAssetSubmission.created_at.desc(), UserPetAssetSubmission.id
            ).limit(limit)
        )
    )
    return [_view(session, item) for item in rows]


@asset_submission_router.get(
    "/pet-asset-submissions/{submission_id}", response_model=PetAssetSubmissionView
)
def get_my_pet_asset_submission(
    submission_id: str,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetSubmissionView:
    return _view(
        session,
        _owned_submission(
            session, account_id=principal.account_id, submission_id=submission_id
        ),
    )


@asset_submission_router.get("/pet-asset-submissions/{submission_id}/image")
def download_my_pet_asset_submission_image(
    submission_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_account)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    item = _owned_submission(
        session, account_id=principal.account_id, submission_id=submission_id
    )
    try:
        path = _object_store(request).path(item.image_object_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="宠物图片对象不存在") from exc
    extension = "png" if item.image_media_type == "image/png" else "jpg"
    return FileResponse(
        path,
        media_type=item.image_media_type,
        filename=f"pet-submission-{item.id}.{extension}",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@admin_asset_submission_router.get(
    "/pet-asset-submissions", response_model=list[PetAssetSubmissionView]
)
def list_admin_pet_asset_submissions(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    status_filter: SubmissionStatus | None = Query(default=None, alias="status"),
    account_id: str | None = Query(default=None, max_length=36),
    pet_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[PetAssetSubmissionView]:
    statement = select(UserPetAssetSubmission)
    if status_filter is not None:
        statement = statement.where(UserPetAssetSubmission.status == status_filter)
    if account_id:
        statement = statement.where(UserPetAssetSubmission.account_id == account_id)
    if pet_id:
        statement = statement.where(UserPetAssetSubmission.pet_id == pet_id)
    rows = list(
        session.scalars(
            statement.order_by(
                UserPetAssetSubmission.created_at.desc(), UserPetAssetSubmission.id
            ).limit(limit)
        )
    )
    return [_view(session, item, admin=True) for item in rows]


@admin_asset_submission_router.get(
    "/pet-asset-submissions/{submission_id}", response_model=PetAssetSubmissionView
)
def get_admin_pet_asset_submission(
    submission_id: str,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetSubmissionView:
    return _view(session, _submission_or_404(session, submission_id), admin=True)


@admin_asset_submission_router.get("/pet-asset-submissions/{submission_id}/image")
def download_admin_pet_asset_submission_image(
    submission_id: str,
    request: Request,
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> FileResponse:
    item = _submission_or_404(session, submission_id)
    try:
        path = _object_store(request).path(item.image_object_key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="宠物图片对象不存在") from exc
    extension = "png" if item.image_media_type == "image/png" else "jpg"
    return FileResponse(
        path,
        media_type=item.image_media_type,
        filename=f"pet-submission-{item.id}.{extension}",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def _transition_submission(
    *,
    submission_id: str,
    action: Literal["start-review", "approve", "reject"],
    comment: str,
    principal: Principal,
    session: Session,
) -> PetAssetSubmissionView:
    item = _submission_or_404(session, submission_id)
    now = datetime.now(UTC)
    if action == "start-review":
        if item.status != "pending_processing":
            raise HTTPException(status_code=409, detail="只有待处理提交可以进入审核")
        item.status = "in_review"
        item.review_comment = comment
        item.reviewed_by_account_id = principal.account_id
        cause = "submission_review_started"
    elif action == "approve":
        if item.status != "in_review":
            raise HTTPException(status_code=409, detail="只有审核中的提交可以通过")
        item.status = "approved"
        item.review_comment = comment
        item.reviewed_by_account_id = principal.account_id
        item.reviewed_at = now
        cause = "submission_approved"
    else:
        if item.status != "in_review":
            raise HTTPException(status_code=409, detail="只有审核中的提交可以驳回")
        if len(comment) < 3:
            raise HTTPException(status_code=422, detail="驳回时必须填写至少 3 个字符的原因")
        item.status = "rejected"
        item.review_comment = comment
        item.reviewed_by_account_id = principal.account_id
        item.reviewed_at = now
        cause = "submission_rejected"
    item.updated_at = now
    session.flush()
    _publish_submission_event(
        session,
        item,
        cause=cause,
        idempotency_key=f"pet-asset-submission:{item.id}:{item.status}:{uuid4()}",
    )
    _audit_submission(
        session,
        principal=principal,
        action=f"pet_asset_submission.{action}",
        item=item,
        details={"status": item.status, "comment": comment},
    )
    session.commit()
    return _view(session, item, admin=True)


@admin_asset_submission_router.post(
    "/pet-asset-submissions/{submission_id}/start-review",
    response_model=PetAssetSubmissionView,
)
def start_pet_asset_submission_review(
    submission_id: str,
    body: SubmissionReviewRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetSubmissionView:
    return _transition_submission(
        submission_id=submission_id,
        action="start-review",
        comment=body.comment,
        principal=principal,
        session=session,
    )


@admin_asset_submission_router.post(
    "/pet-asset-submissions/{submission_id}/approve",
    response_model=PetAssetSubmissionView,
)
def approve_pet_asset_submission(
    submission_id: str,
    body: SubmissionReviewRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetSubmissionView:
    return _transition_submission(
        submission_id=submission_id,
        action="approve",
        comment=body.comment,
        principal=principal,
        session=session,
    )


@admin_asset_submission_router.post(
    "/pet-asset-submissions/{submission_id}/reject",
    response_model=PetAssetSubmissionView,
)
def reject_pet_asset_submission(
    submission_id: str,
    body: SubmissionReviewRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> PetAssetSubmissionView:
    return _transition_submission(
        submission_id=submission_id,
        action="reject",
        comment=body.comment,
        principal=principal,
        session=session,
    )
