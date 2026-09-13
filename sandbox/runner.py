"""
SOPM Runner

This script runs INSIDE the sandbox container (not in the main platform).
It downloads the function artifact from MinIO, imports it, calls the handler,
and writes the result to stdout as SOPM_RESULT:<json>.

It is intentionally minimal â€” no FastAPI, no SQLAlchemy.
All output is via print() to stdout; collected by the worker via pod logs.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any


def _download_artifact(artifact_path: str, dest: Path) -> None:
    from minio import Minio

    endpoint = os.environ["MINIO_ENDPOINT"]
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"
    bucket = os.environ.get("MINIO_BUCKET_ARTIFACTS", "sopm-artifacts")

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    client.fget_object(bucket, artifact_path, str(dest))


def _extract_archive(archive_path: Path, extract_to: Path) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        # Safety: skip any paths with traversal attempts
        for member in zf.namelist():
            if ".." in member or member.startswith("/"):
                continue
            zf.extract(member, extract_to)


def _write_inline_source(work_dir: Path, entrypoint: str, source_code: str) -> None:
    module_path, _func_name = entrypoint.rsplit(".", 1)
    source_path = work_dir / (module_path.replace(".", "/") + ".py")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(source_code, encoding="utf-8")



def _install_requirements_if_needed(work_dir: Path, deps_dir: Path, timeout: int) -> None:
    requirements = work_dir / "requirements.txt"
    if not requirements.exists():
        return

    marker = deps_dir / ".sopm-installed"
    if marker.exists():
        sys.path.insert(0, str(deps_dir))
        return

    if deps_dir.exists():
        shutil.rmtree(deps_dir)
    deps_dir.mkdir(parents=True, exist_ok=True)

    print(f"[sopm-runner] installing dependencies from requirements.txt", flush=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--no-input",
            "--target",
            str(deps_dir),
            "-r",
            str(requirements),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=min(120, max(15, timeout)),
    )
    if result.returncode != 0:
        raise RuntimeError(f"dependency install failed:\n{result.stdout[-4000:]}")

    marker.write_text(str(time.time()), encoding="utf-8")
    sys.path.insert(0, str(deps_dir))

def _load_handler(work_dir: Path, entrypoint: str) -> Any:
    """
    Load the handler function from entrypoint string like 'handler.handler'
    i.e. module_name.function_name.
    """
    parts = entrypoint.rsplit(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Entrypoint must be 'module.function', got: {entrypoint}")

    module_path_str, func_name = parts
    module_file = work_dir / (module_path_str.replace(".", "/") + ".py")

    if not module_file.exists():
        raise FileNotFoundError(f"Module file not found: {module_file}")

    spec = importlib.util.spec_from_file_location(module_path_str, module_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {module_file}")

    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(work_dir))
    spec.loader.exec_module(module)

    handler_fn = getattr(module, func_name, None)
    if handler_fn is None:
        raise AttributeError(f"Function '{func_name}' not found in module '{module_path_str}'")
    return handler_fn


def _emit_result(result: Any) -> None:
    print(f"SOPM_RESULT:{json.dumps(result)}", flush=True)


def main() -> int:
    execution_id = os.environ.get("SOPM_EXECUTION_ID", "unknown")
    artifact_path = os.environ.get("SOPM_ARTIFACT_PATH")
    entrypoint = os.environ.get("SOPM_ENTRYPOINT", "handler.handler")
    payload_raw = os.environ.get("SOPM_PAYLOAD", "{}")
    source_code = os.environ.get("SOPM_SOURCE_CODE")
    timeout = int(os.environ.get("SOPM_TIMEOUT", "300"))

    work_dir = Path(os.environ.get("SOPM_WORK_DIR", "/work"))
    cache_dir_raw = os.environ.get("SOPM_CACHE_DIR")
    cache_dir = Path(cache_dir_raw) if cache_dir_raw else None
    if cache_dir:
        work_dir = cache_dir / "src"
        deps_dir = cache_dir / "deps"
    else:
        deps_dir = work_dir / ".deps"

    work_dir.mkdir(parents=True, exist_ok=True)
    archive_path = work_dir / "source.zip"
    extracted_marker = work_dir / ".sopm-extracted"

    print(f"[sopm-runner] execution_id={execution_id}", flush=True)

    if source_code is not None:
        print(f"[sopm-runner] using inline source for {entrypoint}", flush=True)
        try:
            _write_inline_source(work_dir, entrypoint, source_code)
        except Exception as exc:
            print(f"[sopm-runner] ERROR: inline source write failed: {exc}", flush=True, file=sys.stderr)
            _emit_result({"error": f"inline source write failed: {exc}", "success": False})
            return 1
    elif not extracted_marker.exists():
        if not artifact_path:
            print("[sopm-runner] ERROR: SOPM_ARTIFACT_PATH is required without SOPM_SOURCE_CODE", flush=True, file=sys.stderr)
            _emit_result({"error": "SOPM_ARTIFACT_PATH is required without SOPM_SOURCE_CODE", "success": False})
            return 1
        print(f"[sopm-runner] downloading artifact: {artifact_path}", flush=True)
        try:
            _download_artifact(artifact_path, archive_path)
        except Exception as exc:
            print(f"[sopm-runner] ERROR: artifact download failed: {exc}", flush=True, file=sys.stderr)
            _emit_result({"error": f"artifact download failed: {exc}", "success": False})
            return 1

        try:
            _extract_archive(archive_path, work_dir)
            extracted_marker.write_text(str(time.time()), encoding="utf-8")
        except Exception as exc:
            print(f"[sopm-runner] ERROR: archive extraction failed: {exc}", flush=True, file=sys.stderr)
            _emit_result({"error": f"archive extraction failed: {exc}", "success": False})
            return 1
    else:
        print(f"[sopm-runner] using cached artifact: {work_dir}", flush=True)

    for secret_name in ("MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_ENDPOINT"):
        os.environ.pop(secret_name, None)

    try:
        _install_requirements_if_needed(work_dir, deps_dir, timeout)
    except Exception as exc:
        print(f"[sopm-runner] ERROR: dependency install failed: {exc}", flush=True, file=sys.stderr)
        _emit_result({"error": f"dependency install failed: {exc}", "success": False, "phase": "dependency_install"})
        return 1

    try:
        handler = _load_handler(work_dir, entrypoint)
    except Exception as exc:
        print(f"[sopm-runner] ERROR: handler load failed: {exc}", flush=True, file=sys.stderr)
        _emit_result({"error": f"handler load failed: {exc}", "success": False})
        return 1

    # 4. Parse payload
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        payload = {}

    # 5. Execute
    print(f"[sopm-runner] executing {entrypoint}", flush=True)
    start = time.monotonic()

    import signal

    def _timeout_handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"Execution exceeded timeout of {timeout}s")

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout)

    try:
        context = {"execution_id": execution_id, "timeout": timeout}
        signature = inspect.signature(handler)
        positional = [
            p
            for p in signature.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            and p.default is p.empty
        ]
        has_varargs = any(p.kind == p.VAR_POSITIONAL for p in signature.parameters.values())

        if has_varargs or len(positional) >= 2:
            result = handler(payload, context)
        elif len(positional) == 1:
            result = handler(payload)
        else:
            result = handler()
        signal.alarm(0)  # Cancel alarm
        duration = time.monotonic() - start
        print(f"[sopm-runner] completed in {duration:.3f}s", flush=True)

        if not isinstance(result, dict):
            result = {"return_value": result}

        _emit_result({"success": True, "result": result, "duration_ms": int(duration * 1000)})
        return 0

    except TimeoutError as exc:
        signal.alarm(0)
        print(f"[sopm-runner] TIMEOUT: {exc}", flush=True, file=sys.stderr)
        _emit_result({"success": False, "error": str(exc), "timed_out": True})
        return 1

    except Exception as exc:
        signal.alarm(0)
        tb = traceback.format_exc()
        print(f"[sopm-runner] ERROR: {exc}\n{tb}", flush=True, file=sys.stderr)
        _emit_result({"success": False, "error": str(exc), "traceback": tb})
        return 1


if __name__ == "__main__":
    sys.exit(main())



