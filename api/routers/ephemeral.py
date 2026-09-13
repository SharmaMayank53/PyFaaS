"""Ephemeral raw-code execution endpoint for agent-facing use cases."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.api_keys import ApiKeyPrincipal, get_api_key_principal
from api.schemas.schemas import ExecutionResponse, SOPMBase
from shared.config import get_settings
from shared.db.models import Execution, ExecutionStatus
from shared.db.session import get_db
from shared.observability.logging import get_logger
from shared.queue.redis_client import enqueue_job, get_redis

router = APIRouter(tags=["Ephemeral Execution"])
settings = get_settings()
logger = get_logger(__name__)

TERMINAL_STATUSES = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.CANCELLED,
}
ACTIVE_STATUSES = {ExecutionStatus.PENDING, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING}


class EphemeralExecutionRequest(SOPMBase):
    code: str = Field(..., min_length=1)
    entrypoint: str = Field(
        default="handler.handler",
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_.]*\.[a-zA-Z_][a-zA-Z0-9_]*$",
    )
    event: dict[str, Any] = Field(default_factory=dict)
    timeout: int = Field(default=30, ge=1, le=300)
    memory_mb: int = Field(default=128, ge=64, le=1024)

    @field_validator("code")
    @classmethod
    def validate_code_size(cls, value: str) -> str:
        max_bytes = settings.ephemeral_max_code_bytes
        if len(value.encode("utf-8")) > max_bytes:
            raise ValueError(f"Code must not exceed {max_bytes} bytes")
        return value

    @field_validator("event")
    @classmethod
    def validate_event_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        import json

        raw = json.dumps(value)
        if len(raw.encode("utf-8")) > settings.max_payload_size_bytes:
            raise ValueError("Event payload must not exceed 1 MB")
        return value


async def _enforce_ephemeral_gate() -> None:
    if settings.sandbox_enabled:
        return
    if settings.ephemeral_local_execution_enabled:
        logger.warning(
            "ephemeral_local_execution_enabled",
            message="SANDBOX_ENABLED=false and EPHEMERAL_LOCAL_EXECUTION_ENABLED=true; raw code runs in the worker container.",
        )
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Ephemeral raw-code execution requires SANDBOX_ENABLED=true. "
            "For local-only testing set EPHEMERAL_LOCAL_EXECUTION_ENABLED=true, but do not use that mode for untrusted code."
        ),
    )


async def _enforce_rate_limits(
    db: AsyncSession,
    redis: Any,
    principal: ApiKeyPrincipal,
) -> None:
    rate_key = f"sopm:ephemeral:rate:{principal.key.id}:{datetime.now(timezone.utc):%Y%m%d%H%M}"
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, 120)
    if count > settings.ephemeral_rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Ephemeral execution rate limit exceeded ({settings.ephemeral_rate_limit_per_minute}/minute)",
        )

    active_count = (
        await db.execute(
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.api_key_id == principal.key.id,
                Execution.execution_type == "ephemeral",
                Execution.status.in_(ACTIVE_STATUSES),
            )
        )
    ).scalar_one()
    if active_count >= settings.ephemeral_concurrency_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Ephemeral execution concurrency limit exceeded ({settings.ephemeral_concurrency_limit})",
        )


@router.post("/execute-ephemeral", response_model=ExecutionResponse, status_code=status.HTTP_202_ACCEPTED)
async def execute_ephemeral(
    body: EphemeralExecutionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[ApiKeyPrincipal, Depends(get_api_key_principal)],
    wait: bool = Query(False),
    wait_timeout: float = Query(2.0, ge=0.1, le=30.0),
) -> ExecutionResponse:
    await _enforce_ephemeral_gate()

    redis = get_redis()
    try:
        await _enforce_rate_limits(db, redis, principal)

        execution = Execution(
            function_id=None,
            function_version_id=None,
            triggered_by=principal.user.id,
            api_key_id=principal.key.id,
            execution_type="ephemeral",
            status=ExecutionStatus.QUEUED,
            payload=body.event,
            queued_at=datetime.now(timezone.utc),
            timeout=body.timeout,
        )
        db.add(execution)
        await db.commit()
        await db.refresh(execution)

        try:
            await enqueue_job(
                redis,
                str(execution.id),
                {
                    "execution_id": str(execution.id),
                    "function_id": "ephemeral",
                    "version_id": "ephemeral",
                    "entrypoint": body.entrypoint,
                    "payload": body.event,
                    "timeout": body.timeout,
                    "environment": {},
                    "memory_mb": body.memory_mb,
                    "execution_type": "ephemeral",
                    "source_code": body.code,
                },
            )
        except Exception as exc:
            execution.status = ExecutionStatus.FAILED
            execution.error_message = f"Failed to enqueue: {exc}"
            execution.failure_kind = "queue"
            await db.commit()
            await db.refresh(execution)

        if wait:
            deadline = asyncio.get_running_loop().time() + wait_timeout
            while asyncio.get_running_loop().time() < deadline:
                await db.refresh(execution)
                if execution.status in TERMINAL_STATUSES:
                    break
                await asyncio.sleep(0.1)

        return ExecutionResponse.model_validate(execution)
    finally:
        await redis.aclose()
