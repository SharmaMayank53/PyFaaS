# SOPM API Reference

Base URL: `https://sopm.yourdomain.com/api/v1`

Interactive docs: `GET /api/docs` (Swagger UI)

All endpoints except `/health`, `/ready`, and `/metrics` require authentication.

---

## Authentication

### `POST /auth/register`

Register a new user.

**Request:**
```json
{
  "username": "alice",
  "email": "alice@example.com",
  "password": "mypassword"
}
```

**Response `201`:**
```json
{
  "id": "uuid",
  "username": "alice",
  "email": "alice@example.com",
  "is_active": true,
  "is_superuser": false,
  "created_at": "2024-01-01T00:00:00Z"
}
```

---

### `POST /auth/login`

Obtain access and refresh tokens.

**Request** (form-encoded):
```
username=alice&password=mypassword
```

**Response `200`:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

---

### `POST /auth/refresh`

Refresh an expired access token.

**Request:**
```json
{ "refresh_token": "eyJ..." }
```

**Response `200`:** Same as login.

---

### `GET /auth/me`

Get the current user.

**Response `200`:** User object.

---

## Functions

### `GET /functions`

List functions for the authenticated user.

**Query params:**
- `page` (int, default 1)
- `page_size` (int, default 20, max 100)
- `status` (ACTIVE | INACTIVE | DEPRECATED)

**Response `200`:**
```json
{
  "items": [...],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

---

### `POST /functions`

Create a function.

**Request:**
```json
{
  "name": "my-function",
  "description": "Does something useful",
  "tags": {"team": "ml", "env": "prod"}
}
```

**Response `201`:** Function object.

**Validation:**
- Name: letters, numbers, hyphens, underscores; must start with letter; max 128 chars
- Max 100 functions per user (active/inactive)

---

### `GET /functions/{function_id}`

Get a function.

---

### `PATCH /functions/{function_id}`

Update function metadata.

**Request (all fields optional):**
```json
{
  "description": "Updated",
  "status": "INACTIVE",
  "tags": {"k": "v"}
}
```

---

### `DELETE /functions/{function_id}`

Delete a function and all its versions and artifacts.

**Response `204`**

---

## Function Versions

### `POST /functions/{function_id}/versions`

Upload a new version. **Multipart form.**

**Form fields:**
- `archive` (file, required) — ZIP archive containing Python source
- `entrypoint` (string, default `handler.handler`) — `module.function` path
- `timeout` (int, default 300, max 3600) — seconds
- `memory_mb` (int, default 128, max 3072)
- `change_notes` (string, optional)

**ZIP requirements:**
- Must contain at least one `.py` file
- Max 10 MB
- No path traversal (`..`)
- Code must pass AST security validation

**Response `201`:** Version object.

---

### `GET /functions/{function_id}/versions`

List all versions for a function.

---

### `GET /functions/{function_id}/versions/{version_id}`

Get a specific version.

---

### `POST /functions/{function_id}/versions/{version_id}/activate`

Set a version as the active (default) version for execution.

---

## Executions

### `POST /functions/{function_id}/execute`

Trigger an execution. Returns immediately with status `QUEUED`.

**Request:**
```json
{
  "payload": {"key": "value"},
  "version_id": "uuid (optional — defaults to active version)",
  "timeout": 60
}
```

**Response `202`:**
```json
{
  "id": "uuid",
  "function_id": "uuid",
  "function_version_id": "uuid",
  "status": "QUEUED",
  "payload": {"key": "value"},
  "result": null,
  "error_message": null,
  "queued_at": "2024-01-01T00:00:00Z",
  "started_at": null,
  "completed_at": null,
  "duration_ms": null,
  "created_at": "2024-01-01T00:00:00Z"
}
```

**Poll** `GET /executions/{id}` until status is terminal.

---

### `GET /executions`

List executions.

**Query params:**
- `function_id` (uuid, optional)
- `status` (PENDING | QUEUED | RUNNING | COMPLETED | FAILED | TIMED_OUT | CANCELLED)
- `page`, `page_size`

---

### `GET /executions/{execution_id}`

Get execution details including result.

**Completed execution:**
```json
{
  "id": "uuid",
  "status": "COMPLETED",
  "result": {"message": "hello", "input": {"key": "value"}},
  "duration_ms": 234,
  "completed_at": "2024-01-01T00:00:05Z"
}
```

---

### `GET /executions/{execution_id}/logs`

Get execution logs.

**Query params:**
- `limit` (int, default 500, max 5000)
- `offset` (int, default 0)

**Response:**
```json
{
  "execution_id": "uuid",
  "total": 42,
  "logs": [
    {
      "id": "uuid",
      "timestamp": "2024-01-01T00:00:01Z",
      "level": "INFO",
      "stream": "stdout",
      "message": "[sopm-runner] executing handler.handler",
      "sequence": 0
    }
  ]
}
```

---

### `DELETE /executions/{execution_id}`

Cancel a PENDING or QUEUED execution. Running executions cannot be cancelled via API (they have their own timeout).

**Response `204`**

---

## Schedules

### `POST /schedules?function_id={uuid}`

Create a cron schedule.

**Request:**
```json
{
  "name": "nightly-report",
  "cron_expression": "0 2 * * *",
  "payload": {"mode": "full"}
}
```

**Response `201`:** Schedule object.

---

### `GET /schedules`

List schedules.

---

### `GET /schedules/{schedule_id}`

Get schedule details.

---

### `PATCH /schedules/{schedule_id}`

Update schedule. Pause it with `"status": "PAUSED"`.

---

### `DELETE /schedules/{schedule_id}`

Delete schedule.

---

## Platform

### `GET /health`

Liveness probe. Returns 200 if the process is running.

### `GET /ready`

Readiness probe. Checks database and Redis connectivity.

**Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

### `GET /metrics`

Prometheus metrics in text exposition format.

---

## Error Responses

All errors follow this format:

```json
{
  "error": "Human readable message",
  "detail": "Optional additional detail",
  "request_id": "uuid"
}
```

| Status | Meaning |
|---|---|
| 400 | Bad request |
| 401 | Not authenticated |
| 403 | Not authorized |
| 404 | Resource not found |
| 409 | Conflict (duplicate name, invalid state transition) |
| 413 | Payload too large |
| 422 | Validation error (security, schema) |
| 429 | Rate limit / quota exceeded |
| 500 | Internal error |
