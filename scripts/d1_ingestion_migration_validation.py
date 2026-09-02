#!/usr/bin/env python3
"""Fail-closed validation for the governed quant-ingest D1 migration chain.

The validator never mutates a remote database.  A preflight export is restored
locally, its migration history must be an exact canonical prefix, and the
remaining migrations are replayed against an in-memory copy.  This makes an
interrupted, unrecorded 0012 prefix resumable only when rerunning it produces
the exact final schema without losing any legacy JSDA job, event, discovery,
or foreign-key relation.  A recorded-but-partial migration is rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, Mapping, Sequence

from scripts._private_d1_export import (
    _table_schema_manifest,
    reject_temp_governed_deputies,
)
from scripts.cloudflare_d1_migration_manifest import MANIFEST, build_manifest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = (
    ROOT / "platform" / "workers" / "ingestion-premium" / "migrations"
)
TARGET_NAME = "quant-ingest"
MIGRATIONS: tuple[Path, ...] = tuple(sorted(MIGRATION_DIR.glob("*.sql")))
MIGRATION_NAMES: tuple[str, ...] = tuple(path.name for path in MIGRATIONS)
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class IngestionMigrationError(ValueError):
    """The observed export cannot safely enter or prove the canonical chain."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_target() -> tuple[dict[str, Any], str]:
    generated = build_manifest()
    rendered = json.dumps(generated, indent=2, sort_keys=False) + "\n"
    try:
        frozen = MANIFEST.read_text(encoding="utf-8")
    except OSError as exc:
        raise IngestionMigrationError("canonical D1 manifest is missing") from exc
    if frozen != rendered:
        raise IngestionMigrationError("canonical D1 manifest is stale")
    target = generated.get("targets", {}).get(TARGET_NAME)
    if not isinstance(target, dict):
        raise IngestionMigrationError("canonical quant-ingest target is missing")
    rows = target.get("migrations")
    if not isinstance(rows, list) or tuple(
        Path(str(row.get("path", ""))).name for row in rows
    ) != MIGRATION_NAMES:
        raise IngestionMigrationError("canonical quant-ingest sequence drift")
    for path, row in zip(MIGRATIONS, rows, strict=True):
        checksum = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if row.get("checksum") != checksum:
            raise IngestionMigrationError(f"canonical checksum drift: {path.name}")
    return target, "sha256:" + hashlib.sha256(frozen.encode("utf-8")).hexdigest()


def canonical_binding(environment: str) -> dict[str, str]:
    target, _manifest_digest = _canonical_target()
    if environment not in {"staging", "production"}:
        raise IngestionMigrationError("environment must be staging or production")
    try:
        raw = target["environments"][environment]
    except (KeyError, TypeError) as exc:
        raise IngestionMigrationError("canonical environment binding is missing") from exc
    return {
        "environment": environment,
        "config": str(raw["config"]),
        "binding": str(raw["binding"]),
        "database_name": str(raw["database_name"]),
        "database_id": str(raw["database_id"]),
        "migrations_table": str(raw["migrations_table"]),
    }


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _reject_attached(conn: sqlite3.Connection) -> None:
    rows = tuple(conn.execute("PRAGMA database_list"))
    names = tuple(str(row[1]) for row in rows if len(row) >= 2)
    if not rows or names[0] != "main" or any(
        name not in {"main", "temp"} for name in names
    ):
        raise IngestionMigrationError("attached databases are forbidden")


def _history_names(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    row = conn.execute(
        "SELECT type FROM main.sqlite_master WHERE name=?", (table,)
    ).fetchone()
    if row != ("table",):
        raise IngestionMigrationError("canonical D1 migration history is missing")
    columns = tuple(
        str(item[1]) for item in conn.execute(f"PRAGMA main.table_info({_quote(table)})")
    )
    if columns != ("id", "name", "applied_at"):
        raise IngestionMigrationError("canonical D1 migration history is malformed")
    try:
        rows = tuple(
            conn.execute(f"SELECT name FROM main.{_quote(table)} ORDER BY id")
        )
    except sqlite3.DatabaseError as exc:
        raise IngestionMigrationError("canonical D1 migration history is unreadable") from exc
    names = tuple(str(item[0]) for item in rows)
    if names != MIGRATION_NAMES[: len(names)]:
        raise IngestionMigrationError("D1 migration history is not an exact prefix")
    return names


def _integrity_and_fk(conn: sqlite3.Connection) -> None:
    integrity = tuple(str(row[0]) for row in conn.execute("PRAGMA integrity_check"))
    if integrity != ("ok",):
        raise IngestionMigrationError("D1 export failed integrity_check")
    foreign_keys = tuple(tuple(row) for row in conn.execute("PRAGMA foreign_key_check"))
    if foreign_keys:
        raise IngestionMigrationError("D1 export has foreign-key violations")


def _table_names(conn: sqlite3.Connection, history_table: str) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM main.sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>? "
            "ORDER BY name",
            (history_table,),
        )
    )


def _schema_inventory(
    conn: sqlite3.Connection,
    *,
    history_table: str,
) -> dict[str, Any]:
    _reject_attached(conn)
    tables = _table_names(conn, history_table)
    reject_temp_governed_deputies(conn, tables)
    views = tuple(
        tuple(row)
        for row in conn.execute(
            "SELECT type,name,tbl_name,sql FROM main.sqlite_master "
            "WHERE type='view' ORDER BY name"
        )
    )
    return {
        "tables": {table: _table_schema_manifest(conn, table) for table in tables},
        "views": views,
    }


def _new_history(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(
        f"CREATE TABLE {_quote(table)} ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "name TEXT NOT NULL UNIQUE,"
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)"
    )


def _record(conn: sqlite3.Connection, table: str, name: str) -> None:
    conn.execute(f"INSERT INTO {_quote(table)} (name) VALUES (?)", (name,))


def _canonical_final(environment: str) -> tuple[dict[str, Any], str]:
    binding = canonical_binding(environment)
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        _new_history(conn, binding["migrations_table"])
        for path in MIGRATIONS:
            conn.executescript(path.read_text(encoding="utf-8"))
            _record(conn, binding["migrations_table"], path.name)
        conn.commit()
        inventory = _schema_inventory(
            conn, history_table=binding["migrations_table"]
        )
        return inventory, _digest(inventory)
    finally:
        conn.close()


_PRESERVED_JOB_COLUMNS: tuple[str, ...] = (
    "work_key",
    "run_key",
    "dataset",
    "job_type",
    "target_url",
    "segment_id",
    "parent_work_key",
    "contract_digest",
    "requested_by",
    "requested_at",
    "first_seen_at",
)


def _except_count(
    conn: sqlite3.Connection,
    left: str,
    right: str,
    left_columns: Sequence[str],
    right_columns: Sequence[str],
) -> int:
    left_projection = ",".join(_quote(column) for column in left_columns)
    right_projection = ",".join(_quote(column) for column in right_columns)
    sql = (
        "SELECT COUNT(*) FROM (SELECT "
        + left_projection
        + f" FROM {_quote(left)} EXCEPT SELECT "
        + right_projection
        + f" FROM {_quote(right)})"
    )
    value = conn.execute(sql).fetchone()
    return int(value[0]) if value else -1


def _preservation_evidence(
    conn: sqlite3.Connection,
    *,
    require_exact_cutover: bool,
) -> dict[str, Any]:
    pairs = (
        (
            "jobs",
            "jsda_acquisition_jobs_v2",
            "jsda_acquisition_jobs_v3",
            _PRESERVED_JOB_COLUMNS,
            _PRESERVED_JOB_COLUMNS,
        ),
        (
            "events",
            "jsda_acquisition_events_v2",
            "jsda_acquisition_events_v3",
            (
                "event_id",
                "work_key",
                "run_key",
                "dataset",
                "job_type",
                "segment_id",
                "attempt",
                "cursor",
                "result",
                "reason_code",
                "detail",
                "content_digest",
                "raw_key",
                "audit_receipt_key",
                "audit_receipt_digest",
                "occurred_at",
            ),
            (
                "legacy_event_id",
                "work_key",
                "run_key",
                "dataset",
                "job_type",
                "segment_id",
                "attempt",
                "cursor",
                "result",
                "reason_code",
                "detail",
                "content_digest",
                "raw_key",
                "audit_receipt_key",
                "audit_receipt_digest",
                "occurred_at",
            ),
        ),
        (
            "discoveries",
            "jsda_acquisition_discoveries_v2",
            "jsda_acquisition_discoveries_v3",
            ("parent_work_key", "child_work_key", "run_key", "discovered_at"),
            ("parent_work_key", "child_work_key", "run_key", "discovered_at"),
        ),
    )
    result: dict[str, Any] = {}
    for label, legacy, current, legacy_columns, current_columns in pairs:
        legacy_count = int(conn.execute(f"SELECT COUNT(*) FROM {_quote(legacy)}").fetchone()[0])
        current_count = int(conn.execute(f"SELECT COUNT(*) FROM {_quote(current)}").fetchone()[0])
        missing = _except_count(
            conn, legacy, current, legacy_columns, current_columns
        )
        unexpected = _except_count(
            conn, current, legacy, current_columns, legacy_columns
        )
        if missing or current_count < legacy_count:
            raise IngestionMigrationError(f"0012 {label} lost legacy rows")
        if require_exact_cutover and (unexpected or legacy_count != current_count):
            raise IngestionMigrationError(
                f"0012 {label} cutover copy is incomplete or divergent"
            )
        result[label] = {
            "legacy_rows": legacy_count,
            "current_rows": current_count,
            "missing_rows": missing,
            "unexpected_rows": unexpected,
            "validation_mode": (
                "EXACT_CUTOVER_COPY"
                if require_exact_cutover
                else "LEGACY_SUBSET_OF_ACTIVE"
            ),
        }
    return result


def validate_postflight_connection(
    conn: sqlite3.Connection,
    *,
    environment: str,
    require_exact_cutover: bool = False,
) -> dict[str, Any]:
    binding = canonical_binding(environment)
    _integrity_and_fk(conn)
    history = _history_names(conn, binding["migrations_table"])
    if history != MIGRATION_NAMES:
        raise IngestionMigrationError("postflight has unapplied canonical migrations")
    observed = _schema_inventory(conn, history_table=binding["migrations_table"])
    expected, expected_digest = _canonical_final(environment)
    if observed != expected:
        raise IngestionMigrationError("postflight schema is not the exact canonical schema")
    preservation = _preservation_evidence(
        conn, require_exact_cutover=require_exact_cutover
    )
    _target, manifest_digest = _canonical_target()
    return {
        "status": "EXACT_POSTFLIGHT",
        "environment": environment,
        "database": binding,
        "canonical_manifest_digest": manifest_digest,
        "applied_migrations": list(history),
        "schema_digest": _digest(observed),
        "expected_schema_digest": expected_digest,
        "foreign_key_check": "PASS",
        "preservation": preservation,
    }



INVARIANT_MANIFEST = ROOT / "specs" / "cloudflare" / "quant_ingest_schema_invariants.json"


def _independent_invariants() -> dict[str, Any]:
    try:
        document = json.loads(INVARIANT_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IngestionMigrationError("canonical schema invariant manifest is missing") from exc
    if (
        document.get("schema_version") != "quant-ingest-schema-invariants/v1"
        or document.get("trigger_count") != 45
        or document.get("index_count") != 47
        or document.get("receipt_authority_foreign_key_count") != 3
        or type(document.get("triggers")) is not list
        or type(document.get("indexes")) is not list
    ):
        raise IngestionMigrationError("canonical schema invariant manifest is invalid")
    return document


def _sqlite_master_names(conn: sqlite3.Connection, kind: str) -> set[str]:
    sql = "SELECT name FROM main.sqlite_master WHERE type=?"
    if kind == "index":
        sql += " AND name NOT LIKE 'sqlite_%'"
    return {str(row[0]) for row in conn.execute(sql, (kind,))}


def reject_unknown_pre_0020_objects(conn: sqlite3.Connection) -> None:
    """Reject sqlite_master objects that 0020 rebuild would silently drop."""
    expected = _independent_invariants()
    expected_triggers = {row["name"] for row in expected["triggers"]}
    expected_indexes = {row["name"] for row in expected["indexes"]}
    observed_triggers = _sqlite_master_names(conn, "trigger")
    observed_indexes = _sqlite_master_names(conn, "index")
    bootstrap_objects = {
        name
        for name in observed_triggers | observed_indexes
        if name.startswith("quant_ingest_mutation_")
    }
    unknown_triggers = sorted(observed_triggers - expected_triggers - bootstrap_objects)
    unknown_indexes = sorted(observed_indexes - expected_indexes - bootstrap_objects)
    if unknown_triggers or unknown_indexes:
        raise IngestionMigrationError(
            "preflight has unknown triggers/indexes that 0020 would drop: "
            + ", ".join(unknown_triggers + unknown_indexes)
        )
    if len(expected_triggers) != 45 or len(expected_indexes) != 47:
        raise IngestionMigrationError("canonical 45 triggers/47 indexes drifted")
    expected_fks = {
        (str(row["table"]), str(row["from"]), str(row["ref_table"]), str(row["to"]))
        for row in expected.get("receipt_authority_foreign_keys") or []
    }
    if len(expected_fks) != 3:
        raise IngestionMigrationError("canonical 3 receipt-authority foreign keys drifted")
    tables = {name for name, *_ in expected_fks}
    observed_fks: set[tuple[str, str, str, str]] = set()
    present = _sqlite_master_names(conn, "table")
    for table in tables:
        if table not in present:
            continue
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
            # id, seq, table, from, to, ...
            observed_fks.add((table, str(fk[3]), str(fk[2]), str(fk[4])))
    if present.issuperset(tables) and observed_fks != expected_fks:
        raise IngestionMigrationError(
            "canonical receipt-authority foreign keys mismatch"
        )
    extra_fk_tables = observed_fks - expected_fks
    if extra_fk_tables and present.issuperset(tables):
        raise IngestionMigrationError(
            "canonical receipt-authority foreign keys mismatch"
        )

def validate_preflight_connection(
    conn: sqlite3.Connection,
    *,
    environment: str,
) -> dict[str, Any]:
    binding = canonical_binding(environment)
    _integrity_and_fk(conn)
    history = _history_names(conn, binding["migrations_table"])
    _target, manifest_digest = _canonical_target()
    if len(history) == len(MIGRATIONS):
        postflight = validate_postflight_connection(conn, environment=environment)
        return {
            "status": "ALREADY_EXACT",
            "environment": environment,
            "database": binding,
            "canonical_manifest_digest": manifest_digest,
            "applied_migrations": list(history),
            "pending_migrations": [],
            "simulated_postflight": postflight,
        }

    canonical_inventory, _canonical_digest = _canonical_final(environment)
    canonical_tables = set(canonical_inventory["tables"])
    observed_tables = set(_table_names(conn, binding["migrations_table"]))
    extra_tables = sorted(observed_tables - canonical_tables)
    if extra_tables:
        raise IngestionMigrationError(
            "preflight has non-canonical tables: " + ", ".join(extra_tables)
        )
    pending = list(MIGRATION_NAMES[len(history):])
    if any(name.startswith("0020_") for name in pending):
        reject_unknown_pre_0020_objects(conn)

    simulated = sqlite3.connect(":memory:")
    try:
        conn.backup(simulated)
        simulated.execute("PRAGMA foreign_keys=ON")
        for path in MIGRATIONS[len(history) :]:
            try:
                simulated.executescript(path.read_text(encoding="utf-8"))
                _record(simulated, binding["migrations_table"], path.name)
                simulated.commit()
            except sqlite3.DatabaseError as exc:
                raise IngestionMigrationError(
                    f"preflight cannot safely resume {path.name}"
                ) from exc
        postflight = validate_postflight_connection(
            simulated,
            environment=environment,
            require_exact_cutover=True,
        )
    finally:
        simulated.close()

    initial_inventory = _schema_inventory(
        conn, history_table=binding["migrations_table"]
    )
    return {
        "status": "RESUMABLE_EXACT_PREFIX",
        "environment": environment,
        "database": binding,
        "canonical_manifest_digest": manifest_digest,
        "applied_migrations": list(history),
        "pending_migrations": list(MIGRATION_NAMES[len(history) :]),
        "observed_schema_digest": _digest(initial_inventory),
        "simulated_postflight": postflight,
    }


def _restore_export(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        raise IngestionMigrationError("D1 SQL export must be a non-empty regular file")
    temporary = tempfile.NamedTemporaryFile(
        prefix="quant-ingest-migration-validation-", suffix=".sqlite3", delete=False
    )
    temporary_path = Path(temporary.name)
    temporary.close()
    conn = sqlite3.connect(temporary_path)
    try:
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.commit()
    except (OSError, UnicodeError, sqlite3.DatabaseError) as exc:
        conn.close()
        temporary_path.unlink(missing_ok=True)
        raise IngestionMigrationError("D1 SQL export cannot be restored") from exc
    # The caller closes the connection; unlinking an open SQLite file is safe
    # on the supported release host and prevents plaintext persistence.
    temporary_path.unlink(missing_ok=True)
    return conn


def validate_export(
    path: Path,
    *,
    environment: str,
    phase: str,
    require_exact_cutover: bool = False,
) -> dict[str, Any]:
    conn = _restore_export(path)
    try:
        if phase == "preflight":
            if require_exact_cutover:
                raise IngestionMigrationError(
                    "exact cutover mode applies only to postflight"
                )
            return validate_preflight_connection(conn, environment=environment)
        if phase == "postflight":
            return validate_postflight_connection(
                conn,
                environment=environment,
                require_exact_cutover=require_exact_cutover,
            )
        raise IngestionMigrationError("phase must be preflight or postflight")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--phase", choices=("preflight", "postflight"), required=True)
    parser.add_argument("--export-sql", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_export(
        args.export_sql, environment=args.environment, phase=args.phase
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
