"""Server-authoritative SQLAlchemy models for MyPets cloud synchronization."""

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
    event,
    select,
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


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("direct_key", name="uq_conversation_direct_key"),
        Index("ix_conversations_updated", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="direct", nullable=False)
    direct_key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    created_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (Index("ix_conversation_members_account", "account_id", "conversation_id"),)

    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    last_read_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_sequence", "conversation_id", "sequence"),
        Index("ix_messages_sender_created", "sender_account_id", "created_at"),
    )

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    sender_pet_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="SET NULL"), nullable=True
    )
    message_type: Mapped[str] = mapped_column(String(32), default="text", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MessageReceipt(Base):
    __tablename__ = "message_receipts"
    __table_args__ = (Index("ix_message_receipts_account_state", "account_id", "state"),)

    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(String(32), default="delivered", nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class PetAssetDeployment(Base):
    """Mutable channel pointer to an immutable pet asset release."""

    __tablename__ = "pet_asset_deployments"
    __table_args__ = (
        Index("ix_pet_asset_deployments_release", "active_release_id"),
    )

    template_code: Mapped[str] = mapped_column(String(160), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), primary_key=True, default="stable")
    active_release_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pet_asset_releases.id", ondelete="RESTRICT"), nullable=False
    )
    previous_release_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pet_asset_releases.id", ondelete="RESTRICT"), nullable=True
    )
    updated_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, default="publish", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


@event.listens_for(PetAssetRelease, "after_insert")
def _activate_new_release(_mapper, connection, target: PetAssetRelease) -> None:
    """Move the stable channel to each newly published immutable release."""

    table = PetAssetDeployment.__table__
    current = connection.execute(
        select(table.c.active_release_id).where(
            table.c.template_code == target.template_code,
            table.c.channel == "stable",
        )
    ).scalar_one_or_none()
    now = utc_now()
    if current is None:
        connection.execute(
            table.insert().values(
                template_code=target.template_code,
                channel="stable",
                active_release_id=target.id,
                previous_release_id=None,
                updated_by_account_id=target.published_by_account_id,
                reason="publish",
                created_at=now,
                updated_at=now,
            )
        )
        return
    connection.execute(
        table.update()
        .where(
            table.c.template_code == target.template_code,
            table.c.channel == "stable",
        )
        .values(
            active_release_id=target.id,
            previous_release_id=current,
            updated_by_account_id=target.published_by_account_id,
            reason="publish",
            updated_at=now,
        )
    )


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


class PetGrowthLog(Base):
    """宠物成长与阶段变更里程碑日志。"""

    __tablename__ = "pet_growth_logs"
    __table_args__ = (Index("ix_pet_growth_logs_pet", "pet_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    to_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PetPersonalityScore(Base):
    """宠物性格路线与日常交互倾向积分。"""

    __tablename__ = "pet_personality_scores"

    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True
    )
    lively_score: Mapped[int] = mapped_column(Integer, default=0)
    gentle_score: Mapped[int] = mapped_column(Integer, default=0)
    social_score: Mapped[int] = mapped_column(Integer, default=0)
    exploratory_score: Mapped[int] = mapped_column(Integer, default=0)
    lazy_score: Mapped[int] = mapped_column(Integer, default=0)
    primary_personality: Mapped[str] = mapped_column(String(64), default="balanced")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PetInteractionLog(Base):
    """宠物日常照料与互动历史日志模型。"""

    __tablename__ = "pet_interaction_logs"
    __table_args__ = (Index("ix_pet_interaction_logs_pet", "pet_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action_name: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


