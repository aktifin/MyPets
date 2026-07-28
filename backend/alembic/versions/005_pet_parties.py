"""minimal multi-pet party sessions

Revision ID: 005_pet_parties
Revises: 004_revocation_follow_up
Create Date: 2026-07-28 21:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "005_pet_parties"
down_revision: str | Sequence[str] | None = "004_revocation_follow_up"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pet_parties",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("host_account_id", sa.String(length=36), nullable=False),
        sa.Column("host_pet_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("max_members", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("completion_reason", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["host_account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["host_pet_id"], ["pets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pet_parties", schema=None) as batch_op:
        batch_op.create_index(
            "ix_pet_parties_host_status",
            ["host_account_id", "status", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_pet_parties_status_started",
            ["status", "started_at"],
            unique=False,
        )

    op.create_table(
        "pet_party_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("pet_id", sa.String(length=36), nullable=True),
        sa.Column("invited_by_account_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invited_by_account_id"], ["accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["party_id"], ["pet_parties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("party_id", "account_id", name="uq_pet_party_member_account"),
        sa.UniqueConstraint("party_id", "pet_id", name="uq_pet_party_member_pet"),
    )
    with op.batch_alter_table("pet_party_members", schema=None) as batch_op:
        batch_op.create_index(
            "ix_pet_party_members_account_status",
            ["account_id", "status", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_pet_party_members_party_status",
            ["party_id", "status", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("pet_party_members", schema=None) as batch_op:
        batch_op.drop_index("ix_pet_party_members_party_status")
        batch_op.drop_index("ix_pet_party_members_account_status")
    op.drop_table("pet_party_members")
    with op.batch_alter_table("pet_parties", schema=None) as batch_op:
        batch_op.drop_index("ix_pet_parties_status_started")
        batch_op.drop_index("ix_pet_parties_host_status")
    op.drop_table("pet_parties")
