"""revocation operations follow-up history

Revision ID: 004_revocation_follow_up
Revises: 003_rights_evidence_history
Create Date: 2026-07-26 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "004_revocation_follow_up"
down_revision: str | Sequence[str] | None = "003_rights_evidence_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pet_asset_revocation_follow_ups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("right_id", sa.String(length=36), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("pet_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("acknowledgement_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["acknowledgement_id"],
            ["pet_asset_revocation_acknowledgements.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["release_id"], ["pet_personal_asset_releases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["right_id"], ["pet_asset_rights.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("pet_asset_revocation_follow_ups", schema=None) as batch_op:
        batch_op.create_index(
            "ix_pet_asset_revocation_follow_up_status",
            ["status", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_pet_asset_revocation_follow_up_target",
            ["right_id", "release_id", "device_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("pet_asset_revocation_follow_ups", schema=None) as batch_op:
        batch_op.drop_index("ix_pet_asset_revocation_follow_up_target")
        batch_op.drop_index("ix_pet_asset_revocation_follow_up_status")
    op.drop_table("pet_asset_revocation_follow_ups")
