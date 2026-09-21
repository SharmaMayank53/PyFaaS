"""
SOPM - Artifact Storage (MinIO)

Handles upload/download of function source archives and build artifacts.
"""

from __future__ import annotations

import hashlib
import io

from minio import Minio
from minio.error import S3Error

from shared.config import get_settings

settings = get_settings()

_client: Minio | None = None


def get_minio_client() -> Minio:
    """Return (or create) a singleton MinIO client."""
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _client


async def ensure_buckets() -> None:
    """Create required MinIO buckets if they don't exist. Called at startup."""
    client = get_minio_client()
    for bucket in [settings.minio_bucket_artifacts, settings.minio_bucket_packages]:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)


class ArtifactStorage:
    """Service for storing and retrieving function artifacts."""

    def __init__(self) -> None:
        self._client = get_minio_client()
        self._artifacts_bucket = settings.minio_bucket_artifacts
        self._packages_bucket = settings.minio_bucket_packages

    def _artifact_path(self, function_id: str, version_id: str) -> str:
        return f"functions/{function_id}/{version_id}/source.zip"

    def upload_artifact(
        self,
        function_id: str,
        version_id: str,
        data: bytes,
    ) -> tuple[str, str, int]:
        """
        Upload a function source archive.

        Returns:
            (artifact_path, sha256_hash, size_bytes)
        """
        sha256 = hashlib.sha256(data).hexdigest()
        path = self._artifact_path(function_id, version_id)
        size = len(data)

        self._client.put_object(
            self._artifacts_bucket,
            path,
            io.BytesIO(data),
            length=size,
            content_type="application/zip",
            metadata={"sha256": sha256, "function_id": function_id, "version_id": version_id},
        )
        return path, sha256, size

    def download_artifact(self, artifact_path: str) -> bytes:
        """Download a function source archive and return raw bytes."""
        response = self._client.get_object(self._artifacts_bucket, artifact_path)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete_artifact(self, artifact_path: str) -> None:
        """Delete an artifact. Does not raise if the object doesn't exist."""
        try:
            self._client.remove_object(self._artifacts_bucket, artifact_path)
        except S3Error as exc:
            if exc.code != "NoSuchKey":
                raise

    def get_presigned_download_url(
        self,
        artifact_path: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a presigned download URL for an artifact."""
        from datetime import timedelta

        return self._client.presigned_get_object(
            self._artifacts_bucket,
            artifact_path,
            expires=timedelta(seconds=expires_in_seconds),
        )

    def verify_artifact_hash(self, artifact_path: str, expected_hash: str) -> bool:
        """Download artifact and verify SHA-256 hash."""
        data = self.download_artifact(artifact_path)
        actual_hash = hashlib.sha256(data).hexdigest()
        return actual_hash == expected_hash

    @staticmethod
    def compute_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


def get_artifact_storage() -> ArtifactStorage:
    """Dependency factory for ArtifactStorage."""
    return ArtifactStorage()
