"""
SOPM - Worker

Pulls execution jobs from Redis queue, dispatches to Kubernetes sandbox,
enforces timeouts, reports results back to PostgreSQL.

Design principles:
- Stateless: each worker instance is identical
- Isolated: one failing job never crashes the worker
- Graceful: handles SIGTERM/SIGINT cleanly
"""
from __future__ import annotations

import asyncio
import signal
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from sandbox.k8s_sandbox import KubernetesSandbox, SandboxResult
from shared.config import get_settings
from shared.db.models import Execution, ExecutionLog, ExecutionStatus
from shared.db.session import get_db_context
from shared.observability.logging import configure_logging, get_logger
from shared.observability.metrics import (
    EXECUTIONS_TOTAL,
    EXECUTION_DURATION_SECONDS,
    EXECUTION_ERRORS_TOTAL,
    QUEUE_DEPTH,
    WORKER_ACTIVE,
    WORKER_JOBS_PROCESSED_TOTAL,
)
from shared.queue.redis_client import (
    ack_job,
    dequeue_job,
    get_redis,
    heartbeat,
    queue_depth,
)

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


class Worker:
    """
    Single-threaded async worker that polls the queue and processes jobs.

    Multiple Worker instances run concurrently within one process (controlled
    by WORKER_CONCURRENCY), each as a separate asyncio task.
    """

    def __init__(self, worker_id: str) -> None:
        self._id = worker_id
        self._shutdown = asyncio.Event()
        self._sandbox = KubernetesSandbox()

    async def run(self) -> None:
        logger.info("worker_started", worker_id=self._id)
        WORKER_ACTIVE.inc()

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        recovery_task = (
            asyncio.create_task(self._stale_recovery_loop())
            if self._id.endswith("-0")
            else None
        )

        try:
            while not self._shutdown.is_set():
                try:
                    await self._poll_once()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("worker_poll_error", worker_id=self._id, error=str(exc))
                    await asyncio.sleep(5)
        finally:
            heartbeat_task.cancel()
            if recovery_task is not None:
                recovery_task.cancel()
            WORKER_ACTIVE.dec()
            logger.info("worker_stopped", worker_id=self._id)

    async def _poll_once(self) -> None:
        redis = get_redis()
        try:
            job = await dequeue_job(redis, timeout=max(1, settings.worker_queue_poll_interval))
            if job is None:
                return

            # Update queue depth metric
            depth = await queue_depth(redis)
            QUEUE_DEPTH.set(depth)

            await self._process_job(job)
            await ack_job(redis, job["job_id"])
        finally:
            await redis.aclose()

    async def _process_job(self, job: dict[str, Any]) -> None:
        execution_id = job["job_id"]
        logger.info("job_started", worker_id=self._id, execution_id=execution_id)

        start_time = time.monotonic()

        async with get_db_context() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(Execution).where(Execution.id == uuid.UUID(execution_id))
            )
            execution = result.scalar_one_or_none()

            if execution is None:
                logger.warning("execution_not_found", execution_id=execution_id)
                return

            if execution.status == ExecutionStatus.CANCELLED:
                logger.info("execution_already_cancelled", execution_id=execution_id)
                return

            # Transition to RUNNING
            try:
                execution.transition_to(ExecutionStatus.RUNNING)
            except ValueError as exc:
                logger.warning(
                    "invalid_transition",
                    execution_id=execution_id,
                    error=str(exc),
                )
                return

            execution.started_at = datetime.now(timezone.utc)
            execution.worker_id = self._id
            await db.flush()

        # Execute in sandbox (outside the DB transaction to avoid long locks)
        sandbox_result: SandboxResult | None = None
        try:
            sandbox_result = await asyncio.wait_for(
                self._sandbox.execute(job),
                timeout=job.get("timeout", settings.sandbox_default_timeout) + 30,
            )
        except asyncio.TimeoutError:
            sandbox_result = SandboxResult(
                success=False,
                error="Execution timed out (worker timeout)",
                logs=[],
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        except Exception as exc:
            logger.error(
                "sandbox_error",
                execution_id=execution_id,
                error=str(exc),
                exc_info=True,
            )
            sandbox_result = SandboxResult(
                success=False,
                error=f"Sandbox error: {exc}",
                logs=[],
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )

        duration_ms = sandbox_result.duration_ms or int((time.monotonic() - start_time) * 1000)

        # Write results back
        async with get_db_context() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(Execution).where(Execution.id == uuid.UUID(execution_id))
            )
            execution = result.scalar_one_or_none()
            if execution is None:
                return

            new_status = (
                ExecutionStatus.COMPLETED if sandbox_result.success else ExecutionStatus.FAILED
            )

            # Handle timeout specifically
            if sandbox_result.timed_out:
                new_status = ExecutionStatus.TIMED_OUT

            try:
                execution.transition_to(new_status)
            except ValueError:
                pass  # Already in terminal state — skip

            execution.completed_at = datetime.now(timezone.utc)
            execution.duration_ms = duration_ms
            execution.result = sandbox_result.result
            execution.error_message = sandbox_result.error
            if sandbox_result.success:
                execution.failure_kind = None
            elif sandbox_result.error and ("Sandbox error" in sandbox_result.error or "Kubernetes API" in sandbox_result.error or "worker timeout" in sandbox_result.error):
                execution.failure_kind = "infra"
            else:
                execution.failure_kind = "handler"
            execution.k8s_job_name = sandbox_result.k8s_job_name

            # Persist logs
            for seq, log_entry in enumerate(sandbox_result.logs):
                log = ExecutionLog(
                    execution_id=execution.id,
                    level=log_entry.get("level", "INFO"),
                    stream=log_entry.get("stream", "stdout"),
                    message=log_entry.get("message", ""),
                    sequence=seq,
                )
                db.add(log)

            await db.flush()

        # Metrics
        runtime = "python3.12"
        EXECUTIONS_TOTAL.labels(status=new_status.value, runtime=runtime).inc()
        EXECUTION_DURATION_SECONDS.labels(runtime=runtime).observe(duration_ms / 1000)
        WORKER_JOBS_PROCESSED_TOTAL.labels(
            worker_id=self._id,
            outcome="success" if sandbox_result.success else "failure",
        ).inc()
        if not sandbox_result.success:
            EXECUTION_ERRORS_TOTAL.labels(error_type=new_status.value).inc()

        logger.info(
            "job_completed",
            worker_id=self._id,
            execution_id=execution_id,
            status=new_status.value,
            duration_ms=duration_ms,
        )


    async def _stale_recovery_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                recovered = await self._recover_stale_running_executions()
                if recovered:
                    logger.warning("stale_execution_recovery_completed", worker_id=self._id, recovered=recovered)
            except Exception as exc:
                logger.error("stale_execution_recovery_error", worker_id=self._id, error=str(exc))
            await asyncio.sleep(settings.worker_stale_recovery_interval)

    async def _recover_stale_running_executions(self) -> int:
        from sqlalchemy import select

        now = datetime.now(timezone.utc)
        recovered = 0
        async with get_db_context() as db:
            result = await db.execute(
                select(Execution).where(
                    Execution.status == ExecutionStatus.RUNNING,
                    Execution.started_at.is_not(None),
                )
            )
            for execution in result.scalars().all():
                timeout_seconds = max(1, execution.timeout) * 2 + settings.worker_stale_timeout_grace
                if execution.started_at and execution.started_at > now - timedelta(seconds=timeout_seconds):
                    continue

                try:
                    execution.transition_to(ExecutionStatus.FAILED)
                except ValueError:
                    continue

                execution.completed_at = now
                execution.failure_kind = "infra"
                execution.error_message = "Worker did not report completion before stale recovery deadline"
                if execution.started_at:
                    execution.duration_ms = int((now - execution.started_at).total_seconds() * 1000)
                db.add(
                    ExecutionLog(
                        execution_id=execution.id,
                        level="ERROR",
                        stream="system",
                        message="Stale execution recovered: worker did not report completion",
                        sequence=0,
                    )
                )
                recovered += 1
                EXECUTIONS_TOTAL.labels(status=ExecutionStatus.FAILED.value, runtime="python3.12").inc()
                EXECUTION_ERRORS_TOTAL.labels(error_type="stale_recovery").inc()
                logger.warning(
                    "stale_execution_recovered",
                    execution_id=str(execution.id),
                    worker_id=execution.worker_id,
                    timeout=execution.timeout,
                )
            await db.flush()
        return recovered
    async def _heartbeat_loop(self) -> None:
        redis = get_redis()
        try:
            while not self._shutdown.is_set():
                try:
                    await heartbeat(redis, self._id)
                except Exception:
                    pass
                await asyncio.sleep(settings.worker_heartbeat_interval)
        finally:
            await redis.aclose()

    def request_shutdown(self) -> None:
        self._shutdown.set()


async def run_workers() -> None:
    """Launch WORKER_CONCURRENCY workers and handle graceful shutdown."""
    worker_ids = [
        f"{settings.worker_id}-{i}" for i in range(settings.worker_concurrency)
    ]
    workers = [Worker(wid) for wid in worker_ids]

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("shutdown_signal_received")
        for w in workers:
            w.request_shutdown()
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    tasks = [asyncio.create_task(w.run()) for w in workers]

    logger.info("workers_launched", count=settings.worker_concurrency)

    await shutdown_event.wait()
    logger.info("waiting_for_workers_to_finish")

    # Give workers up to WORKER_SHUTDOWN_TIMEOUT seconds to finish current jobs
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=settings.worker_shutdown_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("worker_shutdown_timeout_exceeded")
        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(run_workers())

