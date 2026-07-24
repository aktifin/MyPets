"""Server-authoritative reminder occurrence persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .models import utc_now


class ReminderOccurrence(Base):
    """One concrete reminder delivery owned by exactly one account."""

    __tablename__ = "reminder_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "source",
            "source_reminder_id",
            name="uq_reminder_occurrence_source",
        ),
        Index(
            "ix_reminder_occurrences_due",
            "account_id",
            "state",
            "scheduled_at",
        ),
        Index("ix_reminder_occurrences_updated", "account_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_reminder_id: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default="normal", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    snooze_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
