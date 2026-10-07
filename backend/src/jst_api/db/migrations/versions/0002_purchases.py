"""purchases

Revision ID: 4a0d67dce347
Revises: 10207e245d08
Create Date: 2026-10-06 23:09:06.783123
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a0d67dce347"
down_revision: str | None = "10207e245d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchases",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("plan_id", sa.String(length=40), nullable=False),
        sa.Column("amount_aud", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("provider_session_id", sa.String(length=255), nullable=True),
        sa.Column("analysis_id", sa.String(length=40), nullable=True),
        sa.Column("trip_id", sa.String(length=40), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_purchases_analysis_id_analyses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trip_id"], ["trips.id"], name=op.f("fk_purchases_trip_id_trips"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchases")),
        sa.UniqueConstraint("provider_session_id", name=op.f("uq_purchases_provider_session_id")),
    )
    op.create_index(op.f("ix_purchases_analysis_id"), "purchases", ["analysis_id"], unique=False)
    op.create_index(op.f("ix_purchases_plan_id"), "purchases", ["plan_id"], unique=False)
    op.create_index(op.f("ix_purchases_status"), "purchases", ["status"], unique=False)
    op.create_index(op.f("ix_purchases_trip_id"), "purchases", ["trip_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_purchases_trip_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_status"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_plan_id"), table_name="purchases")
    op.drop_index(op.f("ix_purchases_analysis_id"), table_name="purchases")
    op.drop_table("purchases")
