"""Controlled work orders and immutable artifacts for user-specific pet assets."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class PetAssetProductionJob(Base):
    """One manual production job created from one approved source-image submission."""

    __tablename__ = "pet_asset_production_jobs"
    __table_args__ = (
        UniqueConstraint("submission_id", name="uq_pet_asset_production_job_submission"),
        Index("ix_pet_asset_production_jobs_account_status", "account_id", "status", "created_at"),
        Index("ix_pet_asset_production_jobs_assignee_status", "assignee_account_id", "status", "updated_at"),
        Index("ix_pet_asset_production_jobs_pet", "pet_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_pet_asset_submissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    assignee_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    target_template_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pet_template_versions.id", ondelete="RESTRICT"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetAssetProductionArtifact(Base):
    """One validated, immutable package produced for a work order.

    The artifact remains staged. D2 never publishes it or changes the pet's active
    identity/asset versions.
    """

    __tablename__ = "pet_asset_production_artifacts"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_pet_asset_production_artifact_job"),
        Index("ix_pet_asset_production_artifacts_submission", "submission_id", "created_at"),
        Index("ix_pet_asset_production_artifacts_template_version", "template_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    submission_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user_pet_asset_submissions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="RESTRICT"), nullable=False
    )
    template_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    package_size: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PetAssetProductionReferenceImage(Base):
    """Additional sanitized user reference image attached to a production job."""

    __tablename__ = "pet_asset_production_reference_images"
    __table_args__ = (
        Index("ix_pet_asset_production_refs_job", "job_id", "created_at"),
        Index("ix_pet_asset_production_refs_hash", "job_id", "image_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    image_media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    image_object_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_size: Mapped[int] = mapped_column(Integer, nullable=False)
    image_width: Mapped[int] = mapped_column(Integer, nullable=False)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PetAssetProductionJobLog(Base):
    """Append-only operation history for a production job."""

    __tablename__ = "pet_asset_production_job_logs"
    __table_args__ = (Index("ix_pet_asset_production_job_logs_job", "job_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_production_jobs.id", ondelete="CASCADE"), nullable=False
    )
    actor_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
