"""rights evidence, validity, and history

Revision ID: 003_rights_evidence_history
Revises: 002_asset_revocation_ack
Create Date: 2026-07-26 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "003_rights_evidence_history"
down_revision: str | Sequence[str] | None = "002_asset_revocation_ack"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pet_asset_rights", schema=None) as batch_op:
        batch_op.add_column(sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("review_comment", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            "ix_pet_asset_rights_validity", ["valid_from", "valid_until"], unique=False
        )

    op.create_table(
        "pet_asset_right_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("right_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_account_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["right_id"], ["pet_asset_rights.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "right_id", "sha256", name="uq_pet_asset_right_evidence_hash"
        ),
    )
    with op.batch_alter_table("pet_asset_right_evidence", schema=None) as batch_op:
        batch_op.create_index(
            "ix_pet_asset_right_evidence_right", ["right_id", "created_at"], unique=False
        )

    op.create_table(
        "pet_asset_right_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("right_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("status_snapshot", sa.String(length=32), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["right_id"], ["pet_asset_rights.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pet_asset_right_history", schema=None) as batch_op:
        batch_op.create_index(
            "ix_pet_asset_right_history_event", ["event_type", "created_at"], unique=False
        )
        batch_op.create_index(
            "ix_pet_asset_right_history_right", ["right_id", "created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("pet_asset_right_history", schema=None) as batch_op:
        batch_op.drop_index("ix_pet_asset_right_history_right")
        batch_op.drop_index("ix_pet_asset_right_history_event")
    op.drop_table("pet_asset_right_history")

    with op.batch_alter_table("pet_asset_right_evidence", schema=None) as batch_op:
        batch_op.drop_index("ix_pet_asset_right_evidence_right")
    op.drop_table("pet_asset_right_evidence")

    with op.batch_alter_table("pet_asset_rights", schema=None) as batch_op:
        batch_op.drop_index("ix_pet_asset_rights_validity")
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("verified_at")
        batch_op.drop_column("review_comment")
        batch_op.drop_column("valid_until")
        batch_op.drop_column("valid_from")
