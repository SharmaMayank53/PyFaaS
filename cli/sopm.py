"""Minimal SOPM CLI."""
from __future__ import annotations

import argparse
import fnmatch
import getpass
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib import request, parse, error

DEFAULT_API = os.environ.get("SOPM_API_URL", "http://localhost:8000/api/v1")
CONFIG_DIR = Path.home() / ".sopm"
CONFIG_FILE = CONFIG_DIR / "credentials.json"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {"api_url": DEFAULT_API}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def http(method: str, path: str, *, token: str | None = None, api_key: str | None = None, data=None, headers=None, files=None):
    config = load_config()
    url = config.get("api_url", DEFAULT_API).rstrip("/") + path
    hdrs = dict(headers or {})
    body = None

    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if api_key:
        hdrs["X-SOPM-Key"] = api_key

    if files:
        boundary = "----sopm" + next(tempfile._get_candidate_names())
        chunks = []
        for name, value in (data or {}).items():
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        for name, path_value in files.items():
            path_obj = Path(path_value)
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{path_obj.name}\"\r\nContent-Type: application/zip\r\n\r\n".encode())
            chunks.append(path_obj.read_bytes())
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif isinstance(data, dict):
        body = json.dumps(data).encode()
        hdrs["Content-Type"] = "application/json"
    elif isinstance(data, str):
        body = data.encode()

    req = request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {raw}") from exc


def cmd_login(args) -> None:
    api_url = args.api_url or DEFAULT_API
    username = args.username or input("Username: ")
    password = args.password or getpass.getpass("Password: ")
    body = parse.urlencode({"username": username, "password": password})
    req = request.Request(
        api_url.rstrip("/") + "/auth/login",
        data=body.encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except error.HTTPError as exc:
        raise SystemExit(f"Login failed: {exc.read().decode(errors='replace')}") from exc

    config = load_config()
    config.update({"api_url": api_url, "token": payload["access_token"], "username": username})
    if args.api_key:
        config["api_key"] = args.api_key
    save_config(config)
    print(f"Logged in as {username}")


def ignore_patterns(root: Path) -> list[str]:
    ignore = root / ".sopmignore"
    if not ignore.exists():
        return []
    return [line.strip() for line in ignore.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


def should_ignore(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(Path(rel).name, pat) for pat in patterns)


def zip_folder(path: Path) -> Path:
    temp = Path(tempfile.mkstemp(prefix="sopm-deploy-", suffix=".zip")[1])
    patterns = ignore_patterns(path)
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in path.rglob("*"):
            if file.is_dir():
                continue
            rel = file.relative_to(path).as_posix()
            if should_ignore(rel, patterns):
                continue
            zf.write(file, rel)
    return temp


def find_function(token: str, name: str) -> dict | None:
    data = http("GET", "/functions?size=100", token=token)
    for fn in data.get("items", []):
        if fn.get("name") == name:
            return fn
    return None


def cmd_deploy(args) -> None:
    config = load_config()
    token = config.get("token")
    if not token:
        raise SystemExit("Run `sopm login` first.")

    root = Path(args.path).resolve()
    if not root.exists():
        raise SystemExit(f"Path not found: {root}")

    fn = find_function(token, args.function)
    if not fn:
        fn = http("POST", "/functions", token=token, data={"name": args.function, "description": None, "tags": {}})
        print(f"Created function {args.function}")

    archive = zip_folder(root)
    try:
        version = http(
            "POST",
            f"/functions/{fn['id']}/versions",
            token=token,
            data={"entrypoint": args.entrypoint, "timeout": args.timeout, "memory_mb": args.memory},
            files={"archive": archive},
        )
    finally:
        archive.unlink(missing_ok=True)
    print(json.dumps(version, indent=2))


def cmd_invoke(args) -> None:
    config = load_config()
    api_key = args.api_key or config.get("api_key")
    if not api_key:
        raise SystemExit("Provide --api-key or save one with `sopm login --api-key ...`.")
    token = config.get("token")
    fn = find_function(token, args.function) if token else None
    function_id = fn["id"] if fn else args.function
    payload = json.loads(args.payload) if args.payload else {}
    result = http("POST", f"/invoke/{function_id}?wait=true", api_key=api_key, data={"payload": payload})
    print(json.dumps(result, indent=2))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sopm")
    sub = parser.add_subparsers(required=True)

    login = sub.add_parser("login")
    login.add_argument("--api-url", default=DEFAULT_API)
    login.add_argument("--username")
    login.add_argument("--password")
    login.add_argument("--api-key")
    login.set_defaults(func=cmd_login)

    deploy = sub.add_parser("deploy")
    deploy.add_argument("path")
    deploy.add_argument("--function", required=True)
    deploy.add_argument("--entrypoint", default="handler.handler")
    deploy.add_argument("--timeout", type=int, default=300)
    deploy.add_argument("--memory", type=int, default=128)
    deploy.set_defaults(func=cmd_deploy)

    invoke = sub.add_parser("invoke")
    invoke.add_argument("function")
    invoke.add_argument("--payload")
    invoke.add_argument("--api-key")
    invoke.set_defaults(func=cmd_invoke)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
