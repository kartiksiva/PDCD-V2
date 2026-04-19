"""add ttl_expires_at index on jobs

Revision ID: 20260420_0005
Revises: 20260419_0004
Create Date: 2026-04-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "20260420_0005"
down_revision = "20260419_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_jobs_ttl_expires_at", "jobs", ["ttl_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_ttl_expires_at", table_name="jobs")
