"""Execution-time version routing helpers."""
from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Function, FunctionVersion


async def choose_execution_version(
    db: AsyncSession,
    fn: Function,
    explicit_version_id: Any | None = None,
) -> FunctionVersion | None:
    """Return the version to execute, honoring explicit version and canary split."""
    version_id = explicit_version_id
    if version_id is None:
        version_id = fn.active_version_id
        if fn.canary_version_id and fn.canary_percent > 0:
            if fn.canary_percent >= 100 or secrets.randbelow(100) < fn.canary_percent:
                version_id = fn.canary_version_id

    if version_id is None:
        return None

    result = await db.execute(
        select(FunctionVersion).where(
            FunctionVersion.id == version_id,
            FunctionVersion.function_id == fn.id,
            FunctionVersion.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()