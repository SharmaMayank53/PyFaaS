"""
SOPM - WebSocket Connection Manager

Manages dashboard WebSocket connections and broadcasts events.
Lightweight: in-process pub/sub, no external broker needed.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from shared.observability.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections for the dashboard.
    Thread-safe via asyncio primitives only (single-process assumption).
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("ws_client_connected", total=len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("ws_client_disconnected", total=len(self._connections))

    async def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event to all connected clients. Dead connections are removed."""
        if not self._connections:
            return

        message = json.dumps({
            "type": event_type,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        dead: set[WebSocket] = set()
        async with self._lock:
            connections = set(self._connections)

        results = await asyncio.gather(
            *[self._send_safe(ws, message) for ws in connections],
            return_exceptions=True,
        )

        for ws, result in zip(connections, results):
            if isinstance(result, Exception):
                dead.add(ws)

        if dead:
            async with self._lock:
                self._connections -= dead

    async def _send_safe(self, ws: WebSocket, message: str) -> None:
        await ws.send_text(message)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Global singleton
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Typed event emitters
# ---------------------------------------------------------------------------


async def emit_execution_started(execution_id: str, function_name: str | None, worker_id: str | None) -> None:
    await manager.broadcast("execution_started", {
        "execution_id": execution_id,
        "function_name": function_name,
        "worker_id": worker_id,
    })


async def emit_execution_completed(execution_id: str, function_name: str | None, duration_ms: int | None, status: str) -> None:
    await manager.broadcast("execution_completed", {
        "execution_id": execution_id,
        "function_name": function_name,
        "duration_ms": duration_ms,
        "status": status,
    })


async def emit_execution_failed(execution_id: str, function_name: str | None, error: str | None) -> None:
    await manager.broadcast("execution_failed", {
        "execution_id": execution_id,
        "function_name": function_name,
        "error": error,
    })


async def emit_deployment(function_name: str, version_number: int, status: str) -> None:
    await manager.broadcast(f"deployment_{status}", {
        "function_name": function_name,
        "version_number": version_number,
    })


async def emit_worker_status(worker_id: str, status: str) -> None:
    await manager.broadcast(f"worker_{status}", {"worker_id": worker_id})


async def emit_queue_depth_changed(depth: int) -> None:
    await manager.broadcast("queue_depth_changed", {"depth": depth})


async def emit_health_changed(component: str, status: str) -> None:
    await manager.broadcast("health_changed", {"component": component, "status": status})
