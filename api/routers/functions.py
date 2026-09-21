"""
SOPM - Functions Router

Endpoints for function CRUD and version management.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies.deps import get_current_user, pagination_params
from api.schemas.schemas import (
    CanaryUpdateRequest,
    FunctionCreateRequest,
    FunctionListResponse,
    FunctionResponse,
    FunctionUpdateRequest,
    FunctionVersionCreateRequest,
    FunctionVersionListResponse,
    FunctionVersionResponse,
    VersionActivationResponse,
)
from shared.config import get_settings
from shared.db.models import (
    Execution,
    ExecutionStatus,
    Function,
    FunctionStatus,
    FunctionVersion,
    Schedule,
    User,
    VersionActivation,
)
from shared.db.session import get_db
from shared.observability.logging import get_logger
from shared.security.code_validator import validate_function_archive
from shared.storage.artifact_storage import ArtifactStorage, get_artifact_storage

router = APIRouter(prefix="/functions", tags=["Functions"])
settings = get_settings()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper: ownership check
# ---------------------------------------------------------------------------


async def _get_function_or_404(
    function_id: uuid.UUID,
    owner: User,
    db: AsyncSession,
) -> Function:
    result = await db.execute(
        select(Function)
        .options(selectinload(Function.active_version), selectinload(Function.canary_version))
        .where(
            Function.id == function_id,
            Function.owner_id == owner.id,
        )
    )
    fn = result.scalar_one_or_none()
    if fn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Function not found")
    return fn


def _record_activation(
    db: AsyncSession,
    fn: Function,
    actor: User,
    action: str,
    previous_version_id: uuid.UUID | None,
    activated_version_id: uuid.UUID | None = None,
    canary_version_id: uuid.UUID | None = None,
    canary_percent: int = 0,
) -> None:
    db.add(
        VersionActivation(
            function_id=fn.id,
            actor_id=actor.id,
            action=action,
            previous_version_id=previous_version_id,
            activated_version_id=activated_version_id,
            canary_version_id=canary_version_id,
            canary_percent=canary_percent,
        )
    )


# ---------------------------------------------------------------------------
# Function CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=FunctionListResponse, summary="List functions")
async def list_functions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    pagination: Annotated[tuple[int, int], Depends(pagination_params)],
    status_filter: FunctionStatus | None = Query(None, alias="status"),
) -> FunctionListResponse:
    offset, limit = pagination
    page = offset // limit + 1

    query = (
        select(Function)
        .options(selectinload(Function.active_version), selectinload(Function.canary_version))
        .where(Function.owner_id == current_user.id)
    )
    count_query = (
        select(func.count()).select_from(Function).where(Function.owner_id == current_user.id)
    )

    if status_filter:
        query = query.where(Function.status == status_filter)
        count_query = count_query.where(Function.status == status_filter)

    query = query.offset(offset).limit(limit).order_by(Function.created_at.desc())

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(query)
    functions = result.scalars().all()

    return FunctionListResponse(
        items=[FunctionResponse.model_validate(f) for f in functions],
        total=total,
        page=page,
        page_size=limit,
    )


@router.post(
    "",
    response_model=FunctionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new function",
)
async def create_function(
    body: FunctionCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FunctionResponse:
    # Enforce per-user function limit
    count_result = await db.execute(
        select(func.count())
        .select_from(Function)
        .where(
            Function.owner_id == current_user.id,
            Function.status != FunctionStatus.DEPRECATED,
        )
    )
    count = count_result.scalar_one()
    if count >= settings.max_functions_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum of {settings.max_functions_per_user} functions per user",
        )

    # Check for name collision
    existing = await db.execute(
        select(Function).where(
            Function.owner_id == current_user.id,
            Function.name == body.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Function '{body.name}' already exists",
        )

    fn = Function(
        owner_id=current_user.id,
        name=body.name,
        description=body.description,
        tags=body.tags,
    )
    db.add(fn)
    await db.flush()
    await db.refresh(fn)
    logger.info("function_created", function_id=str(fn.id), name=fn.name)
    return FunctionResponse.model_validate(fn)


@router.get("/{function_id}", response_model=FunctionResponse, summary="Get function")
async def get_function(
    function_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FunctionResponse:
    fn = await _get_function_or_404(function_id, current_user, db)
    return FunctionResponse.model_validate(fn)


@router.patch(
    "/{function_id}",
    response_model=FunctionResponse,
    summary="Update function metadata",
)
async def update_function(
    function_id: uuid.UUID,
    body: FunctionUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FunctionResponse:
    fn = await _get_function_or_404(function_id, current_user, db)

    if body.description is not None:
        fn.description = body.description
    if body.status is not None:
        fn.status = body.status
    if body.tags is not None:
        fn.tags = body.tags

    await db.flush()
    await db.refresh(fn)
    return FunctionResponse.model_validate(fn)


@router.delete(
    "/{function_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a function",
)
async def delete_function(
    function_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    storage: Annotated[ArtifactStorage, Depends(get_artifact_storage)],
) -> None:
    fn = await _get_function_or_404(function_id, current_user, db)

    active_count = (
        await db.execute(
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.function_id == fn.id,
                Execution.status.in_(
                    [
                        ExecutionStatus.PENDING,
                        ExecutionStatus.QUEUED,
                        ExecutionStatus.RUNNING,
                    ]
                ),
            )
        )
    ).scalar_one()
    if active_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Function has active executions. "
                "Wait for them to finish or cancel them before deleting."
            ),
        )

    versions_result = await db.execute(
        select(FunctionVersion).where(FunctionVersion.function_id == fn.id)
    )
    versions = list(versions_result.scalars().all())
    version_ids = [version.id for version in versions]
    artifact_paths = [version.artifact_path for version in versions]

    # Keep operational history, but detach it from definitions that are being removed.
    await db.execute(
        update(Execution)
        .where(Execution.function_id == fn.id)
        .values(
            function_id=None,
            function_version_id=None,
            schedule_id=None,
            triggered_by=current_user.id,
        )
    )
    if version_ids:
        await db.execute(
            update(Execution)
            .where(Execution.function_version_id.in_(version_ids))
            .values(function_version_id=None)
        )

    fn.active_version_id = None
    fn.canary_version_id = None
    fn.canary_percent = 0
    await db.flush()

    await db.execute(sa_delete(Schedule).where(Schedule.function_id == fn.id))
    await db.execute(sa_delete(VersionActivation).where(VersionActivation.function_id == fn.id))
    await db.execute(sa_delete(FunctionVersion).where(FunctionVersion.function_id == fn.id))
    await db.execute(sa_delete(Function).where(Function.id == fn.id))
    await db.flush()

    for artifact_path in artifact_paths:
        try:
            storage.delete_artifact(artifact_path)
        except Exception as exc:
            logger.error(
                "function_artifact_delete_failed",
                function_id=str(function_id),
                artifact_path=artifact_path,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to delete function artifact: {artifact_path}",
            ) from exc

    logger.info("function_deleted", function_id=str(function_id))


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@router.post(
    "/{function_id}/versions",
    response_model=FunctionVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new function version",
)
async def create_version(
    function_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    storage: Annotated[ArtifactStorage, Depends(get_artifact_storage)],
    archive: UploadFile = File(..., description="ZIP archive containing Python source"),
    entrypoint: str = Form("handler.handler"),
    timeout: int = Form(300),
    memory_mb: int = Form(128),
    change_notes: str | None = Form(None),
) -> FunctionVersionResponse:
    fn = await _get_function_or_404(function_id, current_user, db)

    # Validate request body via schema (entrypoint etc.)
    params = FunctionVersionCreateRequest(
        entrypoint=entrypoint,
        timeout=timeout,
        memory_mb=memory_mb,
        change_notes=change_notes,
    )

    # Read archive
    archive_bytes = await archive.read()
    if len(archive_bytes) > settings.max_function_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Archive exceeds maximum size of {settings.max_function_size_bytes} bytes",
        )

    # Security validation
    validation = validate_function_archive(archive_bytes)
    if not validation.is_valid:
        violations_summary = "; ".join(
            f"{v.file}:{v.line} - {v.message}" for v in validation.violations[:5]
        )
        logger.warning(
            "function_upload_rejected",
            function_id=str(function_id),
            violations=len(validation.violations),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Security validation failed: {violations_summary or validation.error}",
        )

    # Check version count
    count_result = await db.execute(
        select(func.count())
        .select_from(FunctionVersion)
        .where(FunctionVersion.function_id == fn.id)
    )
    version_count = count_result.scalar_one()
    if version_count >= settings.max_versions_per_function:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Maximum of {settings.max_versions_per_function} versions per function",
        )

    # Assign next version number
    max_version_result = await db.execute(
        select(func.max(FunctionVersion.version_number)).where(FunctionVersion.function_id == fn.id)
    )
    max_version = max_version_result.scalar_one() or 0
    next_version = max_version + 1

    # Generate a version UUID for storage path
    version_id = uuid.uuid4()

    # Upload to MinIO
    artifact_path, artifact_hash, artifact_size = storage.upload_artifact(
        str(function_id), str(version_id), archive_bytes
    )

    version = FunctionVersion(
        id=version_id,
        function_id=fn.id,
        version_number=next_version,
        entrypoint=params.entrypoint,
        artifact_path=artifact_path,
        artifact_hash=artifact_hash,
        artifact_size=artifact_size,
        environment=params.environment,
        timeout=params.timeout,
        memory_mb=params.memory_mb,
        change_notes=params.change_notes,
    )
    db.add(version)

    # Insert the version before pointing functions.active_version_id at it.
    # PostgreSQL enforces the FK immediately, and SQLAlchemy may otherwise
    # flush the parent update before the child insert.
    await db.flush()

    fn.active_version_id = version_id

    await db.flush()
    await db.refresh(version)
    logger.info(
        "version_created",
        function_id=str(function_id),
        version_id=str(version_id),
        version_number=next_version,
    )
    return FunctionVersionResponse.model_validate(version)


@router.get(
    "/{function_id}/versions",
    response_model=FunctionVersionListResponse,
    summary="List function versions",
)
async def list_versions(
    function_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FunctionVersionListResponse:
    fn = await _get_function_or_404(function_id, current_user, db)

    result = await db.execute(
        select(FunctionVersion)
        .where(FunctionVersion.function_id == fn.id)
        .order_by(FunctionVersion.version_number.desc())
    )
    versions = result.scalars().all()
    return FunctionVersionListResponse(
        items=[FunctionVersionResponse.model_validate(v) for v in versions],
        total=len(versions),
    )


@router.get(
    "/{function_id}/versions/{version_id}",
    response_model=FunctionVersionResponse,
    summary="Get a specific version",
)
async def get_version(
    function_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FunctionVersionResponse:
    fn = await _get_function_or_404(function_id, current_user, db)
    result = await db.execute(
        select(FunctionVersion).where(
            FunctionVersion.id == version_id,
            FunctionVersion.function_id == fn.id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
    return FunctionVersionResponse.model_validate(version)


@router.post(
    "/{function_id}/versions/{version_id}/activate",
    response_model=FunctionResponse,
    summary="Set a version as the active version",
)
async def activate_version(
    function_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FunctionResponse:
    fn = await _get_function_or_404(function_id, current_user, db)
    result = await db.execute(
        select(FunctionVersion).where(
            FunctionVersion.id == version_id,
            FunctionVersion.function_id == fn.id,
            FunctionVersion.is_active.is_(True),
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")

    previous_version_id = fn.active_version_id
    fn.active_version_id = version_id
    fn.canary_version_id = None
    fn.canary_percent = 0
    _record_activation(
        db, fn, current_user, "activate", previous_version_id, activated_version_id=version_id
    )
    await db.flush()

    refreshed = await _get_function_or_404(function_id, current_user, db)
    logger.info("version_activated", function_id=str(function_id), version_id=str(version_id))
    return FunctionResponse.model_validate(refreshed)


@router.patch(
    "/{function_id}/canary",
    response_model=FunctionResponse,
    summary="Configure canary traffic for a function",
)
async def update_canary(
    function_id: uuid.UUID,
    body: CanaryUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FunctionResponse:
    fn = await _get_function_or_404(function_id, current_user, db)
    previous_version_id = fn.active_version_id

    if body.canary_percent == 0 or body.canary_version_id is None:
        fn.canary_version_id = None
        fn.canary_percent = 0
        _record_activation(db, fn, current_user, "canary_clear", previous_version_id)
    else:
        result = await db.execute(
            select(FunctionVersion).where(
                FunctionVersion.id == body.canary_version_id,
                FunctionVersion.function_id == fn.id,
                FunctionVersion.is_active.is_(True),
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
        if body.canary_version_id == fn.active_version_id and body.canary_percent < 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Canary version must differ from active version",
            )

        if body.canary_percent == 100:
            fn.active_version_id = body.canary_version_id
            fn.canary_version_id = None
            fn.canary_percent = 0
            _record_activation(
                db,
                fn,
                current_user,
                "promote",
                previous_version_id,
                activated_version_id=body.canary_version_id,
            )
        else:
            fn.canary_version_id = body.canary_version_id
            fn.canary_percent = body.canary_percent
            _record_activation(
                db,
                fn,
                current_user,
                "canary_update",
                previous_version_id,
                activated_version_id=fn.active_version_id,
                canary_version_id=body.canary_version_id,
                canary_percent=body.canary_percent,
            )

    await db.flush()
    refreshed = await _get_function_or_404(function_id, current_user, db)
    logger.info("canary_updated", function_id=str(function_id), canary_percent=body.canary_percent)
    return FunctionResponse.model_validate(refreshed)


@router.get(
    "/{function_id}/activations",
    response_model=list[VersionActivationResponse],
    summary="List version activation history",
)
async def list_activations(
    function_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[VersionActivationResponse]:
    fn = await _get_function_or_404(function_id, current_user, db)
    result = await db.execute(
        select(VersionActivation)
        .where(VersionActivation.function_id == fn.id)
        .order_by(VersionActivation.created_at.desc())
        .limit(100)
    )
    return [VersionActivationResponse.model_validate(row) for row in result.scalars().all()]
