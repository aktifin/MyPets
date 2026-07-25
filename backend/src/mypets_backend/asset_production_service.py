"""Transactional helpers for user-specific pet asset production work orders."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .asset_production_models import PetAssetProductionJob, PetAssetProductionJobLog
from .asset_submission_models import UserPetAssetSubmission
from .services import append_event


JOB_STATUSES = {"queued", "processing", "needs_input", "ready", "failed", "cancelled"}
TERMINAL_JOB_STATUSES = {"ready", "cancelled"}


def job_event_payload(job: PetAssetProductionJob, *, cause: str) -> dict[str, Any]:
    return {
        "cause": cause,
        "job": {
            "job_id": job.id,
            "submission_id": job.submission_id,
            "pet_id": job.pet_id,
            "status": job.status,
            "progress": job.progress,
            "status_note": job.status_note,
            "assignee_account_id": job.assignee_account_id,
            "target_template_version_id": job.target_template_version_id,
        },
    }


def publish_job_event(
    session: Session,
    job: PetAssetProductionJob,
    *,
    cause: str,
    idempotency_key: str,
) -> None:
    append_event(
        session,
        account_id=job.account_id,
        event_type="pet_asset_production_job_updated",
        idempotency_key=idempotency_key,
        payload=job_event_payload(job, cause=cause),
    )


def append_job_log(
    session: Session,
    job: PetAssetProductionJob,
    *,
    actor_account_id: str | None,
    action: str,
    from_status: str | None,
    message: str = "",
    details: dict[str, Any] | None = None,
) -> PetAssetProductionJobLog:
    entry = PetAssetProductionJobLog(
        id=str(uuid4()),
        job_id=job.id,
        actor_account_id=actor_account_id,
        action=action,
        from_status=from_status,
        to_status=job.status,
        progress=job.progress,
        message=message.strip(),
        details_json=json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
    )
    session.add(entry)
    return entry


def ensure_production_job(
    session: Session,
    submission: UserPetAssetSubmission,
    *,
    actor_account_id: str | None,
) -> PetAssetProductionJob:
    """Create the unique queued work order for an approved submission."""

    existing = session.scalar(
        select(PetAssetProductionJob).where(
            PetAssetProductionJob.submission_id == submission.id
        )
    )
    if existing is not None:
        return existing
    if submission.status != "approved":
        raise ValueError("只有已通过的宠物原图可以创建制作工单")
    now = datetime.now(UTC)
    job = PetAssetProductionJob(
        id=str(uuid4()),
        submission_id=submission.id,
        account_id=submission.account_id,
        pet_id=submission.pet_id,
        status="queued",
        progress=0,
        status_note="原图已通过审核，等待人工素材制作。",
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.flush()
    append_job_log(
        session,
        job,
        actor_account_id=actor_account_id,
        action="job.created",
        from_status=None,
        message=job.status_note,
        details={"submission_id": submission.id},
    )
    publish_job_event(
        session,
        job,
        cause="production_job_created",
        idempotency_key=f"pet-asset-production-job:{job.id}:created",
    )
    return job
