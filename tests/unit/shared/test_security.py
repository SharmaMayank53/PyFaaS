"""Tests for the AST-based code security validator."""
from __future__ import annotations

import io
import zipfile

import pytest

from shared.security.code_validator import validate_function_archive


def _make_zip(**files: str) -> bytes:
    """Create a zip archive from a mapping of filename -> source."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, source in files.items():
            zf.writestr(name, source)
    return buf.getvalue()


class TestValidArchives:
    def test_simple_handler(self) -> None:
        archive = _make_zip(**{"handler.py": "def handler(event):\n    return {'ok': True}\n"})
        result = validate_function_archive(archive)
        assert result.is_valid
        assert result.files_checked == 1

    def test_handler_with_allowed_imports(self) -> None:
        source = (
            "import json\nimport math\nfrom datetime import datetime\n"
            "def handler(event):\n    return {'ts': str(datetime.now())}\n"
        )
        archive = _make_zip(**{"handler.py": source})
        result = validate_function_archive(archive)
        assert result.is_valid

    def test_multiple_modules(self) -> None:
        archive = _make_zip(
            **{
                "handler.py": "from utils import compute\ndef handler(e): return compute(e)\n",
                "utils.py": "def compute(x): return x\n",
            }
        )
        result = validate_function_archive(archive)
        assert result.is_valid


class TestRejectedArchives:
    def test_eval_call(self) -> None:
        archive = _make_zip(**{"handler.py": "def handler(e):\n    return eval(e['code'])\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid
        assert any("eval" in v.message for v in result.violations)

    def test_exec_call(self) -> None:
        archive = _make_zip(**{"handler.py": "exec('import os')\ndef handler(e): pass\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_os_import(self) -> None:
        archive = _make_zip(**{"handler.py": "import os\ndef handler(e): return os.listdir('/')\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_subprocess_import(self) -> None:
        archive = _make_zip(**{"handler.py": "import subprocess\ndef handler(e): pass\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_os_system_via_attribute(self) -> None:
        archive = _make_zip(**{"handler.py": "import os\ndef handler(e):\n    os.system('id')\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_dunder_import(self) -> None:
        archive = _make_zip(
            **{"handler.py": "__import__('os').system('id')\ndef handler(e): pass\n"}
        )
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_compile_call(self) -> None:
        archive = _make_zip(**{"handler.py": "compile('1+1', '<str>', 'eval')\ndef h(e): pass\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_from_os_import(self) -> None:
        archive = _make_zip(**{"handler.py": "from os import system\ndef handler(e): pass\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_socket_import(self) -> None:
        archive = _make_zip(**{"handler.py": "import socket\ndef handler(e): pass\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid

    def test_path_traversal_in_archive(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.py", "import os")
        result = validate_function_archive(buf.getvalue())
        assert not result.is_valid

    def test_not_a_zip(self) -> None:
        result = validate_function_archive(b"this is not a zip file")
        assert not result.is_valid
        assert "not a valid ZIP" in (result.error or "")

    def test_no_python_files(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.md", "# hi")
        result = validate_function_archive(buf.getvalue())
        assert not result.is_valid
        assert "no Python" in (result.error or "")

    def test_syntax_error_flagged(self) -> None:
        archive = _make_zip(**{"handler.py": "def handler(:\n    pass\n"})
        result = validate_function_archive(archive)
        assert not result.is_valid
        assert any("Syntax error" in v.message for v in result.violations)


class TestStateTransitions:
    def test_valid_transitions(self) -> None:
        from shared.db.models import ExecutionStatus, validate_transition

        validate_transition(ExecutionStatus.PENDING, ExecutionStatus.QUEUED)
        validate_transition(ExecutionStatus.QUEUED, ExecutionStatus.RUNNING)
        validate_transition(ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED)
        validate_transition(ExecutionStatus.RUNNING, ExecutionStatus.FAILED)
        validate_transition(ExecutionStatus.RUNNING, ExecutionStatus.TIMED_OUT)

    def test_invalid_transition_raises(self) -> None:
        from shared.db.models import ExecutionStatus, validate_transition

        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(ExecutionStatus.COMPLETED, ExecutionStatus.RUNNING)

    def test_terminal_state_no_transition(self) -> None:
        from shared.db.models import ExecutionStatus, validate_transition

        for terminal in (
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.TIMED_OUT,
            ExecutionStatus.CANCELLED,
        ):
            with pytest.raises(ValueError):
                validate_transition(terminal, ExecutionStatus.RUNNING)
