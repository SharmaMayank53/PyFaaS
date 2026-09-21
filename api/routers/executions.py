"""
SOPM - Executions Router

Endpoints: POST /functions/{id}/execute, GET /executions, GET /executions/{id},
           GET /executions/{id}/logs, DELETE /executions/{id} (cancel)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from api.dependencies.deps import get_current_user, pagination_params
from api.schemas.schemas import (
    ExecutionListResponse,
    ExecutionLogResponse,
    ExecutionResponse,
    ExecutionTriggerRequest,
)
from shared.db.models import (
    Execution,
    ExecutionLog,
    ExecutionStatus,
    Function,
    User,
)
from shared.db.session import get_db
from shared.execution.version_routing import choose_execution_version
from shared.observability.logging import get_logger
from shared.observability.metrics import EXECUTIONS_TOTAL
from shared.queue.redis_client import enqueue_job, get_redis

router = APIRouter(tags=["Executions"])
logger = get_logger(__name__)

TERMINAL_STATUSES = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.CANCELLED,
}


def _execution_owner_clause(current_user: User) -> ColumnElement[bool]:
    return or_(Function.owner_id == current_user.id, Execution.triggered_by == current_user.id)


@router.post(
    "/functions/{function_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a function execution",
)
async def trigger_execution(
    function_id: uuid.UUID,
    body: ExecutionTriggerRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ExecutionResponse:
    result = await db.execute(
        select(Function).where(
            Function.id == function_id,
            Function.owner_id == current_user.id,
        )
    )
    fn = result.scalar_one_or_none()
    if fn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Function not found")

    version = await choose_execution_version(db, fn, body.version_id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Function has no executable version; upload or activate a version first",
        )

    timeout = body.timeout or version.timeout

    execution = Execution(
        function_id=fn.id,
        function_version_id=version.id,
        triggered_by=current_user.id,
        execution_type="function",
        status=ExecutionStatus.QUEUED,
        payload=body.payload,
        queued_at=datetime.now(UTC),
        timeout=timeout,
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
                "timeout": timeout,
                "environment": version.environment,
                "memory_mb": version.memory_mb,
                "execution_type": "function",
            },
        )
    except Exception as exc:
        logger.error("enqueue_failed", execution_id=str(execution.id), error=str(exc))
        execution.status = ExecutionStatus.FAILED
        execution.error_message = f"Failed to enqueue: {exc}"
        execution.failure_kind = "queue"
        await db.commit()
        await db.refresh(execution)
    finally:
        await redis.aclose()

    EXECUTIONS_TOTAL.labels(status=execution.status.value, runtime="python3.12").inc()
    logger.info(
        "execution_triggered",
        execution_id=str(execution.id),
        function_id=str(function_id),
        status=execution.status.value,
    )
    return ExecutionResponse.model_validate(execution)


@router.get(
    "/executions",
    response_model=ExecutionListResponse,
    summary="List executions for the current user",
)
async def list_executions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[tuple[int, int], Depends(pagination_params)],
    function_id: uuid.UUID | None = Query(None),
    execution_status: ExecutionStatus | None = Query(None, alias="status"),
    failure_kind: str | None = Query(None),
    source: Literal["function", "ephemeral"] | None = Query(None),
) -> ExecutionListResponse:
    offset, limit = pagination
    page = offset // limit + 1

    base = (
        select(Execution)
        .outerjoin(Function, Execution.function_id == Function.id)
        .where(_execution_owner_clause(current_user))
    )
    count_base = (
        select(func.count())
        .select_from(Execution)
        .outerjoin(Function, Execution.function_id == Function.id)
        .where(_execution_owner_clause(current_user))
    )

    if function_id:
        base = base.where(Execution.function_id == function_id)
        count_base = count_base.where(Execution.function_id == function_id)
    if execution_status:
        base = base.where(Execution.status == execution_status)
        count_base = count_base.where(Execution.status == execution_status)
    if failure_kind:
        kinds = [kind.strip() for kind in failure_kind.split(",") if kind.strip()]
        if kinds:
            base = base.where(Execution.failure_kind.in_(kinds))
            count_base = count_base.where(Execution.failure_kind.in_(kinds))
    if source:
        base = base.where(Execution.execution_type == source)
        count_base = count_base.where(Execution.execution_type == source)

    total = (await db.execute(count_base)).scalar_one()
    executions = (
        (await db.execute(base.order_by(Execution.created_at.desc()).offset(offset).limit(limit)))
        .scalars()
        .all()
    )

    return ExecutionListResponse(
        items=[ExecutionResponse.model_validate(e) for e in executions],
        total=total,
        page=page,
        page_size=limit,
    )


@router.get(
    "/executions/{execution_id}",
    response_model=ExecutionResponse,
    summary="Get execution details",
)
async def get_execution(
    execution_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ExecutionResponse:
    result = await db.execute(
        select(Execution)
        .outerjoin(Function, Execution.function_id == Function.id)
        .where(Execution.id == execution_id, _execution_owner_clause(current_user))
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return ExecutionResponse.model_validate(execution)


@router.get(
    "/executions/{execution_id}/logs",
    response_model=ExecutionLogResponse,
    summary="Get execution logs",
)
async def get_execution_logs(
    execution_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> ExecutionLogResponse:
    exec_result = await db.execute(
        select(Execution)
        .outerjoin(Function, Execution.function_id == Function.id)
        .where(Execution.id == execution_id, _execution_owner_clause(current_user))
    )
    if exec_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    count_result = await db.execute(
        select(func.count())
        .select_from(ExecutionLog)
        .where(ExecutionLog.execution_id == execution_id)
    )
    total = count_result.scalar_one()

    logs_result = await db.execute(
        select(ExecutionLog)
        .where(ExecutionLog.execution_id == execution_id)
        .order_by(ExecutionLog.sequence.asc(), ExecutionLog.timestamp.asc())
        .offset(offset)
        .limit(limit)
    )
    logs = logs_result.scalars().all()

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


@router.delete(
    "/executions/{execution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a pending or queued execution",
)
async def cancel_execution(
    execution_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    result = await db.execute(
        select(Execution)
        .outerjoin(Function, Execution.function_id == Function.id)
        .where(Execution.id == execution_id, _execution_owner_clause(current_user))
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")

    try:
        execution.transition_to(ExecutionStatus.CANCELLED)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    logger.info("execution_cancelled", execution_id=str(execution_id))
