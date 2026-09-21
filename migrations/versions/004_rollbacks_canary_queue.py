"""Add rollback canary and execution failure metadata.

Revision ID: 004_rollbacks_canary_queue
Revises: 003_api_keys
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004_rollbacks_canary_queue"
down_revision = "003_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "functions", sa.Column("canary_version_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "functions", sa.Column("canary_percent", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_foreign_key(
        "fk_functions_canary_version_id_function_versions",
        "functions",
        "function_versions",
        ["canary_version_id"],
        ["id"],
        use_alter=True,
    )
    op.alter_column("functions", "canary_percent", server_default=None)

    op.add_column("executions", sa.Column("failure_kind", sa.String(length=32), nullable=True))
    op.create_index("ix_executions_failure_kind", "executions", ["failure_kind"])

    op.create_table(
        "version_activations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "function_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("functions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "previous_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("function_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "activated_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("function_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "canary_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("function_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("canary_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("action", sa.String(length=32), nullable=False, server_default="activate"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_version_activations_function_id", "version_activations", ["function_id"])
    op.create_index("ix_version_activations_actor_id", "version_activations", ["actor_id"])
    op.create_index(
        "ix_version_activation_function_created",
        "version_activations",
        ["function_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_version_activation_function_created", table_name="version_activations")
    op.drop_index("ix_version_activations_actor_id", table_name="version_activations")
    op.drop_index("ix_version_activations_function_id", table_name="version_activations")
    op.drop_table("version_activations")

    op.drop_index("ix_executions_failure_kind", table_name="executions")
    op.drop_column("executions", "failure_kind")

    op.drop_constraint(
        "fk_functions_canary_version_id_function_versions", "functions", type_="foreignkey"
    )
    op.drop_column("functions", "canary_percent")
    op.drop_column("functions", "canary_version_id")
