"""宠物视觉身份档案、版权授权存证、证据附件与状态历史 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class PetVisualIdentity(Base):
    """宠物实例/模板的稳定视觉身份特征档案。"""

    __tablename__ = "pet_visual_identities"
    __table_args__ = (
        UniqueConstraint("template_id", "identity_version", name="uq_pet_visual_identity_version"),
        Index("ix_pet_visual_identities_template", "template_id", "identity_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    hair_style: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    eye_style: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    color_palette_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    features_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    reference_images_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetAssetRight(Base):
    """宠物美术素材版权授权存证与复核状态。"""

    __tablename__ = "pet_asset_rights"
    __table_args__ = (
        Index("ix_pet_asset_rights_artifact", "artifact_id"),
        Index("ix_pet_asset_rights_status", "status"),
        Index("ix_pet_asset_rights_validity", "valid_from", "valid_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rights_type: Mapped[str] = mapped_column(String(64), default="MIT", nullable=False)
    source_declaration: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="verified", nullable=False)
    declared_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    verified_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetAssetRightEvidence(Base):
    """不可变版权证据附件元数据；文件正文存放在对象存储。"""

    __tablename__ = "pet_asset_right_evidence"
    __table_args__ = (
        UniqueConstraint("right_id", "sha256", name="uq_pet_asset_right_evidence_hash"),
        Index("ix_pet_asset_right_evidence_right", "right_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    right_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_rights.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PetAssetRightHistory(Base):
    """面向运营查询的不可变版权状态和证据操作历史。"""

    __tablename__ = "pet_asset_right_history"
    __table_args__ = (
        Index("ix_pet_asset_right_history_right", "right_id", "created_at"),
        Index("ix_pet_asset_right_history_event", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    right_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_rights.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
