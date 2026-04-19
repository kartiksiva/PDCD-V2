"""add optimistic-lock version column to jobs

Revision ID: 20260419_0004
Revises: 20260411_0003
Create Date: 2026-04-19 23:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260419_0004"
down_revision = "20260411_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("version")
