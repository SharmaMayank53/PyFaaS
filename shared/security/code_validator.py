"""
SOPM - Code Security Validator

Uses AST analysis to reject dangerous Python constructs before execution.
This is a defense-in-depth measure; gVisor provides the primary sandbox.
"""
from __future__ import annotations

import ast
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Deny-list: these names are NEVER allowed in user code
# ---------------------------------------------------------------------------

DENIED_BUILTINS: frozenset[str] = frozenset(
    [
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
    ]
)

DENIED_MODULES: frozenset[str] = frozenset(
    [
        "subprocess",
        "socket",
        "os",
        "sys",
        "ctypes",
        "cffi",
        "importlib",
        "imp",
        "builtins",
        "shutil",
        "pathlib",
        "glob",
        "tempfile",
        "pty",
        "atexit",
        "signal",
        "multiprocessing",
        "threading",
        "concurrent",
        "asyncio",
        "ssl",
        "http",
        "urllib",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "pickle",
        "shelve",
        "marshal",
        "copyreg",
        "code",
        "codeop",
        "dis",
        "inspect",
        "gc",
        "weakref",
    ]
)

DENIED_ATTRIBUTES: frozenset[str] = frozenset(
    [
        "system",
        "popen",
        "spawn",
        "exec",
        "execve",
        "execvp",
        "fork",
        "kill",
        "listdir",
        "getcwd",
        "chdir",
        "environ",
        "__dict__",
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
        "__globals__",
        "__builtins__",
        "__code__",
        "__closure__",
    ]
)

# Allowed modules (allow-list for imports)
ALLOWED_MODULES: frozenset[str] = frozenset(
    [
        # Standard library (safe subset)
        "abc",
        "collections",
        "copy",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "hashlib",
        "hmac",
        "itertools",
        "json",
        "logging",
        "math",
        "operator",
        "pprint",
        "random",
        "re",
        "statistics",
        "string",
        "struct",
        "textwrap",
        "time",
        "traceback",
        "typing",
        "uuid",
        # Data science (safe)
        "numpy",
        "pandas",
        "scipy",
        "sklearn",
        # HTTP clients are allowed (network access controlled by NetworkPolicy)
        "requests",
        "httpx",
        "aiohttp",
        # Utilities
        "pydantic",
        "attrs",
        "cattrs",
        "arrow",
        "dateutil",
        "yaml",
        "toml",
        "csv",
        "io",
        "base64",
        "binascii",
        "codecs",
        "html",
        "xml",
        "urllib.parse",  # URL parsing only, not fetching
    ]
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_FILES = 50


@dataclass
class ValidationViolation:
    file: str
    line: int
    col: int
    message: str
    severity: str = "ERROR"


@dataclass
class ValidationResult:
    is_valid: bool
    violations: list[ValidationViolation] = field(default_factory=list)
    files_checked: int = 0
    error: str | None = None

    def add_violation(self, file: str, line: int, col: int, message: str) -> None:
        self.violations.append(ValidationViolation(file=file, line=line, col=col, message=message))
        self.is_valid = False


class CodeSecurityValidator:
    """
    Validates Python function archives using AST analysis.

    This is a defense-in-depth control. The primary sandbox is gVisor.
    """

    def validate_archive(self, archive_bytes: bytes) -> ValidationResult:
        """Validate all Python files in a zip archive."""
        result = ValidationResult(is_valid=True)

        # 1. Validate it's a valid zip
        if not zipfile.is_zipfile(BytesIO(archive_bytes)):
            result.is_valid = False
            result.error = "Uploaded file is not a valid ZIP archive"
            return result

        with zipfile.ZipFile(BytesIO(archive_bytes)) as zf:
            names = zf.namelist()

            # 2. Check file count
            if len(names) > MAX_FILES:
                result.is_valid = False
                result.error = f"Archive contains too many files: {len(names)} > {MAX_FILES}"
                return result

            # 3. Check for path traversal
            for name in names:
                if name.startswith("/") or ".." in name:
                    result.is_valid = False
                    result.error = f"Suspicious path in archive: {name}"
                    return result

            # 4. Validate each Python file
            py_files = [n for n in names if n.endswith(".py")]
            if not py_files:
                result.is_valid = False
                result.error = "Archive contains no Python (.py) files"
                return result

            for name in py_files:
                info = zf.getinfo(name)
                if info.file_size > MAX_FILE_SIZE:
                    result.is_valid = False
                    result.error = f"File {name} exceeds size limit"
                    return result

                source = zf.read(name).decode("utf-8", errors="replace")
                result.files_checked += 1
                self._validate_source(source, name, result)
                if not result.is_valid and len(result.violations) > 10:
                    # Short-circuit: too many violations
                    return result

        return result

    def _validate_source(self, source: str, filename: str, result: ValidationResult) -> None:
        """Parse and validate a single Python source file."""
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            result.add_violation(
                filename,
                exc.lineno or 0,
                exc.offset or 0,
                f"Syntax error: {exc.msg}",
            )
            return

        visitor = _ASTValidator(filename, result)
        visitor.visit(tree)


class _ASTValidator(ast.NodeVisitor):
    """AST node visitor that flags dangerous constructs."""

    def __init__(self, filename: str, result: ValidationResult) -> None:
        self._file = filename
        self._result = result

    def _flag(self, node: ast.AST, message: str) -> None:
        self._result.add_violation(
            self._file,
            getattr(node, "lineno", 0),
            getattr(node, "col_offset", 0),
            message,
        )

    # -- Imports -------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root in DENIED_MODULES:
                self._flag(node, f"Forbidden import: '{alias.name}'")
            elif root not in ALLOWED_MODULES and not alias.name.split(".")[0] in ALLOWED_MODULES:
                # Warn about unknown modules but allow them (pip may install them)
                pass
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        root = module.split(".")[0]
        if root in DENIED_MODULES:
            self._flag(node, f"Forbidden import: 'from {module} import ...'")
        self.generic_visit(node)

    # -- Dangerous calls -----------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        # Direct call: eval(...), exec(...), compile(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in DENIED_BUILTINS:
                self._flag(node, f"Forbidden call: '{node.func.id}()'")

        # Attribute call: os.system(...), subprocess.run(...)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in DENIED_ATTRIBUTES:
                self._flag(node, f"Forbidden attribute access: '.{node.func.attr}'")

        # __import__("os")
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            self._flag(node, "Dynamic imports via __import__() are forbidden")

        self.generic_visit(node)

    # -- Dangerous attribute access -----------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in DENIED_ATTRIBUTES:
            self._flag(node, f"Forbidden attribute: '.{node.attr}'")
        self.generic_visit(node)

    # -- __dunder__ names ---------------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in DENIED_BUILTINS:
            self._flag(node, f"Use of forbidden name: '{node.id}'")
        self.generic_visit(node)

    # -- Global / nonlocal (harmless but flag __builtins__ re-assignment) ---

    def visit_Global(self, node: ast.Global) -> None:
        for name in node.names:
            if name == "__builtins__":
                self._flag(node, "Manipulation of '__builtins__' is forbidden")
        self.generic_visit(node)


def validate_function_archive(archive_bytes: bytes) -> ValidationResult:
    """Module-level convenience wrapper."""
    return CodeSecurityValidator().validate_archive(archive_bytes)
