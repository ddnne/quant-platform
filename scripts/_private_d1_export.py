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
import stat
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from weakref import WeakSet

from storage.migrations import SNAPSHOT_INVALIDATION_TRIGGERS

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


@dataclass(frozen=True, slots=True)
class _PinnedFileIdentity:
    device: int
    inode: int
    size: int
    digest: str


def _measure_regular_file(path: Path) -> _PinnedFileIdentity:
    """Hash one opened inode and prove the path still names that inode."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        path_before = path.stat()
        if not stat.S_ISREG(before.st_mode) or (
            path_before.st_dev,
            path_before.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise ValueError("D1 export artifact identity changed while opening")
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(handle.fileno())
        path_after = path.stat()
    if (
        (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        or (path_after.st_dev, path_after.st_ino)
        != (before.st_dev, before.st_ino)
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or size != after.st_size
    ):
        raise ValueError("D1 export artifact changed while hashing")
    return _PinnedFileIdentity(
        device=before.st_dev,
        inode=before.st_ino,
        size=size,
        digest=f"sha256:{digest.hexdigest()}",
    )


def _file_sha256(path: Path) -> tuple[str, int]:
    identity = _measure_regular_file(path)
    return identity.digest, identity.size


def _require_file_identity(path: Path, expected: _PinnedFileIdentity) -> None:
    observed = _measure_regular_file(path)
    if observed != expected:
        raise ValueError("pinned D1 export artifact identity changed")


def _snapshot_source_artifact(
    source: Path, destination_directory: Path
) -> tuple[Path, _PinnedFileIdentity]:
    """Copy and hash a raw artifact from the same single opened file view."""
    destination_directory.mkdir(parents=True, exist_ok=True)
    snapshot_path: Path | None = None
    try:
        with source.open("rb") as input_handle:
            before = os.fstat(input_handle.fileno())
            path_before = source.stat()
            if not stat.S_ISREG(before.st_mode) or (
                path_before.st_dev,
                path_before.st_ino,
            ) != (before.st_dev, before.st_ino):
                raise ValueError("D1 export artifact identity changed while opening")
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=".pinned-d1-source-",
                dir=destination_directory,
                delete=False,
            ) as output_handle:
                snapshot_path = Path(output_handle.name)
                for chunk in iter(lambda: input_handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
                    output_handle.write(chunk)
                output_handle.flush()
                os.fsync(output_handle.fileno())
            after = os.fstat(input_handle.fileno())
            path_after = source.stat()
        if (
            (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
            or (path_after.st_dev, path_after.st_ino)
            != (before.st_dev, before.st_ino)
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or size != after.st_size
        ):
            raise ValueError("D1 export artifact changed while snapshotting")
        assert snapshot_path is not None
        snapshot_path.chmod(0o600)
        identity = _measure_regular_file(snapshot_path)
        if identity.digest != f"sha256:{digest.hexdigest()}" or identity.size != size:
            raise ValueError("D1 export artifact snapshot digest changed")
        return snapshot_path, identity
    except Exception:
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)
        raise


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


def _materialize_d1_export_with_identity(
    artifact: Path,
    sqlite_path: Path,
) -> tuple[str, int, str, _PinnedFileIdentity]:
    """Materialize a standalone Wrangler SQL/SQLite artifact for read-only sync."""
    source = artifact.expanduser().resolve(strict=True)
    wal_path = Path(f"{source}-wal")
    if wal_path.exists() and wal_path.stat().st_size:
        raise ValueError(
            "SQLite artifact has a live WAL; checkpoint it before offline sync"
        )
    snapshot, raw_identity = _snapshot_source_artifact(source, sqlite_path.parent)
    try:
        if raw_identity.size == 0:
            raise ValueError("D1 export artifact is empty")
        with snapshot.open("rb") as handle:
            is_sqlite = handle.read(16) == b"SQLite format 3\x00"
        if is_sqlite and wal_path.exists() and wal_path.stat().st_size:
            raise ValueError(
                "SQLite artifact has a live WAL; checkpoint it before offline sync"
            )
        if sqlite_path.exists():
            raise ValueError("D1 materialized destination already exists")
        descriptor = os.open(
            sqlite_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            created = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        created_identity = (created.st_dev, created.st_ino)
        if is_sqlite:
            source_uri = (
                f"file:{quote(str(snapshot), safe='/')}?mode=ro&immutable=1"
            )
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
            _import_d1_sql(snapshot, sqlite_path)
            artifact_format = "sql"
        sqlite_path.chmod(0o600)
        _validate_sqlite_artifact(sqlite_path)
        materialized_identity = _measure_regular_file(sqlite_path)
        if (
            materialized_identity.device,
            materialized_identity.inode,
        ) != created_identity:
            raise ValueError("D1 materialized artifact path was replaced")
        _require_file_identity(snapshot, raw_identity)
        return (
            raw_identity.digest,
            raw_identity.size,
            artifact_format,
            materialized_identity,
        )
    finally:
        snapshot.unlink(missing_ok=True)


def materialize_d1_export(
    artifact: Path,
    sqlite_path: Path,
) -> tuple[str, int, str]:
    digest, size, artifact_format, _identity = (
        _materialize_d1_export_with_identity(artifact, sqlite_path)
    )
    return digest, size, artifact_format


def open_export_sqlite(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def reject_temp_governed_deputies(
    conn: sqlite3.Connection, tables: tuple[str, ...]
) -> None:
    """TEMP objects must never shadow or trigger governed main objects."""
    governed = tuple(
        sorted(
            set(tables)
            | {
                "ingestion_change_log",
                "sync_change_state",
                "local_d1_export_sync_runs",
            }
        )
    )
    placeholders = ",".join("?" for _ in governed)
    deputy = conn.execute(
        "SELECT type,name,tbl_name FROM sqlite_temp_master "
        f"WHERE name IN ({placeholders}) OR tbl_name IN ({placeholders}) "
        "LIMIT 1",
        (*governed, *governed),
    ).fetchone()
    if deputy is not None:
        raise ValueError("temporary object shadows governed D1 state")


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _canonical_schema_sql(value: object) -> str | None:
    """Collapse insignificant DDL whitespace without changing quoted text."""
    if value is None:
        return None
    text = str(value)
    rendered: list[str] = []
    pending_space = False
    quote_end: str | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if quote_end is not None:
            rendered.append(character)
            if character == quote_end:
                if quote_end != "]" and index + 1 < len(text) and text[index + 1] == quote_end:
                    rendered.append(text[index + 1])
                    index += 1
                else:
                    quote_end = None
            index += 1
            continue
        if character.isspace():
            pending_space = bool(rendered)
            index += 1
            continue
        if pending_space:
            rendered.append(" ")
            pending_space = False
        rendered.append(character)
        if character in {"'", '"', "`"}:
            quote_end = character
        elif character == "[":
            quote_end = "]"
        index += 1
    return "".join(rendered).strip()


def _table_schema_manifest(
    conn: sqlite3.Connection, table: str
) -> dict[str, Any]:
    """Return a deterministic manifest of SQLite structural semantics."""
    table_identifier = _quoted_identifier(table)
    xinfo = [
        {
            "cid": int(row[0]),
            "name": str(row[1]),
            "type": str(row[2] or ""),
            "not_null": int(row[3]),
            "default": row[4],
            "primary_key_ordinal": int(row[5]),
            "hidden": int(row[6]),
        }
        for row in conn.execute(f"PRAGMA main.table_xinfo({table_identifier})")
    ]
    if not xinfo:
        raise ValueError(f"governed table has no columns: {table}")

    master = [
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table_name": str(row[2]),
            "sql": _canonical_schema_sql(row[3]),
        }
        for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM main.sqlite_master "
            "WHERE (type='table' AND name=?) "
            "OR (type IN ('index','trigger') AND tbl_name=?) "
            "ORDER BY type,name",
            (table, table),
        )
    ]

    indexes: list[dict[str, Any]] = []
    index_rows = list(
        conn.execute(f"PRAGMA main.index_list({table_identifier})")
    )
    for row in sorted(index_rows, key=lambda candidate: str(candidate[1])):
        name = str(row[1])
        index_identifier = _quoted_identifier(name)
        columns = [
            {
                "sequence": int(item[0]),
                "column_id": int(item[1]),
                "name": None if item[2] is None else str(item[2]),
                "descending": int(item[3]),
                "collation": None if item[4] is None else str(item[4]),
                "key": int(item[5]),
            }
            for item in conn.execute(
                f"PRAGMA main.index_xinfo({index_identifier})"
            )
        ]
        indexes.append(
            {
                "name": name,
                "unique": int(row[2]),
                "origin": str(row[3]),
                "partial": int(row[4]),
                "columns": columns,
            }
        )

    foreign_keys = [
        {
            "id": int(row[0]),
            "sequence": int(row[1]),
            "target_table": str(row[2]),
            "from": None if row[3] is None else str(row[3]),
            "to": None if row[4] is None else str(row[4]),
            "on_update": str(row[5]),
            "on_delete": str(row[6]),
            "match": str(row[7]),
        }
        for row in conn.execute(
            f"PRAGMA main.foreign_key_list({table_identifier})"
        )
    ]
    return {
        "table_xinfo": xinfo,
        "sqlite_master": master,
        "indexes": indexes,
        "foreign_keys": foreign_keys,
    }


_CANONICAL_LOCAL_INVALIDATION_TRIGGERS = {
    trigger.name: {
        "type": "trigger",
        "name": trigger.name,
        "table_name": trigger.table,
        "sql": trigger.sqlite_master_sql,
    }
    for trigger in SNAPSHOT_INVALIDATION_TRIGGERS
}


def _replicated_schema_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Remove only the local snapshot-invalidation capability from parity.

    Those triggers are intentionally installed on the research mirror, not on
    acquisition D1. Their full DDL still participates in the signed local
    schema digest; every other table/index/trigger/FK object must match.
    """
    replicated = json.loads(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    )
    retained: list[dict[str, Any]] = []
    for row in replicated["sqlite_master"]:
        if row["type"] != "trigger" or not row["name"].startswith(
            "invalidate_snapshot_"
        ):
            retained.append(row)
            continue
        expected = _CANONICAL_LOCAL_INVALIDATION_TRIGGERS.get(row["name"])
        if expected is None or row != expected:
            raise ValueError(
                "local snapshot invalidation trigger is not canonical"
            )
    replicated["sqlite_master"] = retained
    return replicated


def _table_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    manifest = _table_schema_manifest(conn, table)
    return tuple(str(row["name"]) for row in manifest["table_xinfo"])


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
    for row in conn.execute(f"SELECT {selected} FROM main.{_quoted_identifier(table)}"):
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

    reject_temp_governed_deputies(conn, tables)
    inventory: dict[str, dict[str, Any]] = {}
    schema: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for table in tables:
        if not _table_exists(conn, table):
            raise ValueError(f"governed mirror is missing table: {table}")
        schema_manifest = _table_schema_manifest(conn, table)
        columns = tuple(
            str(column["name"]) for column in schema_manifest["table_xinfo"]
        )
        count, digest = _table_fingerprint(conn, table, columns)
        schema[table] = schema_manifest
        counts[table] = count
        inventory[table] = {
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
) -> tuple[str, str, str, dict[str, int]]:
    reject_temp_governed_deputies(source, tables)
    reject_temp_governed_deputies(local, tables)
    for table in tables:
        if not _table_exists(source, table):
            raise ValueError(f"D1 export is missing governed table: {table}")
        if not _table_exists(local, table):
            raise ValueError(f"local mirror is missing governed table: {table}")
        source_schema = _table_schema_manifest(source, table)
        local_schema = _table_schema_manifest(local, table)
        if source_schema != _replicated_schema_manifest(local_schema):
            raise ValueError(
                f"authenticated D1 source/local schema mismatch for {table}"
            )
        source_columns = tuple(
            str(column["name"]) for column in source_schema["table_xinfo"]
        )
        local_columns = tuple(
            str(column["name"]) for column in local_schema["table_xinfo"]
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
        or source_counts != local_counts
    ):
        raise ValueError("authenticated D1 governed inventory reconciliation failed")
    return source_identity, source_schema, local_schema, source_counts


def _change_seq(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "ingestion_change_log"):
        raise ValueError("D1 export is missing ingestion_change_log")
    row = conn.execute(
        "SELECT COALESCE(MAX(change_seq), 0) FROM main.ingestion_change_log"
    ).fetchone()
    value = row[0] if row is not None else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("D1 export change cursor is invalid")
    return value


def _local_change_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT last_applied_change_seq FROM main.sync_change_state "
        "WHERE feed='jquants_records'"
    ).fetchone()
    value = row[0] if row is not None else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("local D1 applied cursor is invalid")
    return value


def _build_authenticated_export_authority():
    """Close capability minting over process-private membership registries."""
    acquired_exports = WeakSet()
    authenticated_exports = WeakSet()

    class _AuthenticatedWranglerExport:
        """Opaque proof minted only after exact local reconciliation."""

        __slots__ = ("_facts_json", "_consumed", "__weakref__")

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError(
                "authenticated Wrangler export has no public constructor"
            )

        def _consume_for_signing(self) -> dict[str, Any]:
            return _consume_authenticated_export(self)

    def _consume_authenticated_export(capability: object) -> dict[str, Any]:
        if type(capability) is not _AuthenticatedWranglerExport:
            raise RuntimeError(
                "authenticated Wrangler export was already consumed"
            )
        if capability._consumed or capability not in authenticated_exports:
            raise RuntimeError(
                "authenticated Wrangler export was already consumed"
            )
        capability._consumed = True
        authenticated_exports.discard(capability)
        return json.loads(capability._facts_json)

    class _PinnedWranglerExport:
        """Actual pinned remote export pending exact reconciliation."""

        __slots__ = (
            "export_digest",
            "artifact_size",
            "artifact_format",
            "_sqlite_path",
            "_materialized_identity",
            "_source_conn",
            "_exported_at",
            "_authenticated",
            "__weakref__",
        )

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("pinned Wrangler export has no public constructor")

        def _require_acquired(self) -> None:
            if self not in acquired_exports:
                raise RuntimeError(
                    "pinned Wrangler export was not minted by governed acquisition"
                )
            _require_file_identity(
                self._sqlite_path, self._materialized_identity
            )

        def open_source(self) -> sqlite3.Connection:
            self._require_acquired()
            if self._source_conn is not None:
                raise RuntimeError("pinned Wrangler export source is single-use")
            source = open_export_sqlite(self._sqlite_path)
            try:
                _require_file_identity(
                    self._sqlite_path, self._materialized_identity
                )
            except Exception:
                source.close()
                raise
            self._source_conn = source
            return source

        def authenticate_local(
            self,
            local: sqlite3.Connection,
            tables: tuple[str, ...],
            *,
            sync_kind: str,
            prior_audit_digest: str | None,
        ) -> _AuthenticatedWranglerExport:
            self._require_acquired()
            if self._authenticated:
                raise RuntimeError(
                    "pinned Wrangler export authentication is single-use"
                )
            source = self._source_conn
            if source is None:
                raise RuntimeError(
                    "pinned Wrangler export source must be opened exactly once"
                )
            source_cursor = _change_seq(source)
            local_cursor = _local_change_seq(local)
            if source_cursor != local_cursor:
                raise ValueError(
                    "authenticated D1 source/local applied cursor mismatch"
                )
            (
                content_digest,
                source_schema_digest,
                local_schema_digest,
                counts,
            ) = _exact_source_local_reconciliation(source, local, tables)
            _require_file_identity(
                self._sqlite_path, self._materialized_identity
            )
            facts = {
                "sync_kind": sync_kind,
                "export_digest": self.export_digest,
                "artifact_format": self.artifact_format,
                "source_change_seq": source_cursor,
                "applied_change_seq": local_cursor,
                "source_content_digest": content_digest,
                "local_content_digest": content_digest,
                "source_schema_digest": source_schema_digest,
                "schema_digest": local_schema_digest,
                "table_counts": counts,
                "prior_audit_digest": prior_audit_digest,
                "exported_at": self._exported_at,
            }
            authenticated = object.__new__(_AuthenticatedWranglerExport)
            authenticated._facts_json = json.dumps(
                facts, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            authenticated._consumed = False
            authenticated_exports.add(authenticated)
            self._authenticated = True
            acquired_exports.discard(self)
            return authenticated

    def acquire_pinned_wrangler_export(directory: Path) -> _PinnedWranglerExport:
        """Acquire, materialize, and bind one governed remote D1 export."""
        from ops.d1_sync_signing import (
            _preflight_d1_sync_signing_authority,
            _utc_now,
        )

        _preflight_d1_sync_signing_authority()
        raw_artifact = directory / "remote-export.sql"
        run_wrangler_d1_export(output_path=raw_artifact)
        materialized = directory / "remote-export.sqlite"
        (
            export_digest,
            artifact_size,
            artifact_format,
            materialized_identity,
        ) = _materialize_d1_export_with_identity(raw_artifact, materialized)
        acquired = object.__new__(_PinnedWranglerExport)
        acquired.export_digest = export_digest
        acquired.artifact_size = artifact_size
        acquired.artifact_format = artifact_format
        acquired._sqlite_path = materialized
        acquired._materialized_identity = materialized_identity
        acquired._source_conn = None
        acquired._exported_at = _utc_now().isoformat()
        acquired._authenticated = False
        acquired_exports.add(acquired)
        return acquired

    from ops.d1_sync_signing import _bind_authenticated_export_authority

    _bind_authenticated_export_authority(
        _AuthenticatedWranglerExport, _consume_authenticated_export
    )
    return (
        _AuthenticatedWranglerExport,
        _PinnedWranglerExport,
        acquire_pinned_wrangler_export,
    )


(
    _AuthenticatedWranglerExport,
    _PinnedWranglerExport,
    acquire_pinned_wrangler_export,
) = _build_authenticated_export_authority()
del _build_authenticated_export_authority
