# Agent Quickstart

SOPM can be used as a sandboxed execution backend for AI agents. The agent can run raw Python once with `run_code`, or call persistent functions that already exist in SOPM.

## 1. Start SOPM

For local development, start the normal stack:

```powershell
cd C:\sopm
docker compose -f deploy/docker/docker-compose.yml up -d --build
```

## 2. Create an API Key

Open the dashboard, sign in, and create an API key from `/keys`.

The raw key is shown only once. Save it in the MCP server environment as `SOPM_API_KEY`.

## 3. Register the MCP Server

Use this MCP server command from `C:\sopm`:

```powershell
python -m sopm_mcp.server
```

Example MCP config:

```json
{
  "mcpServers": {
    "sopm": {
      "command": "python",
      "args": ["-m", "sopm_mcp.server"],
      "cwd": "C:\\sopm",
      "env": {
        "SOPM_API_URL": "http://localhost:8000",
        "SOPM_API_KEY": "sopm_your_api_key_here",
        "SOPM_MCP_WAIT_TIMEOUT": "10"
      }
    }
  }
}
```

## 4. Run Raw Code

Example tool call shape:

```json
{
  "code": "def handler(event, context):\n    return {'message': 'hello from agent', 'event': event}\n",
  "event": {"name": "SOPM"},
  "timeout": 10,
  "memory_mb": 128
}
```

Expected structured result shape:

```json
{
  "success": true,
  "status": "COMPLETED",
  "execution_type": "ephemeral",
  "result": {
    "success": true,
    "result": {
      "message": "hello from agent",
      "event": {"name": "SOPM"}
    }
  }
}
```

## 5. Error Cases

Timeouts return `status: TIMED_OUT` and `timed_out: true`.

Handler exceptions return `status: FAILED`, `failure_kind: handler`, and the handler error message.

Infrastructure or queue problems return `failure_kind: infra` or `failure_kind: queue` so an agent can distinguish retryable platform problems from bugs in generated code.

## Safety Gate

`POST /api/v1/execute-ephemeral` refuses to run when `SANDBOX_ENABLED=false` unless `EPHEMERAL_LOCAL_EXECUTION_ENABLED=true` is set.

That local override runs raw code in the worker container and is not a security boundary. Agent-facing raw-code execution should use the Kubernetes/gVisor sandbox path.

## Visibility

Ephemeral executions do not create `Function` or `FunctionVersion` rows. They do create normal `Execution` rows, so they appear in `/executions` and can be filtered as `Ephemeral` in the dashboard.
