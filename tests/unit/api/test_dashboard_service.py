from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services import dashboard_service as svc
from shared.config import get_settings
from shared.db.models import Execution, ExecutionStatus


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (None, "healthy"),
        ("postgres", "unhealthy"),
        ("redis", "unhealthy"),
        ("workers", "degraded"),
        ("minio", "degraded"),
        ("kubernetes", "degraded"),
    ],
)
async def test_health_aggregates_dependency_failures(monkeypatch, failure, expected):
    db, redis = AsyncMock(), AsyncMock()
    redis.keys.return_value = ["worker"]
    if failure == "postgres":
        db.execute.side_effect = RuntimeError("offline")
    if failure == "redis":
        redis.ping.side_effect = RuntimeError("offline")
    if failure == "workers":
        redis.keys.return_value = []
    minio = MagicMock()
    if failure == "minio":
        minio.bucket_exists.side_effect = RuntimeError("offline")
    monkeypatch.setattr("shared.storage.artifact_storage.get_minio_client", lambda: minio)
    monkeypatch.setattr(get_settings(), "sandbox_enabled", True)
    monkeypatch.setattr(
        "kubernetes.config.load_incluster_config", MagicMock(side_effect=RuntimeError("local"))
    )
    monkeypatch.setattr("kubernetes.config.load_kube_config", MagicMock())
    kubernetes = MagicMock()
    if failure == "kubernetes":
        kubernetes.list_node.side_effect = RuntimeError("offline")
    monkeypatch.setattr("kubernetes.client.CoreV1Api", lambda: kubernetes)
    health = await svc.get_health(db, redis, detailed=True)
    assert health["overall"] == expected
    assert health["components"]["api"] == "healthy"


async def test_overview_and_history_use_real_database(
    db_session, test_function, test_version, monkeypatch
):
    db_session.add(
        Execution(
            function_id=test_function.id,
            function_version_id=test_version.id,
            status=ExecutionStatus.FAILED,
            error_message="handler error",
            duration_ms=10,
            payload={},
            created_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    redis = AsyncMock()
    redis.keys.return_value = ["worker"]
    monkeypatch.setattr(svc, "queue_depth", AsyncMock(return_value=2))
    overview = await svc.get_overview(db_session, redis)
    assert overview["active_functions"] == 1
    assert overview["failed_executions_24h"] == 1
    assert overview["queue_depth"] == 2
    for method in (svc.get_recent_executions, svc.get_recent_failures):
        history = await method(db_session)
        assert history[0]["function_name"] == test_function.name
        assert history[0]["error_message"] == "handler error"
    deploys = await svc.get_recent_deployments(db_session)
    assert deploys[0]["version_number"] == 1
    monkeypatch.setattr(svc, "queue_depth", AsyncMock(side_effect=RuntimeError("offline")))
    redis.keys.side_effect = RuntimeError("offline")
    overview = await svc.get_overview(db_session, redis)
    assert overview["queue_depth"] == -1
    assert overview["active_workers"] == 0


async def test_worker_and_queue_metrics_include_stale_workers_and_fallbacks(monkeypatch):
    redis = AsyncMock()
    monkeypatch.setattr(svc.time, "time", lambda: 1000)
    redis.keys.return_value = ["sopm:worker:live:heartbeat", "sopm:worker:stale:heartbeat"]
    redis.get.side_effect = ["990", "800"]
    workers = await svc.get_worker_metrics(redis)
    assert workers["total"] == 2
    assert workers["online"] == 1
    assert workers["workers"][1]["status"] == "stale"
    redis.zcard.side_effect = [2, 1, 3]
    assert await svc.get_queue_metrics(redis) == {
        "queue_depth": 2,
        "processing_depth": 1,
        "dlq_depth": 3,
    }
    redis.keys.side_effect = RuntimeError("offline")
    redis.zcard.side_effect = RuntimeError("offline")
    assert (await svc.get_worker_metrics(redis))["total"] == 0
    assert (await svc.get_queue_metrics(redis))["queue_depth"] == 0
    assert await svc.check_runner_pool(redis) == "unhealthy"


async def test_metric_aggregation_serializes_database_results():
    db = AsyncMock()
    now = datetime.now(UTC)
    # PostgreSQL percentile/date_trunc results; aggregation SQL is not supported by SQLite.
    stats = SimpleNamespace(total=4, completed=3, failed=1, avg_ms=12.5, p95_ms=20, p99_ms=25)
    trend = SimpleNamespace(hour=now, total=4, completed=3, failed=1)
    db.execute.side_effect = [
        MagicMock(one=MagicMock(return_value=stats)),
        MagicMock(fetchall=MagicMock(return_value=[trend])),
    ]
    metrics = await svc.get_execution_metrics(db)
    assert metrics["success_rate"] == 75
    assert metrics["p95_runtime_ms"] == 20
    assert metrics["hourly_trend"][0]["hour"] == now.isoformat()
    db.execute.side_effect = [
        MagicMock(fetchall=MagicMock(return_value=[SimpleNamespace(day=now, deployments=2)])),
        MagicMock(scalar_one=MagicMock(return_value=2)),
    ]
    metrics = await svc.get_deployment_metrics(db)
    assert metrics["total_7d"] == 2
    assert metrics["daily_trend"] == [{"day": now.isoformat(), "count": 2}]
