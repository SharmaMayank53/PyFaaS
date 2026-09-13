"""
SOPM - API Schemas (Pydantic v2)

All request/response models. Strict validation on all inputs.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from shared.db.models import ExecutionStatus, FunctionStatus, ScheduleStatus

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$")
CRON_PARTS = 5


class SOPMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class UserRegisterRequest(SOPMBase):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLoginRequest(SOPMBase):
    username: str
    password: str


class TokenResponse(SOPMBase):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshTokenRequest(SOPMBase):
    refresh_token: str


class UserResponse(SOPMBase):
    id: uuid.UUID
    username: str
    email: str
    is_active: bool
    is_superuser: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


class FunctionCreateRequest(SOPMBase):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(None, max_length=1024)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not FUNCTION_NAME_RE.match(v):
            raise ValueError(
                "Function name must start with a letter and contain only "
                "letters, numbers, hyphens, and underscores"
            )
        return v


class FunctionUpdateRequest(SOPMBase):
    description: str | None = Field(None, max_length=1024)
    status: FunctionStatus | None = None
    tags: dict[str, str] | None = None


class FunctionResponse(SOPMBase):
    id: uuid.UUID
    name: str
    description: str | None
    runtime: str
    status: FunctionStatus
    active_version_id: uuid.UUID | None
    canary_version_id: uuid.UUID | None = None
    canary_percent: int = 0
    tags: dict[str, Any]
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    active_version: "FunctionVersionResponse | None" = None
    canary_version: "FunctionVersionResponse | None" = None


class FunctionListResponse(SOPMBase):
    items: list[FunctionResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Function Versions
# ---------------------------------------------------------------------------


class FunctionVersionCreateRequest(SOPMBase):
    entrypoint: str = Field(
        default="handler.handler",
        description="module.function path, e.g. 'handler.handler'",
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*\.[a-zA-Z_][a-zA-Z0-9_]*$",
    )
    environment: dict[str, str] = Field(default_factory=dict, max_length=50)
    timeout: int = Field(default=300, ge=1, le=3600)
    memory_mb: int = Field(default=128, ge=64, le=3072)
    change_notes: str | None = Field(None, max_length=512)

    @field_validator("environment")
    @classmethod
    def validate_env(cls, v: dict[str, str]) -> dict[str, str]:
        for key in v:
            if not re.match(r"^[A-Z_][A-Z0-9_]*$", key):
                raise ValueError(f"Environment variable key must be uppercase: {key}")
        return v


class FunctionVersionResponse(SOPMBase):
    id: uuid.UUID
    function_id: uuid.UUID
    version_number: int
    entrypoint: str
    artifact_path: str
    artifact_hash: str
    artifact_size: int
    environment: dict[str, Any]
    timeout: int
    memory_mb: int
    is_active: bool
    change_notes: str | None
    created_at: datetime


class FunctionVersionListResponse(SOPMBase):
    items: list[FunctionVersionResponse]
    total: int


class CanaryUpdateRequest(SOPMBase):
    canary_version_id: uuid.UUID | None = None
    canary_percent: int = Field(default=0, ge=0, le=100)


class VersionActivationResponse(SOPMBase):
    id: uuid.UUID
    function_id: uuid.UUID
    actor_id: uuid.UUID | None
    previous_version_id: uuid.UUID | None
    activated_version_id: uuid.UUID | None
    canary_version_id: uuid.UUID | None
    canary_percent: int
    action: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Executions
# ---------------------------------------------------------------------------


class ExecutionTriggerRequest(SOPMBase):
    payload: dict[str, Any] = Field(default_factory=dict)
    version_id: uuid.UUID | None = Field(
        None, description="Specific version to run; defaults to active version"
    )
    timeout: int | None = Field(None, ge=1, le=3600)

    @field_validator("payload")
    @classmethod
    def validate_payload_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        import json

        raw = json.dumps(v)
        if len(raw.encode()) > 1_048_576:
            raise ValueError("Payload must not exceed 1 MB")
        return v


class ExecutionResponse(SOPMBase):
    id: uuid.UUID
    function_id: uuid.UUID | None
    function_version_id: uuid.UUID | None
    execution_type: str = "function"
    status: ExecutionStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    failure_kind: str | None = None
    worker_id: str | None
    k8s_job_name: str | None
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    attempt_number: int
    timeout: int
    created_at: datetime


class ExecutionListResponse(SOPMBase):
    items: list[ExecutionResponse]
    total: int
    page: int
    page_size: int


class ExecutionLogEntry(SOPMBase):
    id: uuid.UUID
    timestamp: datetime
    level: str
    stream: str
    message: str
    sequence: int


class ExecutionLogResponse(SOPMBase):
    execution_id: uuid.UUID
    logs: list[ExecutionLogEntry]
    total: int


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


class ScheduleCreateRequest(SOPMBase):
    name: str = Field(..., min_length=1, max_length=128)
    cron_expression: str = Field(..., description="Standard 5-part cron expression")
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        from croniter import CroniterBadCronError, croniter

        try:
            croniter(v)
        except (CroniterBadCronError, ValueError) as exc:
            raise ValueError(f"Invalid cron expression: {exc}") from exc
        parts = v.strip().split()
        if len(parts) != CRON_PARTS:
            raise ValueError("Cron expression must have exactly 5 parts")
        return v


class ScheduleUpdateRequest(SOPMBase):
    name: str | None = Field(None, min_length=1, max_length=128)
    cron_expression: str | None = None
    payload: dict[str, Any] | None = None
    status: ScheduleStatus | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from croniter import CroniterBadCronError, croniter

        try:
            croniter(v)
        except (CroniterBadCronError, ValueError) as exc:
            raise ValueError(f"Invalid cron expression: {exc}") from exc
        return v


class ScheduleResponse(SOPMBase):
    id: uuid.UUID
    function_id: uuid.UUID
    name: str
    cron_expression: str
    payload: dict[str, Any]
    status: ScheduleStatus
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScheduleListResponse(SOPMBase):
    items: list[ScheduleResponse]
    total: int


# ---------------------------------------------------------------------------
# Health / Platform
# ---------------------------------------------------------------------------


class HealthStatus(SOPMBase):
    status: str  # "healthy" | "degraded" | "unhealthy"
    version: str
    checks: dict[str, str]
    timestamp: datetime


class ErrorResponse(SOPMBase):
    error: str
    detail: str | None = None
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------


class PaginationParams(SOPMBase):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

