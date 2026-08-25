"""Private Cloudflare D1 export acquisition and isolated materialization.

This module owns the only subprocess boundary used by local D1 sync. It never
places credentials in argv, never uses a shell, and never returns provider
stdout/stderr to the caller. Wrangler SQL and standalone SQLite artifacts are
materialized into a caller-owned temporary directory before any product table
is read.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import tomllib
from pathlib import Path
from typing import Callable
from urllib.parse import quote

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WRANGLER_CONFIG = (
    _REPO_ROOT / "platform" / "workers" / "ingestion-premium" / "wrangler.toml"
)
DEFAULT_WRANGLER_BIN = (
    _REPO_ROOT
    / "platform"
    / "workers"
    / "ingestion-premium"
    / "node_modules"
    / ".bin"
    / "wrangler"
)
PINNED_WRANGLER_VERSION = "4.125.0"
GOVERNED_D1_NAME = "quant-ingest"
GOVERNED_D1_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
GOVERNED_WRANGLER_ENV = "production"


def run_process(argv: list[str], **kwargs):
    """Injectable subprocess boundary; production delegates to subprocess.run."""
    return subprocess.run(argv, **kwargs)


def _validated_governed_wrangler() -> tuple[str, Path]:
    """Return the repository-pinned executable/config after authority checks.

    Production acquisition deliberately has no executable, config, environment,
    database-name, or database-id override.  A caller can inject only the
    private process runner used by unit tests; it cannot change the command.
    """
    executable = DEFAULT_WRANGLER_BIN.resolve()
    config = DEFAULT_WRANGLER_CONFIG.resolve()
    package_json = executable.parents[1] / "package.json"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(
            "repository-pinned Wrangler is unavailable; install the locked "
            "ingestion-premium dependencies"
        )
    try:
        installed_version = str(
            json.loads(package_json.read_text(encoding="utf-8"))["version"]
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("cannot verify the repository-pinned Wrangler") from exc
    if installed_version != PINNED_WRANGLER_VERSION:
        raise RuntimeError("repository Wrangler version does not match the pinned policy")
    try:
        document = tomllib.loads(config.read_text(encoding="utf-8"))
        production = document["env"][GOVERNED_WRANGLER_ENV]
        bindings = production["d1_databases"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("cannot verify the governed production D1 binding") from exc
    expected = {
        "binding": "DB",
        "database_name": GOVERNED_D1_NAME,
        "database_id": GOVERNED_D1_ID,
    }
    if bindings != [expected]:
        raise RuntimeError("production Wrangler config is not bound to governed D1")
    return str(executable), config


def run_wrangler_d1_export(
    *,
    output_path: Path,
    runner: Callable[..., object] | None = None,
) -> None:
    """Acquire a private D1 SQL export with the current Wrangler credentials.

    No credential is placed in argv, printed, or copied to the artifact. The
    child inherits Wrangler's normal authenticated profile/environment. Its
    output is withheld because provider diagnostics can contain account data.
    """
    executable, config = _validated_governed_wrangler()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        executable,
        "d1",
        "export",
        GOVERNED_D1_NAME,
        "--remote",
        "--output",
        str(output_path),
        "--config",
        str(config),
        "--env",
        GOVERNED_WRANGLER_ENV,
        "--skip-confirmation",
    ]
    if runner is not None and not os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("Wrangler runner injection is test-only")
    invoke = runner or subprocess.run
    try:
        completed = invoke(
            command,
            cwd=str(config.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError("failed to start Wrangler D1 export") from exc
    returncode = getattr(completed, "returncode", None)
    if returncode != 0:
        raise RuntimeError(
            f"Wrangler D1 export failed (exit={returncode}); provider output withheld"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("Wrangler D1 export produced no SQL artifact")
    output_path.chmod(0o600)


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return f"sha256:{digest.hexdigest()}", size


def _sql_import_authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    _database: str | None,
    _trigger: str | None,
) -> int:
    """Deny SQL features that can escape the private temporary database."""
    if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        function = str(arg2 or arg1 or "").lower()
        if function in {"load_extension", "readfile", "writefile"}:
            return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA and str(arg1 or "").lower() == "writable_schema":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _import_d1_sql(sql_path: Path, sqlite_path: Path) -> None:
    """Stream a Wrangler SQL export into an isolated SQLite database."""
    conn = sqlite3.connect(sqlite_path)
    conn.enable_load_extension(False)
    conn.set_authorizer(_sql_import_authorizer)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    statement_parts: list[str] = []
    statement_bytes = 0
    max_statement_bytes = 256 * 1024 * 1024
    try:
        with sql_path.open("r", encoding="utf-8", newline="") as handle:
            for line in handle:
                if line.lstrip().startswith("."):
                    raise ValueError("SQLite dot-commands are not allowed in D1 export")
                statement_parts.append(line)
                statement_bytes += len(line.encode("utf-8"))
                if statement_bytes > max_statement_bytes:
                    raise ValueError("D1 export contains an oversized SQL statement")
                candidate = "".join(statement_parts)
                if not sqlite3.complete_statement(candidate):
                    continue
                if candidate.strip():
                    conn.execute(candidate)
                statement_parts.clear()
                statement_bytes = 0
        if "".join(statement_parts).strip():
            raise ValueError("D1 export ends with an incomplete SQL statement")
        conn.commit()
    except (OSError, UnicodeError, sqlite3.Error) as exc:
        conn.rollback()
        raise ValueError("D1 export SQL import failed; statement content withheld") from exc
    finally:
        conn.close()
    sqlite_path.chmod(0o600)


def _validate_sqlite_artifact(path: Path) -> None:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result is None or str(result[0]).lower() != "ok":
            raise ValueError("D1 export SQLite integrity check failed")
    finally:
        conn.close()


def materialize_d1_export(
    artifact: Path,
    sqlite_path: Path,
) -> tuple[str, int, str]:
    """Materialize a standalone Wrangler SQL/SQLite artifact for read-only sync."""
    source = artifact.expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("D1 export artifact is not a regular file")
    digest, size = _file_sha256(source)
    if size == 0:
        raise ValueError("D1 export artifact is empty")
    with source.open("rb") as handle:
        is_sqlite = handle.read(16) == b"SQLite format 3\x00"
    if is_sqlite:
        wal_path = Path(f"{source}-wal")
        if wal_path.exists() and wal_path.stat().st_size:
            raise ValueError(
                "SQLite artifact has a live WAL; checkpoint it before offline sync"
            )
        source_uri = f"file:{quote(str(source), safe='/')}?mode=ro&immutable=1"
        source_conn = sqlite3.connect(source_uri, uri=True)
        destination = sqlite3.connect(sqlite_path)
        try:
            source_conn.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source_conn.close()
        artifact_format = "sqlite"
    else:
        _import_d1_sql(source, sqlite_path)
        artifact_format = "sql"
    sqlite_path.chmod(0o600)
    _validate_sqlite_artifact(sqlite_path)
    return digest, size, artifact_format


def open_export_sqlite(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn
