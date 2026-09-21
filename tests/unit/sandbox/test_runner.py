import json
import signal
import sys
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sandbox import runner


@pytest.fixture
def runner_env(monkeypatch, tmp_path):
    for key in ("SOPM_SOURCE_CODE", "SOPM_CACHE_DIR", "SOPM_ARTIFACT_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SOPM_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("SOPM_PAYLOAD", '{"value": 7}')
    monkeypatch.setenv("SOPM_EXECUTION_ID", "test-execution")
    monkeypatch.setenv("SOPM_ENTRYPOINT", "handler.handler")
    monkeypatch.setattr(sys, "path", sys.path.copy())
    # Exercise result handling on Windows too; OS delivery is Linux-specific.
    monkeypatch.setattr(signal, "SIGALRM", 14, raising=False)
    monkeypatch.setattr(signal, "signal", MagicMock())
    monkeypatch.setattr(signal, "alarm", MagicMock(), raising=False)
    return tmp_path


def result(capsys):
    return json.loads(
        next(
            line[12:]
            for line in capsys.readouterr().out.splitlines()
            if line.startswith("SOPM_RESULT:")
        )
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def handler(): return 42", {"return_value": 42}),
        ("def handler(event): return event", {"value": 7}),
        (
            "def handler(event, context): return context",
            {"execution_id": "test-execution", "timeout": 300},
        ),
        ("def handler(*args): return args[0]", {"value": 7}),
    ],
)
def test_inline_handler_signatures(runner_env, monkeypatch, capsys, source, expected):
    monkeypatch.setenv("SOPM_SOURCE_CODE", source)
    monkeypatch.setenv("MINIO_SECRET_KEY", "must-not-reach-handler")
    assert runner.main() == 0
    data = result(capsys)
    assert data["success"] is True
    assert data["result"] == expected
    import os

    assert "MINIO_SECRET_KEY" not in os.environ
    signal.alarm.assert_called_with(0)


@pytest.mark.parametrize(
    ("exception", "timed_out"), [("ValueError", False), ("TimeoutError", True)]
)
def test_handler_failures(runner_env, monkeypatch, capsys, exception, timed_out):
    monkeypatch.setenv("SOPM_SOURCE_CODE", f"def handler(): raise {exception}('failed')")
    assert runner.main() == 1
    data = result(capsys)
    assert data["success"] is False
    assert data["error"] == "failed"
    assert data.get("timed_out", False) is timed_out


def test_zip_execution_and_cache(runner_env, monkeypatch, capsys):
    def download(path, dest):
        with zipfile.ZipFile(dest, "w") as bundle:
            bundle.writestr("handler.py", "def handler(event): return event")
            bundle.writestr("../escape.py", "bad")
            bundle.writestr("/absolute.py", "bad")

    downloader = MagicMock(side_effect=download)
    monkeypatch.setattr(runner, "_download_artifact", downloader)
    monkeypatch.setenv("SOPM_ARTIFACT_PATH", "functions/f/v/source.zip")
    monkeypatch.setenv("SOPM_CACHE_DIR", str(runner_env / "cache"))
    monkeypatch.setenv("SOPM_PAYLOAD", "not-json")
    for _ in range(2):
        assert runner.main() == 0
        assert result(capsys)["result"] == {}
    downloader.assert_called_once()
    assert not (runner_env / "cache" / "escape.py").exists()


@pytest.mark.parametrize(
    ("phase", "message"),
    [
        ("missing", "SOPM_ARTIFACT_PATH is required"),
        ("download", "artifact download failed"),
        ("extract", "archive extraction failed"),
        ("source", "inline source write failed"),
        ("dependencies", "dependency install failed"),
        ("handler", "handler load failed"),
    ],
)
def test_setup_failures(runner_env, monkeypatch, capsys, phase, message):
    if phase in {"download", "extract"}:
        monkeypatch.setenv("SOPM_ARTIFACT_PATH", "test.zip")
        monkeypatch.setattr(
            runner,
            "_download_artifact",
            MagicMock(side_effect=RuntimeError("offline") if phase == "download" else None),
        )
    elif phase != "missing":
        monkeypatch.setenv("SOPM_SOURCE_CODE", "def handler(): return 1")
        method = {
            "source": "_write_inline_source",
            "dependencies": "_install_requirements_if_needed",
            "handler": "_load_handler",
        }[phase]
        monkeypatch.setattr(runner, method, MagicMock(side_effect=RuntimeError("broken")))
    assert runner.main() == 1
    assert message in result(capsys)["error"]


def test_dependency_cache_and_failure(runner_env, monkeypatch):
    (runner_env / "requirements.txt").write_text("example==1.0")
    deps = runner_env / "deps"
    deps.mkdir()
    (deps / "stale").write_text("stale")
    install = MagicMock(return_value=SimpleNamespace(returncode=1, stdout="cannot resolve"))
    monkeypatch.setattr(runner.subprocess, "run", install)
    with pytest.raises(RuntimeError, match="cannot resolve"):
        runner._install_requirements_if_needed(runner_env, deps, 2)
    assert not (deps / "stale").exists()
    assert not (deps / ".sopm-installed").exists()
    install.return_value = SimpleNamespace(returncode=0)
    runner._install_requirements_if_needed(runner_env, deps, 2)
    runner._install_requirements_if_needed(runner_env, deps, 2)
    assert install.call_count == 2
    assert install.call_args.kwargs["timeout"] == 15
    assert str(deps) in sys.path


@pytest.mark.parametrize(
    ("entrypoint", "error"),
    [
        ("invalid", ValueError),
        ("missing.handler", FileNotFoundError),
        ("handler.missing", AttributeError),
    ],
)
def test_invalid_entrypoints(runner_env, entrypoint, error):
    (runner_env / "handler.py").write_text("def handler(): return 1")
    with pytest.raises(error):
        runner._load_handler(runner_env, entrypoint)


def test_download_uses_configured_bucket(runner_env, monkeypatch):
    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("minio.Minio", factory)
    for key, value in {
        "MINIO_ENDPOINT": "storage:9000",
        "MINIO_ACCESS_KEY": "access",
        "MINIO_SECRET_KEY": "secret",
        "MINIO_SECURE": "true",
        "MINIO_BUCKET_ARTIFACTS": "artifacts",
    }.items():
        monkeypatch.setenv(key, value)
    runner._download_artifact("path.zip", runner_env / "source.zip")
    assert factory.call_args.kwargs["secure"] is True
    client.fget_object.assert_called_once_with(
        "artifacts", "path.zip", str(runner_env / "source.zip")
    )
