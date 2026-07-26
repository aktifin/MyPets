"""Administrator operations dashboard and manual follow-up for revoked asset cleanup."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_api import _audit, require_admin
from .api import get_session
from .asset_deployment_models import PetPersonalAssetRelease
from .asset_revocation_models import (
    PetAssetRevocationAcknowledgement,
    PetAssetRevocationFollowUp,
)
from .governance_models import PetAssetRight
from .models import Account, AccountPetRelation, Device, Pet
from .security import Principal


admin_asset_revocation_operations_router = APIRouter(
    prefix="/api/v1/admin/governance",
    tags=["admin-governance"],
)

FollowUpStatus = Literal["investigating", "resolved", "waived"]
FollowUpState = Literal["unreviewed", "investigating", "resolved", "waived"]
AckStatus = Literal["completed", "failed"]


class RevocationFollowUpRequest(BaseModel):
    right_id: str = Field(min_length=36, max_length=36)
    release_id: str = Field(min_length=36, max_length=36)
    device_id: str = Field(min_length=36, max_length=36)
    status: FollowUpStatus
    note: str = Field(min_length=3, max_length=2000)

    @field_validator("right_id", "release_id", "device_id", "note")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()


class RevocationFollowUpView(BaseModel):
    follow_up_id: str
    right_id: str
    release_id: str
    pet_id: str
    account_id: str
    device_id: str
    acknowledgement_id: str | None
    status: FollowUpStatus
    note: str
    actor_account_id: str
    created_at: datetime


class RevocationDeviceOperationView(BaseModel):
    right_id: str
    release_id: str
    pet_id: str
    pet_name: str
    account_id: str
    account_username: str
    account_display_name: str
    device_id: str
    device_public_id: str
    device_name: str
    platform: str
    last_seen_at: datetime | None
    acknowledgement_id: str | None
    acknowledgement_status: AckStatus | None
    cache_cleared: bool | None
    fallback_applied: bool | None
    acknowledgement_message: str
    attempt_count: int
    client_processed_at: datetime | None
    acknowledgement_updated_at: datetime | None
    follow_up_status: FollowUpState
    follow_up_note: str
    follow_up_actor_account_id: str | None
    follow_up_at: datetime | None
    needs_attention: bool


class RevocationGroupView(BaseModel):
    right_id: str
    release_id: str
    artifact_id: str
    pet_id: str
    pet_name: str
    revoked_reason: str
    revoked_at: datetime
    expected_device_count: int
    acknowledged_device_count: int
    completed_device_count: int
    failed_device_count: int
    pending_device_count: int
    attention_device_count: int
    investigating_device_count: int
    resolved_device_count: int
    waived_device_count: int
    completion_rate: float


class RevocationOperationsTotals(BaseModel):
    revocation_count: int
    expected_device_count: int
    acknowledged_device_count: int
    completed_device_count: int
    failed_device_count: int
    pending_device_count: int
    attention_device_count: int
    investigating_device_count: int
    resolved_device_count: int
    waived_device_count: int


class RevocationOperationsDashboard(BaseModel):
    totals: RevocationOperationsTotals
    groups: list[RevocationGroupView]
    devices: list[RevocationDeviceOperationView]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _aware_optional(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


def _latest_right(session: Session, artifact_id: str) -> PetAssetRight | None:
    return session.scalar(
        select(PetAssetRight)
        .where(PetAssetRight.artifact_id == artifact_id)
        .order_by(
            PetAssetRight.updated_at.desc(),
            PetAssetRight.created_at.desc(),
            PetAssetRight.id.desc(),
        )
        .limit(1)
    )


def _follow_up_view(item: PetAssetRevocationFollowUp) -> RevocationFollowUpView:
    status_value = item.status if item.status in {"investigating", "resolved", "waived"} else "investigating"
    return RevocationFollowUpView(
        follow_up_id=item.id,
        right_id=item.right_id,
        release_id=item.release_id,
        pet_id=item.pet_id,
        account_id=item.account_id,
        device_id=item.device_id,
        acknowledgement_id=item.acknowledgement_id,
        status=status_value,  # type: ignore[arg-type]
        note=item.note,
        actor_account_id=item.actor_account_id,
        created_at=_aware(item.created_at),
    )


def _target_or_404(
    session: Session,
    *,
    right_id: str,
    release_id: str,
    device_id: str,
) -> tuple[PetAssetRight, PetPersonalAssetRelease, Device, AccountPetRelation]:
    right = session.get(PetAssetRight, right_id)
    if right is None or right.status != "revoked":
        raise HTTPException(status_code=404, detail="已撤销版权存证不存在")
    release = session.get(PetPersonalAssetRelease, release_id)
    if release is None or release.artifact_id != right.artifact_id:
        raise HTTPException(status_code=409, detail="专属 Release 与版权存证不匹配")
    device = session.get(Device, device_id)
    if device is None or device.revoked_at is not None:
        raise HTTPException(status_code=404, detail="待跟进设备不存在或已经撤销")
    relation = session.get(AccountPetRelation, (device.account_id, release.pet_id))
    if relation is None:
        raise HTTPException(status_code=409, detail="设备账户不在目标宠物的照料关系中")
    return right, release, device, relation


@admin_asset_revocation_operations_router.get(
    "/revocation-operations",
    response_model=RevocationOperationsDashboard,
)
def get_revocation_operations_dashboard(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    right_id: str | None = Query(default=None, max_length=36),
    attention_only: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
) -> RevocationOperationsDashboard:
    releases = list(
        session.scalars(
            select(PetPersonalAssetRelease)
            .order_by(PetPersonalAssetRelease.created_at.desc(), PetPersonalAssetRelease.id)
            .limit(limit)
        )
    )
    groups: list[RevocationGroupView] = []
    device_rows: list[RevocationDeviceOperationView] = []

    for release in releases:
        right = _latest_right(session, release.artifact_id)
        if right is None or right.status != "revoked":
            continue
        if right_id and right.id != right_id:
            continue
        pet = session.get(Pet, release.pet_id)
        if pet is None:
            continue
        account_ids = list(
            session.scalars(
                select(AccountPetRelation.account_id).where(
                    AccountPetRelation.pet_id == release.pet_id
                )
            )
        )
        if account_ids:
            devices = list(
                session.scalars(
                    select(Device)
                    .where(Device.account_id.in_(account_ids), Device.revoked_at.is_(None))
                    .order_by(Device.account_id, Device.name, Device.id)
                )
            )
        else:
            devices = []
        acknowledgements = list(
            session.scalars(
                select(PetAssetRevocationAcknowledgement).where(
                    PetAssetRevocationAcknowledgement.right_id == right.id,
                    PetAssetRevocationAcknowledgement.release_id == release.id,
                )
            )
        )
        acknowledgement_by_device = {item.device_id: item for item in acknowledgements}
        follow_ups = list(
            session.scalars(
                select(PetAssetRevocationFollowUp)
                .where(
                    PetAssetRevocationFollowUp.right_id == right.id,
                    PetAssetRevocationFollowUp.release_id == release.id,
                )
                .order_by(
                    PetAssetRevocationFollowUp.created_at,
                    PetAssetRevocationFollowUp.id,
                )
            )
        )
        latest_follow_up_by_device: dict[str, PetAssetRevocationFollowUp] = {}
        for item in follow_ups:
            latest_follow_up_by_device[item.device_id] = item

        completed_count = 0
        failed_count = 0
        pending_count = 0
        acknowledged_count = 0
        attention_count = 0
        investigating_count = 0
        resolved_count = 0
        waived_count = 0

        for device in devices:
            account = session.get(Account, device.account_id)
            if account is None:
                continue
            acknowledgement = acknowledgement_by_device.get(device.id)
            follow_up = latest_follow_up_by_device.get(device.id)
            follow_up_status: FollowUpState = "unreviewed"
            if follow_up is not None and follow_up.status in {"investigating", "resolved", "waived"}:
                follow_up_status = follow_up.status  # type: ignore[assignment]
            healthy = bool(
                acknowledgement is not None
                and acknowledgement.status == "completed"
                and acknowledgement.cache_cleared
                and acknowledgement.fallback_applied
            )
            if acknowledgement is None:
                pending_count += 1
            else:
                acknowledged_count += 1
                if healthy:
                    completed_count += 1
                else:
                    failed_count += 1
            if follow_up_status == "investigating":
                investigating_count += 1
            elif follow_up_status == "resolved":
                resolved_count += 1
            elif follow_up_status == "waived":
                waived_count += 1
            needs_attention = (
                follow_up_status == "investigating"
                or (not healthy and follow_up_status not in {"resolved", "waived"})
            )
            if needs_attention:
                attention_count += 1
            ack_status: AckStatus | None = None
            if acknowledgement is not None:
                ack_status = (
                    acknowledgement.status
                    if acknowledgement.status in {"completed", "failed"}
                    else "failed"
                )  # type: ignore[assignment]
            row = RevocationDeviceOperationView(
                right_id=right.id,
                release_id=release.id,
                pet_id=release.pet_id,
                pet_name=pet.name,
                account_id=account.id,
                account_username=account.username,
                account_display_name=account.display_name,
                device_id=device.id,
                device_public_id=device.public_id,
                device_name=device.name,
                platform=device.platform,
                last_seen_at=_aware_optional(device.last_seen_at),
                acknowledgement_id=acknowledgement.id if acknowledgement else None,
                acknowledgement_status=ack_status,
                cache_cleared=acknowledgement.cache_cleared if acknowledgement else None,
                fallback_applied=acknowledgement.fallback_applied if acknowledgement else None,
                acknowledgement_message=acknowledgement.message if acknowledgement else "",
                attempt_count=acknowledgement.attempt_count if acknowledgement else 0,
                client_processed_at=(
                    _aware(acknowledgement.client_processed_at) if acknowledgement else None
                ),
                acknowledgement_updated_at=(
                    _aware(acknowledgement.updated_at) if acknowledgement else None
                ),
                follow_up_status=follow_up_status,
                follow_up_note=follow_up.note if follow_up else "",
                follow_up_actor_account_id=(follow_up.actor_account_id if follow_up else None),
                follow_up_at=_aware(follow_up.created_at) if follow_up else None,
                needs_attention=needs_attention,
            )
            if not attention_only or needs_attention:
                device_rows.append(row)

        expected_count = len(devices)
        groups.append(
            RevocationGroupView(
                right_id=right.id,
                release_id=release.id,
                artifact_id=release.artifact_id,
                pet_id=release.pet_id,
                pet_name=pet.name,
                revoked_reason=right.revoked_reason or "版权授权已撤销。",
                revoked_at=_aware(right.revoked_at or right.updated_at),
                expected_device_count=expected_count,
                acknowledged_device_count=acknowledged_count,
                completed_device_count=completed_count,
                failed_device_count=failed_count,
                pending_device_count=pending_count,
                attention_device_count=attention_count,
                investigating_device_count=investigating_count,
                resolved_device_count=resolved_count,
                waived_device_count=waived_count,
                completion_rate=(round(completed_count * 100 / expected_count, 1) if expected_count else 100.0),
            )
        )

    groups.sort(key=lambda item: (item.attention_device_count == 0, -item.attention_device_count, item.pet_name))
    device_rows.sort(
        key=lambda item: (
            not item.needs_attention,
            item.acknowledgement_status == "completed",
            item.pet_name,
            item.device_name,
        )
    )
    totals = RevocationOperationsTotals(
        revocation_count=len(groups),
        expected_device_count=sum(item.expected_device_count for item in groups),
        acknowledged_device_count=sum(item.acknowledged_device_count for item in groups),
        completed_device_count=sum(item.completed_device_count for item in groups),
        failed_device_count=sum(item.failed_device_count for item in groups),
        pending_device_count=sum(item.pending_device_count for item in groups),
        attention_device_count=sum(item.attention_device_count for item in groups),
        investigating_device_count=sum(item.investigating_device_count for item in groups),
        resolved_device_count=sum(item.resolved_device_count for item in groups),
        waived_device_count=sum(item.waived_device_count for item in groups),
    )
    return RevocationOperationsDashboard(totals=totals, groups=groups, devices=device_rows)


@admin_asset_revocation_operations_router.post(
    "/revocation-follow-ups",
    response_model=RevocationFollowUpView,
    status_code=status.HTTP_201_CREATED,
)
def create_revocation_follow_up(
    body: RevocationFollowUpRequest,
    principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> RevocationFollowUpView:
    _right, release, device, _relation = _target_or_404(
        session,
        right_id=body.right_id,
        release_id=body.release_id,
        device_id=body.device_id,
    )
    acknowledgement = session.scalar(
        select(PetAssetRevocationAcknowledgement).where(
            PetAssetRevocationAcknowledgement.right_id == body.right_id,
            PetAssetRevocationAcknowledgement.release_id == body.release_id,
            PetAssetRevocationAcknowledgement.device_id == body.device_id,
        )
    )
    item = PetAssetRevocationFollowUp(
        id=str(uuid4()),
        right_id=body.right_id,
        release_id=body.release_id,
        pet_id=release.pet_id,
        account_id=device.account_id,
        device_id=device.id,
        acknowledgement_id=acknowledgement.id if acknowledgement else None,
        status=body.status,
        note=body.note,
        actor_account_id=principal.account_id,
    )
    session.add(item)
    session.flush()
    _audit(
        session,
        principal=principal,
        action="pet_asset_revocation.follow_up_recorded",
        resource_type="pet_asset_revocation_device",
        resource_id=f"{body.right_id}:{body.release_id}:{body.device_id}",
        details={
            "right_id": body.right_id,
            "release_id": body.release_id,
            "device_id": body.device_id,
            "acknowledgement_id": item.acknowledgement_id,
            "status": body.status,
            "note": body.note,
        },
    )
    session.commit()
    return _follow_up_view(item)


@admin_asset_revocation_operations_router.get(
    "/revocation-follow-ups",
    response_model=list[RevocationFollowUpView],
)
def list_revocation_follow_ups(
    _principal: Annotated[Principal, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    right_id: str = Query(min_length=36, max_length=36),
    release_id: str = Query(min_length=36, max_length=36),
    device_id: str = Query(min_length=36, max_length=36),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RevocationFollowUpView]:
    _target_or_404(
        session,
        right_id=right_id,
        release_id=release_id,
        device_id=device_id,
    )
    rows = session.scalars(
        select(PetAssetRevocationFollowUp)
        .where(
            PetAssetRevocationFollowUp.right_id == right_id,
            PetAssetRevocationFollowUp.release_id == release_id,
            PetAssetRevocationFollowUp.device_id == device_id,
        )
        .order_by(
            PetAssetRevocationFollowUp.created_at.desc(),
            PetAssetRevocationFollowUp.id.desc(),
        )
        .limit(limit)
    )
    return [_follow_up_view(item) for item in rows]
