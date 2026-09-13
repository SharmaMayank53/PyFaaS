"""Tests for Redis queue helpers and distributed locking."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.queue.redis_client import DistributedLock, ack_job, enqueue_job, queue_depth


class TestEnqueueJob:
    async def test_enqueue_calls_zadd(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.zadd = AsyncMock(return_value=1)

        await enqueue_job(redis_mock, "exec-123", {"execution_id": "exec-123"})

        redis_mock.zadd.assert_called_once()
        call_args = redis_mock.zadd.call_args
        # First positional arg is queue name
        assert call_args[0][0] == "sopm:queue"
        # Second is a dict mapping job JSON -> score
        member_dict = call_args[0][1]
        assert len(member_dict) == 1
        raw_key = list(member_dict.keys())[0]
        parsed = json.loads(raw_key)
        assert parsed["job_id"] == "exec-123"
        assert parsed["execution_id"] == "exec-123"

    async def test_enqueue_high_priority_lower_score(self) -> None:
        """Higher priority jobs should have lower scores (sorted set pops lowest first)."""
        scores = {}

        async def fake_zadd(queue, mapping, *args, **kwargs):
            for k, v in mapping.items():
                scores[k] = v

        redis_mock = AsyncMock()
        redis_mock.zadd = fake_zadd

        await enqueue_job(redis_mock, "low", {"execution_id": "low"}, priority=0)
        await enqueue_job(redis_mock, "high", {"execution_id": "high"}, priority=1)

        score_values = list(scores.values())
        # High priority job should have lower score
        assert score_values[1] < score_values[0]


class TestQueueDepth:
    async def test_queue_depth(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.zcard = AsyncMock(return_value=5)

        depth = await queue_depth(redis_mock)
        assert depth == 5
        redis_mock.zcard.assert_called_once_with("sopm:queue")


class TestDistributedLock:
    async def test_acquire_success(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)

        lock = DistributedLock(redis_mock, "test-resource", timeout=10, wait=1)
        acquired = await lock.acquire()

        assert acquired is True
        redis_mock.set.assert_called_once()
        call_kwargs = redis_mock.set.call_args[1]
        assert call_kwargs["nx"] is True
        assert call_kwargs["ex"] == 10

    async def test_acquire_failure_returns_false(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=None)  # key already exists

        lock = DistributedLock(redis_mock, "test-resource", timeout=10, wait=0)
        acquired = await lock.acquire()

        assert acquired is False

    async def test_release_uses_lua_script(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.eval = AsyncMock(return_value=1)

        lock = DistributedLock(redis_mock, "test-resource", timeout=10, wait=1)
        await lock.acquire()
        await lock.release()

        redis_mock.eval.assert_called_once()
        # Verify it's the check-and-delete Lua script (KEYS[1] and ARGV[1])
        call_args = redis_mock.eval.call_args[0]
        script = call_args[0]
        assert "if redis.call" in script
        assert "del" in script

    async def test_context_manager_acquires_and_releases(self) -> None:
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.eval = AsyncMock(return_value=1)

        async with DistributedLock(redis_mock, "ctx-resource", timeout=10, wait=1) as acquired:
            assert acquired is True

        redis_mock.eval.assert_called_once()

    async def test_release_without_token_is_noop(self) -> None:
        redis_mock = AsyncMock()
        lock = DistributedLock(redis_mock, "test-resource")
        # Never acquired
        await lock.release()
        redis_mock.eval.assert_not_called()
