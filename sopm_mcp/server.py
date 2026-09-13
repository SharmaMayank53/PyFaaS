"""MCP server exposing SOPM execution tools to agents."""
from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

SOPM_API_URL = os.environ.get("SOPM_API_URL", "http://localhost:8000").rstrip("/")
SOPM_API_KEY = os.environ.get("SOPM_API_KEY")
DEFAULT_WAIT_TIMEOUT = float(os.environ.get("SOPM_MCP_WAIT_TIMEOUT", "10"))


def _headers() -> dict[str, str]:
    if not SOPM_API_KEY:
        raise RuntimeError("SOPM_API_KEY is required")
    return {"X-SOPM-Key": SOPM_API_KEY}


def _api(path: str) -> str:
    return f"{SOPM_API_URL}/api/v1{path}"


def _structured_execution(execution: dict[str, Any], logs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    status = execution.get("status")
    result = execution.get("result") or {}
    success = status == "COMPLETED"
    return {
        "success": success,
        "status": status,
        "execution_id": execution.get("id"),
        "execution_type": execution.get("execution_type"),
        "function_id": execution.get("function_id"),
        "function_version_id": execution.get("function_version_id"),
        "result": result,
        "error": execution.get("error_message") or result.get("error"),
        "failure_kind": execution.get("failure_kind"),
        "timed_out": status == "TIMED_OUT" or bool(result.get("timed_out")),
        "duration_ms": execution.get("duration_ms") or result.get("duration_ms"),
        "logs": logs or [],
    }


async def _get_logs(client: httpx.AsyncClient, execution_id: str) -> list[dict[str, Any]]:
    response = await client.get(_api(f"/invoke/executions/{execution_id}/logs"), headers=_headers())
    response.raise_for_status()
    return response.json().get("logs", [])


async def run_code(
    code: str,
    event: dict[str, Any] | None = None,
    timeout: int = 30,
    memory_mb: int = 128,
    include_logs: bool = False,
) -> dict[str, Any]:
    """Run raw Python source once through SOPM ephemeral execution."""
    async with httpx.AsyncClient(timeout=timeout + DEFAULT_WAIT_TIMEOUT + 5) as client:
        response = await client.post(
            _api("/execute-ephemeral"),
            headers=_headers(),
            params={"wait": "true", "wait_timeout": DEFAULT_WAIT_TIMEOUT},
            json={
                "code": code,
                "event": event or {},
                "timeout": timeout,
                "memory_mb": memory_mb,
            },
        )
        response.raise_for_status()
        execution = response.json()
        logs: list[dict[str, Any]] = []
        if include_logs or execution.get("status") in {"FAILED", "TIMED_OUT", "CANCELLED"}:
            logs = await _get_logs(client, execution["id"])
        return _structured_execution(execution, logs)


async def list_functions() -> list[dict[str, Any]]:
    """List persistent SOPM functions available to this API key."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(_api("/invoke/functions"), headers=_headers())
        response.raise_for_status()
        return response.json().get("items", [])


async def invoke_function(
    function_name_or_id: str,
    event: dict[str, Any] | None = None,
    include_logs: bool = False,
) -> dict[str, Any]:
    """Invoke an existing persistent SOPM function by name or UUID."""
    async with httpx.AsyncClient(timeout=DEFAULT_WAIT_TIMEOUT + 15) as client:
        function_id = function_name_or_id
        if not _looks_like_uuid(function_name_or_id):
            functions = (await client.get(_api("/invoke/functions"), headers=_headers())).json().get("items", [])
            match = next((fn for fn in functions if fn.get("name") == function_name_or_id), None)
            if match is None:
                return {
                    "success": False,
                    "error": f"Function not found: {function_name_or_id}",
                    "available_functions": [fn.get("name") for fn in functions],
                }
            function_id = match["id"]

        response = await client.post(
            _api(f"/invoke/{function_id}"),
            headers=_headers(),
            params={"wait": "true", "wait_timeout": DEFAULT_WAIT_TIMEOUT},
            json={"payload": event or {}},
        )
        response.raise_for_status()
        execution = response.json()
        logs: list[dict[str, Any]] = []
        if include_logs or execution.get("status") in {"FAILED", "TIMED_OUT", "CANCELLED"}:
            logs = await _get_logs(client, execution["id"])
        return _structured_execution(execution, logs)


def _looks_like_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


TOOL_HANDLERS: dict[str, Callable[..., Awaitable[Any]]] = {
    "run_code": run_code,
    "list_functions": list_functions,
    "invoke_function": invoke_function,
}


def _tool_schemas() -> list[Tool]:
    return [
        Tool(
            name="run_code",
            description="Run raw Python source once through SOPM ephemeral execution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "event": {"type": "object", "additionalProperties": True},
                    "timeout": {"type": "integer", "default": 30},
                    "memory_mb": {"type": "integer", "default": 128},
                    "include_logs": {"type": "boolean", "default": False},
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="list_functions",
            description="List persistent SOPM functions available to this API key.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        Tool(
            name="invoke_function",
            description="Invoke an existing persistent SOPM function by name or UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "function_name_or_id": {"type": "string"},
                    "event": {"type": "object", "additionalProperties": True},
                    "include_logs": {"type": "boolean", "default": False},
                },
                "required": ["function_name_or_id"],
                "additionalProperties": False,
            },
        ),
    ]


async def _list_tools(_context, _params) -> ListToolsResult:
    return ListToolsResult(tools=_tool_schemas())


async def _call_tool(_context, params) -> CallToolResult:
    handler = TOOL_HANDLERS.get(params.name)
    if handler is None:
        return _tool_error(f"Unknown tool: {params.name}")

    try:
        result = await handler(**(params.arguments or {}))
    except Exception as exc:
        return _tool_error(str(exc))

    return CallToolResult(
        content=[TextContent(text=json.dumps(result, indent=2, default=str))],
        structuredContent=result,
    )


def _tool_error(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(text=message)], isError=True)


async def _run_stdio() -> None:
    server = Server("sopm", on_list_tools=_list_tools, on_call_tool=_call_tool)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_run_stdio)