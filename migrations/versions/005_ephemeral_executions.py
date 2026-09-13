"""Add ephemeral execution metadata.

Revision ID: 005_ephemeral_executions
Revises: 004_rollbacks_canary_queue
Create Date: 2026-08-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005_ephemeral_executions"
down_revision: str | None = "004_rollbacks_canary_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "executions",
        sa.Column("execution_type", sa.String(length=32), nullable=False, server_default="function"),
    )
    op.alter_column("executions", "execution_type", server_default=None)
    op.create_foreign_key(
        "fk_executions_api_key_id_api_keys",
        "executions",
        "api_keys",
        ["api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_executions_api_key_id", "executions", ["api_key_id"])
    op.create_index("ix_executions_execution_type", "executions", ["execution_type"])
    op.create_index("ix_execution_type_created_at", "executions", ["execution_type", "created_at"])
    op.create_index("ix_execution_api_key_status", "executions", ["api_key_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_execution_api_key_status", table_name="executions")
    op.drop_index("ix_execution_type_created_at", table_name="executions")
    op.drop_index("ix_executions_execution_type", table_name="executions")
    op.drop_index("ix_executions_api_key_id", table_name="executions")
    op.drop_constraint("fk_executions_api_key_id_api_keys", "executions", type_="foreignkey")
    op.drop_column("executions", "execution_type")
    op.drop_column("executions", "api_key_id")


