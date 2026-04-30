"""add pending_next_phase column to jobs (outbox pattern)

Revision ID: 20260430_0007
Revises: 20260420_0006
Create Date: 2026-04-30

Adds pending_next_phase so that the transition from
"phase N done" to "phase N+1 enqueued" becomes durable.
The cleanup sweeper re-enqueues any job stuck with a non-NULL
pending_next_phase older than a configurable staleness window.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260430_0007"
down_revision = "20260420_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(
            sa.Column("pending_next_phase", sa.String(32), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("pending_next_phase")
