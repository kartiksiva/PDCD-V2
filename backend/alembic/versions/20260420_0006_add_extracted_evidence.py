"""add extracted_evidence column to jobs

Revision ID: 20260420_0006
Revises: 20260420_0005
Create Date: 2026-04-20

The extracted_evidence JSON column was missing from the jobs table, causing
extraction results to be silently discarded on every upsert_job call. Processing
workers always received empty evidence, producing 1-step stub drafts.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260420_0006"
down_revision = "20260420_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("extracted_evidence", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "extracted_evidence")
