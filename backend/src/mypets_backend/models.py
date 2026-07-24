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
