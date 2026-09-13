"""
SOPM - Application Configuration

All settings are loaded from environment variables or .env file.
No credentials are hardcoded here.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # API
    # -----------------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_workers: int = 4
    api_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # -----------------------------------------------------------------------
    # Security / JWT
    # -----------------------------------------------------------------------
    secret_key: str = Field(..., min_length=32)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # -----------------------------------------------------------------------
    # PostgreSQL
    # -----------------------------------------------------------------------
    database_url: str = Field(...)
    database_url_sync: str = Field(...)
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_timeout: int = 30

    # -----------------------------------------------------------------------
    # Redis
    # -----------------------------------------------------------------------
    redis_url: str = Field(...)
    redis_max_connections: int = 20
    redis_socket_timeout: int = 5
    redis_socket_connect_timeout: int = 5

    queue_default_timeout: int = 300
    queue_max_retries: int = 3
    queue_retry_delay: int = 60
    queue_dlq_name: str = "sopm:dlq"

    # -----------------------------------------------------------------------
    # MinIO
    # -----------------------------------------------------------------------
    minio_endpoint: str = Field(...)
    minio_access_key: str = Field(...)
    minio_secret_key: str = Field(...)
    minio_secure: bool = False
    minio_bucket_artifacts: str = "sopm-artifacts"
    minio_bucket_packages: str = "sopm-packages"

    # -----------------------------------------------------------------------
    # Worker
    # -----------------------------------------------------------------------
    worker_concurrency: int = 4
    worker_heartbeat_interval: int = 30
    worker_shutdown_timeout: int = 60
    worker_queue_poll_interval: int = 1
    worker_stale_recovery_interval: int = 60
    worker_stale_timeout_grace: int = 60
    worker_id: str = Field(default_factory=lambda: os.urandom(8).hex())

    # -----------------------------------------------------------------------
    # Sandbox (Kubernetes)
    # -----------------------------------------------------------------------
    sandbox_enabled: bool = True
    sandbox_namespace: str = "sopm-sandbox"
    sandbox_runtime_class: str = "gvisor"
    sandbox_image: str = "sopm/runner:latest"
    sandbox_image_pull_policy: str = "IfNotPresent"
    sandbox_default_timeout: int = 300
    sandbox_max_timeout: int = 3600
    sandbox_cpu_request: str = "100m"
    sandbox_cpu_limit: str = "500m"
    sandbox_memory_request: str = "128Mi"
    sandbox_memory_limit: str = "512Mi"
    sandbox_service_account: str = "sopm-runner"

    # -----------------------------------------------------------------------
    # Ephemeral agent execution
    # -----------------------------------------------------------------------
    ephemeral_local_execution_enabled: bool = False
    ephemeral_rate_limit_per_minute: int = 20
    ephemeral_concurrency_limit: int = 3
    ephemeral_max_code_bytes: int = 64 * 1024

    # -----------------------------------------------------------------------
    # Observability
    # -----------------------------------------------------------------------
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "sopm-api"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    # -----------------------------------------------------------------------
    # Scheduling
    # -----------------------------------------------------------------------
    scheduler_enabled: bool = True
    scheduler_poll_interval: int = 30
    scheduler_max_missed_runs: int = 3

    # -----------------------------------------------------------------------
    # Platform limits
    # -----------------------------------------------------------------------
    max_function_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_payload_size_bytes: int = 1024 * 1024  # 1 MB
    max_execution_timeout: int = 3600
    max_functions_per_user: int = 100
    max_versions_per_function: int = 50

    @field_validator("database_url", "database_url_sync", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v

    @field_validator("redis_url", mode="before")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        if not v:
            raise ValueError("REDIS_URL must be set")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]

