"""
SOPM - SQLAlchemy ORM Models

All tables defined here; never auto-created on startup.
Use Alembic for all schema changes.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Text as SAText
from sqlalchemy.types import TypeDecorator, TypeEngine


class JSONType(TypeDecorator[Any]):
    """
    Dialect-agnostic JSON column.

    Uses PostgreSQL JSONB in production; falls back to plain JSON
    (stored as text) in SQLite for testing.
    """

    impl = SAText
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if dialect.name != "postgresql" and value is not None:
            import json

            return json.dumps(value)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if dialect.name != "postgresql" and isinstance(value, str):
            import json

            return json.loads(value)
        return value


class UUIDType(TypeDecorator[Any]):
    """Dialect-agnostic UUID: native on PostgreSQL, TEXT on SQLite."""

    impl = SAText
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(SAText(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name != "postgresql":
            return str(value)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name != "postgresql":
            return uuid.UUID(str(value))
        return value


class Base(DeclarativeBase):
    """Shared base for all models."""

    type_annotation_map = {
        dict[str, Any]: JSONType,
    }


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ExecutionStatus(str, enum.Enum):  # noqa: UP042 - Preserve existing enum string representations.
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class FunctionStatus(str, enum.Enum):  # noqa: UP042 - Preserve existing enum string representations.
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class ScheduleStatus(str, enum.Enum):  # noqa: UP042 - Preserve existing enum string representations.
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.PENDING: {ExecutionStatus.QUEUED, ExecutionStatus.CANCELLED},
    ExecutionStatus.QUEUED: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.RUNNING: {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.TIMED_OUT: set(),
    ExecutionStatus.CANCELLED: set(),
}


def validate_transition(current: ExecutionStatus, next_state: ExecutionStatus) -> None:
    """Raise ValueError if the state transition is not allowed."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if next_state not in allowed:
        raise ValueError(
            f"Invalid state transition: {current} -> {next_state}. "
            f"Allowed: {allowed or 'none (terminal state)'}"
        )


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    functions: Mapped[list[Function]] = relationship(back_populates="owner", lazy="select")
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username}>"


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User] = relationship(back_populates="api_keys")
    executions: Mapped[list[Execution]] = relationship(
        foreign_keys="Execution.api_key_id", lazy="select"
    )

    __table_args__ = (Index("ix_api_key_owner_created", "owner_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<ApiKey id={self.id} owner_id={self.owner_id}>"


class Function(TimestampMixin, Base):
    __tablename__ = "functions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime: Mapped[str] = mapped_column(String(32), nullable=False, default="python3.12")
    status: Mapped[FunctionStatus] = mapped_column(
        Enum(FunctionStatus), nullable=False, default=FunctionStatus.ACTIVE
    )
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("function_versions.id", use_alter=True), nullable=True
    )
    canary_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("function_versions.id", use_alter=True), nullable=True
    )
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)

    owner: Mapped[User] = relationship(back_populates="functions")
    versions: Mapped[list[FunctionVersion]] = relationship(
        back_populates="function",
        foreign_keys="FunctionVersion.function_id",
        lazy="select",
    )
    active_version: Mapped[FunctionVersion | None] = relationship(
        foreign_keys=[active_version_id],
        primaryjoin="Function.active_version_id == FunctionVersion.id",
        lazy="select",
    )
    canary_version: Mapped[FunctionVersion | None] = relationship(
        foreign_keys=[canary_version_id],
        primaryjoin="Function.canary_version_id == FunctionVersion.id",
        lazy="select",
    )
    activations: Mapped[list[VersionActivation]] = relationship(
        back_populates="function", cascade="all, delete-orphan", lazy="select"
    )
    executions: Mapped[list[Execution]] = relationship(back_populates="function", lazy="select")
    schedules: Mapped[list[Schedule]] = relationship(back_populates="function", lazy="select")

    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_function_owner_name"),
        Index("ix_function_owner_id", "owner_id"),
        Index("ix_function_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Function id={self.id} name={self.name}>"


class VersionActivation(TimestampMixin, Base):
    __tablename__ = "version_activations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    function_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("functions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("function_versions.id", ondelete="SET NULL"), nullable=True
    )
    activated_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("function_versions.id", ondelete="SET NULL"), nullable=True
    )
    canary_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("function_versions.id", ondelete="SET NULL"), nullable=True
    )
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="activate")

    function: Mapped[Function] = relationship(
        back_populates="activations", foreign_keys=[function_id]
    )

    __table_args__ = (Index("ix_version_activation_function_created", "function_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<VersionActivation id={self.id} action={self.action}>"


class FunctionVersion(TimestampMixin, Base):
    __tablename__ = "function_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    function_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("functions.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(255), nullable=False, default="handler.handler")
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_size: Mapped[int] = mapped_column(Integer, nullable=False)
    environment: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    memory_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=128)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    change_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    function: Mapped[Function] = relationship(
        back_populates="versions",
        foreign_keys=[function_id],
    )
    executions: Mapped[list[Execution]] = relationship(
        back_populates="function_version", lazy="select"
    )

    __table_args__ = (
        UniqueConstraint("function_id", "version_number", name="uq_version_function_number"),
        Index("ix_function_version_function_id", "function_id"),
    )

    def __repr__(self) -> str:
        return f"<FunctionVersion id={self.id} version={self.version_number}>"


class Execution(TimestampMixin, Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    function_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("functions.id", ondelete="SET NULL"), nullable=True
    )
    function_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(),
        ForeignKey("function_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    execution_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="function", index=True
    )
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus), nullable=False, default=ExecutionStatus.PENDING, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    k8s_job_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout: Mapped[int] = mapped_column(Integer, nullable=False, default=300)

    function: Mapped[Function | None] = relationship(back_populates="executions")
    function_version: Mapped[FunctionVersion | None] = relationship(back_populates="executions")
    logs: Mapped[list[ExecutionLog]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", lazy="select"
    )
    schedule: Mapped[Schedule | None] = relationship(foreign_keys=[schedule_id])

    __table_args__ = (
        Index("ix_execution_function_id", "function_id"),
        Index("ix_execution_status", "status"),
        Index("ix_execution_created_at", "created_at"),
        Index("ix_execution_type_created_at", "execution_type", "created_at"),
        Index("ix_execution_api_key_status", "api_key_id", "status"),
    )

    def transition_to(self, new_status: ExecutionStatus) -> None:
        validate_transition(self.status, new_status)
        self.status = new_status

    def __repr__(self) -> str:
        return f"<Execution id={self.id} status={self.status}>"


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    stream: Mapped[str] = mapped_column(String(8), nullable=False, default="stdout")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    execution: Mapped[Execution] = relationship(back_populates="logs")

    __table_args__ = (Index("ix_execution_log_execution_timestamp", "execution_id", "timestamp"),)

    def __repr__(self) -> str:
        return f"<ExecutionLog id={self.id} level={self.level}>"


class Schedule(TimestampMixin, Base):
    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    function_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("functions.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType(), nullable=False, default=dict)
    status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus), nullable=False, default=ScheduleStatus.ACTIVE
    )
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType(), ForeignKey("executions.id", ondelete="SET NULL"), nullable=True
    )
    missed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    function: Mapped[Function] = relationship(back_populates="schedules")

    __table_args__ = (Index("ix_schedule_next_run_at", "next_run_at"),)

    def __repr__(self) -> str:
        return f"<Schedule id={self.id} cron={self.cron_expression}>"
