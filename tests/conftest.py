"""
SOPM - Test Configuration and Fixtures
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from shared.db.models import Base, Function, FunctionStatus, FunctionVersion, User
from shared.db.session import get_db
from shared.security.auth import create_access_token, hash_password

# ---------------------------------------------------------------------------
# In-memory SQLite for fast unit tests
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# App + HTTP client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def app(db_session: AsyncSession) -> FastAPI:
    from api.main import create_app

    _app = create_app()

    async def _override_db():
        yield db_session

    _app.dependency_overrides[get_db] = _override_db
    return _app


@pytest_asyncio.fixture(scope="function")
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test users
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        username="testuser",
        email="test@example.com",
        hashed_password=hash_password("testpassword"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def superuser(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        username="admin",
        email="admin@example.com",
        hashed_password=hash_password("adminpassword"),
        is_active=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_function(db_session: AsyncSession, test_user: User) -> Function:
    fn = Function(
        id=uuid.uuid4(),
        owner_id=test_user.id,
        name="my-function",
        description="A test function",
        status=FunctionStatus.ACTIVE,
        tags={},
    )
    db_session.add(fn)
    await db_session.commit()
    await db_session.refresh(fn)
    return fn


@pytest_asyncio.fixture
async def test_version(db_session: AsyncSession, test_function: Function) -> FunctionVersion:
    version = FunctionVersion(
        id=uuid.uuid4(),
        function_id=test_function.id,
        version_number=1,
        entrypoint="handler.handler",
        artifact_path=f"functions/{test_function.id}/v1/source.zip",
        artifact_hash="abc123" * 10,
        artifact_size=1024,
        environment={},
        timeout=300,
        memory_mb=128,
    )
    db_session.add(version)
    test_function.active_version_id = version.id
    await db_session.commit()
    await db_session.refresh(version)
    return version


# ---------------------------------------------------------------------------
# Mock external services
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    with patch("shared.queue.redis_client.get_redis") as mock:
        redis_mock = AsyncMock()
        redis_mock.zadd = AsyncMock(return_value=1)
        redis_mock.zcard = AsyncMock(return_value=0)
        redis_mock.ping = AsyncMock(return_value=True)
        redis_mock.aclose = AsyncMock()
        mock.return_value = redis_mock
        yield redis_mock


@pytest.fixture
def mock_minio():
    with patch("shared.storage.artifact_storage.get_minio_client") as mock:
        minio_mock = MagicMock()
        minio_mock.bucket_exists.return_value = True
        minio_mock.put_object.return_value = None
        minio_mock.get_object.return_value = MagicMock(
            read=MagicMock(return_value=b"fake-zip-data"),
            close=MagicMock(),
            release_conn=MagicMock(),
        )
        mock.return_value = minio_mock
        yield minio_mock


@pytest.fixture
def mock_storage(app):
    """Override the ArtifactStorage FastAPI dependency with a mock."""
    from shared.storage.artifact_storage import ArtifactStorage, get_artifact_storage

    storage_mock = MagicMock(spec=ArtifactStorage)
    storage_mock.upload_artifact.return_value = (
        "functions/abc/v1/source.zip",
        "a" * 64,
        1024,
    )
    storage_mock.delete_artifact.return_value = None

    app.dependency_overrides[get_artifact_storage] = lambda: storage_mock
    yield storage_mock
    app.dependency_overrides.pop(get_artifact_storage, None)
