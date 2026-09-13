"""
PyFaaS - FastAPI Application

Entry point for the API Gateway component.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.middleware.middleware import MetricsMiddleware, RequestIDMiddleware
from api.routers import auth, ephemeral, executions, functions, health, invoke, keys, schedules
from api.routers.dashboard import router as dashboard_router
from shared.config import get_settings
from shared.observability.logging import configure_logging
from shared.queue.redis_client import close_redis_pool
from shared.storage.artifact_storage import ensure_buckets

settings = get_settings()
configure_logging()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    logger.info("sopm_starting", version="0.1.0")

    # Ensure MinIO buckets exist
    try:
        await ensure_buckets()
        logger.info("minio_buckets_ready")
    except Exception as exc:
        logger.warning("minio_bucket_init_failed", error=str(exc))

    yield

    # Graceful shutdown
    logger.info("sopm_shutting_down")
    await close_redis_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title="PyFaaS - Python Functions-as-a-Service Platform",
        description=(
            "Self-hosted serverless function execution platform. "
            "Upload Python functions, version them, execute on demand or on schedule."
        ),
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ---------------------------------------------------------------------------
    # CORS
    # ---------------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------------------
    # Custom middleware (order matters — outermost first)
    # ---------------------------------------------------------------------------
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    PREFIX = "/api/v1"
    app.include_router(health.router)          # /health, /ready, /metrics
    app.include_router(auth.router, prefix=PREFIX)
    app.include_router(functions.router, prefix=PREFIX)
    app.include_router(executions.router, prefix=PREFIX)
    app.include_router(schedules.router, prefix=PREFIX)
    app.include_router(keys.router, prefix=PREFIX)
    app.include_router(invoke.router, prefix=PREFIX)
    app.include_router(ephemeral.router, prefix=PREFIX)
    app.include_router(dashboard_router, prefix=PREFIX)
    app.include_router(dashboard_router)

    # ---------------------------------------------------------------------------
    # Exception handlers
    # ---------------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error"},
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        log_config=None,  # structlog handles logging
    )


