"""Server-authoritative SQLAlchemy models for the first cloud synchronization slice."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("account_id", "public_id", name="uq_device_account_public"),
        Index("ix_devices_account", "account_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_version: Mapped[int] = mapped_column(Integer, default=1)
    active_pet_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="SET NULL"), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Pet(Base):
    __tablename__ = "pets"
    __table_args__ = (Index("ix_pets_owner", "primary_owner_account_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    template_id: Mapped[str] = mapped_column(String(160), nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_version: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_owner_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    growth_stage: Mapped[str] = mapped_column(String(32), default="newborn")
    growth_level: Mapped[int] = mapped_column(Integer, default=1)
    growth_exp: Mapped[int] = mapped_column(Integer, default=0)
    bond_level: Mapped[int] = mapped_column(Integer, default=1)
    bond_exp: Mapped[int] = mapped_column(Integer, default=0)
    hunger: Mapped[int] = mapped_column(Integer, default=100)
    energy: Mapped[int] = mapped_column(Integer, default=100)
    mood: Mapped[int] = mapped_column(Integer, default=80)
    cleanliness: Mapped[int] = mapped_column(Integer, default=100)
    health: Mapped[int] = mapped_column(Integer, default=100)
    boredom: Mapped[int] = mapped_column(Integer, default=0)
    presence: Mapped[str] = mapped_column(String(32), default="home")
    personality_type: Mapped[str] = mapped_column(String(64), default="balanced")
    asset_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    state_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AccountPetRelation(Base):
    __tablename__ = "account_pet_relations"

    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    affinity: Mapped[int] = mapped_column(Integer, default=0)
    care_contribution: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SyncEvent(Base):
    __tablename__ = "sync_events"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "idempotency_key", name="uq_sync_event_account_idempotency"
        ),
        Index("ix_sync_events_account_sequence", "account_id", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    target_device_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PetTemplate(Base):
    __tablename__ = "pet_templates"
    __table_args__ = (Index("ix_pet_templates_status", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_code: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    species: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    created_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetTemplateVersion(Base):
    __tablename__ = "pet_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "template_version",
            "identity_version",
            "asset_version",
            name="uq_pet_template_version_identity",
        ),
        Index("ix_pet_template_versions_template_status", "template_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_templates.id", ondelete="CASCADE"), nullable=False
    )
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_version: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    staging_object_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    reviewed_by_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    review_comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetAssetRelease(Base):
    __tablename__ = "pet_asset_releases"
    __table_args__ = (
        UniqueConstraint("template_version_id", name="uq_asset_release_template_version"),
        Index(
            "ix_asset_releases_lookup",
            "template_code",
            "identity_version",
            "asset_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pet_template_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_code: Mapped[str] = mapped_column(String(160), nullable=False)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_version: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    object_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    package_size: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    published_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        Index("ix_admin_audit_resource", "resource_type", "resource_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    admin_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
