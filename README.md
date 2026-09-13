# PyFaaS - Python Functions-as-a-Service Platform

PyFaaS is a self-hosted serverless platform for running Python functions from ZIP uploads. It includes a FastAPI backend, a Next.js dashboard, PostgreSQL, Redis, MinIO, workers, scheduling, API-key invocation, and Prometheus/Grafana monitoring.

The goal is simple: upload a Python function, run it on your own infrastructure, and inspect executions, structured results, and logs from a dashboard.

Compatibility note: some internal environment variables, API headers, Redis keys, package paths, and artifact prefixes still use the legacy SOPM/sopm names. Those identifiers are part of the current runtime contract and were kept stable during the rebrand.

## What It Does

- Upload Python functions as ZIP files
- Version functions, activate previous versions, and configure canary traffic
- Execute functions on demand from the dashboard or API
- Store execution results and logs
- Render common result structures as readable UI instead of raw JSON first
- Schedule functions with cron
- Invoke functions externally with API keys
- Show dashboard metrics, health, workers, queue state, and executions
- Expose Prometheus metrics
- Support a Kubernetes/gVisor sandbox path for production-style isolation

## Architecture

```text
Dashboard -> API -> PostgreSQL
              |
              +-> MinIO      stores uploaded ZIP artifacts
              |
              +-> Redis      queues execution jobs
                     |
                     v
                  Worker -> Runner/Sandbox -> PostgreSQL results/logs

Scheduler -> Redis queue
API keys  -> Invoke/Ephemeral API -> Redis queue
```

Main folders:

```text
api/             FastAPI backend
sopm-dashboard/  Next.js dashboard
worker/          execution worker
sandbox/         runner and Kubernetes sandbox logic
scheduler/       cron scheduler
shared/          database, auth, queue, storage, config
migrations/      Alembic migrations
deploy/docker/   local Docker stack
sopm_mcp/        MCP server for agent-facing execution
docs/            extra architecture/API/deployment notes
```

## Local Development

### 1. Start the backend stack

From the repository root:

```powershell
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

This starts the core local stack: PostgreSQL, Redis, MinIO, API, worker, scheduler, and the one-shot migration container.

The migration container exiting with code `0` is normal. It means Alembic finished successfully.

### 2. Start the dashboard

```powershell
cd sopm-dashboard
npm install
npm run dev
```

### 3. Open the app

```text
Dashboard:  http://localhost:3000
API:        http://localhost:8000
API docs:   http://localhost:8000/api/docs
MinIO:      http://localhost:9001
```

Port `3000` is for the Next.js dashboard.

### Optional observability

Prometheus and Grafana are behind the `observability` Compose profile:

```powershell
docker compose -f deploy/docker/docker-compose.yml --profile observability up -d prometheus grafana
```

Then open:

```text
Grafana:    http://localhost:3100
Prometheus: http://localhost:9090
```

Grafana uses host port `3100`, not `3000`.

## Create a User

```powershell
curl.exe -X POST http://localhost:8000/api/v1/auth/register `
  -H "Content-Type: application/json" `
  --data-raw "{\"username\":\"devadmin\",\"email\":\"devadmin@example.com\",\"password\":\"admin12345\"}"
```

Then sign in at:

```text
http://localhost:3000/login
```

## Function Format

Default entrypoint:

```text
handler.handler
```

Example `handler.py`:

```python
def handler(event, context):
    name = event.get("name", "world")
    return {
        "message": f"Hello, {name}!",
        "stats": {
            "count": 3,
            "success": True,
        },
    }
```

Zip the file and upload it from the dashboard's Functions page.

Supported handler styles:

```python
def handler():
    ...

def handler(event):
    ...

def handler(event, context):
    ...
```

## Results and Logs

Execution results are shown in a human-readable format first. Common fields like `message`, `status`, `stats`, `external_call`, timestamps, arrays, and small object lists are rendered as text, rows, chips, or tables.

Raw JSON is still available for debugging under `View raw JSON`, collapsed by default. Logs are also behind a collapsed `View logs` section.

## Automation

The dashboard page for cron automation is:

```text
http://localhost:3000/schedules
```

The `scheduler` service must be running for schedules to fire. In Docker Compose it runs:

```text
python -m scheduler.scheduler
```

## API Keys and Agent-Facing Execution

Create API keys from the dashboard at:

```text
http://localhost:3000/keys
```

API keys are used for external invocation:

```text
POST /api/v1/invoke/{function_id}
Header: X-SOPM-Key: <key>
```

PyFaaS also includes an MCP server for agents:

```powershell
python -m sopm_mcp.server
```

See:

- [Agent quickstart](docs/AGENTS.md)
- [MCP server guide](mcp/README.md)

Ephemeral raw-code execution exists at `POST /api/v1/execute-ephemeral`, but it is gated for safety. It requires the Kubernetes/gVisor sandbox path by default. Local unsandboxed testing requires `EPHEMERAL_LOCAL_EXECUTION_ENABLED=true` and should only be used with trusted code.

## Local Execution Note

In the Docker development stack, `SANDBOX_ENABLED=false`. That means uploaded functions run through the PyFaaS runner inside the worker container.

This is useful for local development, but it is not a security boundary. For untrusted production workloads, use the Kubernetes/gVisor sandbox path.

## Useful Commands

Check containers:

```powershell
docker compose -f deploy/docker/docker-compose.yml ps
```

Check API readiness:

```powershell
curl.exe http://localhost:8000/ready
```

Follow API logs:

```powershell
docker compose -f deploy/docker/docker-compose.yml logs -f api
```

Follow worker logs:

```powershell
docker compose -f deploy/docker/docker-compose.yml logs -f worker
```

Restart only the dashboard after frontend changes:

```powershell
cd sopm-dashboard
npm run dev
```

If the dashboard keeps showing stale development output:

```powershell
cd sopm-dashboard
Remove-Item -Recurse -Force .next
npm run dev
```

Run frontend checks:

```powershell
cd sopm-dashboard
npm run type-check
npm run build
```

## Troubleshooting

If Docker starts only `api`, `worker`, or `scheduler` but `/ready` says PostgreSQL or Redis cannot resolve, start the full dependency set again:

```powershell
docker compose -f deploy/docker/docker-compose.yml up -d postgres redis minio migrate api worker scheduler
```

If Docker Desktop/WSL is not running, `docker compose` may fail with a missing Docker pipe. Start Docker Desktop, wait for it to finish booting, then rerun the compose command.

Do not edit `pyproject.toml` with a tool that writes a UTF-8 BOM. The Docker Python build expects a normal UTF-8 file without BOM.

## More Docs

- [Project handoff](PROJECT_HANDOFF.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API reference](docs/API.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Security](docs/SECURITY.md)

## License

MIT