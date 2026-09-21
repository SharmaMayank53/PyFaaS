"""
SOPM - Prometheus Metrics

All platform metrics are defined here as module-level singletons.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

# ---------------------------------------------------------------------------
# API metrics
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "sopm_http_requests_total",
    "Total HTTP requests received",
    ["method", "endpoint", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "sopm_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# Execution metrics
# ---------------------------------------------------------------------------

EXECUTIONS_TOTAL = Counter(
    "sopm_executions_total",
    "Total executions triggered",
    ["status", "runtime"],
)

EXECUTION_DURATION_SECONDS = Histogram(
    "sopm_execution_duration_seconds",
    "Function execution duration in seconds",
    ["runtime"],
    buckets=(0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

EXECUTION_ERRORS_TOTAL = Counter(
    "sopm_execution_errors_total",
    "Total execution errors",
    ["error_type"],
)

# ---------------------------------------------------------------------------
# Queue metrics
# ---------------------------------------------------------------------------

QUEUE_DEPTH = Gauge(
    "sopm_queue_depth",
    "Current number of jobs in the execution queue",
)

QUEUE_PROCESSING_DEPTH = Gauge(
    "sopm_queue_processing_depth",
    "Current number of jobs being processed",
)

JOB_RETRIES_TOTAL = Counter(
    "sopm_job_retries_total",
    "Total job retries",
)

DLQ_DEPTH = Gauge(
    "sopm_dlq_depth",
    "Current number of jobs in the dead-letter queue",
)

# ---------------------------------------------------------------------------
# Worker metrics
# ---------------------------------------------------------------------------

WORKER_ACTIVE = Gauge(
    "sopm_worker_active",
    "Number of active workers",
)

WORKER_JOBS_PROCESSED_TOTAL = Counter(
    "sopm_worker_jobs_processed_total",
    "Total jobs processed by workers",
    ["worker_id", "outcome"],
)

# ---------------------------------------------------------------------------
# Function registry metrics
# ---------------------------------------------------------------------------

FUNCTIONS_TOTAL = Gauge(
    "sopm_functions_total",
    "Total number of registered functions",
    ["status"],
)

FUNCTION_VERSIONS_TOTAL = Gauge(
    "sopm_function_versions_total",
    "Total number of function versions",
)

# ---------------------------------------------------------------------------
# Platform info
# ---------------------------------------------------------------------------

PLATFORM_INFO = Info(
    "sopm_platform",
    "SOPM platform version and build information",
)

PLATFORM_INFO.info(
    {
        "version": "0.1.0",
        "python_version": "3.12",
    }
)
