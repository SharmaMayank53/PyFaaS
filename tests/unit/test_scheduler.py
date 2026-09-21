import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from scheduler import scheduler as module
from shared.db.models import ExecutionStatus, ScheduleStatus


@pytest.fixture
def schedule_context(monkeypatch):
    now = datetime.now(UTC)
    schedule = SimpleNamespace(
        id=uuid.uuid4(),
        function_id=uuid.uuid4(),
        status=ScheduleStatus.ACTIVE,
        next_run_at=now - timedelta(seconds=1),
        cron_expression="* * * * *",
        payload={"scheduled": True},
        missed_runs=0,
    )
    function = SimpleNamespace(id=schedule.function_id)
    version = SimpleNamespace(
        id=uuid.uuid4(),
        timeout=30,
        memory_mb=128,
        artifact_path="source.zip",
        entrypoint="handler.handler",
        environment={},
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=function)),
    ]

    async def refresh(execution):
        execution.id = uuid.uuid4()

    db.refresh.side_effect = refresh

    @asynccontextmanager
    async def context():
        yield db

    monkeypatch.setattr(module, "get_db_context", context)
    monkeypatch.setattr(module, "choose_execution_version", AsyncMock(return_value=version))
    monkeypatch.setattr(module, "enqueue_job", AsyncMock())
    redis = AsyncMock()
    monkeypatch.setattr(module, "get_redis", lambda: redis)
    return schedule, db, redis


@pytest.mark.parametrize("queue_fails", [False, True])
async def test_schedule_fires_and_advances_after_queue_result(schedule_context, queue_fails):
    schedule, db, redis = schedule_context
    if queue_fails:
        module.enqueue_job.side_effect = RuntimeError("offline")
    await module.Scheduler()._fire_schedule(schedule)
    execution = db.add.call_args.args[0]
    assert execution.schedule_id == schedule.id
    assert execution.status == (ExecutionStatus.FAILED if queue_fails else ExecutionStatus.QUEUED)
    assert schedule.last_execution_id == execution.id
    assert schedule.next_run_at > schedule.last_run_at
    assert module.enqueue_job.call_args.args[2]["payload"] == {"scheduled": True}
    if queue_fails:
        assert execution.failure_kind == "queue"
    redis.aclose.assert_awaited_once()


@pytest.mark.parametrize(
    "reason", ["paused", "future", "missing", "no_function", "no_version", "missed"]
)
async def test_schedule_skips_ineligible_runs(schedule_context, reason):
    schedule, db, _ = schedule_context
    if reason == "paused":
        schedule.status = ScheduleStatus.PAUSED
    elif reason == "future":
        schedule.next_run_at = datetime.now(UTC) + timedelta(hours=1)
    elif reason == "missing":
        db.execute.side_effect = [MagicMock(scalar_one_or_none=MagicMock(return_value=None))]
    elif reason == "no_function":
        db.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=schedule)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
    elif reason == "no_version":
        module.choose_execution_version.return_value = None
    else:
        schedule.next_run_at = datetime.now(UTC) - timedelta(days=1)
    await module.Scheduler()._fire_schedule(schedule)
    db.add.assert_not_called()
    module.enqueue_job.assert_not_awaited()


@pytest.mark.parametrize("acquired", [False, True])
async def test_tick_releases_redis_when_lock_unavailable_or_processing_fails(monkeypatch, acquired):
    redis = AsyncMock()
    monkeypatch.setattr(module, "get_redis", lambda: redis)
    lock = AsyncMock()
    lock.__aenter__.return_value = acquired
    monkeypatch.setattr(module, "DistributedLock", MagicMock(return_value=lock))
    scheduler = module.Scheduler()
    scheduler._process_due_schedules = AsyncMock(side_effect=RuntimeError("database"))
    if acquired:
        with pytest.raises(RuntimeError, match="database"):
            await scheduler._tick()
    else:
        await scheduler._tick()
        scheduler._process_due_schedules.assert_not_awaited()
    redis.aclose.assert_awaited_once()


async def test_due_schedule_failure_does_not_block_other_schedules(schedule_context):
    schedule, db, _ = schedule_context
    second = SimpleNamespace(id=uuid.uuid4())
    db.execute.side_effect = None
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[schedule, second])))
    )
    scheduler = module.Scheduler()
    scheduler._fire_schedule = AsyncMock(side_effect=[RuntimeError("broken"), None])
    await scheduler._process_due_schedules()
    assert scheduler._fire_schedule.await_count == 2
