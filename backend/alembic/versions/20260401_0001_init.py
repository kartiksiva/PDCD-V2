"""init durable persistence

Revision ID: 20260401_0001
Revises: 
Create Date: 2026-04-01 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260401_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.Column("profile_requested", sa.String(length=32), nullable=False),
        sa.Column("provider_effective", sa.Text(), nullable=False),
        sa.Column("has_video", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("has_audio", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("has_transcript", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("teams_metadata", sa.Text(), nullable=False),
        sa.Column("transcript_media_consistency", sa.Text(), nullable=False),
        sa.Column("agent_signals", sa.Text(), nullable=False),
        sa.Column("agent_review", sa.Text(), nullable=False),
        sa.Column("speaker_resolutions", sa.Text(), nullable=False),
        sa.Column("user_saved_draft", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("user_saved_at", sa.String(length=64), nullable=True),
        sa.Column("current_phase", sa.String(length=32), nullable=True),
        sa.Column("last_completed_phase", sa.String(length=32), nullable=True),
        sa.Column("phase_attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("payload_hash", sa.String(length=128), nullable=True),
        sa.Column("active_agent_run_id", sa.String(length=64), nullable=True),
        sa.Column("deleted_at", sa.String(length=64), nullable=True),
        sa.Column("cleanup_pending", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("ttl_expires_at", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "input_manifests",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "review_notes",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "drafts",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        sa.Column("draft_kind", sa.String(length=32), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("generated_at", sa.String(length=64), nullable=True),
        sa.Column("user_reconciled_at", sa.String(length=64), nullable=True),
        sa.Column("finalized_at", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "agent_runs",
        sa.Column("agent_run_id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_estimate_usd", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence_delta", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "exports",
        sa.Column("job_id", sa.String(length=64), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "job_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_events")
    op.drop_table("exports")
    op.drop_table("agent_runs")
    op.drop_table("drafts")
    op.drop_table("review_notes")
    op.drop_table("input_manifests")
    op.drop_table("jobs")
