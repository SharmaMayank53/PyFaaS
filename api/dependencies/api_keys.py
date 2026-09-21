"""API-key authentication helpers shared by invoke-style routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routers.keys import hash_api_key
from shared.db.models import ApiKey, User
from shared.db.session import get_db


@dataclass
class ApiKeyPrincipal:
    key: ApiKey
    user: User


async def get_api_key_principal(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_sopm_key: Annotated[str | None, Header(alias="X-SOPM-Key")] = None,
) -> ApiKeyPrincipal:
    if not x_sopm_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

    result = await db.execute(
        select(ApiKey, User)
        .join(User, ApiKey.owner_id == User.id)
        .where(ApiKey.key_hash == hash_api_key(x_sopm_key), ApiKey.revoked_at.is_(None))
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    key, user = row
    key.last_used_at = datetime.now(UTC)
    return ApiKeyPrincipal(key=key, user=user)


async def get_api_key_user(
    principal: Annotated[ApiKeyPrincipal, Depends(get_api_key_principal)],
) -> User:
    return principal.user
