"""asset revocation acknowledgements

Revision ID: 002_asset_revocation_ack
Revises: 001_initial_schema
Create Date: 2026-07-26 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "002_asset_revocation_ack"
down_revision: str | Sequence[str] | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pet_asset_revocation_acknowledgements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("right_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("release_id", sa.String(length=36), nullable=False),
        sa.Column("pet_id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("cache_cleared", sa.Boolean(), nullable=False),
        sa.Column("fallback_applied", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("client_processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["artifact_id"], ["pet_asset_production_artifacts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["release_id"], ["pet_personal_asset_releases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["right_id"], ["pet_asset_rights.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "right_id",
            "release_id",
            "device_id",
            name="uq_pet_asset_revocation_ack_device",
        ),
    )
    with op.batch_alter_table(
        "pet_asset_revocation_acknowledgements", schema=None
    ) as batch_op:
        batch_op.create_index(
            "ix_pet_asset_revocation_ack_pet",
            ["pet_id", "updated_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_pet_asset_revocation_ack_status",
            ["status", "updated_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table(
        "pet_asset_revocation_acknowledgements", schema=None
    ) as batch_op:
        batch_op.drop_index("ix_pet_asset_revocation_ack_status")
        batch_op.drop_index("ix_pet_asset_revocation_ack_pet")
    op.drop_table("pet_asset_revocation_acknowledgements")
