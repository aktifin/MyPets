"""Per-device acknowledgements and administrator follow-up for revoked pet assets."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class PetAssetRevocationAcknowledgement(Base):
    """One device's durable report that a revoked asset was evicted and safely degraded."""

    __tablename__ = "pet_asset_revocation_acknowledgements"
    __table_args__ = (
        UniqueConstraint(
            "right_id",
            "release_id",
            "device_id",
            name="uq_pet_asset_revocation_ack_device",
        ),
        Index(
            "ix_pet_asset_revocation_ack_status",
            "status",
            "updated_at",
        ),
        Index(
            "ix_pet_asset_revocation_ack_pet",
            "pet_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    right_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_rights.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_asset_production_artifacts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    release_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_personal_asset_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="completed", nullable=False)
    cache_cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    client_processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetAssetRevocationFollowUp(Base):
    """Immutable administrator follow-up history for an expected device cleanup."""

    __tablename__ = "pet_asset_revocation_follow_ups"
    __table_args__ = (
        Index(
            "ix_pet_asset_revocation_follow_up_target",
            "right_id",
            "release_id",
            "device_id",
            "created_at",
        ),
        Index(
            "ix_pet_asset_revocation_follow_up_status",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    right_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_rights.id", ondelete="RESTRICT"), nullable=False
    )
    release_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_personal_asset_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    acknowledgement_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("pet_asset_revocation_acknowledgements.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    actor_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
