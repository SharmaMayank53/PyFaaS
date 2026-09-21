"""
SOPM - Redis Client

Provides connection pooling, retries, reconnection, and distributed locking.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any, cast

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError
from tenacity import retry, stop_after_attempt, wait_exponential

from shared.config import get_settings

settings = get_settings()

_pool: aioredis.ConnectionPool | None = None


def get_redis_pool() -> aioredis.ConnectionPool:
    """Return (or create) the global Redis connection pool."""
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            socket_timeout=settings.redis_socket_timeout,
            socket_connect_timeout=settings.redis_socket_connect_timeout,
            decode_responses=True,
            retry_on_timeout=True,
        )
    return _pool


def get_redis() -> Redis:
    """Return a Redis client backed by the shared connection pool."""
    return aioredis.Redis(connection_pool=get_redis_pool())


async def close_redis_pool() -> None:
    """Close the connection pool on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


# ---------------------------------------------------------------------------
# Retry decorator for Redis operations
# ---------------------------------------------------------------------------


def redis_retry(func: Any) -> Any:
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        reraise=True,
    )(func)


# ---------------------------------------------------------------------------
# Distributed Lock
# ---------------------------------------------------------------------------

LOCK_PREFIX = "sopm:lock:"
DEFAULT_LOCK_TIMEOUT = 30  # seconds
DEFAULT_LOCK_WAIT = 10  # seconds


class DistributedLock:
    """
    Redis-based distributed lock using SET NX with expiry.

    Usage:
        async with DistributedLock(redis, "my-resource") as acquired:
            if acquired:
                # do work
    """

    def __init__(
        self,
        redis: Redis,
        name: str,
        timeout: int = DEFAULT_LOCK_TIMEOUT,
        wait: int = DEFAULT_LOCK_WAIT,
    ) -> None:
        self._redis = redis
        self._name = f"{LOCK_PREFIX}{name}"
        self._timeout = timeout
        self._wait = wait
        self._token: str | None = None

    async def acquire(self) -> bool:
        """Try to acquire the lock, waiting up to `self._wait` seconds."""
        self._token = str(uuid.uuid4())
        deadline = time.monotonic() + self._wait
        while time.monotonic() < deadline:
            acquired = await self._redis.set(
                self._name,
                self._token,
                nx=True,
                ex=self._timeout,
            )
            if acquired:
                return True
            await asyncio.sleep(0.1)
        return False

    async def release(self) -> None:
        """Release the lock only if we hold it (check-and-delete via Lua)."""
        if self._token is None:
            return
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        with contextlib.suppress(RedisError):
            await self._redis.eval(script, 1, self._name, self._token)

    async def __aenter__(self) -> bool:
        return await self.acquire()

    async def __aexit__(self, *_: Any) -> None:
        await self.release()


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

QUEUE_NAME = "sopm:queue"
PROCESSING_SET = "sopm:processing"


@redis_retry
async def enqueue_job(
    redis: Redis,
    job_id: str,
    payload: dict[str, Any],
    priority: int = 0,
) -> None:
    """Push a job onto the sorted set queue (score = -priority for FIFO at same priority)."""
    import json

    score = time.time() - priority * 1_000_000
    await redis.zadd(QUEUE_NAME, {json.dumps({"job_id": job_id, **payload}): score})


@redis_retry
async def dequeue_job(
    redis: Redis,
    timeout: int = 5,
) -> dict[str, Any] | None:
    """
    Blocking pop from the priority queue and move the job to processing.

    BZPOPMIN removes sleep-poll latency while keeping the sorted-set queue
    shape used elsewhere. Moving to processing happens immediately after pop.
    """
    import json

    result = await redis.bzpopmin(QUEUE_NAME, timeout=timeout)
    if result is None:
        return None

    # BZPOPMIN returns a key, member and numeric score in that order.
    _queue, job, score = cast(tuple[str, str, float], result)
    await redis.zadd(PROCESSING_SET, {job: score})
    return cast(dict[str, Any], json.loads(job))


@redis_retry
async def ack_job(
    redis: Redis,
    job_id: str,
) -> None:
    """Remove a job from the processing set after completion."""
    import json

    # Scan the processing set for this job_id
    cursor = 0
    while True:
        cursor, members = await redis.zscan(PROCESSING_SET, cursor)
        for member, _ in members:
            try:
                data = json.loads(cast(str, member))
                if data.get("job_id") == job_id:
                    await redis.zrem(PROCESSING_SET, member)
                    return
            except (json.JSONDecodeError, AttributeError):
                continue
        if cursor == 0:
            break


@redis_retry
async def queue_depth(redis: Redis) -> int:
    """Return the current queue depth."""
    return await redis.zcard(QUEUE_NAME)


async def heartbeat(redis: Redis, worker_id: str, ttl: int = 90) -> None:
    """Write a worker heartbeat key with TTL."""
    key = f"sopm:worker:{worker_id}:heartbeat"
    await redis.set(key, int(time.time()), ex=ttl)


@contextlib.asynccontextmanager
async def redis_dependency() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency for Redis."""
    client = get_redis()
    try:
        yield client
    finally:
        await client.aclose()
