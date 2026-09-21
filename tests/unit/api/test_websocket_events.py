import json
from unittest.mock import AsyncMock

from api.services import ws_manager as events


async def test_broadcast_removes_dead_connections_and_preserves_live_clients():
    manager = events.ConnectionManager()
    live, dead = AsyncMock(), AsyncMock()
    dead.send_text.side_effect = RuntimeError("closed")
    await manager.broadcast("empty", {})
    await manager.connect(live)
    await manager.connect(dead)
    assert manager.connection_count == 2
    await manager.broadcast("execution_started", {"execution_id": "id"})
    assert manager.connection_count == 1
    message = json.loads(live.send_text.call_args.args[0])
    assert message["type"] == "execution_started"
    assert message["payload"] == {"execution_id": "id"}
    assert message["timestamp"]
    await manager.disconnect(live)
    assert manager.connection_count == 0


async def test_event_payloads(monkeypatch):
    manager = AsyncMock()
    monkeypatch.setattr(events, "manager", manager)
    await events.emit_execution_started("e", "fn", "w")
    await events.emit_execution_completed("e", "fn", 12, "COMPLETED")
    await events.emit_execution_failed("e", "fn", "failed")
    await events.emit_deployment("fn", 2, "completed")
    await events.emit_worker_status("w", "online")
    await events.emit_queue_depth_changed(3)
    await events.emit_health_changed("redis", "healthy")
    calls = manager.broadcast.call_args_list
    assert [call.args[0] for call in calls] == [
        "execution_started",
        "execution_completed",
        "execution_failed",
        "deployment_completed",
        "worker_online",
        "queue_depth_changed",
        "health_changed",
    ]
    assert calls[1].args[1]["duration_ms"] == 12
    assert calls[2].args[1]["error"] == "failed"
    assert calls[5].args[1] == {"depth": 3}
