"""add job_id indexes on agent_runs and job_events

Revision ID: 20260402_0002
Revises: 20260401_0001
Create Date: 2026-04-02 12:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "20260402_0002"
down_revision = "20260401_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_agent_runs_job_id", "agent_runs", ["job_id"])
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_index("ix_agent_runs_job_id", table_name="agent_runs")
