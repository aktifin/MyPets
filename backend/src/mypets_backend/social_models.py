"""Friendship, blocking, privacy, and shared-care persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class FriendRequest(Base):
    __tablename__ = "friend_requests"
    __table_args__ = (
        Index("ix_friend_requests_recipient_status", "recipient_account_id", "status", "created_at"),
        Index("ix_friend_requests_sender_status", "sender_account_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sender_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    recipient_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("account_low_id", "account_high_id", name="uq_friendship_pair"),
        Index("ix_friendships_low", "account_low_id", "created_at"),
        Index("ix_friendships_high", "account_high_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_low_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    account_high_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AccountBlock(Base):
    __tablename__ = "account_blocks"
    __table_args__ = (Index("ix_account_blocks_blocked", "blocked_account_id"),)

    blocker_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PetPrivacy(Base):
    __tablename__ = "pet_privacy"

    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), primary_key=True
    )
    visibility: Mapped[str] = mapped_column(String(24), default="private", nullable=False)
    allow_remote_care: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CaregiverInvitation(Base):
    __tablename__ = "caregiver_invitations"
    __table_args__ = (
        Index("ix_caregiver_invites_recipient", "invited_account_id", "status", "created_at"),
        Index("ix_caregiver_invites_pet", "pet_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pet_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False
    )
    invited_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    invited_by_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(24), default="caregiver", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
