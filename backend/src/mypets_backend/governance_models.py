"""宠物视觉身份档案与版权授权存证 ORM 模型。

本模块定义了 PetVisualIdentity（稳定外观特征档案）与 PetAssetRight（版权授权与复核记录）
数据表，用于宠物视觉一致性治理与版权追溯防扩散。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rights_type: Mapped[str] = mapped_column(String(64), default="MIT", nullable=False)
    source_declaration: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="verified", nullable=False)  # pending, verified, revoked
    declared_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    verified_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
