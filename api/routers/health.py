"""
SOPM - Health & Metrics Router
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from shared.db.session import AsyncSessionLocal
from shared.observability.logging import get_logger
from shared.queue.redis_client import get_redis

router = APIRouter(tags=["Platform"])
logger = get_logger(__name__)


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/ready", summary="Readiness probe — checks all dependencies")
async def ready() -> dict:
    checks: dict[str, str] = {}
    overall = "healthy"

    # Database
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        overall = "unhealthy"

    # Redis
    try:
        redis = get_redis()
        await redis.ping()
        await redis.aclose()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        overall = "degraded" if overall == "healthy" else overall

    return {
        "status": overall,
        "version": "0.1.0",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics", summary="Prometheus metrics scrape endpoint")
async def metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
