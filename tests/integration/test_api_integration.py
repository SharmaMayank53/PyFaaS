"""
Integration tests — full request/response cycle through the API.

These use in-memory SQLite and mock external services (Redis, MinIO, K8s).
They test multi-step workflows end to end.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient


def _make_valid_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "handler.py",
            "def handler(event):\n    return {'message': 'hello', 'input': event}\n",
        )
    return buf.getvalue()


class TestFullFunctionLifecycle:
    """
    Register → create function → upload version → trigger execution → check history.
    """

    async def test_full_lifecycle(
        self,
        client: AsyncClient,
        mock_redis: AsyncMock,
        mock_storage: MagicMock,
    ) -> None:
        # 1. Register user
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": f"user_{uuid.uuid4().hex[:8]}",
                "email": f"{uuid.uuid4().hex[:8]}@test.com",
                "password": "strongpassword123",
            },
        )
        assert reg_resp.status_code == 201

        # 2. Login
        login_resp = await client.post(
            "/api/v1/auth/login",
            data={
                "username": reg_resp.json()["username"],
                "password": "strongpassword123",
            },
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Create function
        fn_resp = await client.post(
            "/api/v1/functions",
            json={"name": "integration-test-fn", "description": "Integration test"},
            headers=headers,
        )
        assert fn_resp.status_code == 201
        function_id = fn_resp.json()["id"]

        # 4. Upload version
        archive = _make_valid_zip()
        ver_resp = await client.post(
            f"/api/v1/functions/{function_id}/versions",
            headers=headers,
            files={"archive": ("source.zip", archive, "application/zip")},
            data={"entrypoint": "handler.handler", "timeout": "60"},
        )
        assert ver_resp.status_code == 201
        assert ver_resp.json()["id"]

        # 5. Trigger execution
        exec_resp = await client.post(
            f"/api/v1/functions/{function_id}/execute",
            json={"payload": {"name": "world"}},
            headers=headers,
        )
        assert exec_resp.status_code == 202
        execution_id = exec_resp.json()["id"]
        assert exec_resp.json()["function_id"] == function_id
        assert exec_resp.json()["status"] == "QUEUED"
        mock_redis.zadd.assert_awaited_once()

        # 6. Check execution history
        hist_resp = await client.get(
            f"/api/v1/executions?function_id={function_id}",
            headers=headers,
        )
        assert hist_resp.status_code == 200
        assert hist_resp.json()["total"] >= 1

        # 7. Get specific execution
        get_exec_resp = await client.get(
            f"/api/v1/executions/{execution_id}",
            headers=headers,
        )
        assert get_exec_resp.status_code == 200
        assert get_exec_resp.json()["id"] == execution_id

        # 8. Get execution logs (empty — no worker ran)
        logs_resp = await client.get(
            f"/api/v1/executions/{execution_id}/logs",
            headers=headers,
        )
        assert logs_resp.status_code == 200
        assert "logs" in logs_resp.json()

        # 9. List versions
        vers_resp = await client.get(
            f"/api/v1/functions/{function_id}/versions",
            headers=headers,
        )
        assert vers_resp.status_code == 200
        assert vers_resp.json()["total"] == 1

        # 10. Queued executions prevent deletion. No worker runs in this test,
        # so cancel the execution before deleting the function.
        blocked = await client.delete(f"/api/v1/functions/{function_id}", headers=headers)
        assert blocked.status_code == 409
        cancelled = await client.delete(f"/api/v1/executions/{execution_id}", headers=headers)
        assert cancelled.status_code == 204
        execution = await client.get(f"/api/v1/executions/{execution_id}", headers=headers)
        assert execution.json()["status"] == "CANCELLED"

        # 11. Delete function
        del_resp = await client.delete(
            f"/api/v1/functions/{function_id}",
            headers=headers,
        )
        assert del_resp.status_code == 204


class TestScheduleLifecycle:
    async def test_create_and_manage_schedule(
        self,
        client: AsyncClient,
        mock_redis: AsyncMock,
        mock_storage: MagicMock,
    ) -> None:
        # Register and login
        username = f"sched_{uuid.uuid4().hex[:8]}"
        await client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": f"{username}@test.com", "password": "pass12345"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": username, "password": "pass12345"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # Create function
        fn = await client.post(
            "/api/v1/functions",
            json={"name": "scheduled-fn"},
            headers=headers,
        )
        function_id = fn.json()["id"]

        # Create schedule
        sched_resp = await client.post(
            "/api/v1/schedules",
            params={"function_id": function_id},
            json={
                "name": "nightly",
                "cron_expression": "0 2 * * *",
                "payload": {"mode": "nightly"},
            },
            headers=headers,
        )
        assert sched_resp.status_code == 201
        sched_id = sched_resp.json()["id"]
        assert sched_resp.json()["cron_expression"] == "0 2 * * *"
        assert sched_resp.json()["status"] == "ACTIVE"

        # List schedules
        list_resp = await client.get("/api/v1/schedules", headers=headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1

        # Pause schedule
        update_resp = await client.patch(
            f"/api/v1/schedules/{sched_id}",
            json={"status": "PAUSED"},
            headers=headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "PAUSED"

        # Delete schedule
        del_resp = await client.delete(f"/api/v1/schedules/{sched_id}", headers=headers)
        assert del_resp.status_code == 204


class TestHealthEndpoints:
    async def test_liveness(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_readiness_with_db(self, client: AsyncClient, db_session) -> None:
        # DB is in-memory SQLite; Redis mock may fail but that's degraded not unhealthy
        with (
            patch("api.routers.health.get_redis") as mock_redis_factory,
            patch("api.routers.health.AsyncSessionLocal") as session_factory,
        ):
            session_factory.return_value.__aenter__.return_value = db_session
            redis_mock = AsyncMock()
            redis_mock.ping = AsyncMock(return_value=True)
            redis_mock.aclose = AsyncMock()
            mock_redis_factory.return_value = redis_mock
            resp = await client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["checks"]["database"] == "ok"

    async def test_metrics_endpoint(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics")
        assert resp.status_code == 200
        assert "sopm_" in resp.text


class TestSecurityBoundaries:
    async def test_cannot_access_other_users_function(
        self,
        client: AsyncClient,
        mock_storage: MagicMock,
    ) -> None:
        # Create two users
        for username in ["alice", "bob"]:
            await client.post(
                "/api/v1/auth/register",
                json={
                    "username": username,
                    "email": f"{username}@test.com",
                    "password": "pass12345",
                },
            )

        def _login(username: str):
            return client.post(
                "/api/v1/auth/login",
                data={"username": username, "password": "pass12345"},
            )

        alice_login = await _login("alice")
        bob_login = await _login("bob")
        alice_headers = {"Authorization": f"Bearer {alice_login.json()['access_token']}"}
        bob_headers = {"Authorization": f"Bearer {bob_login.json()['access_token']}"}

        # Alice creates a function
        fn_resp = await client.post(
            "/api/v1/functions",
            json={"name": "alice-private-fn"},
            headers=alice_headers,
        )
        alice_fn_id = fn_resp.json()["id"]

        # Bob tries to access Alice's function → 404 (not 403 to avoid enumeration)
        resp = await client.get(f"/api/v1/functions/{alice_fn_id}", headers=bob_headers)
        assert resp.status_code == 404

        # Bob tries to delete Alice's function
        resp = await client.delete(f"/api/v1/functions/{alice_fn_id}", headers=bob_headers)
        assert resp.status_code == 404

    async def test_invalid_cron_expression_rejected(
        self, client: AsyncClient, mock_storage: MagicMock
    ) -> None:
        await client.post(
            "/api/v1/auth/register",
            json={"username": "crontest", "email": "cron@test.com", "password": "pass12345"},
        )
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": "crontest", "password": "pass12345"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        fn = await client.post("/api/v1/functions", json={"name": "cron-fn"}, headers=headers)

        bad_cron_resp = await client.post(
            "/api/v1/schedules",
            params={"function_id": fn.json()["id"]},
            json={"name": "bad-sched", "cron_expression": "not a cron", "payload": {}},
            headers=headers,
        )
        assert bad_cron_resp.status_code == 422
