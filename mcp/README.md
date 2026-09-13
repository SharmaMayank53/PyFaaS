# SOPM MCP Server

SOPM includes a small MCP server that lets an agent call SOPM with tools instead of hand-writing HTTP requests.

The server is a thin client. It does not run code itself. It calls the SOPM API with the same `X-SOPM-Key` API-key auth used by `/api/v1/invoke`.

## Tools

- `run_code(code, event?, timeout?, memory_mb?, include_logs?)`
  - Calls `POST /api/v1/execute-ephemeral`.
  - Runs raw Python source once without creating a persistent Function.
  - Returns structured status, result, error, failure kind, duration, and optional logs.
- `invoke_function(function_name_or_id, event?, include_logs?)`
  - Calls an existing persistent SOPM function through `/api/v1/invoke/{function_id}`.
  - Resolves names through the API-key function list.
- `list_functions()`
  - Lists persistent functions visible to the API key.

## Environment

```powershell
$env:SOPM_API_URL = "http://localhost:8000"
$env:SOPM_API_KEY = "sopm_your_api_key_here"
$env:SOPM_MCP_WAIT_TIMEOUT = "10"
```

## Claude Code Example

Add a local MCP server entry that runs from the SOPM repo:

```json
{
  "mcpServers": {
    "sopm": {
      "command": "python",
      "args": ["-m", "sopm_mcp.server"],
      "cwd": "C:\\sopm",
      "env": {
        "SOPM_API_URL": "http://localhost:8000",
        "SOPM_API_KEY": "sopm_your_api_key_here"
      }
    }
  }
}
```

Install Python dependencies first:

```powershell
cd C:\sopm
python -m pip install -e .
```

## Safety Gate

`run_code` uses SOPM ephemeral execution. By default that endpoint requires `SANDBOX_ENABLED=true`, meaning the Kubernetes/gVisor path. Local Docker mode with `SANDBOX_ENABLED=false` refuses raw-code execution unless `EPHEMERAL_LOCAL_EXECUTION_ENABLED=true` is explicitly set.

That override is only for local testing. Do not use it for untrusted code.
