"""Tests for Worker job processing logic."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.db.models import Execution, ExecutionStatus
from sandbox.k8s_sandbox import SandboxResult


class TestWorkerProcessJob:
    """Test the Worker._process_job method in isolation."""

    def _make_job(self, execution_id: str) -> dict:
        return {
            "job_id": execution_id,
            "execution_id": execution_id,
            "function_id": str(uuid.uuid4()),
            "version_id": str(uuid.uuid4()),
            "artifact_path": "functions/abc/v1/source.zip",
            "entrypoint": "handler.handler",
            "payload": {"key": "value"},
            "timeout": 30,
            "environment": {},
            "memory_mb": 128,
        }

    async def test_process_successful_job(self, db_session) -> None:
        from worker.worker import Worker

        # Create a real execution in DB
        exec_id = uuid.uuid4()
        ex = Execution(
            id=exec_id,
            status=ExecutionStatus.QUEUED,
            payload={},
            timeout=30,
        )
        db_session.add(ex)
        await db_session.commit()

        sandbox_mock = AsyncMock()
        sandbox_mock.execute = AsyncMock(
            return_value=SandboxResult(
                success=True,
                result={"output": "hello"},
                logs=[{"level": "INFO", "stream": "stdout", "message": "done"}],
                duration_ms=150,
            )
        )

        worker = Worker("test-worker-1")
        worker._sandbox = sandbox_mock

        with patch("worker.worker.get_db_context") as mock_ctx:
            # Use the real db_session via a context manager mock
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            job = self._make_job(str(exec_id))
            await worker._process_job(job)

        sandbox_mock.execute.assert_called_once()

    async def test_process_job_not_found(self, db_session) -> None:
        """Worker should silently skip jobs with no matching DB record."""
        from worker.worker import Worker

        worker = Worker("test-worker-2")
        worker._sandbox = AsyncMock()

        with patch("worker.worker.get_db_context") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            job = self._make_job(str(uuid.uuid4()))  # non-existent
            # Should not raise
            await worker._process_job(job)

        worker._sandbox.execute.assert_not_called()

    async def test_process_cancelled_job_is_skipped(self, db_session) -> None:
        """Worker should skip jobs that were cancelled before pickup."""
        from worker.worker import Worker

        exec_id = uuid.uuid4()
        ex = Execution(
            id=exec_id,
            status=ExecutionStatus.CANCELLED,
            payload={},
            timeout=30,
        )
        db_session.add(ex)
        await db_session.commit()

        worker = Worker("test-worker-3")
        worker._sandbox = AsyncMock()

        with patch("worker.worker.get_db_context") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await worker._process_job(self._make_job(str(exec_id)))

        worker._sandbox.execute.assert_not_called()

    async def test_sandbox_exception_does_not_crash_worker(self, db_session) -> None:
        """A sandbox error must be caught; the worker stays alive."""
        from worker.worker import Worker

        exec_id = uuid.uuid4()
        ex = Execution(
            id=exec_id,
            status=ExecutionStatus.QUEUED,
            payload={},
            timeout=30,
        )
        db_session.add(ex)
        await db_session.commit()

        worker = Worker("test-worker-4")
        worker._sandbox = AsyncMock()
        worker._sandbox.execute = AsyncMock(side_effect=RuntimeError("sandbox boom"))

        with patch("worker.worker.get_db_context") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not propagate the exception
            await worker._process_job(self._make_job(str(exec_id)))


class TestWorkerShutdown:
    async def test_shutdown_event_stops_loop(self) -> None:
        from worker.worker import Worker

        worker = Worker("test-shutdown")
        worker._shutdown.set()  # pre-set shutdown

        redis_mock = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with patch("worker.worker.get_redis", return_value=redis_mock):
            with patch("worker.worker.dequeue_job", return_value=None):
                with patch("worker.worker.heartbeat", new_callable=AsyncMock):
                    # Should exit quickly without processing
                    import asyncio
                    await asyncio.wait_for(worker.run(), timeout=2.0)
