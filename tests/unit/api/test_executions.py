"""Tests for execution endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from shared.db.models import Function, FunctionVersion, User


class TestTriggerExecution:
    async def test_trigger_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        test_version: FunctionVersion,
        mock_redis,
    ) -> None:
        resp = await client.post(
            f"/api/v1/functions/{test_function.id}/execute",
            json={"payload": {"key": "value"}},
            headers=auth_headers,
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] in ("QUEUED", "FAILED")
        assert data["function_id"] == str(test_function.id)

    async def test_trigger_no_active_version(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        mock_redis,
    ) -> None:
        # test_function has no active_version_id set
        resp = await client.post(
            f"/api/v1/functions/{test_function.id}/execute",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_trigger_function_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict,
        mock_redis,
    ) -> None:
        import uuid

        resp = await client.post(
            f"/api/v1/functions/{uuid.uuid4()}/execute",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_trigger_payload_too_large(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        test_version: FunctionVersion,
        mock_redis,
    ) -> None:
        huge_payload = {"data": "x" * 2_000_000}
        resp = await client.post(
            f"/api/v1/functions/{test_function.id}/execute",
            json={"payload": huge_payload},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestListExecutions:
    async def test_list_empty(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        resp = await client.get("/api/v1/executions", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/executions")
        assert resp.status_code == 401


class TestCancelExecution:
    async def test_cancel_queued(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        test_version: FunctionVersion,
        mock_redis,
        db_session,
    ) -> None:
        import uuid
        from datetime import datetime, timezone

        from shared.db.models import Execution, ExecutionStatus

        # Create a QUEUED execution directly
        ex = Execution(
            id=uuid.uuid4(),
            function_id=test_function.id,
            function_version_id=test_version.id,
            status=ExecutionStatus.QUEUED,
            payload={},
            timeout=300,
            queued_at=datetime.now(timezone.utc),
        )
        db_session.add(ex)
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/executions/{ex.id}", headers=auth_headers
        )
        assert resp.status_code == 204

    async def test_cancel_completed_fails(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        test_version: FunctionVersion,
        mock_redis,
        db_session,
    ) -> None:
        import uuid
        from datetime import datetime, timezone

        from shared.db.models import Execution, ExecutionStatus

        ex = Execution(
            id=uuid.uuid4(),
            function_id=test_function.id,
            function_version_id=test_version.id,
            status=ExecutionStatus.COMPLETED,
            payload={},
            timeout=300,
            queued_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(ex)
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/executions/{ex.id}", headers=auth_headers
        )
        assert resp.status_code == 409
