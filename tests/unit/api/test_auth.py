"""Tests for authentication endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from shared.db.models import User
from shared.security.auth import hash_password


class TestRegister:
    async def test_register_success(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "newuser", "email": "new@example.com", "password": "securepass123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["email"] == "new@example.com"
        assert "id" in data
        assert "hashed_password" not in data

    async def test_register_duplicate_username(
        self, client: AsyncClient, test_user: User
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": test_user.username,
                "email": "other@example.com",
                "password": "securepass123",
            },
        )
        assert resp.status_code == 409

    async def test_register_invalid_username(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "bad user!", "email": "x@x.com", "password": "pass12345"},
        )
        assert resp.status_code == 422

    async def test_register_short_password(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/register",
            json={"username": "gooduser", "email": "x@x.com", "password": "short"},
        )
        assert resp.status_code == 422


class TestLogin:
    async def test_login_success(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": test_user.username, "password": "testpassword"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": test_user.username, "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    async def test_login_unknown_user(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "nobody", "password": "password"},
        )
        assert resp.status_code == 401


class TestMe:
    async def test_me_authenticated(
        self, client: AsyncClient, test_user: User, auth_headers: dict
    ) -> None:
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == test_user.username

    async def test_me_unauthenticated(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_invalid_token(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
        )
        assert resp.status_code == 401
