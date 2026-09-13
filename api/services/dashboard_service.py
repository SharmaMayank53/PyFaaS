"""
SOPM - Dashboard Service

Aggregates all operational metrics in a minimal number of DB/Redis queries.
Designed for < 500ms response time on the /api/v1/dashboard endpoint.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from minio.error import S3Error
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Execution, ExecutionStatus, Function, FunctionStatus, FunctionVersion
from shared.observability.logging import get_logger
from shared.queue.redis_client import get_redis, queue_depth

logger = get_logger(__name__)

# Health state constants
HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


async def get_overview(db: AsyncSession, redis: Any) -> dict[str, Any]:
    """Single-query overview stats."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    # All counts in one query via CASE WHEN aggregation
    result = await db.execute(
        text("""
        SELECT
            COUNT(*) FILTER (WHERE status = 'RUNNING') AS running_executions,
            COUNT(*) FILTER (WHERE status = 'COMPLETED' AND created_at >= :since) AS successful_24h,
            COUNT(*) FILTER (WHERE status IN ('FAILED','TIMED_OUT') AND created_at >= :since) AS failed_24h
        FROM executions
        WHERE created_at >= :since OR status IN ('RUNNING','QUEUED','PENDING')
        """),
        {"since": since_24h},
    )
    row = result.fetchone()

    fn_result = await db.execute(
        select(func.count()).where(Function.status == FunctionStatus.ACTIVE)
    )
    active_functions = fn_result.scalar_one()

    # Redis stats
    try:
        depth = await queue_depth(redis)
    except Exception:
        depth = -1

    # Active workers from heartbeat keys
    try:
        worker_keys = await redis.keys("sopm:worker:*:heartbeat")
        active_workers = len(worker_keys)
    except Exception:
        active_workers = 0

    return {
        "active_functions": active_functions,
        "running_executions": row.running_executions if row else 0,
        "successful_executions_24h": row.successful_24h if row else 0,
        "failed_executions_24h": row.failed_24h if row else 0,
        "queue_depth": depth,
        "active_workers": active_workers,
    }


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------


async def check_postgres(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return HEALTHY
    except Exception as exc:
        logger.warning("health_postgres_failed", error=str(exc))
        return UNHEALTHY


async def check_redis(redis: Any) -> str:
    try:
        await redis.ping()
        return HEALTHY
    except Exception as exc:
        logger.warning("health_redis_failed", error=str(exc))
        return UNHEALTHY


async def check_minio() -> str:
    try:
        from shared.storage.artifact_storage import get_minio_client
        from shared.config import get_settings
        settings = get_settings()
        client = get_minio_client()
        # Lightweight check — list buckets
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: client.bucket_exists(settings.minio_bucket_artifacts))
        return HEALTHY
    except Exception as exc:
        logger.warning("health_minio_failed", error=str(exc))
        return DEGRADED


async def check_kubernetes() -> str:
    from shared.config import get_settings
    settings = get_settings()
    if not settings.sandbox_enabled:
        return HEALTHY

    try:
        from kubernetes import client as k8s_client, config as k8s_config
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        v1 = k8s_client.CoreV1Api()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: v1.list_node(limit=1))
        return HEALTHY
    except Exception as exc:
        logger.warning("health_k8s_failed", error=str(exc))
        return DEGRADED


async def check_runner_pool(redis: Any) -> str:
    try:
        keys = await redis.keys("sopm:worker:*:heartbeat")
        if len(keys) == 0:
            return DEGRADED
        return HEALTHY
    except Exception:
        return UNHEALTHY


async def get_health(db: AsyncSession, redis: Any, detailed: bool = False) -> dict[str, Any]:
    """Run all health checks concurrently."""
    results = await asyncio.gather(
        check_postgres(db),
        check_redis(redis),
        check_minio() if detailed else asyncio.sleep(0, result=HEALTHY),
        check_kubernetes() if detailed else asyncio.sleep(0, result=HEALTHY),
        check_runner_pool(redis),
        return_exceptions=False,
    )

    statuses = {
        "api": HEALTHY,
        "postgres": results[0],
        "redis": results[1],
        "minio": results[2],
        "kubernetes": results[3],
        "runner_pool": results[4],
    }

    # Determine overall
    vals = list(statuses.values())
    if UNHEALTHY in vals:
        overall = UNHEALTHY
    elif DEGRADED in vals:
        overall = DEGRADED
    else:
        overall = HEALTHY

    return {"overall": overall, "components": statuses, "timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# Recent executions / failures
# ---------------------------------------------------------------------------


async def get_recent_executions(db: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            Execution.id,
            Execution.function_id,
            Execution.status,
            Execution.duration_ms,
            Execution.started_at,
            Execution.completed_at,
            Execution.created_at,
            Execution.worker_id,
            Execution.error_message,
            Function.name.label("function_name"),
        )
        .outerjoin(Function, Execution.function_id == Function.id)
        .order_by(Execution.created_at.desc())
        .limit(limit)
    )
    rows = result.fetchall()
    return [
        {
            "id": str(r.id),
            "function_id": str(r.function_id) if r.function_id else None,
            "function_name": r.function_name,
            "status": r.status.value,
            "duration_ms": r.duration_ms,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "created_at": r.created_at.isoformat(),
            "worker_id": r.worker_id,
            "error_message": r.error_message,
        }
        for r in rows
    ]


async def get_recent_failures(db: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            Execution.id,
            Execution.function_id,
            Execution.status,
            Execution.duration_ms,
            Execution.error_message,
            Execution.created_at,
            Execution.completed_at,
            Function.name.label("function_name"),
        )
        .outerjoin(Function, Execution.function_id == Function.id)
        .where(Execution.status.in_([ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT]))
        .order_by(Execution.created_at.desc())
        .limit(limit)
    )
    rows = result.fetchall()
    return [
        {
            "id": str(r.id),
            "function_id": str(r.function_id) if r.function_id else None,
            "function_name": r.function_name,
            "status": r.status.value,
            "duration_ms": r.duration_ms,
            "error_message": r.error_message,
            "created_at": r.created_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]


async def get_recent_deployments(db: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    result = await db.execute(
        select(
            FunctionVersion.id,
            FunctionVersion.function_id,
            FunctionVersion.version_number,
            FunctionVersion.created_at,
            FunctionVersion.artifact_size,
            FunctionVersion.is_active,
            Function.name.label("function_name"),
            Function.runtime,
        )
        .outerjoin(Function, FunctionVersion.function_id == Function.id)
        .order_by(FunctionVersion.created_at.desc())
        .limit(limit)
    )
    rows = result.fetchall()
    return [
        {
            "id": str(r.id),
            "function_id": str(r.function_id),
            "function_name": r.function_name,
            "version_number": r.version_number,
            "runtime": r.runtime,
            "artifact_size": r.artifact_size,
            "is_active": r.is_active,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


async def get_execution_metrics(db: AsyncSession) -> dict[str, Any]:
    """Execution stats: success rate, avg/p95/p99 runtime, hourly trend."""
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    # Aggregate stats
    stats_result = await db.execute(
        text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'COMPLETED') AS completed,
            COUNT(*) FILTER (WHERE status IN ('FAILED','TIMED_OUT')) AS failed,
            AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) AS avg_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
                FILTER (WHERE duration_ms IS NOT NULL) AS p95_ms,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms)
                FILTER (WHERE duration_ms IS NOT NULL) AS p99_ms
        FROM executions
        WHERE created_at >= :since
        """),
        {"since": since_24h},
    )
    stats = stats_result.fetchone()

    total = stats.total or 0
    completed = stats.completed or 0
    failed = stats.failed or 0
    success_rate = round((completed / total * 100), 2) if total > 0 else 0.0

    # Hourly trend (last 24 buckets)
    trend_result = await db.execute(
        text("""
        SELECT
            date_trunc('hour', created_at) AS hour,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'COMPLETED') AS completed,
            COUNT(*) FILTER (WHERE status IN ('FAILED','TIMED_OUT')) AS failed
        FROM executions
        WHERE created_at >= :since
        GROUP BY hour
        ORDER BY hour ASC
        """),
        {"since": since_24h},
    )
    trend_rows = trend_result.fetchall()

    trend = [
        {
            "hour": r.hour.isoformat(),
            "total": r.total,
            "completed": r.completed,
            "failed": r.failed,
        }
        for r in trend_rows
    ]

    return {
        "total_24h": total,
        "completed_24h": completed,
        "failed_24h": failed,
        "success_rate": success_rate,
        "avg_runtime_ms": round(stats.avg_ms or 0, 2),
        "p95_runtime_ms": round(float(stats.p95_ms or 0), 2),
        "p99_runtime_ms": round(float(stats.p99_ms or 0), 2),
        "hourly_trend": trend,
    }


async def get_worker_metrics(redis: Any) -> dict[str, Any]:
    """Worker heartbeat data from Redis."""
    try:
        keys = await redis.keys("sopm:worker:*:heartbeat")
        workers = []
        now_ts = time.time()
        for key in keys:
            val = await redis.get(key)
            worker_id = key.split(":")[2] if ":" in key else key
            last_seen = int(val) if val else 0
            age_s = now_ts - last_seen
            workers.append({
                "worker_id": worker_id,
                "last_heartbeat": datetime.fromtimestamp(last_seen, tz=timezone.utc).isoformat() if last_seen else None,
                "age_seconds": round(age_s, 1),
                "status": "online" if age_s < 120 else "stale",
            })
        return {"workers": workers, "total": len(workers), "online": sum(1 for w in workers if w["status"] == "online")}
    except Exception as exc:
        logger.warning("worker_metrics_failed", error=str(exc))
        return {"workers": [], "total": 0, "online": 0}


async def get_queue_metrics(redis: Any) -> dict[str, Any]:
    """Queue depth, processing depth, DLQ."""
    try:
        from shared.queue.redis_client import QUEUE_NAME, PROCESSING_SET
        from shared.config import get_settings
        settings = get_settings()

        depth, processing, dlq = await asyncio.gather(
            redis.zcard(QUEUE_NAME),
            redis.zcard(PROCESSING_SET),
            redis.zcard(settings.queue_dlq_name),
        )
        return {
            "queue_depth": depth,
            "processing_depth": processing,
            "dlq_depth": dlq,
        }
    except Exception as exc:
        logger.warning("queue_metrics_failed", error=str(exc))
        return {"queue_depth": 0, "processing_depth": 0, "dlq_depth": 0}


async def get_deployment_metrics(db: AsyncSession) -> dict[str, Any]:
    """Deployment frequency stats."""
    now = datetime.now(timezone.utc)
    since_7d = now - timedelta(days=7)

    result = await db.execute(
        text("""
        SELECT
            date_trunc('day', created_at) AS day,
            COUNT(*) AS deployments
        FROM function_versions
        WHERE created_at >= :since
        GROUP BY day
        ORDER BY day ASC
        """),
        {"since": since_7d},
    )
    rows = result.fetchall()

    total_result = await db.execute(
        text("SELECT COUNT(*) FROM function_versions WHERE created_at >= :since"),
        {"since": since_7d},
    )
    total = total_result.scalar_one()

    return {
        "total_7d": total,
        "daily_trend": [{"day": r.day.isoformat(), "count": r.deployments} for r in rows],
    }
