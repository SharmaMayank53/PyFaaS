"""
SOPM - Dashboard & Metrics Router

Endpoints:
  GET  /api/v1/dashboard          - Consolidated dashboard data
  GET  /api/v1/health             - Simple liveness (replaces old /health)
  GET  /api/v1/health/detailed    - Full component health checks
  GET  /api/v1/metrics/executions - Execution metrics
  GET  /api/v1/metrics/workers    - Worker metrics
  GET  /api/v1/metrics/queue      - Queue metrics
  GET  /api/v1/metrics/deployments- Deployment metrics
  WS   /ws/dashboard              - Real-time event stream
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.deps import get_current_user
from api.services import dashboard_service as svc
from api.services.ws_manager import manager as ws_manager
from shared.db.models import User
from shared.db.session import get_db
from shared.observability.logging import get_logger
from shared.queue.redis_client import get_redis

router = APIRouter(tags=["Dashboard & Metrics"])
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def get_redis_dep():
    redis = get_redis()
    try:
        yield redis
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# GET /api/v1/dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard", summary="Consolidated operational dashboard data")
async def get_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    redis = get_redis()
    try:
        overview, health, recent_execs, recent_failures, recent_deploys, exec_metrics = (
            await asyncio.gather(
                svc.get_overview(db, redis),
                svc.get_health(db, redis, detailed=False),
                svc.get_recent_executions(db, limit=10),
                svc.get_recent_failures(db, limit=10),
                svc.get_recent_deployments(db, limit=10),
                svc.get_execution_metrics(db),
            )
        )
    finally:
        await redis.aclose()

    return {
        "overview": overview,
        "health": {
            "api": health["components"]["api"],
            "postgres": health["components"]["postgres"],
            "redis": health["components"]["redis"],
            "minio": health["components"]["minio"],
            "kubernetes": health["components"]["kubernetes"],
            "runner_pool": health["components"]["runner_pool"],
        },
        "deployments": recent_deploys,
        "recent_executions": recent_execs,
        "recent_failures": recent_failures,
        "metrics": {
            "success_rate": exec_metrics["success_rate"],
            "avg_runtime": exec_metrics["avg_runtime_ms"],
            "executions_last_24h": exec_metrics["hourly_trend"],
            "total_24h": exec_metrics["total_24h"],
            "p95_runtime_ms": exec_metrics["p95_runtime_ms"],
            "p99_runtime_ms": exec_metrics["p99_runtime_ms"],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@router.get("/health", summary="Liveness probe", tags=["Health"])
async def health_simple():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/health/detailed", summary="Full dependency health check", tags=["Health"])
async def health_detailed(
    db: Annotated[AsyncSession, Depends(get_db)],
):
    redis = get_redis()
    try:
        health = await svc.get_health(db, redis, detailed=True)
    finally:
        await redis.aclose()
    return health


# ---------------------------------------------------------------------------
# Metrics endpoints
# ---------------------------------------------------------------------------


@router.get("/metrics/executions", summary="Execution metrics (24h)")
async def metrics_executions(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    return await svc.get_execution_metrics(db)


@router.get("/metrics/workers", summary="Worker availability and heartbeat status")
async def metrics_workers(
    _: Annotated[User, Depends(get_current_user)],
):
    redis = get_redis()
    try:
        return await svc.get_worker_metrics(redis)
    finally:
        await redis.aclose()


@router.get("/metrics/queue", summary="Queue depth and throughput")
async def metrics_queue(
    _: Annotated[User, Depends(get_current_user)],
):
    redis = get_redis()
    try:
        return await svc.get_queue_metrics(redis)
    finally:
        await redis.aclose()


@router.get("/metrics/deployments", summary="Deployment frequency (7d)")
async def metrics_deployments(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    return await svc.get_deployment_metrics(db)


# ---------------------------------------------------------------------------
# WebSocket /ws/dashboard
# ---------------------------------------------------------------------------


@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    """
    Real-time dashboard event stream.

    Events emitted:
      execution_started, execution_completed, execution_failed,
      deployment_started, deployment_completed,
      worker_online, worker_offline,
      queue_depth_changed, health_changed
    """
    await ws_manager.connect(ws)
    try:
        # Keep connection alive; ping/pong handled by client
        while True:
            # Wait for client messages (heartbeat ping expected)
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                if data == "ping":
                    await ws.send_text('{"type":"pong"}')
            except asyncio.TimeoutError:
                # Send server-side keepalive
                await ws.send_text('{"type":"keepalive"}')
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("ws_error", error=str(exc))
    finally:
        await ws_manager.disconnect(ws)
