"""Independent review, immutable release, and per-pet deployment models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class PetAssetDeploymentReview(Base):
    """One independent review record for one validated production artifact."""

    __tablename__ = "pet_asset_deployment_reviews"
    __table_args__ = (
        UniqueConstraint("artifact_id", name="uq_pet_asset_deployment_review_artifact"),
        Index("ix_pet_asset_deployment_reviews_status", "status", "created_at"),
        Index("ix_pet_asset_deployment_reviews_pet", "pet_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_asset_production_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_asset_production_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    submitted_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    review_comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rights_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    visual_identity_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    compatibility_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetPersonalAssetRelease(Base):
    """Immutable private release generated from one approved production artifact."""

    __tablename__ = "pet_personal_asset_releases"
    __table_args__ = (
        UniqueConstraint("review_id", name="uq_pet_personal_asset_release_review"),
        UniqueConstraint("artifact_id", name="uq_pet_personal_asset_release_artifact"),
        Index("ix_pet_personal_asset_releases_pet", "pet_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_asset_deployment_reviews.id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_asset_production_artifacts.id", ondelete="RESTRICT"),
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
    published_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PetPersonalAssetDeployment(Base):
    """Mutable per-pet pointer to immutable personal releases, with one-step rollback."""

    __tablename__ = "pet_personal_asset_deployments"
    __table_args__ = (
        Index("ix_pet_personal_asset_deployments_active", "active_release_id"),
        Index("ix_pet_personal_asset_deployments_previous", "previous_release_id"),
    )

    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True
    )
    active_release_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_personal_asset_releases.id", ondelete="RESTRICT"), nullable=False
    )
    previous_release_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pet_personal_asset_releases.id", ondelete="RESTRICT"), nullable=True
    )
    updated_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, default="publish", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
