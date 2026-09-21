"""
Dashboard performance indexes.

Adds composite indexes used by the dashboard aggregation queries.
"""

from __future__ import annotations

from alembic import op

revision = "002_dashboard_indexes"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_exec_status_created
        ON executions (status, created_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_exec_created_status
        ON executions (created_at DESC, status)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_exec_failed_created
        ON executions (created_at DESC)
        WHERE status IN ('FAILED', 'TIMED_OUT')
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fv_created
        ON function_versions (created_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_exec_fn_status
        ON executions (function_id, status, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_exec_status_created")
    op.execute("DROP INDEX IF EXISTS ix_exec_created_status")
    op.execute("DROP INDEX IF EXISTS ix_exec_failed_created")
    op.execute("DROP INDEX IF EXISTS ix_fv_created")
    op.execute("DROP INDEX IF EXISTS ix_exec_fn_status")
