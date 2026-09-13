# PyFaaS Architecture

## Design Philosophy

PyFaaS is built on three guiding principles:

1. **Small surface area** — fewer components means fewer failure modes and less operational burden.
2. **Standard technology** — PostgreSQL, Redis, MinIO, Kubernetes. No proprietary systems.
3. **Defense in depth** — multiple independent security layers (AST validation + gVisor + NetworkPolicy + RBAC).

---

## Component Overview

### API Gateway (`api/`)

The only public-facing component. Built with FastAPI.

Responsibilities:
- JWT authentication and authorization
- Function CRUD and version management
- Execution triggering (enqueues to Redis)
- Schedule management
- Execution history and log retrieval
- Prometheus metrics endpoint

All user input is validated with Pydantic v2 schemas before processing.

### Function Registry (PostgreSQL)

Stores all platform state:
- Users and credentials (bcrypt hashed)
- Function metadata and versioning
- Execution records and state machine
- Schedules and cron expressions

Tables: `users`, `functions`, `function_versions`, `executions`, `execution_logs`, `schedules`

Schema is managed exclusively with Alembic — no auto-creation on startup.

### Artifact Storage (MinIO)

Object storage for function source archives (ZIP files).

Layout:
```
sopm-artifacts/
  functions/{function_id}/{version_id}/source.zip

sopm-packages/
  (reserved for pre-built package layers)
```

### Job Queue (Redis)

A sorted set (`sopm:queue`) acts as a priority queue.

- Score = `time.time() - priority * 1_000_000` (lower score = higher priority)
- Processing set (`sopm:processing`) tracks in-flight jobs
- Dead-letter queue (`sopm:dlq`) for permanently failed jobs
- Distributed locking for scheduler deduplication
- Worker heartbeats with TTL keys

### Worker (`worker/`)

Stateless processes that poll Redis and dispatch to Kubernetes.

Each worker:
1. Pops a job from the queue (atomic Lua script)
2. Marks execution as RUNNING in PostgreSQL
3. Creates a Kubernetes Job via the K8s API
4. Polls the Job until terminal state
5. Writes result and logs back to PostgreSQL
6. Acknowledges the job (removes from processing set)

One worker can handle N concurrent jobs (configurable via `WORKER_CONCURRENCY`).

### Sandbox (Kubernetes Jobs + gVisor)

Each execution runs in an isolated Kubernetes Job:

```yaml
spec:
  runtimeClassName: gvisor
  containers:
    - securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        readOnlyRootFilesystem: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
```

The runner container:
1. Downloads the function archive from MinIO
2. Extracts it to `/work` (emptyDir)
3. Dynamically imports the handler module
4. Calls `handler(payload)` with a SIGALRM timeout
5. Writes `SOPM_RESULT:{json}` to stdout
6. Exits

gVisor intercepts all syscalls, preventing kernel exploits even if the AST validator misses something.

### Scheduler (`scheduler/`)

A lightweight async process that polls PostgreSQL for due schedules.

Uses a Redis distributed lock (`sopm:scheduler:lock`) to ensure exactly one scheduler instance fires each schedule tick, even with multiple replicas running.

---

## State Machine

Execution states and valid transitions:

```
PENDING ──────────────────────────────────┐
   │                                       │
   ▼                                       │
QUEUED ────────────────────────────────── │ (CANCELLED)
   │                                       │
   ▼                                       │
RUNNING ──────────────────────────────── │
   │                                       │
   ├──▶ COMPLETED (terminal)              │
   ├──▶ FAILED    (terminal)              │
   ├──▶ TIMED_OUT (terminal)              │
   └──▶ CANCELLED (terminal) ◀───────────┘
```

Invalid transitions raise `ValueError` at the model layer.

---

## Data Flow: On-Demand Execution

```
Client
  │
  │ POST /api/v1/functions/{id}/execute
  ▼
API
  │ 1. Validate JWT + ownership
  │ 2. Look up active version
  │ 3. Create Execution(status=PENDING)
  │ 4. ZADD sopm:queue ...
  │ 5. Execution(status=QUEUED)
  │ 6. Return 202 {execution_id}
  ▼
Redis Queue
  │
  │ Worker polls
  ▼
Worker
  │ 1. ZPOPMIN → Execution(status=RUNNING)
  │ 2. BatchV1Api.create_namespaced_job(...)
  │ 3. Poll job until succeeded/failed
  │ 4. Fetch pod logs
  │ 5. Write result + logs to PostgreSQL
  │ 6. Execution(status=COMPLETED|FAILED|TIMED_OUT)
  │ 7. ZREM processing set
  ▼
PostgreSQL
```

---

## Security Layers

| Layer | Mechanism | Protects against |
|---|---|---|
| Input validation | Pydantic schemas | Malformed requests |
| Code validation | AST analysis | Obvious malicious code |
| Runtime isolation | gVisor | Kernel exploits |
| Process isolation | Kubernetes Job | Cross-tenant access |
| Network isolation | NetworkPolicy | Lateral movement |
| Privilege isolation | SecurityContext | Privilege escalation |
| Secret management | K8s Secrets | Credential exposure |

---

## Scalability Characteristics

| Component | Scaling approach |
|---|---|
| API | Horizontal (HPA on CPU) |
| Worker | Horizontal (more pods = more concurrent jobs) |
| Scheduler | Active/standby via distributed lock |
| PostgreSQL | Vertical + read replicas |
| Redis | Single instance (sentinel for HA) |
| MinIO | Horizontal (distributed mode) |

For a team of 5–20 engineers running hundreds of functions per day:
- 2 API replicas (2 cores / 512 MB each)
- 2–4 worker replicas (4 concurrent jobs each = 16 concurrent executions)
- 1 scheduler replica
- PostgreSQL: `db.t3.medium` or equivalent
- Redis: single instance, 1 GB RAM
- MinIO: 4 drives, 10 TB

---

## Technology Decisions

### Why FastAPI?
Async, fast, automatic OpenAPI docs, native Pydantic v2 support.

### Why PostgreSQL over a document store?
Relational integrity matters: functions, versions, executions, and logs have real relationships. JSONB columns handle flexible metadata where needed.

### Why Redis sorted set instead of a dedicated queue?
Redis is already in the stack (for locking and heartbeats). A sorted set gives priority queuing, atomic pop, and at-least-once delivery — enough for this scale without Kafka complexity.

### Why Kubernetes Jobs instead of a custom container runtime?
K8s Jobs give us free retry logic, timeout via `activeDeadlineSeconds`, automatic cleanup via `ttlSecondsAfterFinished`, and audit logs — with zero custom code.

### Why gVisor?
gVisor intercepts syscalls in userspace, providing a strong isolation boundary even for sophisticated kernel exploits. It's the industry standard for running untrusted code on Kubernetes.

### Why MinIO instead of S3?
Self-hosted. S3-compatible API means you can switch to S3 by changing an endpoint and credentials — no code changes.
