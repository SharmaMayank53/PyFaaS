"""Initial schema - all tables

Revision ID: 001_initial_schema
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # ENUMS
    # -----------------------------------------------------------------------
    execution_status = postgresql.ENUM(
        "PENDING",
        "QUEUED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "TIMED_OUT",
        "CANCELLED",
        name="executionstatus",
        create_type=False,
    )
    execution_status.create(op.get_bind(), checkfirst=True)

    function_status = postgresql.ENUM(
        "ACTIVE", "INACTIVE", "DEPRECATED", name="functionstatus", create_type=False
    )
    function_status.create(op.get_bind(), checkfirst=True)

    schedule_status = postgresql.ENUM(
        "ACTIVE", "PAUSED", "DELETED", name="schedulestatus", create_type=False
    )
    schedule_status.create(op.get_bind(), checkfirst=True)

    # -----------------------------------------------------------------------
    # users
    # -----------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])

    # -----------------------------------------------------------------------
    # functions  (active_version_id added after function_versions)
    # -----------------------------------------------------------------------
    op.create_table(
        "functions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("runtime", sa.String(32), nullable=False, server_default="python3.12"),
        sa.Column(
            "status",
            function_status,
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tags", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_function_owner_name", "functions", ["owner_id", "name"])
    op.create_index("ix_function_owner_id", "functions", ["owner_id"])
    op.create_index("ix_function_status", "functions", ["status"])

    # -----------------------------------------------------------------------
    # function_versions
    # -----------------------------------------------------------------------
    op.create_table(
        "function_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "function_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("functions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("entrypoint", sa.String(255), nullable=False, server_default="handler.handler"),
        sa.Column("artifact_path", sa.String(512), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("artifact_size", sa.Integer, nullable=False),
        sa.Column("environment", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("timeout", sa.Integer, nullable=False, server_default="300"),
        sa.Column("memory_mb", sa.Integer, nullable=False, server_default="128"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("change_notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_version_function_number", "function_versions", ["function_id", "version_number"]
    )
    op.create_index("ix_function_version_function_id", "function_versions", ["function_id"])

    # Now add the FK from functions.active_version_id -> function_versions.id
    op.create_foreign_key(
        "fk_functions_active_version",
        "functions",
        "function_versions",
        ["active_version_id"],
        ["id"],
    )

    # -----------------------------------------------------------------------
    # schedules  (needed before executions for FK)
    # -----------------------------------------------------------------------
    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "function_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("functions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("cron_expression", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "status",
            schedule_status,
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("missed_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_schedule_next_run_at", "schedules", ["next_run_at"])

    # -----------------------------------------------------------------------
    # executions
    # -----------------------------------------------------------------------
    op.create_table(
        "executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "function_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("functions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "function_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("function_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "schedule_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            execution_status,
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("k8s_job_name", sa.String(255), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("attempt_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("timeout", sa.Integer, nullable=False, server_default="300"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_execution_function_id", "executions", ["function_id"])
    op.create_index("ix_execution_status", "executions", ["status"])
    op.create_index("ix_execution_created_at", "executions", ["created_at"])

    # Add FK from schedules.last_execution_id -> executions.id
    op.create_foreign_key(
        "fk_schedules_last_execution",
        "schedules",
        "executions",
        ["last_execution_id"],
        ["id"],
        source_schema=None,
        referent_schema=None,
    )

    # -----------------------------------------------------------------------
    # execution_logs
    # -----------------------------------------------------------------------
    op.create_table(
        "execution_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("level", sa.String(16), nullable=False, server_default="INFO"),
        sa.Column("stream", sa.String(8), nullable=False, server_default="stdout"),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_execution_log_execution_timestamp",
        "execution_logs",
        ["execution_id", "timestamp"],
    )
    op.create_index(
        "ix_execution_log_execution_id",
        "execution_logs",
        ["execution_id"],
    )


def downgrade() -> None:
    op.drop_table("execution_logs")
    op.drop_constraint("fk_schedules_last_execution", "schedules", type_="foreignkey")
    op.drop_table("executions")
    op.drop_table("schedules")
    op.drop_constraint("fk_functions_active_version", "functions", type_="foreignkey")
    op.drop_table("function_versions")
    op.drop_table("functions")
    op.drop_table("users")

    # Drop enums
    for enum_name in ("executionstatus", "functionstatus", "schedulestatus"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
