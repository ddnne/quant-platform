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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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

_ACQUISITION_TOKEN = object()
_AUTHENTICATED_TOKEN = object()


def _validated_governed_wrangler() -> tuple[str, Path]:
    """Return the repository-pinned executable/config after authority checks.

    Production acquisition deliberately has no executable, config, environment,
    database-name, or database-id override.
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
    try:
        completed = subprocess.run(
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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in conn.execute(f'PRAGMA table_xinfo("{table}")'))


def _fingerprint_value(column: str, value: Any) -> Any:
    if column == "available_at" and isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return value
    return value


def _table_fingerprint(
    conn: sqlite3.Connection, table: str, columns: tuple[str, ...]
) -> tuple[int, str]:
    if not columns:
        raise ValueError(f"governed table has no columns: {table}")
    selected = ",".join(f'"{column}"' for column in columns)
    row_digests: list[bytes] = []
    count = 0
    for row in conn.execute(f'SELECT {selected} FROM "{table}"'):
        encoded = json.dumps(
            [
                _fingerprint_value(column, row[index])
                for index, column in enumerate(columns)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        row_digests.append(hashlib.sha256(encoded).digest())
        count += 1
    digest = hashlib.sha256()
    digest.update(str(count).encode("ascii"))
    digest.update(b"\0")
    for row_digest in sorted(row_digests):
        digest.update(row_digest)
    return count, "sha256:" + digest.hexdigest()


def governed_content_identity(
    conn: sqlite3.Connection, tables: tuple[str, ...]
) -> tuple[str, str, dict[str, int]]:
    """Hash one exact governed schema/content inventory.

    This is read-only and grants no remote provenance.  Every table and every
    physical column participates so a source-only or local-only schema drift
    cannot be laundered through a shared-column projection.
    """

    inventory: dict[str, dict[str, Any]] = {}
    schema: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for table in tables:
        if not _table_exists(conn, table):
            raise ValueError(f"governed mirror is missing table: {table}")
        columns = _table_columns(conn, table)
        count, digest = _table_fingerprint(conn, table, columns)
        schema[table] = list(columns)
        counts[table] = count
        inventory[table] = {
            "columns": list(columns),
            "count": count,
            "digest": digest,
        }
    schema_bytes = json.dumps(
        schema, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    content_bytes = json.dumps(
        inventory, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return (
        "sha256:" + hashlib.sha256(content_bytes).hexdigest(),
        "sha256:" + hashlib.sha256(schema_bytes).hexdigest(),
        counts,
    )


def _exact_source_local_reconciliation(
    source: sqlite3.Connection,
    local: sqlite3.Connection,
    tables: tuple[str, ...],
) -> tuple[str, str, dict[str, int]]:
    for table in tables:
        if not _table_exists(source, table):
            raise ValueError(f"D1 export is missing governed table: {table}")
        if not _table_exists(local, table):
            raise ValueError(f"local mirror is missing governed table: {table}")
        source_columns = _table_columns(source, table)
        local_columns = _table_columns(local, table)
        if source_columns != local_columns:
            raise ValueError(
                "authenticated D1 source/local schema mismatch for "
                f"{table}: source={list(source_columns)} local={list(local_columns)}"
            )
        source_count, source_digest = _table_fingerprint(
            source, table, source_columns
        )
        local_count, local_digest = _table_fingerprint(local, table, local_columns)
        if source_count != local_count or source_digest != local_digest:
            raise ValueError(
                "authenticated D1 source/local content mismatch for "
                f"{table}: source_count={source_count} local_count={local_count}"
            )
    source_identity, source_schema, source_counts = governed_content_identity(
        source, tables
    )
    local_identity, local_schema, local_counts = governed_content_identity(local, tables)
    if (
        source_identity != local_identity
        or source_schema != local_schema
        or source_counts != local_counts
    ):
        raise ValueError("authenticated D1 governed inventory reconciliation failed")
    return source_identity, source_schema, source_counts


def _change_seq(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "ingestion_change_log"):
        raise ValueError("D1 export is missing ingestion_change_log")
    row = conn.execute(
        "SELECT COALESCE(MAX(change_seq), 0) FROM ingestion_change_log"
    ).fetchone()
    value = row[0] if row is not None else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("D1 export change cursor is invalid")
    return value


def _local_change_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT last_applied_change_seq FROM sync_change_state "
        "WHERE feed='jquants_records'"
    ).fetchone()
    value = row[0] if row is not None else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("local D1 applied cursor is invalid")
    return value


class _AuthenticatedWranglerExport:
    """Opaque, single-use proof minted only after exact local reconciliation."""

    __slots__ = ("_document", "_audit_digest", "_consumed")

    def __init__(self, document: dict[str, Any], *, _token: object | None = None):
        if _token is not _AUTHENTICATED_TOKEN:
            raise RuntimeError("authenticated Wrangler export has no public constructor")
        from ops.d1_sync_signing import d1_sync_digest

        self._document = document
        self._audit_digest = d1_sync_digest(document)
        self._consumed = False

    def _consume(self) -> tuple[str, str, str, dict[str, Any]]:
        if self._consumed:
            raise RuntimeError("authenticated Wrangler export was already consumed")
        self._consumed = True
        return (
            self._audit_digest,
            self._document["issuer_key_id"],
            self._document["signature"],
            dict(self._document),
        )


class _PinnedWranglerExport:
    """Actual pinned remote export pending exact source/local reconciliation."""

    __slots__ = (
        "export_digest",
        "artifact_size",
        "artifact_format",
        "_sqlite_path",
        "_signer",
        "_authenticated",
    )

    def __init__(
        self,
        *,
        export_digest: str,
        artifact_size: int,
        artifact_format: str,
        sqlite_path: Path,
        signer: Any,
        _token: object | None = None,
    ) -> None:
        if _token is not _ACQUISITION_TOKEN:
            raise RuntimeError("pinned Wrangler export has no public constructor")
        self.export_digest = export_digest
        self.artifact_size = artifact_size
        self.artifact_format = artifact_format
        self._sqlite_path = sqlite_path
        self._signer = signer
        self._authenticated = False

    def open_source(self) -> sqlite3.Connection:
        return open_export_sqlite(self._sqlite_path)

    def authenticate_local(
        self,
        local: sqlite3.Connection,
        tables: tuple[str, ...],
        *,
        sync_kind: str,
        prior_audit_digest: str | None,
    ) -> _AuthenticatedWranglerExport:
        if self._authenticated:
            raise RuntimeError("pinned Wrangler export authentication is single-use")
        with open_export_sqlite(self._sqlite_path) as source:
            source_cursor = _change_seq(source)
            local_cursor = _local_change_seq(local)
            if source_cursor != local_cursor:
                raise ValueError(
                    "authenticated D1 source/local applied cursor mismatch"
                )
            content_digest, schema_digest, counts = (
                _exact_source_local_reconciliation(source, local, tables)
            )
        from ops.d1_sync_signing import (
            AUDIT_ENVELOPE_SCHEMA,
            GOVERNED_AUTHORITY_ID,
            d1_sync_digest,
        )

        registry_digest = self._signer._registry_digest  # noqa: SLF001
        envelope = {
            "schema_version": AUDIT_ENVELOPE_SCHEMA,
            "authority_id": GOVERNED_AUTHORITY_ID,
            "source_mode": "WRANGLER_REMOTE",
            "d1_name": GOVERNED_D1_NAME,
            "d1_id": GOVERNED_D1_ID,
            "sync_kind": sync_kind,
            "export_digest": self.export_digest,
            "artifact_format": self.artifact_format,
            "source_change_seq": source_cursor,
            "applied_change_seq": local_cursor,
            "source_content_digest": content_digest,
            "local_content_digest": content_digest,
            "schema_digest": schema_digest,
            "table_counts": counts,
            "prior_audit_digest": prior_audit_digest,
            "registry_digest": registry_digest,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
        document = self._signer.sign(envelope)
        # Ensure canonical serialization is possible before consuming the
        # acquisition. This also makes the final audit digest deterministic.
        d1_sync_digest(document)
        self._authenticated = True
        return _AuthenticatedWranglerExport(document, _token=_AUTHENTICATED_TOKEN)


def acquire_pinned_wrangler_export(directory: Path) -> _PinnedWranglerExport:
    """Acquire, materialize, and bind one governed remote D1 export.

    The production entrypoint has no executable/config/env/database/key
    override. Tests simulate the provider by monkeypatching ``subprocess.run``
    while still traversing every pinned validation and materialization step.
    """

    from ops.d1_sync_signing import _load_pinned_d1_sync_signer

    signer = _load_pinned_d1_sync_signer()
    raw_artifact = directory / "remote-export.sql"
    run_wrangler_d1_export(output_path=raw_artifact)
    materialized = directory / "remote-export.sqlite"
    export_digest, artifact_size, artifact_format = materialize_d1_export(
        raw_artifact, materialized
    )
    return _PinnedWranglerExport(
        export_digest=export_digest,
        artifact_size=artifact_size,
        artifact_format=artifact_format,
        sqlite_path=materialized,
        signer=signer,
        _token=_ACQUISITION_TOKEN,
    )
