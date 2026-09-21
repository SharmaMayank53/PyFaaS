"""External API-key invocation routes."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.dependencies.api_keys import ApiKeyPrincipal, get_api_key_principal
from api.schemas.schemas import (
    ExecutionLogResponse,
    ExecutionResponse,
    FunctionListResponse,
    FunctionResponse,
)
from shared.db.models import Execution, ExecutionLog, ExecutionStatus, Function
from shared.db.session import get_db
from shared.execution.version_routing import choose_execution_version
from shared.queue.redis_client import enqueue_job, get_redis

router = APIRouter(prefix="/invoke", tags=["Invoke"])


class InvokeRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


TERMINAL_STATUSES = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.CANCELLED,
}


def _api_key_execution_owner_clause(principal: ApiKeyPrincipal) -> ColumnElement[bool]:
    return or_(
        Execution.api_key_id == principal.key.id, Execution.triggered_by == principal.user.id
    )


@router.get("/functions", response_model=FunctionListResponse)
async def list_invokable_functions(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[ApiKeyPrincipal, Depends(get_api_key_principal)],
) -> FunctionListResponse:
    result = await db.execute(
        select(Function)
        .where(Function.owner_id == principal.user.id)
        .order_by(Function.created_at.desc())
    )
    items = result.scalars().all()
    return FunctionListResponse(
        items=[FunctionResponse.model_validate(item) for item in items],
        total=len(items),
        page=1,
        page_size=len(items),
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
async def get_invoked_execution(
    execution_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[ApiKeyPrincipal, Depends(get_api_key_principal)],
) -> ExecutionResponse:
    result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id,
            _api_key_execution_owner_clause(principal),
        )
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return ExecutionResponse.model_validate(execution)


@router.get("/executions/{execution_id}/logs", response_model=ExecutionLogResponse)
async def get_invoked_execution_logs(
    execution_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[ApiKeyPrincipal, Depends(get_api_key_principal)],
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> ExecutionLogResponse:
    exec_result = await db.execute(
        select(Execution).where(
            Execution.id == execution_id,
            _api_key_execution_owner_clause(principal),
        )
    )
    if exec_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    total = (
        await db.execute(
            select(func.count())
            .select_from(ExecutionLog)
            .where(ExecutionLog.execution_id == execution_id)
        )
    ).scalar_one()
    logs = (
        (
            await db.execute(
                select(ExecutionLog)
                .where(ExecutionLog.execution_id == execution_id)
                .order_by(ExecutionLog.sequence.asc(), ExecutionLog.timestamp.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ExecutionLogResponse(
        execution_id=execution_id,
        logs=[
            {
                "id": log.id,
                "timestamp": log.timestamp,
                "level": log.level,
                "stream": log.stream,
                "message": log.message,
                "sequence": log.sequence,
            }
            for log in logs
        ],
        total=total,
    )


@router.post(
    "/{function_id}", response_model=ExecutionResponse, status_code=status.HTTP_202_ACCEPTED
)
async def invoke_function(
    function_id: uuid.UUID,
    body: InvokeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[ApiKeyPrincipal, Depends(get_api_key_principal)],
    wait: bool = Query(False),
    wait_timeout: float = Query(2.0, ge=0.1, le=10.0),
) -> ExecutionResponse:
    current_user = principal.user
    result = await db.execute(
        select(Function).where(Function.id == function_id, Function.owner_id == current_user.id)
    )
    fn = result.scalar_one_or_none()
    if fn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Function not found")
    version = await choose_execution_version(db, fn)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Function has no executable version",
        )

    execution = Execution(
        function_id=fn.id,
        function_version_id=version.id,
        triggered_by=current_user.id,
        api_key_id=principal.key.id,
        execution_type="function",
        status=ExecutionStatus.QUEUED,
        payload=body.payload,
        queued_at=datetime.now(UTC),
        timeout=version.timeout,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    redis = get_redis()
    try:
        await enqueue_job(
            redis,
            str(execution.id),
            {
                "execution_id": str(execution.id),
                "function_id": str(fn.id),
                "version_id": str(version.id),
                "artifact_path": version.artifact_path,
                "entrypoint": version.entrypoint,
                "payload": body.payload,
                "timeout": version.timeout,
                "environment": version.environment,
                "memory_mb": version.memory_mb,
                "execution_type": "function",
            },
        )
    except Exception as exc:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = f"Failed to enqueue: {exc}"
        execution.failure_kind = "queue"
        await db.commit()
        await db.refresh(execution)
    finally:
        await redis.aclose()

    if wait:
        deadline = asyncio.get_running_loop().time() + wait_timeout
        while asyncio.get_running_loop().time() < deadline:
            await db.refresh(execution)
            if execution.status in TERMINAL_STATUSES:
                break
            await asyncio.sleep(0.1)

    return ExecutionResponse.model_validate(execution)
