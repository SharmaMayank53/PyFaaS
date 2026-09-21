import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from api.routers import ephemeral, invoke


@pytest_asyncio.fixture
async def key_headers(client, auth_headers):
    response = await client.post("/api/v1/keys", headers=auth_headers, json={"name": "automation"})
    assert response.status_code == 201
    return {"X-SOPM-Key": response.json()["key"]}


@pytest.fixture
def queue(monkeypatch):
    redis = AsyncMock()
    redis.incr.return_value = 1
    enqueue = AsyncMock()
    for module in (invoke, ephemeral):
        monkeypatch.setattr(module, "get_redis", lambda: redis)
        monkeypatch.setattr(module, "enqueue_job", enqueue)
    return redis, enqueue


async def test_key_lifecycle_and_revocation(client, auth_headers, test_function):
    created = await client.post("/api/v1/keys", headers=auth_headers, json={"name": "test"})
    key = created.json()
    headers = {"X-SOPM-Key": key["key"]}
    listed = await client.get("/api/v1/keys", headers=auth_headers)
    assert listed.status_code == 200
    assert "key" not in listed.json()[0]
    functions = await client.get("/api/v1/invoke/functions", headers=headers)
    assert functions.json()["items"][0]["id"] == str(test_function.id)
    assert (
        await client.delete(f"/api/v1/keys/{key['id']}", headers=auth_headers)
    ).status_code == 204
    assert (await client.get("/api/v1/invoke/functions", headers=headers)).status_code == 401
    assert (await client.get("/api/v1/invoke/functions")).status_code == 401
    assert (
        await client.delete(f"/api/v1/keys/{uuid.uuid4()}", headers=auth_headers)
    ).status_code == 404


@pytest.mark.parametrize("queue_fails", [False, True])
async def test_invoke_and_inspect_execution(client, key_headers, test_version, queue, queue_fails):
    redis, enqueue = queue
    if queue_fails:
        enqueue.side_effect = RuntimeError("queue offline")
    response = await client.post(
        f"/api/v1/invoke/{test_version.function_id}?wait=true&wait_timeout=0.1",
        headers=key_headers,
        json={"payload": {"value": 3}},
    )
    assert response.status_code == 202
    execution = response.json()
    assert execution["status"] == ("FAILED" if queue_fails else "QUEUED")
    assert enqueue.call_args.args[2]["artifact_path"] == test_version.artifact_path
    if queue_fails:
        assert execution["failure_kind"] == "queue"
    fetched = await client.get(f"/api/v1/invoke/executions/{execution['id']}", headers=key_headers)
    assert fetched.json()["id"] == execution["id"]
    logs = await client.get(
        f"/api/v1/invoke/executions/{execution['id']}/logs", headers=key_headers
    )
    assert logs.status_code == 200
    assert logs.json()["logs"] == []
    redis.aclose.assert_awaited_once()


async def test_invoke_missing_resources(client, key_headers, test_function):
    function_id = str(test_function.id)
    response = await client.post(f"/api/v1/invoke/{function_id}", headers=key_headers, json={})
    assert response.status_code == 422
    assert (
        await client.post(f"/api/v1/invoke/{uuid.uuid4()}", headers=key_headers, json={})
    ).status_code == 404
    for suffix in ("", "/logs"):
        response = await client.get(
            f"/api/v1/invoke/executions/{uuid.uuid4()}{suffix}", headers=key_headers
        )
        assert response.status_code == 404


@pytest.mark.parametrize("queue_fails", [False, True])
async def test_ephemeral_queues_source_and_records_failures(
    client, key_headers, queue, monkeypatch, queue_fails
):
    monkeypatch.setattr(ephemeral.settings, "sandbox_enabled", True)
    redis, enqueue = queue
    if queue_fails:
        enqueue.side_effect = RuntimeError("offline")
    response = await client.post(
        "/api/v1/execute-ephemeral?wait=true&wait_timeout=0.1",
        headers=key_headers,
        json={"code": "def handler(event): return event", "event": {"x": 1}},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["execution_type"] == "ephemeral"
    assert data["function_id"] is None
    assert data["status"] == ("FAILED" if queue_fails else "QUEUED")
    assert enqueue.call_args.args[2]["source_code"] == "def handler(event): return event"
    redis.expire.assert_awaited_once()
    redis.aclose.assert_awaited_once()


async def test_ephemeral_gate_limits_and_validation(client, key_headers, queue, monkeypatch):
    body = {"code": "def handler(): return 1"}
    monkeypatch.setattr(ephemeral.settings, "sandbox_enabled", False)
    monkeypatch.setattr(ephemeral.settings, "ephemeral_local_execution_enabled", False)
    assert (
        await client.post("/api/v1/execute-ephemeral", headers=key_headers, json=body)
    ).status_code == 403
    monkeypatch.setattr(ephemeral.settings, "ephemeral_local_execution_enabled", True)
    redis, enqueue = queue
    redis.incr.return_value = ephemeral.settings.ephemeral_rate_limit_per_minute + 1
    assert (
        await client.post("/api/v1/execute-ephemeral", headers=key_headers, json=body)
    ).status_code == 429
    redis.incr.return_value = 1
    monkeypatch.setattr(ephemeral.settings, "ephemeral_concurrency_limit", 0)
    assert (
        await client.post("/api/v1/execute-ephemeral", headers=key_headers, json=body)
    ).status_code == 429
    enqueue.assert_not_awaited()
    monkeypatch.setattr(ephemeral.settings, "ephemeral_max_code_bytes", 1)
    assert (
        await client.post("/api/v1/execute-ephemeral", headers=key_headers, json=body)
    ).status_code == 422
    monkeypatch.setattr(ephemeral.settings, "max_payload_size_bytes", 1)
    assert (
        await client.post(
            "/api/v1/execute-ephemeral", headers=key_headers, json={"code": "x", "event": {"x": 1}}
        )
    ).status_code == 422
