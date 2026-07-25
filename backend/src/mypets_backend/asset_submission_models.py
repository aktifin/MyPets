"""User-owned pet image submissions awaiting controlled asset production review."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class UserPetAssetSubmission(Base):
    """A sanitized still image and explicit rights declaration for one pet.

    Approval only accepts the source into the manual asset-production queue. It never
    changes a pet identity or publishes an executable package by itself.
    """

    __tablename__ = "user_pet_asset_submissions"
    __table_args__ = (
        Index(
            "ix_user_pet_asset_submissions_account_status",
            "account_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_user_pet_asset_submissions_pet_status",
            "pet_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_user_pet_asset_submissions_hash",
            "account_id",
            "pet_id",
            "image_sha256",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending_processing", nullable=False
    )
    style_preference: Mapped[str] = mapped_column(String(32), nullable=False)
    personality_hint: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    rights_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    rights_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    image_media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    image_object_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    image_size: Mapped[int] = mapped_column(Integer, nullable=False)
    image_width: Mapped[int] = mapped_column(Integer, nullable=False)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False)

    review_comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reviewed_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
