"""
SOPM - Scheduler

Polls PostgreSQL for schedules whose next_run_at <= now(),
creates Execution records, and enqueues them on Redis.

Uses a distributed lock to ensure only one scheduler instance
fires a given schedule at a time (safe to run multiple replicas).
"""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from typing import cast

from croniter import croniter
from sqlalchemy import select

from shared.config import get_settings
from shared.db.models import Execution, ExecutionStatus, Schedule, ScheduleStatus
from shared.db.session import get_db_context
from shared.execution.version_routing import choose_execution_version
from shared.observability.logging import configure_logging, get_logger
from shared.queue.redis_client import DistributedLock, enqueue_job, get_redis

settings = get_settings()
configure_logging()
logger = get_logger(__name__)

SCHEDULER_LOCK = "sopm:scheduler:lock"
SCHEDULER_LOCK_TTL = settings.scheduler_poll_interval * 2


class Scheduler:
    def __init__(self) -> None:
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        logger.info("scheduler_started", poll_interval=settings.scheduler_poll_interval)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown.set)

        while not self._shutdown.is_set():
            try:
                await self._tick()
            except Exception as exc:
                logger.error("scheduler_tick_error", error=str(exc), exc_info=True)

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=settings.scheduler_poll_interval,
                )
            except TimeoutError:
                pass

        logger.info("scheduler_stopped")

    async def _tick(self) -> None:
        redis = get_redis()
        try:
            async with DistributedLock(
                redis, SCHEDULER_LOCK, timeout=SCHEDULER_LOCK_TTL
            ) as acquired:
                if not acquired:
                    logger.debug("scheduler_lock_not_acquired")
                    return
                await self._process_due_schedules()
        finally:
            await redis.aclose()

    async def _process_due_schedules(self) -> None:
        now = datetime.now(UTC)

        async with get_db_context() as db:
            result = await db.execute(
                select(Schedule).where(
                    Schedule.status == ScheduleStatus.ACTIVE,
                    Schedule.next_run_at <= now,
                )
            )
            due_schedules = result.scalars().all()

        if not due_schedules:
            return

        logger.info("scheduler_processing_due", count=len(due_schedules))

        for schedule in due_schedules:
            try:
                await self._fire_schedule(schedule)
            except Exception as exc:
                logger.error(
                    "schedule_fire_error",
                    schedule_id=str(schedule.id),
                    error=str(exc),
                    exc_info=True,
                )

    async def _fire_schedule(self, schedule: Schedule) -> None:
        now = datetime.now(UTC)

        async with get_db_context() as db:
            # Re-fetch with lock to prevent double-firing
            result = await db.execute(select(Schedule).where(Schedule.id == schedule.id))
            fresh = result.scalar_one_or_none()
            if fresh is None or fresh.status != ScheduleStatus.ACTIVE:
                return
            if fresh.next_run_at is None or fresh.next_run_at > now:
                return

            # Load function version
            from shared.db.models import Function

            fn_result = await db.execute(select(Function).where(Function.id == fresh.function_id))
            fn = fn_result.scalar_one_or_none()
            if fn is None:
                logger.warning(
                    "schedule_no_active_version",
                    schedule_id=str(schedule.id),
                    function_id=str(schedule.function_id),
                )
                # Advance next_run_at anyway to avoid infinite re-fire
                fresh.next_run_at = _compute_next(fresh.cron_expression, now)
                await db.flush()
                return

            version = await choose_execution_version(db, fn)
            if version is None:
                fresh.next_run_at = _compute_next(fresh.cron_expression, now)
                await db.flush()
                return

            # Check missed run limit
            if fresh.next_run_at < now:
                gap = (now - fresh.next_run_at).total_seconds()
                if gap > settings.scheduler_poll_interval * settings.scheduler_max_missed_runs:
                    logger.warning(
                        "schedule_missed_run_skipped",
                        schedule_id=str(fresh.id),
                        gap_seconds=gap,
                    )
                    fresh.next_run_at = _compute_next(fresh.cron_expression, now)
                    await db.flush()
                    return

            # Create execution
            execution = Execution(
                function_id=fn.id,
                function_version_id=version.id,
                schedule_id=fresh.id,
                status=ExecutionStatus.QUEUED,
                payload=fresh.payload,
                queued_at=now,
                timeout=version.timeout,
            )
            db.add(execution)
            await db.commit()
            await db.refresh(execution)

            # Enqueue
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
                        "payload": fresh.payload,
                        "timeout": version.timeout,
                        "environment": version.environment,
                        "memory_mb": version.memory_mb,
                    },
                )
            except Exception as exc:
                logger.error(
                    "schedule_enqueue_failed",
                    schedule_id=str(fresh.id),
                    error=str(exc),
                )
                execution.status = ExecutionStatus.FAILED
                execution.error_message = str(exc)
                execution.failure_kind = "queue"
            finally:
                await redis.aclose()

            # Update schedule state
            fresh.last_run_at = now
            fresh.last_execution_id = execution.id
            fresh.next_run_at = _compute_next(fresh.cron_expression, now)
            fresh.missed_runs = 0

            await db.flush()

        logger.info(
            "schedule_fired",
            schedule_id=str(schedule.id),
            execution_id=str(execution.id),
            next_run_at=str(fresh.next_run_at),
        )


def _compute_next(cron_expr: str, base: datetime) -> datetime:
    return cast(datetime, croniter(cron_expr, base).get_next(datetime))


if __name__ == "__main__":
    asyncio.run(Scheduler().run())
