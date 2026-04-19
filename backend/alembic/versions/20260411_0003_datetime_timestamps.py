"""convert timestamp text columns to timezone-aware DateTime

Revision ID: 20260411_0003
Revises: 20260402_0002
Create Date: 2026-04-11 23:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260411_0003"
down_revision = "20260402_0002"
branch_labels = None
depends_on = None


_DT = sa.DateTime(timezone=True)
_STR64 = sa.String(length=64)


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=False,
            postgresql_using="created_at::timestamptz",
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=False,
            postgresql_using="updated_at::timestamptz",
        )
        batch_op.alter_column(
            "user_saved_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(user_saved_at, '')::timestamptz",
        )
        batch_op.alter_column(
            "deleted_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(deleted_at, '')::timestamptz",
        )
        batch_op.alter_column(
            "ttl_expires_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(ttl_expires_at, '')::timestamptz",
        )

    with op.batch_alter_table("drafts") as batch_op:
        batch_op.alter_column(
            "generated_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(generated_at, '')::timestamptz",
        )
        batch_op.alter_column(
            "user_reconciled_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(user_reconciled_at, '')::timestamptz",
        )
        batch_op.alter_column(
            "finalized_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(finalized_at, '')::timestamptz",
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(updated_at, '')::timestamptz",
        )

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=False,
            postgresql_using="created_at::timestamptz",
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=True,
            postgresql_using="nullif(updated_at, '')::timestamptz",
        )

    with op.batch_alter_table("job_events") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=_STR64,
            type_=_DT,
            existing_nullable=False,
            postgresql_using="created_at::timestamptz",
        )


def downgrade() -> None:
    with op.batch_alter_table("job_events") as batch_op:
        batch_op.alter_column("created_at", existing_type=_DT, type_=_STR64, existing_nullable=False)

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.alter_column("updated_at", existing_type=_DT, type_=_STR64, existing_nullable=True)
        batch_op.alter_column("created_at", existing_type=_DT, type_=_STR64, existing_nullable=False)

    with op.batch_alter_table("drafts") as batch_op:
        batch_op.alter_column("updated_at", existing_type=_DT, type_=_STR64, existing_nullable=True)
        batch_op.alter_column("finalized_at", existing_type=_DT, type_=_STR64, existing_nullable=True)
        batch_op.alter_column("user_reconciled_at", existing_type=_DT, type_=_STR64, existing_nullable=True)
        batch_op.alter_column("generated_at", existing_type=_DT, type_=_STR64, existing_nullable=True)

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("ttl_expires_at", existing_type=_DT, type_=_STR64, existing_nullable=True)
        batch_op.alter_column("deleted_at", existing_type=_DT, type_=_STR64, existing_nullable=True)
        batch_op.alter_column("user_saved_at", existing_type=_DT, type_=_STR64, existing_nullable=True)
        batch_op.alter_column("updated_at", existing_type=_DT, type_=_STR64, existing_nullable=False)
        batch_op.alter_column("created_at", existing_type=_DT, type_=_STR64, existing_nullable=False)
