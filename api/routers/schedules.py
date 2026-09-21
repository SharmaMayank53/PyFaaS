"""
SOPM - Schedules Router
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, cast

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.deps import get_current_user, pagination_params
from api.schemas.schemas import (
    ScheduleCreateRequest,
    ScheduleListResponse,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from shared.db.models import Function, Schedule, User
from shared.db.session import get_db
from shared.observability.logging import get_logger

router = APIRouter(prefix="/schedules", tags=["Schedules"])
logger = get_logger(__name__)


def _next_run(cron_expr: str) -> datetime:
    return cast(datetime, croniter(cron_expr, datetime.now(UTC)).get_next(datetime))


@router.get("", response_model=ScheduleListResponse, summary="List schedules")
async def list_schedules(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[tuple[int, int], Depends(pagination_params)],
) -> ScheduleListResponse:
    offset, limit = pagination

    total = (
        await db.execute(
            select(func.count()).select_from(Schedule).where(Schedule.owner_id == current_user.id)
        )
    ).scalar_one()

    schedules = (
        (
            await db.execute(
                select(Schedule)
                .where(Schedule.owner_id == current_user.id)
                .order_by(Schedule.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    return ScheduleListResponse(
        items=[ScheduleResponse.model_validate(s) for s in schedules],
        total=total,
    )


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a schedule",
)
async def create_schedule(
    body: ScheduleCreateRequest,
    function_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ScheduleResponse:
    fn_result = await db.execute(
        select(Function).where(
            Function.id == function_id,
            Function.owner_id == current_user.id,
        )
    )
    if fn_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Function not found")

    schedule = Schedule(
        function_id=function_id,
        owner_id=current_user.id,
        name=body.name,
        cron_expression=body.cron_expression,
        payload=body.payload,
        next_run_at=_next_run(body.cron_expression),
    )
    db.add(schedule)
    await db.flush()
    await db.refresh(schedule)
    logger.info("schedule_created", schedule_id=str(schedule.id), cron=body.cron_expression)
    return ScheduleResponse.model_validate(schedule)


@router.get("/{schedule_id}", response_model=ScheduleResponse, summary="Get schedule")
async def get_schedule(
    schedule_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ScheduleResponse:
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id, Schedule.owner_id == current_user.id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return ScheduleResponse.model_validate(s)


@router.patch("/{schedule_id}", response_model=ScheduleResponse, summary="Update schedule")
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ScheduleResponse:
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id, Schedule.owner_id == current_user.id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")

    if body.name is not None:
        s.name = body.name
    if body.cron_expression is not None:
        s.cron_expression = body.cron_expression
        s.next_run_at = _next_run(body.cron_expression)
    if body.payload is not None:
        s.payload = body.payload
    if body.status is not None:
        s.status = body.status

    await db.flush()
    await db.refresh(s)
    return ScheduleResponse.model_validate(s)


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete schedule",
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    result = await db.execute(
        select(Schedule).where(Schedule.id == schedule_id, Schedule.owner_id == current_user.id)
    )
    s = result.scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    await db.delete(s)
    logger.info("schedule_deleted", schedule_id=str(schedule_id))
