import hashlib
from unittest.mock import MagicMock

import pytest
from minio.error import S3Error

from shared.storage import artifact_storage as storage


@pytest.fixture
def client(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(storage, "_client", None)
    monkeypatch.setattr(storage, "Minio", MagicMock(return_value=fake))
    return fake


async def test_bucket_creation_and_singleton(client):
    client.bucket_exists.side_effect = [False, True]
    await storage.ensure_buckets()
    client.make_bucket.assert_called_once_with(storage.settings.minio_bucket_artifacts)
    assert storage.get_minio_client() is client
    storage.Minio.assert_called_once()


def test_artifact_roundtrip_and_integrity(client):
    service = storage.get_artifact_storage()
    path, digest, size = service.upload_artifact("fn", "v1", b"zip-data")
    assert (path, size) == ("functions/fn/v1/source.zip", 8)
    assert digest == hashlib.sha256(b"zip-data").hexdigest()
    assert client.put_object.call_args.args[2].read() == b"zip-data"
    response = client.get_object.return_value
    response.read.return_value = b"zip-data"
    assert service.verify_artifact_hash(path, digest)
    assert not service.verify_artifact_hash(path, "bad")
    assert service.compute_hash(b"zip-data") == digest
    client.presigned_get_object.return_value = "https://storage/download"
    assert service.get_presigned_download_url(path, 60) == "https://storage/download"
    assert client.presigned_get_object.call_args.kwargs["expires"].total_seconds() == 60
    service.delete_artifact(path)
    client.remove_object.assert_called_once()
    assert response.close.call_count == 2
    assert response.release_conn.call_count == 2


def test_download_releases_connection_on_error(client):
    client.get_object.return_value.read.side_effect = OSError("disconnected")
    with pytest.raises(OSError, match="disconnected"):
        storage.ArtifactStorage().download_artifact("path")
    client.get_object.return_value.close.assert_called_once()
    client.get_object.return_value.release_conn.assert_called_once()


@pytest.mark.parametrize("code", ["NoSuchKey", "AccessDenied"])
def test_delete_error_policy(client, code):
    client.remove_object.side_effect = S3Error(
        code=code,
        message="error",
        resource="resource",
        request_id="request",
        host_id="host",
        response=None,
    )
    service = storage.ArtifactStorage()
    if code == "NoSuchKey":
        service.delete_artifact("missing")
    else:
        with pytest.raises(S3Error):
            service.delete_artifact("private")
