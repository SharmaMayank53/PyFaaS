# SOPM Project Handoff

This document is a technical handoff for SOPM: a self-hosted Python function execution platform with a FastAPI backend, worker and scheduler services, PostgreSQL persistence, Redis queueing, MinIO artifact storage, Docker Compose infrastructure, and a Next.js dashboard.

The goal of this handoff is to help a new engineer understand how the project is structured, how data moves through the system, where the important code lives, and what has recently changed. It is not meant to replace the README or deployment documentation.

Current project root on this machine:

```text
C:\sopm
```

## 1. Product Summary

SOPM lets an authenticated user:

- Register and log in.
- Create function records.
- Upload Python ZIP archives as versioned functions.
- Execute functions manually from the dashboard or API.
- Automate functions with cron schedules.
- Inspect execution status, result, logs, worker state, queue state, and platform health.

The system behaves like a small serverless platform:

1. A user uploads code.
2. The platform stores the artifact and metadata.
3. An execution request creates a job.
4. A worker runs the function.
5. Results and logs are persisted.
6. The dashboard displays operational state.

For local Docker development, function code runs inside the worker container through the local runner path. That mode is fast and useful, but it is explicitly not a security boundary. The production isolation path is Kubernetes Jobs with gVisor; Phase 2 hardening is now implemented in code/manifests, but still needs validation on a real Kubernetes cluster with runsc/gVisor installed.

## 2. Repository Map

```text
api/                  FastAPI application, routers, schemas, dashboard services
shared/               Shared config, database models/session, auth, queue, storage, metrics
worker/               Redis worker that processes queued executions
scheduler/            Cron scheduler that fires due function schedules
sandbox/              Kubernetes sandbox abstraction and local runner integration
migrations/           Alembic migrations for PostgreSQL
deploy/docker/        Docker Compose and Dockerfiles
k8s/                  Kubernetes and monitoring manifests
docs/                 Extra architecture/deployment/security docs
sopm-dashboard/       Next.js 14 dashboard frontend
tests/                Unit/integration tests
README.md             Short project overview and local setup
PROJECT_HANDOFF.md    This handoff
```

Canonical local compose file:

```text
C:\sopm\deploy\docker\docker-compose.yml
```

Canonical frontend root:

```text
C:\sopm\sopm-dashboard
```

## 3. High-Level Architecture

```text
Browser / Next.js Dashboard
        |
        | HTTP + JWT / WebSocket
        v
FastAPI API
        |
        | users, functions, versions, executions, schedules
        v
PostgreSQL

FastAPI API
        |
        | ZIP artifact upload/download metadata
        v
MinIO

FastAPI API
        |
        | enqueue execution job
        v
Redis queue
        |
        | dequeue
        v
Worker
        |
        | execute uploaded function
        v
Sandbox / Runner
        |
        | result + logs
        v
PostgreSQL

Scheduler
        |
        | polls due schedules, creates executions, enqueues jobs
        v
Redis queue
```

The source of truth is PostgreSQL. Redis is used for queueing, worker heartbeat, and distributed scheduler locking. MinIO stores uploaded ZIP artifacts. The dashboard is an operational client, not the source of truth.

## 4. Runtime Services

Docker Compose services:

```text
postgres      PostgreSQL database
redis         Redis queue, heartbeat, lock, DLQ
minio         Object storage for function ZIP artifacts
migrate       One-shot Alembic migration container
api           FastAPI backend
worker        Execution worker
scheduler     Cron automation service
prometheus    Metrics scraper
grafana       Metrics dashboard on host port 3100
```

Important service notes:

- `migrate` is expected to exit after `alembic upgrade head`.
- Exit code `0` for `migrate` is success, not failure.
- `api` depends on successful migration completion.
- `worker` and `scheduler` depend on a healthy API.
- Local Docker sets `SANDBOX_ENABLED=false`.
- Grafana maps container port `3000` to host port `3100` so the Next dashboard can use host port `3000`.

Common local ports:

```text
3000  Next.js dashboard
3100  Grafana
8000  FastAPI API
5432  PostgreSQL
6379  Redis
9000  MinIO API
9001  MinIO console
9090  Prometheus
```

## 5. Backend Entry Points

Main FastAPI app:

```text
api/main.py
```

Routers:

```text
api/routers/health.py       /health, /ready, /metrics
api/routers/auth.py         /api/v1/auth/*
api/routers/functions.py    /api/v1/functions/*
api/routers/executions.py   /api/v1/functions/{id}/execute and /api/v1/executions/*
api/routers/schedules.py    /api/v1/schedules/*
api/routers/dashboard.py    /api/v1/dashboard, /api/v1/metrics/*, /ws/dashboard
```

Shared backend modules:

```text
shared/config.py                  environment settings
shared/db/models.py               SQLAlchemy ORM models
shared/db/session.py              async DB session helpers
shared/security/auth.py           password hashing and JWT handling
shared/security/code_validator.py upload validation
shared/storage/artifact_storage.py MinIO artifact storage
shared/queue/redis_client.py      queue, DLQ, worker heartbeat, lock support
shared/observability/metrics.py   Prometheus metrics
```

Backend responsibilities:

- Validate authentication and ownership.
- Validate API payloads with Pydantic schemas.
- Persist users, functions, versions, executions, logs, and schedules.
- Store uploaded function ZIPs in MinIO.
- Enqueue execution jobs in Redis.
- Expose operational metrics and health.
- Provide WebSocket plumbing for dashboard live events.

## 6. Authentication Model

Authentication is JWT-based.

Core files:

```text
api/routers/auth.py
api/dependencies/deps.py
shared/security/auth.py
sopm-dashboard/src/store/index.ts
sopm-dashboard/src/lib/api.ts
sopm-dashboard/src/middleware.ts
sopm-dashboard/src/components/layout/Providers.tsx
```

Flow:

1. User registers with `/api/v1/auth/register`.
2. User logs in with `/api/v1/auth/login` using `application/x-www-form-urlencoded` credentials.
3. Backend returns an access token.
4. Frontend stores the token in `localStorage` under `sopm_token` and also mirrors it into a `sopm_token` cookie.
5. Axios attaches `Authorization: Bearer <token>` on API requests.
6. Frontend middleware checks the cookie and redirects protected pages to `/login?next=...` when missing.
7. `Providers.tsx` validates the token with `/api/v1/auth/me` before rendering the dashboard shell.
8. A 401 response clears stored auth state and sends the user back to login.

Protected dashboard routes include:

```text
/
/functions
/functions/*
/executions
/executions/*
/schedules
/schedules/*
/logs
/keys
/cluster
```

This means users should not be able to bypass the login page by typing dashboard URLs directly.

## 7. Database Model

Canonical ORM file:

```text
shared/db/models.py
```

Main tables:

```text
users
functions
function_versions
version_activations
executions
execution_logs
schedules
api_keys
```

Important relationships:

- `User` owns many `Function` rows.
- `User` owns many `ApiKey` rows.
- `Function` has many `FunctionVersion` rows.
- `Function.active_version_id` points to the primary production version.
- `Function.canary_version_id` and `Function.canary_percent` optionally route a percentage of executions to a canary version.
- `VersionActivation` records activation, rollback, canary, promote, and clear actions for audit history.
- `Execution` references function, the exact function version that ran, optional user trigger, and optional schedule.
- `ExecutionLog` belongs to an execution.
- `Schedule` belongs to a user and function.
- `ApiKey` belongs to a user and stores only a hash/prefix, not the raw key.

Function statuses:

```text
ACTIVE
INACTIVE
DEPRECATED
```

Execution statuses:

```text
PENDING
QUEUED
RUNNING
COMPLETED
FAILED
TIMED_OUT
CANCELLED
```

Valid execution transitions:

```text
PENDING -> QUEUED or CANCELLED
QUEUED -> RUNNING, CANCELLED, or FAILED
RUNNING -> COMPLETED, FAILED, TIMED_OUT, or CANCELLED
terminal: COMPLETED, FAILED, TIMED_OUT, CANCELLED
```

Schedule statuses:

```text
ACTIVE
PAUSED
DELETED
```

Schema changes are managed by Alembic. The app should not auto-create tables on startup.

## 8. Migrations

Migration config:

```text
alembic.ini
migrations/env.py
migrations/versions/
```

Current Docker migration command:

```text
alembic upgrade head
```

Important migration notes:

- The `migrate` container is one-shot.
- Successful migrations produce an exited container with code `0`.
- PostgreSQL enum creation must be handled carefully. Avoid creating duplicate enum types in later migrations.
- The project previously had enum/revision-chain issues; treat migration changes cautiously.

## 9. Function Upload and Versioning

Core backend file:

```text
api/routers/functions.py
```

Frontend upload page:

```text
sopm-dashboard/src/app/functions/page.tsx
```

Upload endpoint:

```text
POST /api/v1/functions/{function_id}/versions
```

Multipart fields:

```text
archive       ZIP file
entrypoint    module.function, normally handler.handler
timeout       execution timeout
memory_mb     memory setting
change_notes  optional notes
```

Upload flow:

1. User creates a function record.
2. User uploads a ZIP archive to that function.
3. API validates ownership.
4. API reads and validates the ZIP.
5. API stores the artifact in MinIO.
6. API creates a `FunctionVersion` row.
7. API updates `Function.active_version_id` to the new version.
8. API records an activation audit row.
9. Dashboard refreshes the function list/details.

Artifact path shape:

```text
functions/{function_id}/{version_id}/source.zip
```

Version control behavior:

- Uploading a new version makes it active by default and clears any canary configuration.
- A previous version can be activated again from the function detail page.
- Activating a previous version is the rollback mechanism.
- Canary configuration can point part of traffic at another active version.
- Every execution stores the exact `function_version_id` that ran.
- Activation/canary changes are stored in `version_activations`.

Important frontend behavior:

- Multipart upload lets Axios/browser set the `Content-Type` boundary.
- The upload form creates the function first, then uploads the ZIP.
- If upload fails after creating the function, the frontend attempts to delete the newly created function to avoid dangling empty records.
- The file input reset uses a `formRef` guard to avoid null `.reset()` errors.

## 10. Manual Execution Flow

Core files:

```text
api/routers/executions.py
shared/queue/redis_client.py
worker/worker.py
sandbox/k8s_sandbox.py
sandbox/runner.py
```

Manual execute endpoint:

```text
POST /api/v1/functions/{function_id}/execute
```

Execution flow:

1. API verifies the current user.
2. API checks that the function belongs to the user.
3. API chooses an executable version with `shared/execution/version_routing.py`.
4. Version choice uses the explicit requested version when supplied, otherwise active/canary routing.
5. API creates an `Execution` row with `QUEUED`, including the chosen `function_version_id`, and commits it.
6. API enqueues a Redis job after the execution row is visible to workers.
7. Worker dequeues the job using Redis blocking pop.
8. Worker marks execution `RUNNING`.
9. Worker calls the sandbox/runner path.
10. Runner imports and calls the uploaded handler.
11. Worker stores result, logs, status, timestamps, duration, failure kind, and worker id.
12. Dashboard polls and displays the execution.

The commit-before-enqueue ordering is important. Earlier faster queue pickup exposed a race where the worker could receive a Redis job before PostgreSQL had committed the execution row, causing `execution_not_found`.

Execution result storage:

- Function return values are stored in `executions.result`.
- Logs/stdout/stderr are stored in `execution_logs`.
- A completed execution can have a result with no logs.
- A failed execution may have logs and an error message.
- `failure_kind` distinguishes handler failures from infra/queue failures for filtering and debugging.

Runner output protocol:

```text
SOPM_RESULT:<json>
```

The worker parses this line and writes the parsed JSON to the execution row.

## 11. Result Display

Frontend execution files:

```text
sopm-dashboard/src/components/execution/ResultRenderer.tsx
sopm-dashboard/src/components/execution/ExecutionDrawer.tsx
sopm-dashboard/src/app/executions/page.tsx
sopm-dashboard/src/app/executions/[id]/page.tsx
sopm-dashboard/src/app/functions/[id]/page.tsx
```

`ResultRenderer` is the shared result presentation component used by the execution drawer and execution detail page. It now treats raw JSON as a secondary debugging view, not the primary UI.

Current result rendering behavior:

- Bare primitives such as a string, number, boolean, or null render directly.
- Common top-level text fields such as `message`, `summary`, `title`, `status`, `state`, `return_value`, and `error` render as prominent readable fields.
- Top-level scalar fields render as labeled key-value rows.
- Nested top-level objects such as `stats` or `external_call` render as small labeled key-value cards.
- Primitive arrays render as compact chips/lists.
- Arrays of objects render as a table when the rows share consistent keys; otherwise they render as item cards.
- Timestamp-like fields such as `timestamp`, `created_at`, `updated_at`, `started_at`, and `completed_at` render in local readable time when they contain ISO-like strings.
- Deep or irregular structures fall back gracefully with a note pointing users to raw JSON.
- `View raw JSON` remains available and is collapsed by default.
- `View logs` remains available and is collapsed by default.

Example result shape:

```json
{
  "message": "Structured renderer verification complete",
  "status": "ok",
  "timestamp": "2026-08-19T12:58:05.753002+00:00",
  "stats": {
    "count": 5,
    "sum": 63,
    "mean": 12.6,
    "median": 11,
    "stdev": 7.18
  },
  "external_call": {
    "url": "https://example.com",
    "status_code": 200,
    "ok": true,
    "content_type": "text/html"
  },
  "tags": ["renderer", "structured", "verified"],
  "samples": [
    {"name": "alpha", "value": 3},
    {"name": "beta", "value": 7}
  ]
}
```

This renders as readable text plus fields/cards/tables first. The exact original JSON remains accessible for debugging and API consumers.

## 12. Worker Service

Core file:

```text
worker/worker.py
```

Responsibilities:

- Poll Redis for queued jobs.
- Maintain heartbeat in Redis.
- Mark executions as `RUNNING`.
- Call sandbox/runner.
- Persist final status, result, logs, duration, worker id, and failure kind.
- Classify failures as handler, infra, or queue-side failures where possible.
- Recover stale RUNNING executions to FAILED when a worker never reports completion.
- Acknowledge completed Redis jobs.
- Emit metrics.

Concurrency is controlled by:

```text
WORKER_CONCURRENCY
```

In Docker Compose, current local worker settings include:

```text
WORKER_CONCURRENCY=2
WORKER_HEARTBEAT_INTERVAL=10
```

Operational note:

The worker should not hold a database transaction while user code executes. It opens short sessions around state updates.

## 13. Scheduler / Automation Service

Backend scheduler code:

```text
scheduler/scheduler.py
```

Docker Compose service:

```text
scheduler
```

Docker command:

```text
python -m scheduler.scheduler
```

Frontend automation page:

```text
sopm-dashboard/src/app/schedules/page.tsx
```

Frontend route:

```text
http://localhost:3000/schedules
```

Backend schedule API:

```text
GET    /api/v1/schedules
POST   /api/v1/schedules?function_id={function_id}
GET    /api/v1/schedules/{schedule_id}
PATCH  /api/v1/schedules/{schedule_id}
DELETE /api/v1/schedules/{schedule_id}
```

Schedule create body:

```json
{
  "name": "nightly-sync",
  "cron_expression": "0 9 * * *",
  "payload": {}
}
```

How automation works:

1. User creates a schedule from the dashboard.
2. Schedule is stored in PostgreSQL with status `ACTIVE`.
3. Scheduler service wakes every configured interval.
4. Scheduler takes a Redis distributed lock so multiple scheduler replicas do not fire the same schedules at the same time.
5. Scheduler queries due active schedules where `next_run_at <= now`.
6. Scheduler creates an execution row for each due schedule.
7. Scheduler enqueues the execution job into Redis.
8. Worker processes it like any manual execution.
9. Scheduler updates schedule timing fields.

Important schedule fields:

```text
cron_expression
payload
status
next_run_at
last_run_at
last_execution_id
missed_runs
```

Local Docker scheduler settings:

```text
SCHEDULER_ENABLED=true
SCHEDULER_POLL_INTERVAL=30
```

Dashboard schedule UI supports:

- Selecting a function.
- Naming a schedule.
- Entering a cron expression.
- Providing payload JSON.
- Creating schedules.
- Pausing active schedules.
- Resuming paused schedules.
- Deleting schedules.
- Viewing next and last run times.

Important caveat:

The dashboard creates and manages schedule records. The actual automated execution only happens when the `scheduler` service is running.

## 14. Sandbox and Runner

Core files:

```text
sandbox/k8s_sandbox.py
sandbox/runner.py
deploy/docker/Dockerfile.runner
k8s/base/runtimeclass-gvisor.yaml
k8s/base/network-policies.yaml
docs/K8S_GVISOR_ISOLATION.md
```

Production-style Kubernetes/gVisor path:

1. Worker checks that the configured RuntimeClass exists.
2. Worker creates a Kubernetes Job in `sopm-sandbox`.
3. Job runs the configured runner image.
4. Pod uses `runtimeClassName: gvisor`.
5. Runner downloads the ZIP artifact from MinIO.
6. Runner removes MinIO credentials from its environment.
7. Runner extracts the archive.
8. Runner optionally installs `requirements.txt` into a scoped dependency directory.
9. Runner imports the configured entrypoint.
10. Runner calls the handler.
11. Runner prints `SOPM_RESULT:<json>`.
12. Worker collects result/logs and stores them.

Implemented Phase 2 hardening:

- Fails closed if `RuntimeClass gvisor` is missing.
- Runs as non-root UID/GID `65534`.
- Drops all Linux capabilities.
- Disables privilege escalation.
- Uses a read-only root filesystem.
- Mounts writable `emptyDir` volumes only at `/tmp` and `/work`.
- Disables service account token automount for runner pods.
- Uses the `sopm-runner` service account with no RoleBinding.
- Applies `sopm/network-profile: artifact-only` labels for NetworkPolicy targeting.
- Sandbox NetworkPolicy now permits DNS and MinIO artifact egress only.
- K8s memory limit is derived from the function version `memory_mb`.
- K8s Job deadline is derived from the function timeout.
- Deadline failures are surfaced as timeout.
- `OOMKilled` failures are surfaced as `Execution exceeded memory limit`.

Current local Docker path:

- `SANDBOX_ENABLED=false` in Docker Compose.
- The worker uses a Docker-local subprocess path.
- It still runs the real uploaded ZIP through `sandbox.runner`.
- It benefits from Phase 1 artifact/dependency cache work.
- This is useful for local development.
- This is not a security boundary for untrusted code.

Supported handler signatures:

```python
def handler(): ...
def handler(event): ...
def handler(event, context): ...
```

Typical uploaded ZIP should contain something like:

```text
handler.py
```

With an entrypoint such as:

```text
handler.handler
```

Important validation caveat:

The repo now contains the hardened K8s spec and unit tests for the generated Job/security/failure-classification behavior, but this machine currently has no active Kubernetes context. The final proof still requires a real cluster with gVisor/runsc installed and a pod inspection showing `Runtime Class Name: gvisor`.
## 15. Redis Queue and Coordination

Core file:

```text
shared/queue/redis_client.py
```

Redis responsibilities:

- Main queue.
- Processing/in-flight tracking.
- Dead-letter queue.
- Worker heartbeat.
- Scheduler distributed lock.

Queue concepts:

```text
sopm:queue       queued execution jobs
sopm:processing  in-flight jobs
sopm:dlq         dead-letter jobs
```

The queue is effectively at-least-once. The worker now has database-level stale RUNNING execution recovery so stuck executions are failed visibly instead of remaining running forever. A deeper Redis processing requeue/DLQ operator UI is still a future hardening area.

## 16. Artifact Storage

Core file:

```text
shared/storage/artifact_storage.py
```

Local storage service:

```text
minio
```

Buckets configured in settings:

```text
sopm-artifacts
sopm-packages
```

Function source ZIP artifacts are stored in MinIO, while metadata such as function version, artifact path, hash, and size are stored in PostgreSQL.

## 17. Dashboard Architecture

Frontend stack:

```text
Next.js 14 App Router
React 18
TypeScript
TanStack Query
Zustand
Axios
Tailwind CSS
Lucide React icons
Recharts
```

Important frontend files:

```text
sopm-dashboard/src/app/layout.tsx
sopm-dashboard/src/components/layout/Providers.tsx
sopm-dashboard/src/components/layout/Sidebar.tsx
sopm-dashboard/src/components/ui/index.tsx
sopm-dashboard/src/lib/api.ts
sopm-dashboard/src/hooks/useQueries.ts
sopm-dashboard/src/hooks/useWebSocket.ts
sopm-dashboard/src/store/index.ts
sopm-dashboard/src/types/index.ts
sopm-dashboard/src/middleware.ts
```

Dashboard routes:

```text
/login              login screen
/register           registration screen
/                   overview dashboard
/functions          create/upload/list functions
/functions/[id]     function detail, versions, executions, execute button
/executions         execution list and drawer
/executions/[id]    full execution detail
/schedules          automation/schedules UI
/keys               API key management
/cluster            platform health and worker state
/logs               logs view
```

Frontend API client:

```text
sopm-dashboard/src/lib/api.ts
```

The API client defaults to:

```text
http://localhost:8000/api/v1
```

Override with:

```text
NEXT_PUBLIC_API_URL
```

WebSocket default:

```text
ws://localhost:8000
```

Override with:

```text
NEXT_PUBLIC_WS_URL
```

## 18. Frontend State and Data Fetching

Server state:

```text
sopm-dashboard/src/hooks/useQueries.ts
```

Uses TanStack Query for:

- Dashboard overview.
- Health.
- Metrics.
- Functions.
- Function detail.
- Executions.
- Execution logs.
- Schedules.

Local/app state:

```text
sopm-dashboard/src/store/index.ts
```

Uses Zustand for:

- Auth state.
- Token persistence.
- Username.
- WebSocket connection state.
- Live events.
- Live queue depth/executions.

Shell and auth gate:

```text
sopm-dashboard/src/components/layout/Providers.tsx
```

`Providers.tsx` prevents the dashboard shell/sidebar from rendering until client mount and token validation are complete. This fixed earlier hydration mismatch and unauthorized dashboard access.

## 19. Observability

Backend files:

```text
api/routers/health.py
api/routers/dashboard.py
api/services/dashboard_service.py
shared/observability/metrics.py
api/middleware/middleware.py
```

Health and metrics endpoints:

```text
/health
/ready
/metrics
/api/v1/health/detailed
/api/v1/dashboard
/api/v1/metrics/executions
/api/v1/metrics/workers
/api/v1/metrics/queue
/api/v1/metrics/deployments
```

Prometheus service scrapes metrics. Grafana is available on host port `3100`.

Worker availability is based on Redis heartbeat data.

## 20. WebSocket State

Backend:

```text
api/routers/dashboard.py
api/services/ws_manager.py
```

Frontend:

```text
sopm-dashboard/src/hooks/useWebSocket.ts
sopm-dashboard/src/store/index.ts
sopm-dashboard/src/components/layout/Providers.tsx
```

The frontend has a WebSocket bridge and displays connected/disconnected state in the sidebar. Most dashboard data still comes from polling queries. WebSocket live event support exists, but deeper worker/event broadcasting is not the primary reliable state path yet.

## 21. Current Known Local Behavior

Important local facts:

- Project is now at `C:\sopm`.
- Dashboard runs from `C:\sopm\sopm-dashboard`.
- Docker Compose runs from `C:\sopm\deploy\docker`.
- Grafana is on `localhost:3100`, not `localhost:3000`.
- Dashboard is on `localhost:3000`.
- API is on `localhost:8000`.
- Kubernetes reachability can appear degraded in local Docker because local dev is not actually using Kubernetes/gVisor execution.
- `migrate` exiting successfully is normal.
- `scheduler` must be running for dashboard schedules to actually trigger executions.

## 22. Recently Completed Fixes and Updates

Backend/Docker:

- Migration command standardized to `alembic upgrade head`.
- Migration chain and enum handling issues were fixed.
- Docker worker image includes scheduler code.
- Grafana moved to host port `3100` to avoid conflicting with the Next dashboard.
- Upload endpoint handles multipart fields correctly.
- Function version creation correctly updates `active_version_id` after the version row exists.
- Local sandbox-disabled mode now executes real uploaded ZIPs through `sandbox.runner` instead of returning a fake local-execution result.
- Runner supports `handler()`, `handler(event)`, and `handler(event, context)`.

Frontend:

- Login endpoint fixed to call the correct backend auth path.
- Auth state now writes both localStorage and cookie for middleware protection.
- Protected routes redirect to login instead of allowing bypass.
- App shell waits for client mount/auth validation to avoid hydration mismatch.
- Next 14 dynamic route params issue was fixed.
- Function upload UI was added and hardened.
- Upload failure handling improved.
- Execution logs response parsing fixed.
- Execution results now show a human summary and raw JSON.
- New `/schedules` automation page added.
- Schedules link added to sidebar.
- Schedule API helpers, query hooks, and frontend types added.

Validation after latest frontend schedule work:

```text
npm.cmd run type-check  passed
npm.cmd run build       passed
/schedules without auth redirects to /login?next=%2Fschedules
```

## 23. Important Debugging Paths

Auth issues:

```text
api/routers/auth.py
api/dependencies/deps.py
shared/security/auth.py
sopm-dashboard/src/store/index.ts
sopm-dashboard/src/lib/api.ts
sopm-dashboard/src/middleware.ts
sopm-dashboard/src/components/layout/Providers.tsx
```

Upload/versioning issues:

```text
api/routers/functions.py
shared/security/code_validator.py
shared/storage/artifact_storage.py
shared/db/models.py
sopm-dashboard/src/app/functions/page.tsx
```

Manual execution issues:

```text
api/routers/executions.py
shared/queue/redis_client.py
worker/worker.py
sandbox/k8s_sandbox.py
sandbox/runner.py
sopm-dashboard/src/app/executions/page.tsx
sopm-dashboard/src/app/executions/[id]/page.tsx
```

Automation/schedule issues:

```text
api/routers/schedules.py
scheduler/scheduler.py
shared/queue/redis_client.py
sopm-dashboard/src/app/schedules/page.tsx
sopm-dashboard/src/lib/api.ts
sopm-dashboard/src/hooks/useQueries.ts
```

Dashboard health/metrics issues:

```text
api/routers/dashboard.py
api/services/dashboard_service.py
sopm-dashboard/src/app/page.tsx
sopm-dashboard/src/app/cluster/page.tsx
```

Docker/local service issues:

```text
deploy/docker/docker-compose.yml
deploy/docker/Dockerfile.api
deploy/docker/Dockerfile.worker
deploy/docker/Dockerfile.runner
shared/config.py
```

Database/migration issues:

```text
migrations/env.py
migrations/versions/
shared/db/models.py
```

## 24. API Surface Summary

Auth:

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
```

Functions:

```text
GET    /api/v1/functions
POST   /api/v1/functions
GET    /api/v1/functions/{function_id}
DELETE /api/v1/functions/{function_id}
POST   /api/v1/functions/{function_id}/versions
GET    /api/v1/functions/{function_id}/versions
POST   /api/v1/functions/{function_id}/versions/{version_id}/activate
PATCH  /api/v1/functions/{function_id}/canary
GET    /api/v1/functions/{function_id}/activations
```

Executions:

```text
POST /api/v1/functions/{function_id}/execute
GET  /api/v1/executions                supports failure_kind filter
GET  /api/v1/executions/{execution_id}
GET  /api/v1/executions/{execution_id}/logs
```

Schedules:

```text
GET    /api/v1/schedules
POST   /api/v1/schedules?function_id={function_id}
GET    /api/v1/schedules/{schedule_id}
PATCH  /api/v1/schedules/{schedule_id}
DELETE /api/v1/schedules/{schedule_id}
```

API keys:

```text
GET    /api/v1/keys
POST   /api/v1/keys
DELETE /api/v1/keys/{key_id}
```

External invocation:

```text
POST /api/v1/invoke/{function_id}
POST /api/v1/invoke/{function_id}?wait=true&wait_timeout=5
```

External invoke uses the `X-SOPM-Key` header, not the dashboard JWT. API keys are shown only once at creation time; only the prefix/hash/metadata are stored afterward.

Health/dashboard:

```text
GET /health
GET /ready
GET /metrics
GET /api/v1/dashboard
GET /api/v1/health/detailed
GET /api/v1/metrics/executions
GET /api/v1/metrics/workers
GET /api/v1/metrics/queue
GET /api/v1/metrics/deployments
WS  /ws/dashboard
```

## 25. Security Notes

Implemented/current:

- JWT auth for dashboard/API users.
- API key auth for external invocation.
- Password hashing.
- Per-user ownership checks for functions, executions, schedules, and API keys.
- Protected frontend routes.
- ZIP validation and Python source checks.
- Artifact hashes/sizes stored with versions.
- API keys stored as SHA-256 hashes and returned only once.
- Kubernetes sandbox Job spec hardened for gVisor/non-root/no-capabilities/read-only-root.
- Runner service account has no app RoleBinding and does not mount a service account token.
- Sandbox NetworkPolicy allows DNS and MinIO artifact download only.
- Runner removes MinIO credentials before user handler import/execution.

Still requiring real-cluster validation:

- Install/confirm gVisor runsc on Kubernetes nodes.
- Apply `k8s/base/runtimeclass-gvisor.yaml`.
- Run a real execution with `SANDBOX_ENABLED=true`.
- Inspect the execution pod and confirm `Runtime Class Name: gvisor`.
- Run malicious test functions for network, filesystem, Kubernetes API, timeout, memory, and concurrency isolation.

Critical caveat:

Local Docker mode with `SANDBOX_ENABLED=false` runs uploaded code in the worker container. Do not treat this as safe for untrusted code.

## 26. Design Direction / North Star

SOPM is moving toward this control-plane / execution-plane split:

- FastAPI API: control plane and source-of-truth operations.
- PostgreSQL: durable metadata and results.
- Redis: queueing, heartbeat, coordination.
- MinIO/S3: immutable artifacts.
- Worker: stateless job consumer.
- Scheduler: stateless cron-to-execution enqueuer.
- Kubernetes/gVisor: real isolation boundary for untrusted code.
- Dashboard: operational console for users and operators.

The Kubernetes/gVisor execution path has been hardened in code and manifests, but the biggest remaining milestone is proving it on a real cluster with runsc/gVisor installed. Docker-local execution should remain a development fallback only.

## 27. Recommended Next Improvements

High value:

- Add Redis processing requeue controls and deeper DLQ operator visibility.
- Add better schedule history visibility in the dashboard.
- Add schedule edit support, not only create/pause/resume/delete.
- Add clearer per-function automation tab on function detail pages.
- Add end-to-end tests for upload -> execute -> result.
- Add end-to-end tests for schedule -> scheduler -> execution.
- Improve WebSocket event integration from worker/scheduler to dashboard.
- Validate Kubernetes/gVisor execution on a real cluster and capture pod inspection evidence.
- Add role/permission model if multi-user operations grow.

Medium value:

- Add copyable IDs and artifact metadata in the dashboard.
- Add structured DLQ view.
- Add worker drain/shutdown visibility.
- Add MinIO bucket bootstrap checks.
- Add richer upload validation errors in the UI.

## 28. Mental Model for New Engineers

When debugging, follow the object through the pipeline:

Function upload:

```text
Dashboard -> API functions router -> validator -> MinIO -> function_versions table -> active_version_id
```

Manual execution:

```text
Dashboard/API -> executions router -> executions table -> Redis queue -> worker -> runner -> executions/result/logs
```

Scheduled execution:

```text
Dashboard -> schedules API -> schedules table -> scheduler -> executions table -> Redis queue -> worker -> runner -> result/logs
```

Dashboard display:

```text
React page -> useQueries hook -> lib/api.ts -> FastAPI endpoint -> PostgreSQL/Redis/MinIO
```

Auth:

```text
Login -> JWT -> localStorage + cookie -> Next middleware + Axios Authorization -> FastAPI get_current_user
```

## 29. Latest Frontend Redesign State

A frontend redesign pass was applied after the original handoff. The goal was to reduce the old flat, border-heavy UI and make the manual execute -> result path much shorter.

New shared frontend components:

```text
sopm-dashboard/src/components/execution/ExecutionDrawer.tsx
sopm-dashboard/src/components/execution/ResultRenderer.tsx
sopm-dashboard/src/components/execution/CopyId.tsx
```

Current execution UX:

- `/functions` has an Execute action that opens a right-side drawer immediately after creating an execution.
- `/functions/[id]` uses the same drawer for Execute.
- Recent execution rows on `/functions/[id]` open the same drawer instead of routing away.
- `/executions` is still a history/list page, but selecting a row opens the drawer.
- `/executions/[id]` remains available as a direct URL fallback/detail page.
- Result display is human-first through the shared `ResultRenderer`.
- `ResultRenderer` renders messages, scalar fields, nested objects, primitive arrays, object arrays, and timestamp-like strings as structured UI.
- Raw JSON is available only behind an explicit collapsed `View raw JSON` disclosure.
- Logs are available behind an explicit collapsed `View logs` disclosure.
- Copyable ID affordances were added for function/execution IDs.

Theme changes:

```text
sopm-dashboard/tailwind.config.ts
sopm-dashboard/src/app/globals.css
sopm-dashboard/src/components/ui/index.tsx
```

The theme now has clearer surface layers:

```text
bg-base
bg-panel
bg-surface
bg-raised
bg-overlay
```

It also uses softer shadows/rings, rounder panel surfaces, more distinct badges, and clearer typography for page headings and primary values.

## 30. Latest Blank Screen / Next Dev Notes

A blank white screen was traced to frontend render/runtime behavior rather than the backend API.

Two fixes were made:

1. `Providers.tsx` now renders the login page immediately instead of returning `null` while auth validation runs. Protected pages still wait for auth validation, but they show a dark loading shell instead of an empty body.
2. `/login` was updated so `useSearchParams()` is wrapped inside a Suspense boundary. This fixed the Next.js production build error:

```text
useSearchParams() should be wrapped in a suspense boundary at page "/login"
```

Files changed:

```text
sopm-dashboard/src/components/layout/Providers.tsx
sopm-dashboard/src/app/login/page.tsx
```

Verification after the fix:

```text
npm.cmd run type-check  passed
npm.cmd run build       passed
```

If the browser shows this Next dev message:

```text
missing required components, refreshing
```

Use this cleanup from PowerShell:

```powershell
cd C:\sopm\sopm-dashboard
Get-NetTCPConnection -LocalPort 3000 -State Listen | ForEach-Object {
  Stop-Process -Id $_.OwningProcess -Force
}
Remove-Item -Recurse -Force .next
npm run dev
```

Then open:

```text
http://localhost:3000/login
```

Hard refresh with `Ctrl+Shift+R`. If it persists, clear site data/cookies for `localhost:3000` because stale auth state can interact badly with frontend shell changes during development.

## 31. Latest Phase 1 / Phase 2 State

Phase 1 execution/API-key work now exists across backend, frontend, runner, and CLI.

Key Phase 1 files:

```text
api/routers/keys.py
api/routers/invoke.py
migrations/versions/003_api_keys.py
shared/db/models.py
shared/queue/redis_client.py
sandbox/runner.py
sandbox/k8s_sandbox.py
cli/sopm.py
cli/__main__.py
sopm-dashboard/src/app/keys/page.tsx
sopm-dashboard/src/lib/api.ts
sopm-dashboard/src/hooks/useQueries.ts
```

Phase 1 behavior:

- Users can create/revoke API keys from `/keys`.
- External callers can invoke functions with `X-SOPM-Key` at `/api/v1/invoke/{function_id}`.
- `wait=true` can return the completed execution when it finishes before `wait_timeout`.
- Redis dequeue uses blocking pop instead of sleep polling.
- Frontend active execution polling is reduced to `250ms`.
- Local runner caches extracted artifacts/dependencies per version.
- Runner supports `requirements.txt` installs.
- Execution creation now commits before enqueueing to avoid the fast-worker race.
- A small CLI exists for login/deploy/invoke.

Phase 1 smoke results from local Docker:

```text
API-key invoke first run:  status=COMPLETED, request ~1002ms, worker duration 674ms
API-key invoke second run: status=COMPLETED, request ~369ms,  worker duration 261ms
Dashboard execute path:    status=COMPLETED, worker duration 235ms
```

Phase 2 isolation hardening now exists in code/manifests/docs.

Key Phase 2 files:

```text
sandbox/k8s_sandbox.py
sandbox/runner.py
k8s/base/runtimeclass-gvisor.yaml
k8s/base/network-policies.yaml
docs/K8S_GVISOR_ISOLATION.md
tests/unit/sandbox/test_k8s_sandbox.py
```

Phase 2 local verification completed:

```text
python -m py_compile sandbox/k8s_sandbox.py sandbox/runner.py tests/unit/sandbox/test_k8s_sandbox.py  passed
docker compose build worker scheduler                                                        passed
docker build -f deploy/docker/Dockerfile.runner . -t sopm/runner:phase2-check                 passed
```

Phase 2 validation not completed on this machine:

- `kubectl config current-context` reports no current context.
- `kubectl get runtimeclass` cannot reach a cluster.
- Local Python does not currently have `pytest`, so the new sandbox tests compile but were not executed here.
- No real pod has yet been inspected to prove `Runtime Class Name: gvisor`.

The next engineer should treat Phase 2 as implemented but not yet cluster-proven.
## 32. Latest Phase 3 State

Phase 3 rollback, canary, and queue resilience work is implemented across the backend, worker, scheduler, and dashboard.

Key Phase 3 backend files:

```text
api/routers/functions.py
api/routers/executions.py
api/routers/invoke.py
api/schemas/schemas.py
shared/db/models.py
shared/execution/version_routing.py
shared/config.py
worker/worker.py
scheduler/scheduler.py
migrations/versions/004_rollbacks_canary_queue.py
```

Key Phase 3 frontend files:

```text
sopm-dashboard/src/app/functions/[id]/page.tsx
sopm-dashboard/src/app/executions/page.tsx
sopm-dashboard/src/lib/api.ts
sopm-dashboard/src/hooks/useQueries.ts
sopm-dashboard/src/types/index.ts
```

New data model pieces:

- `functions.canary_version_id` points at an optional canary version.
- `functions.canary_percent` controls probabilistic routing to the canary.
- `executions.failure_kind` classifies failures without adding a new status.
- `version_activations` stores activation, rollback, canary, promote, and clear audit events.

New API behavior:

- `POST /api/v1/functions/{function_id}/versions/{version_id}/activate` activates or rolls back to a version and clears canary state.
- `PATCH /api/v1/functions/{function_id}/canary` sets, clears, or promotes canary traffic.
- `GET /api/v1/functions/{function_id}/activations` returns recent activation audit history.
- Manual execution, external invoke, and scheduled execution all use the shared version router.
- Every execution records the actual `function_version_id` selected at dispatch time.
- Queue enqueue failures are marked with `failure_kind="queue"`.
- Worker infra/runtime failures are marked with `failure_kind="infra"`.
- Handler/user-code failures are marked with `failure_kind="handler"`.
- Stale `RUNNING` executions are recovered to `FAILED` with an infra failure reason and system log.

Dashboard behavior:

- Function detail now shows version history with Activate actions.
- Function detail has canary controls for target version and percent.
- Executions list shows version IDs and failure kind.
- Executions list can filter infra/queue failures separately from handler failures.

Phase 3 local verification completed on July 26, 2026:

```text
python -m py_compile relevant backend files     passed
npm.cmd run type-check                          passed
npm.cmd run build                               passed
docker compose up -d --build migrate api worker scheduler  passed
Alembic 003_api_keys -> 004_rollbacks_canary_queue          passed
API health after rebuild                                      healthy
```

Phase 3 smoke test from local Docker:

```text
Created disposable function: 953630fb-b481-49a1-bfe9-5beb8ab90376
Uploaded v1:                 c49b4ba5-5299-4c00-bd38-ed55832b5629
Uploaded v2:                 8d1421ca-d761-44ff-aaee-31b025c4ab38
Activated/rolled back to v1: c49b4ba5-5299-4c00-bd38-ed55832b5629
Manual execution status:     COMPLETED
Execution version used:      c49b4ba5-5299-4c00-bd38-ed55832b5629
Execution result message:    phase3-v1
Canary set to v2 percent:    50
Activation audit rows seen:  2
failure_kind filter checked: /api/v1/executions?failure_kind=infra,queue
```

Remaining Phase 3 hardening ideas:

- Add an explicit dashboard panel for activation audit history instead of relying only on the function detail controls.
- Add deterministic canary distribution tests with seeded or injected routing randomness.
- Add a first-class DLQ/operator page if Redis dead-letter operations become part of normal operations.
## 33. Latest Phase 4 State

Phase 4 adds ephemeral raw-code execution and an agent-facing MCP server. The goal is to let an agent run one-off Python code without creating a persistent `Function` or uploading a ZIP, while still reusing SOPM's normal execution observability pipeline.

Key Phase 4 backend files:

```text
api/dependencies/api_keys.py
api/routers/ephemeral.py
api/routers/invoke.py
api/routers/executions.py
api/main.py
api/schemas/schemas.py
shared/config.py
shared/db/models.py
sandbox/runner.py
sandbox/k8s_sandbox.py
migrations/versions/005_ephemeral_executions.py
```

Key Phase 4 MCP/docs files:

```text
sopm_mcp/server.py
sopm_mcp/__init__.py
mcp/README.md
docs/AGENTS.md
README.md
pyproject.toml
```

New data model pieces:

- `executions.execution_type` identifies `function` versus `ephemeral` executions.
- `executions.api_key_id` records which API key submitted API-key/agent executions.
- Ephemeral executions use `function_id = null` and `function_version_id = null`.
- Ephemeral execution rows still use the same status, payload, result, logs, timeout, stale-recovery, and failure-kind behavior as persistent function executions.

New API behavior:

- `POST /api/v1/execute-ephemeral` accepts raw Python source via JSON body.
- The endpoint authenticates with `X-SOPM-Key`, matching `/api/v1/invoke`.
- It supports `wait=true` and `wait_timeout` for synchronous agent-style calls.
- It refuses to run when `SANDBOX_ENABLED=false` unless `EPHEMERAL_LOCAL_EXECUTION_ENABLED=true` is explicitly set.
- Per-key guardrails are configured through `EPHEMERAL_RATE_LIMIT_PER_MINUTE`, `EPHEMERAL_CONCURRENCY_LIMIT`, and `EPHEMERAL_MAX_CODE_BYTES`.
- `/api/v1/executions` now supports `source=function|ephemeral` and uses nullable-function ownership rules so ephemeral rows are visible to the triggering user.
- `/api/v1/invoke/functions` lets API-key clients discover persistent functions.
- `/api/v1/invoke/executions/{execution_id}` and `/logs` let API-key clients inspect executions they submitted.

Runner behavior:

- Normal persistent functions still use MinIO ZIP artifacts.
- Ephemeral jobs pass `source_code` through the queue to the sandbox runner.
- The runner detects `SOPM_SOURCE_CODE`, writes it to the module path implied by the entrypoint, and executes it through the same handler invocation logic.
- Kubernetes/gVisor jobs receive `SOPM_SOURCE_CODE` as an environment variable. Current request validation caps inline code size to keep this practical.

MCP behavior:

- `python -m sopm_mcp.server` starts the MCP server.
- `run_code` calls `/execute-ephemeral` and returns structured result/error/log fields.
- `invoke_function` calls persistent deployed functions by name or id.
- `list_functions` lists functions visible to the API key.

Dashboard behavior:

- `/executions` has a source filter: all, persistent functions, or ephemeral.
- The table shows `Ephemeral` and `inline code` for one-off raw-code executions.

Phase 4 verification completed on August 9, 2026:

```text
python -m py_compile relevant backend/runner/MCP files  passed
npm.cmd run type-check                                  passed
npm.cmd run build                                       passed
literal marker scan                                     passed
docker compose build scheduler                          passed
docker compose up -d --build migrate api worker scheduler passed
Alembic 004_rollbacks_canary_queue -> 005_ephemeral_executions passed
API /ready after rebuild                                healthy
MCP import inside API Docker image                       passed
```

Current Docker runtime state after the latest fix:

- Docker Desktop / WSL2 is working again on this machine.
- `migrate` applies revision `005_ephemeral_executions` and exits successfully.
- `api` is healthy on port `8000`.
- `worker` and `scheduler` are running.
- `postgres`, `redis`, and `minio` are healthy.
- The previous `pyproject.toml` UTF-8 BOM problem was fixed; keep `pyproject.toml` encoded as UTF-8 without BOM.
- `deploy/docker/Dockerfile.api` now copies `sopm_mcp/` into the runtime image so `python -m sopm_mcp.server` can import in Docker.
- `sopm_mcp/server.py` now uses the low-level `mcp 2.0.0` server API instead of the removed `mcp.server.fastmcp` import path.

Ephemeral execution smoke result:

- A test user and API key were created through the API.
- `POST /api/v1/execute-ephemeral?wait=true&wait_timeout=10` was called with `X-SOPM-Key`.
- Local Docker correctly returned `403` because `SANDBOX_ENABLED=false` and `EPHEMERAL_LOCAL_EXECUTION_ENABLED` is not set.
- This is expected safety behavior. Raw-code execution should not run in unsandboxed local mode unless explicitly opted in for trusted local testing.

Optional local-only positive smoke test:

1. Temporarily set this environment variable for `api` and `worker` in local Docker only:

```text
EPHEMERAL_LOCAL_EXECUTION_ENABLED=true
```

2. Restart the stack:

```powershell
cd C:\sopm\deploy\docker
docker compose up -d --build migrate api worker scheduler
```

3. Create an API key from `/keys`, then call:

```powershell
curl.exe -X POST "http://localhost:8000/api/v1/execute-ephemeral?wait=true&wait_timeout=10" `
  -H "Content-Type: application/json" `
  -H "X-SOPM-Key: sopm_your_key" `
  --data-raw "{\"code\":\"def handler(event, context):\\n    return {'message': 'hello from ephemeral', 'event': event}\\n\",\"event\":{\"name\":\"agent\"},\"timeout\":10,\"memory_mb\":128}"
```

4. Confirm the execution appears in `/executions` with source `Ephemeral`.

## 34. Latest Result Renderer / Network Check State

A result-renderer rebuild was applied on August 19, 2026.

Changed frontend files:

```text
sopm-dashboard/src/components/execution/ResultRenderer.tsx
sopm-dashboard/src/components/execution/ExecutionDrawer.tsx
sopm-dashboard/src/app/executions/[id]/page.tsx
```

Result renderer verification completed:

```text
npm.cmd run type-check  passed
npm.cmd run build       passed
```

A real structured test execution was created through the running backend:

```text
Execution ID: 07cd9df1-70a3-4ad3-ad72-e036ea4348f2
Status:       COMPLETED
Duration:     450ms
```

The execution result included:

```text
message:       Structured renderer verification complete
status:        ok
stats:         count, sum, mean, median, stdev
external_call: url, status_code, ok, content_type
tags:          renderer, structured, verified
samples:       two object rows, alpha and beta
```

Important verification caveat:

- The backend execution and frontend build were verified.
- Browser DOM inspection could not be completed from Codex because launching Edge headless was blocked by the tool approval/usage limit.
- The next visual QA pass should open `/executions/07cd9df1-70a3-4ad3-ad72-e036ea4348f2` or the same row from `/executions` and confirm the structured renderer visually.

Expected visual result:

- The message appears as prominent readable text.
- `stats` appears as a labeled card/table with five rows: count, sum, mean, median, stdev.
- `external_call` appears as a labeled card/table with url, status code, ok, and content type.
- `tags` appears as compact chips/list items.
- `samples` appears as a small table/card list.
- `View raw JSON` is present but collapsed by default.
- `View logs` is present but collapsed by default.

Network egress investigation from August 18, 2026:

- The worker image does not include `curl`, so `docker exec docker-worker-1 curl -v https://httpbin.org/uuid` fails with `curl` not found.
- Python HTTPS from inside `docker-worker-1` can reach the internet; `https://example.com` returned HTTP 200 with HTML.
- Running `sandbox.runner` inside the worker container also reached `https://example.com` and returned a successful `SOPM_RESULT`.
- `https://httpbin.org/uuid` timed out from the worker during testing.
- Conclusion: SOPM local runner networking is not the blocking layer. The observed `Expecting value: line 1 column 1 (char 0)` error is consistent with user code calling `.json()` on an empty/non-JSON response or an unreliable external endpoint response.

## 35. Optimization Pass - September 13, 2026

An evidence-based optimization pass was performed from `C:\sopm` after the project root moved from `W:\sopm`.

Changes applied:

```text
.dockerignore
README.md
deploy/docker/docker-compose.yml
sopm-dashboard/package.json
sopm-dashboard/package-lock.json
sopm-dashboard/src/hooks/useQueries.ts
sopm-dashboard/src/components/execution/ExecutionDrawer.tsx
sopm-dashboard/src/app/executions/[id]/page.tsx
sopm-dashboard/src/components/execution/ResultRenderer.tsx
```

What changed and why:

- Added a root `.dockerignore` so Docker builds no longer send local-only artifacts such as `.git`, `node_modules`, `.next`, Python caches, test caches, logs, temp output, and local env files into the build context.
- Moved Prometheus and Grafana behind the Compose profile `observability`. The default Docker stack now starts only the core platform services: `postgres`, `redis`, `minio`, `migrate`, `api`, `worker`, and `scheduler`. This also keeps the local dashboard's normal `3000` port separate from observability.
- Removed the obsolete Compose `version` key to avoid Compose v2 warnings.
- Changed execution-log polling so logs poll every 3 seconds only while the selected execution is live (`QUEUED`, `PENDING`, or `RUNNING`). Terminal executions now fetch logs but do not keep polling forever.
- Changed the result renderer so raw JSON is only stringified/rendered after `View raw JSON` is opened. The toggle remains collapsed by default.
- Removed confirmed-unused frontend dependencies from `sopm-dashboard/package.json`; `npm uninstall` removed 53 packages from the frontend install graph.

Measured or observed deltas:

```text
Default Compose services before: postgres, redis, minio, migrate, api, worker, scheduler, prometheus, grafana
Default Compose services after:  postgres, migrate, minio, redis, api, worker, scheduler
Observability profile adds:      prometheus, grafana
Terminal execution log polling:  from 1 request every 3s per open execution to no interval after initial fetch
Frontend dependency graph:       npm removed 53 packages
```

Verification performed:

```text
npm.cmd run type-check                                      passed
npm.cmd run build                                           passed
docker compose -f deploy/docker/docker-compose.yml config --services                    passed
docker compose -f deploy/docker/docker-compose.yml --profile observability config --services  passed
rg check for removed frontend packages in src/package.json  clean
```

Verification limitations:

- Docker Engine was not reachable from this shell, so image sizes and live container runtime checks could not be measured during this pass. Docker returned a missing pipe error for `docker images`.
- No API contract, auth rule, sandbox security control, execution semantics, database schema, or Kubernetes/gVisor behavior was intentionally changed.

Operational note:

- Normal local backend startup remains:

```powershell
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

- Optional observability startup is now:

```powershell
docker compose -f deploy/docker/docker-compose.yml --profile observability up -d prometheus grafana
```

## 36. Function Deletion Fix - September 13, 2026

Function deletion was traced end to end across the dashboard, API route, SQLAlchemy models, PostgreSQL relationship semantics, schedules, execution history, activation history, and MinIO artifact cleanup.

Root cause:

- The dashboard was calling `DELETE /api/v1/functions/{function_id}`, but the backend route relied on `db.delete(fn)` against a graph with circular and non-null relationships.
- `functions.active_version_id` and `functions.canary_version_id` point back to `function_versions`.
- `FunctionVersion.function_id`, `Schedule.function_id`, and `VersionActivation.function_id` are definition records that should be removed with the function.
- `Execution.function_id`, `Execution.function_version_id`, and `Execution.schedule_id` are historical links and are nullable in the schema, so execution/log history should be retained rather than deleted.
- Active queued/running executions need explicit handling; deleting their function/version while the worker may still use the artifact would create an inconsistent runtime state.

Deletion semantics now used:

```text
Function                 hard-deleted
FunctionVersion          hard-deleted
Schedule                 hard-deleted so scheduler cannot fire deleted functions
VersionActivation        hard-deleted with the deleted function definition
Execution                preserved, with function/version/schedule references detached
ExecutionLog             preserved with its execution
MinIO source.zip objects deleted for each removed function version
Active executions        block deletion with HTTP 409
Other users' functions   remain protected by owner-scoped lookup and return 404
Unauthenticated delete   remains protected by JWT dependency and returns 401
```

Backend changes:

- `api/routers/functions.py` now performs an ordered deletion instead of relying on ORM relationship cascade.
- It rejects deletion when any `PENDING`, `QUEUED`, or `RUNNING` execution exists for the function.
- It collects all version artifact paths before deleting version rows.
- It detaches preserved executions by setting `function_id`, `function_version_id`, and `schedule_id` to `NULL`.
- It clears active/canary version references before deleting versions.
- It deletes schedules, activation records, versions, and then the function definition.
- It deletes MinIO artifacts and reports a `502` if artifact cleanup fails instead of silently reporting success.

Frontend changes:

- `sopm-dashboard/src/hooks/useQueries.ts` now invalidates/removes all affected React Query caches after successful function deletion: function detail, versions, function list, execution list, schedules, and dashboard overview.
- `sopm-dashboard/src/app/functions/page.tsx` now tracks the currently deleting function id, prevents duplicate delete clicks, shows a per-row loading state, and displays useful success/error messages.
- Failed deletion keeps the function visible and restores the delete button.

Tests added/updated:

- Successful deletion.
- Nonexistent function deletion.
- Unauthorized deletion of another user's function.
- Function deletion with versions, schedules, executions, logs, and activation history.
- Active execution rejection.
- Artifact cleanup failure behavior.

Verification performed:

```text
python -m py_compile api\routers\functions.py tests\unit\api\test_functions.py  passed
npm.cmd run type-check                                                        passed
npm.cmd run build                                                             passed
```

Verification limitation:

- `python -m pytest tests/unit/api/test_functions.py -q` could not run because the available system Python does not have `pytest` installed.
- Docker Engine was not reachable earlier in this environment, so the full live Docker end-to-end delete flow was not run from Codex during this pass.

Final delete flow:

```text
Dashboard delete button
  -> DELETE /api/v1/functions/{function_id} with JWT
  -> owner-scoped backend lookup
  -> reject active executions if present
  -> detach preserved execution history
  -> remove schedules/version activations/function versions/function row
  -> delete version artifacts from MinIO
  -> React Query invalidates affected caches
  -> Functions dashboard refetches without the deleted function
```

## 37. Functions Health Indicator and Fixed Sidebar - September 13, 2026

Two dashboard UI/UX issues were addressed in `sopm-dashboard`.

Function health root cause:

- The Functions page health column was a hardcoded five-segment indicator.
- The color only depended on `fn.status === "ACTIVE"`, so a new function or a function with failed executions could still look fully healthy.
- No backend health API was needed because the frontend already has access to recent execution records through the existing `/executions` query path.

Function health logic now used:

```text
Input: recent `/executions` query, size 100, source=function
Per function: take up to 10 recent terminal records for that function
Terminal records considered: COMPLETED, FAILED, TIMED_OUT, CANCELLED

Unknown   no terminal execution history
Healthy   terminal history exists and all considered records are COMPLETED
Failing   more than half of considered records are problem statuses, or latest 3 are all problem statuses
Degraded  at least one problem status, but not enough to be Failing
```

Visual health change:

- The five green bars were removed.
- The health column now shows a compact labeled pill with an icon.
- `Healthy` uses success styling, `Degraded` uses warning styling, `Failing` uses error styling, and `Unknown` uses neutral styling.
- A newly created function with no execution history now shows `Unknown`, not fake full health.

Sidebar/layout root cause:

- The app shell used normal document flow: a flex row with `Sidebar` and `main` inside the page document.
- When dashboard content exceeded the viewport, the sidebar scrolled with the page, so Live status, current user, and logout could disappear.

Sidebar/layout implementation:

- Desktop sidebar is now fixed with `fixed inset-y-0 left-0`, full viewport height, and `md:flex`.
- Sidebar footer uses `mt-auto` so Live/current user/logout stay anchored at the bottom.
- Main content is independently scrollable with `h-screen overflow-y-auto` and offset with `md:ml-56` so it does not render under the fixed sidebar.
- Mobile keeps navigation usable through a fixed top header plus horizontal nav strip instead of forcing the desktop sidebar into a narrow viewport.

Files changed:

```text
sopm-dashboard/src/app/functions/page.tsx
sopm-dashboard/src/components/layout/Sidebar.tsx
sopm-dashboard/src/components/layout/Providers.tsx
PROJECT_HANDOFF.md
```

Verification performed:

```text
npm.cmd run type-check  passed
npm.cmd run build       passed
npm.cmd run lint        not configured; Next opened the interactive ESLint setup prompt
```

Runtime verification notes:

- `curl.exe -I http://localhost:3000/functions` returned a protected-route redirect to `/login?next=%2Ffunctions`, confirming the middleware auth guard is active.
- The process currently bound to host port `3000` is a stale/different Next process whose `/login` route returns a pages-router 404, so Codex could not complete a faithful browser visual check on port `3000` without stopping that process.
- A temporary dev server was started on `3001`, but the backend CORS config currently allows only `http://localhost:3000`, so browser login on `3001` is blocked by environment/CORS rather than by this UI code.

Manual visual verification after restarting the correct dashboard on `3000`:

1. Stop the stale process using port `3000`.
2. Start the real dashboard from `C:\sopm\sopm-dashboard` with `npm run dev`.
3. Sign in at `http://localhost:3000/login`.
4. Open `/functions` and confirm the health column shows `Unknown`, `Healthy`, `Degraded`, or `Failing` labels instead of five bars.
5. Open a tall page such as `/executions`, scroll the main content, and confirm the desktop sidebar, Live status, username, and logout remain visible.
6. Resize to mobile width and confirm the top mobile nav is usable without horizontal page overflow.
