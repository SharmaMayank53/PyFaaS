"""Tests for function management endpoints."""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import (
    Execution,
    ExecutionLog,
    ExecutionStatus,
    Function,
    FunctionVersion,
    Schedule,
    User,
    VersionActivation,
)
from shared.security.auth import create_access_token


def _make_zip(source: str = "def handler(event):\n    return {'ok': True}\n") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("handler.py", source)
    return buf.getvalue()


class TestFunctionCRUD:
    async def test_create_function(
        self, client: AsyncClient, auth_headers: dict, mock_storage
    ) -> None:
        resp = await client.post(
            "/api/v1/functions",
            json={"name": "my-fn", "description": "A function"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "my-fn"
        assert data["status"] == "ACTIVE"

    async def test_create_function_duplicate(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
    ) -> None:
        resp = await client.post(
            "/api/v1/functions",
            json={"name": test_function.name},
            headers=auth_headers,
        )
        assert resp.status_code == 409

    async def test_list_functions(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
    ) -> None:
        resp = await client.get("/api/v1/functions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(f["id"] == str(test_function.id) for f in data["items"])

    async def test_get_function(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
    ) -> None:
        resp = await client.get(
            f"/api/v1/functions/{test_function.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == str(test_function.id)

    async def test_get_function_not_found(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        import uuid

        resp = await client.get(
            f"/api/v1/functions/{uuid.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404

    async def test_update_function(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
    ) -> None:
        resp = await client.patch(
            f"/api/v1/functions/{test_function.id}",
            json={"description": "Updated description"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated description"

    async def test_delete_function(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        test_version: FunctionVersion,
        mock_storage,
    ) -> None:
        resp = await client.delete(
            f"/api/v1/functions/{test_function.id}", headers=auth_headers
        )
        assert resp.status_code == 204

        # Verify deleted
        resp2 = await client.get(
            f"/api/v1/functions/{test_function.id}", headers=auth_headers
        )
        assert resp2.status_code == 404


    async def test_delete_function_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict,
        mock_storage,
    ) -> None:
        resp = await client.delete(
            f"/api/v1/functions/{uuid.uuid4()}", headers=auth_headers
        )
        assert resp.status_code == 404
        mock_storage.delete_artifact.assert_not_called()

    async def test_delete_function_rejects_other_owner(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_function: Function,
        mock_storage,
    ) -> None:
        other = User(
            id=uuid.uuid4(),
            username="other",
            email="other@example.com",
            hashed_password="hashed",
            is_active=True,
        )
        db_session.add(other)
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/functions/{test_function.id}",
            headers={"Authorization": f"Bearer {create_access_token(str(other.id))}"},
        )
        assert resp.status_code == 404
        mock_storage.delete_artifact.assert_not_called()

    async def test_delete_function_with_related_records(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        test_user: User,
        test_function: Function,
        test_version: FunctionVersion,
        mock_storage,
    ) -> None:
        schedule = Schedule(
            id=uuid.uuid4(),
            function_id=test_function.id,
            owner_id=test_user.id,
            name="delete-me",
            cron_expression="*/5 * * * *",
            payload={},
        )
        execution = Execution(
            id=uuid.uuid4(),
            function_id=test_function.id,
            function_version_id=test_version.id,
            triggered_by=None,
            schedule=schedule,
            status=ExecutionStatus.COMPLETED,
            payload={},
        )
        log = ExecutionLog(execution=execution, level="INFO", stream="stdout", message="done")
        activation = VersionActivation(
            function_id=test_function.id,
            actor_id=test_user.id,
            action="activate",
            activated_version_id=test_version.id,
        )
        db_session.add_all([schedule, execution, log, activation])
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/functions/{test_function.id}", headers=auth_headers
        )
        assert resp.status_code == 204

        assert (await db_session.execute(select(Function).where(Function.id == test_function.id))).scalar_one_or_none() is None
        assert (await db_session.execute(select(func.count()).select_from(FunctionVersion))).scalar_one() == 0
        assert (await db_session.execute(select(func.count()).select_from(Schedule))).scalar_one() == 0
        assert (await db_session.execute(select(func.count()).select_from(VersionActivation))).scalar_one() == 0

        remaining_execution = (await db_session.execute(select(Execution).where(Execution.id == execution.id))).scalar_one()
        assert remaining_execution.function_id is None
        assert remaining_execution.function_version_id is None
        assert remaining_execution.schedule_id is None
        assert remaining_execution.triggered_by == test_user.id
        assert (await db_session.execute(select(func.count()).select_from(ExecutionLog))).scalar_one() == 1
        mock_storage.delete_artifact.assert_called_once_with(test_version.artifact_path)

    async def test_delete_function_rejects_active_execution(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        test_function: Function,
        test_version: FunctionVersion,
        mock_storage,
    ) -> None:
        db_session.add(
            Execution(
                function_id=test_function.id,
                function_version_id=test_version.id,
                status=ExecutionStatus.QUEUED,
                payload={},
            )
        )
        await db_session.commit()

        resp = await client.delete(
            f"/api/v1/functions/{test_function.id}", headers=auth_headers
        )
        assert resp.status_code == 409
        assert (await db_session.execute(select(Function).where(Function.id == test_function.id))).scalar_one_or_none() is not None
        mock_storage.delete_artifact.assert_not_called()

    async def test_delete_function_reports_artifact_cleanup_failure(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers: dict,
        test_function: Function,
        test_version: FunctionVersion,
        mock_storage,
    ) -> None:
        mock_storage.delete_artifact.side_effect = RuntimeError("minio unavailable")

        resp = await client.delete(
            f"/api/v1/functions/{test_function.id}", headers=auth_headers
        )
        assert resp.status_code == 502
        assert (await db_session.execute(select(Function).where(Function.id == test_function.id))).scalar_one_or_none() is not None
    async def test_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/functions")
        assert resp.status_code == 401


class TestFunctionVersions:
    async def test_upload_version(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        mock_storage,
    ) -> None:
        archive = _make_zip()
        resp = await client.post(
            f"/api/v1/functions/{test_function.id}/versions",
            headers=auth_headers,
            files={"archive": ("source.zip", archive, "application/zip")},
            data={"entrypoint": "handler.handler", "timeout": "300"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["version_number"] == 1
        assert data["entrypoint"] == "handler.handler"

    async def test_upload_version_with_dangerous_code(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        mock_storage,
    ) -> None:
        dangerous = _make_zip("import os\nos.system('rm -rf /')\n")
        resp = await client.post(
            f"/api/v1/functions/{test_function.id}/versions",
            headers=auth_headers,
            files={"archive": ("source.zip", dangerous, "application/zip")},
        )
        assert resp.status_code == 422
        assert "Security validation failed" in resp.json()["detail"]

    async def test_list_versions(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        test_version,
    ) -> None:
        resp = await client.get(
            f"/api/v1/functions/{test_function.id}/versions",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    async def test_activate_version(
        self,
        client: AsyncClient,
        auth_headers: dict,
        test_function: Function,
        test_version,
    ) -> None:
        resp = await client.post(
            f"/api/v1/functions/{test_function.id}/versions/{test_version.id}/activate",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["active_version_id"] == str(test_version.id)
