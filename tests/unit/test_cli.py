import io
import json
import zipfile
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from cli import sopm


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr(sopm, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(sopm, "CONFIG_FILE", tmp_path / "config" / "credentials.json")
    return tmp_path


def test_login_persists_credentials(config, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"access_token":"token"}'
    open_url = MagicMock(return_value=response)
    monkeypatch.setattr(sopm.request, "urlopen", open_url)
    assert sopm.load_config() == {"api_url": sopm.DEFAULT_API}
    assert sopm.main(["login", "--username", "user", "--password", "pass", "--api-key", "key"]) == 0
    assert sopm.load_config()["token"] == "token"
    assert sopm.load_config()["api_key"] == "key"
    assert open_url.call_args.args[0].data == b"username=user&password=pass"


@pytest.mark.parametrize("command", ["login", "http"])
def test_reject_non_http_urls(config, command):
    sopm.save_config({"api_url": "file:///private"})
    if command == "login":
        with pytest.raises(ValueError, match="http or https"):
            sopm.main(["login", "--api-url", "file:///private"])
    else:
        with pytest.raises(ValueError, match="http or https"):
            sopm.http("GET", "/functions")


@pytest.mark.parametrize("data", [{"value": 1}, "raw-body", None])
def test_http_encodes_auth_and_body(config, monkeypatch, data):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"ok":true}'
    open_url = MagicMock(return_value=response)
    monkeypatch.setattr(sopm.request, "urlopen", open_url)
    assert sopm.http("POST", "/test", data=data, token="token", api_key="key") == {"ok": True}
    req = open_url.call_args.args[0]
    assert req.get_header("Authorization") == "Bearer token"
    assert req.get_header("X-sopm-key") == "key"
    assert req.data == (
        json.dumps(data).encode() if isinstance(data, dict) else data.encode() if data else None
    )


def test_multipart_upload(config, monkeypatch):
    archive = config / "source.zip"
    archive.write_bytes(b"archive")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b""
    open_url = MagicMock(return_value=response)
    monkeypatch.setattr(sopm.request, "urlopen", open_url)
    assert sopm.http("POST", "/upload", data={"timeout": 30}, files={"archive": archive}) is None
    req = open_url.call_args.args[0]
    assert b'filename="source.zip"' in req.data
    assert b"archive\r\n" in req.data
    assert req.get_header("Content-type").startswith("multipart/form-data")


@pytest.mark.parametrize("login", [True, False])
def test_http_errors_include_server_message(config, monkeypatch, login):
    monkeypatch.setattr(
        sopm.request,
        "urlopen",
        MagicMock(
            side_effect=HTTPError(
                "http://api", 403, "Forbidden", {}, io.BytesIO(b"permission denied")
            )
        ),
    )
    if login:
        with pytest.raises(SystemExit, match="permission denied"):
            sopm.main(["login", "--username", "user", "--password", "pass"])
    else:
        with pytest.raises(SystemExit, match="permission denied"):
            sopm.http("GET", "/functions")


def test_zip_ignores_and_deploy_cleanup(config, monkeypatch):
    source = config / "source"
    source.mkdir()
    (source / "handler.py").write_text("def handler(): return 1")
    (source / "secret.env").write_text("secret")
    (source / "subdir").mkdir()
    (source / ".sopmignore").write_text("# secrets\n*.env\n\n")
    assert sopm.ignore_patterns(config) == []
    sopm.save_config({"token": "token"})
    uploaded = []

    def http(method, path, **kwargs):
        if method == "GET":
            return {"items": []}
        if path == "/functions":
            return {"id": "fn"}
        uploaded.append(kwargs["files"]["archive"])
        with zipfile.ZipFile(uploaded[-1]) as archive:
            assert "handler.py" in archive.namelist()
            assert "secret.env" not in archive.namelist()
        return {"version_number": 1}

    monkeypatch.setattr(sopm, "http", http)
    assert sopm.main(["deploy", str(source), "--function", "fn"]) == 0
    assert not uploaded[0].exists()


def test_invoke_resolves_name_and_payload(config, monkeypatch, capsys):
    sopm.save_config({"token": "token", "api_key": "key"})
    http = MagicMock(side_effect=[{"items": [{"id": "id", "name": "fn"}]}, {"status": "QUEUED"}])
    monkeypatch.setattr(sopm, "http", http)
    sopm.main(["invoke", "fn", "--payload", '{"x":1}'])
    assert http.call_args.args == ("POST", "/invoke/id?wait=true")
    assert http.call_args.kwargs["data"] == {"payload": {"x": 1}}
    assert json.loads(capsys.readouterr().out)["status"] == "QUEUED"


def test_missing_credentials_and_path(config):
    with pytest.raises(SystemExit, match="login"):
        sopm.main(["deploy", str(config), "--function", "fn"])
    with pytest.raises(SystemExit, match="api-key"):
        sopm.main(["invoke", "fn"])
    sopm.save_config({"token": "token"})
    with pytest.raises(SystemExit, match="Path not found"):
        sopm.main(["deploy", str(config / "missing"), "--function", "fn"])
