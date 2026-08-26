"""Read-only exact-schema validation for the specialized D1 repair.

This module defines the local validation contract for migration 0013.  It
never opens Wrangler, applies a migration, or treats a migration-history row
as proof of postflight success.  Callers supply already-open SQLite
connections representing the observed preflight and postflight states.

The structural inventory deliberately reuses the D1 sync boundary's exact
SQLite machinery.  Consequently canonical ``sqlite_master`` SQL,
``table_xinfo``, ``index_xinfo`` (including expression/partial indexes),
foreign keys, triggers, and table options all participate in the digest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from scripts._private_d1_export import (
    _main_schema_objects_for_table,
    _quoted_identifier,
    _sqlite_identifier_key,
    _table_schema_manifest,
    reject_temp_governed_deputies,
)
from scripts.cloudflare_d1_migration_manifest import (
    MANIFEST,
    build_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    ROOT / "platform" / "workers" / "ingestion-premium" / "migrations"
)
MIGRATION_0013 = MIGRATIONS / "0013_restore_specialized_jquants_schema.sql"
MIGRATION_FILENAME = MIGRATION_0013.name
MIGRATION_ID = "quant-ingest:0013_restore_specialized_jquants_schema"
MIGRATION_PATH = str(MIGRATION_0013.relative_to(ROOT))
EXPECTED_DEPENDENCY = "quant-ingest:0012_jsda_observation_identity"
EXPECTED_DDL_SHA256 = (
    "8ee5c5954ee309d89dc781aac1ce75b4a6170a0bdf828e262e8a792a536163be"
)
TARGET_NAME = "quant-ingest"

CANONICAL_PREFIX: tuple[Path, ...] = tuple(
    MIGRATIONS / filename
    for filename in (
        "0001_init.sql",
        "0002_watermarks.sql",
        "0003_change_feed.sql",
        "0004_revision_identity_v2.sql",
    )
)

SPECIALIZED_TABLES: tuple[str, ...] = (
    "jquants_listed_info",
    "jquants_daily_bars",
    "jquants_market_calendar",
    "jquants_listed_info_revisions",
    "jquants_daily_bars_revisions",
    "jquants_market_calendar_revisions",
)

SPECIALIZED_INDEX_OWNERS: Mapping[str, str] = {
    "ix_master_available_at": "jquants_listed_info",
    "ix_bars_available_at": "jquants_daily_bars",
    "ix_calendar_available_at": "jquants_market_calendar",
    "ux_listed_info_revisions_version": "jquants_listed_info_revisions",
    "ux_daily_bars_revisions_version": "jquants_daily_bars_revisions",
    "ux_market_calendar_revisions_version": "jquants_market_calendar_revisions",
}


class SpecializedSchemaError(ValueError):
    """The specialized schema or its canonical migration binding is invalid."""


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


def _manifest_for_table(
    conn: sqlite3.Connection,
    table: str,
) -> dict[str, Any] | None:
    objects = _main_schema_objects_for_table(conn, table)
    if not objects:
        return None
    key = _sqlite_identifier_key(table)
    table_objects = [
        row
        for row in objects
        if row[0] == "table" and _sqlite_identifier_key(row[1]) == key
    ]
    if len(table_objects) != 1:
        raise SpecializedSchemaError(
            f"{table}: canonical table identity is absent or ambiguous"
        )
    try:
        return _table_schema_manifest(conn, table)
    except (sqlite3.DatabaseError, TypeError, ValueError) as exc:
        raise SpecializedSchemaError(
            f"{table}: cannot measure exact SQLite schema"
        ) from exc


def _reject_misbound_object_identities(conn: sqlite3.Connection) -> None:
    expected = {
        _sqlite_identifier_key(table): ("table", table)
        for table in SPECIALIZED_TABLES
    }
    expected.update(
        {
            _sqlite_identifier_key(index): ("index", owner)
            for index, owner in SPECIALIZED_INDEX_OWNERS.items()
        }
    )
    for object_type, name, table_name in conn.execute(
        "SELECT type,name,tbl_name FROM main.sqlite_master"
    ):
        if not all(type(value) is str for value in (object_type, name, table_name)):
            raise SpecializedSchemaError("SQLite schema identity is not canonical")
        contract = expected.get(_sqlite_identifier_key(name))
        if contract is None:
            continue
        expected_type, expected_owner = contract
        if object_type != expected_type or _sqlite_identifier_key(
            table_name
        ) != _sqlite_identifier_key(expected_owner):
            raise SpecializedSchemaError(
                f"{name}: canonical schema object identity is bound to the wrong owner"
            )


def _reject_attached_databases(conn: sqlite3.Connection) -> None:
    rows = [tuple(row) for row in conn.execute("PRAGMA database_list")]
    if not rows or any(
        len(row) < 3
        or type(row[0]) is not int
        or type(row[1]) is not str
        or type(row[2]) is not str
        for row in rows
    ):
        raise SpecializedSchemaError("SQLite database inventory is not canonical")
    names = tuple(row[1] for row in rows)
    if (
        rows[0][0] != 0
        or names[0] != "main"
        or names.count("main") != 1
        or names.count("temp") > 1
        or any(name not in {"main", "temp"} for name in names)
    ):
        raise SpecializedSchemaError(
            "attached SQLite databases are forbidden during exact schema validation"
        )


def specialized_schema_inventory(
    conn: sqlite3.Connection,
) -> dict[str, dict[str, Any] | None]:
    """Measure every governed table without consulting migration history."""
    _reject_attached_databases(conn)
    reject_temp_governed_deputies(conn, SPECIALIZED_TABLES)
    _reject_misbound_object_identities(conn)
    return {table: _manifest_for_table(conn, table) for table in SPECIALIZED_TABLES}


def _canonical_specialized_schema_json() -> str:
    conn = sqlite3.connect(":memory:")
    try:
        for migration in CANONICAL_PREFIX:
            conn.executescript(migration.read_text(encoding="utf-8"))
        return _canonical_json(specialized_schema_inventory(conn)).decode("utf-8")
    finally:
        conn.close()


def canonical_specialized_schema() -> dict[str, dict[str, Any]]:
    """Return a fresh copy of the exact 0001+0004 structural contract."""
    document = json.loads(_canonical_specialized_schema_json())
    if not isinstance(document, dict) or any(
        not isinstance(document.get(table), dict) for table in SPECIALIZED_TABLES
    ):
        raise SpecializedSchemaError("canonical specialized schema is incomplete")
    return document


def canonical_specialized_schema_digest() -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_specialized_schema_json().encode("utf-8")
    ).hexdigest()


def classify_specialized_schema(conn: sqlite3.Connection) -> dict[str, str]:
    expected = canonical_specialized_schema()
    observed = specialized_schema_inventory(conn)
    return {
        table: (
            "ABSENT"
            if observed[table] is None
            else "EXACT"
            if observed[table] == expected[table]
            else "MALFORMED"
        )
        for table in SPECIALIZED_TABLES
    }


def _canonical_manifest_binding() -> tuple[dict[str, Any], str]:
    generated = build_manifest()
    rendered = json.dumps(generated, indent=2, sort_keys=False) + "\n"
    try:
        frozen = MANIFEST.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecializedSchemaError("canonical D1 migration manifest is missing") from exc
    if frozen != rendered:
        raise SpecializedSchemaError("canonical D1 migration manifest is stale")

    target = generated["targets"].get(TARGET_NAME)
    if not isinstance(target, dict):
        raise SpecializedSchemaError("quant-ingest migration target is missing")
    migrations = target.get("migrations")
    if not isinstance(migrations, list):
        raise SpecializedSchemaError("quant-ingest migration chain is invalid")
    matches = [row for row in migrations if row.get("migration_id") == MIGRATION_ID]
    if len(matches) != 1:
        raise SpecializedSchemaError("0013 migration identity is not unique")
    migration = matches[0]
    expected = {
        "migration_id": MIGRATION_ID,
        "path": MIGRATION_PATH,
        "checksum": f"sha256:{EXPECTED_DDL_SHA256}",
        "order": 13,
        "depends_on": EXPECTED_DEPENDENCY,
    }
    if migration != expected:
        raise SpecializedSchemaError("0013 migration chain or checksum drift")
    manifest_digest = "sha256:" + hashlib.sha256(frozen.encode("utf-8")).hexdigest()
    return generated, manifest_digest


def _environment_binding(environment: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    manifest, manifest_digest = _canonical_manifest_binding()
    target = manifest["targets"][TARGET_NAME]
    environments = target["environments"]
    if environment not in environments:
        raise SpecializedSchemaError(f"unsupported D1 environment: {environment}")
    binding = environments[environment]
    if binding.get("applied_state") != "UNVERIFIED":
        raise SpecializedSchemaError("source manifest fabricated remote applied state")
    return target, binding, manifest_digest


def _history_observation(
    conn: sqlite3.Connection,
    migrations_table: str,
) -> str:
    row = conn.execute(
        "SELECT name FROM main.sqlite_master "
        "WHERE type='table' AND name=?",
        (migrations_table,),
    ).fetchone()
    if row is None:
        return "NOT_RECORDED"
    identifier = _quoted_identifier(migrations_table)
    try:
        count = conn.execute(
            f"SELECT COUNT(*) FROM main.{identifier} WHERE name=?",
            (MIGRATION_FILENAME,),
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise SpecializedSchemaError("D1 migration history is not queryable") from exc
    if count is None or type(count[0]) is not int or count[0] not in {0, 1}:
        raise SpecializedSchemaError("D1 migration history is not canonical")
    return "RECORDED" if count[0] == 1 else "NOT_RECORDED"


def _observed_state(
    conn: sqlite3.Connection,
    *,
    environment: str,
) -> dict[str, Any]:
    _target, binding, _manifest_digest = _environment_binding(environment)
    inventory = specialized_schema_inventory(conn)
    expected = canonical_specialized_schema()
    statuses = {
        table: (
            "ABSENT"
            if inventory[table] is None
            else "EXACT"
            if inventory[table] == expected[table]
            else "MALFORMED"
        )
        for table in SPECIALIZED_TABLES
    }
    return {
        "history_observation": _history_observation(
            conn, str(binding["migrations_table"])
        ),
        "schema_digest": _digest(inventory),
        "table_status": statuses,
    }


def validate_preflight_specialized_schema(
    conn: sqlite3.Connection,
    *,
    environment: str,
) -> dict[str, Any]:
    """Allow only absent/exact objects and never trust history over structure."""
    state = _observed_state(conn, environment=environment)
    malformed = [
        table
        for table, status in state["table_status"].items()
        if status == "MALFORMED"
    ]
    if malformed:
        raise SpecializedSchemaError(
            "malformed specialized schema objects: " + ", ".join(malformed)
        )
    if state["history_observation"] == "RECORDED" and any(
        status != "EXACT" for status in state["table_status"].values()
    ):
        raise SpecializedSchemaError(
            "recorded 0013 fails mandatory exact-schema postflight"
        )
    return state


def validate_applied_specialized_schema(
    conn: sqlite3.Connection,
    *,
    environment: str,
) -> dict[str, Any]:
    """Require both one history row and an independently exact postflight."""
    state = _observed_state(conn, environment=environment)
    if state["history_observation"] != "RECORDED":
        raise SpecializedSchemaError("0013 is not recorded in D1 migration history")
    if any(status != "EXACT" for status in state["table_status"].values()):
        raise SpecializedSchemaError(
            "recorded 0013 fails mandatory exact-schema postflight"
        )
    if state["schema_digest"] != canonical_specialized_schema_digest():
        raise SpecializedSchemaError("0013 postflight schema digest drift")
    return state


def build_local_validation_evidence(
    preflight: sqlite3.Connection,
    postflight: sqlite3.Connection,
    *,
    environment: str,
) -> dict[str, Any]:
    """Build JSON-safe local evidence without claiming a remote D1 observation."""
    target, binding, manifest_digest = _environment_binding(environment)
    before = validate_preflight_specialized_schema(
        preflight, environment=environment
    )
    after = validate_applied_specialized_schema(
        postflight, environment=environment
    )
    migration = next(
        row for row in target["migrations"] if row["migration_id"] == MIGRATION_ID
    )
    return {
        "schema_version": "d1-specialized-schema-local-validation/v1",
        "evidence_scope": "LOCAL_SQLITE_VALIDATION_ONLY",
        "remote_applied_state": "UNVERIFIED",
        "canonical_migration_manifest_digest": manifest_digest,
        "target": {
            "target_name": TARGET_NAME,
            "target_role": target["target_role"],
            "owner": target["owner"],
            "environment": environment,
            "config": binding["config"],
            "binding": binding["binding"],
            "expected_database_name": binding["database_name"],
            "expected_database_id": binding["database_id"],
            "migrations_table": binding["migrations_table"],
            "identity_observation": "CANONICAL_EXPECTATION_NOT_LIVE_VERIFIED",
        },
        "migration": dict(migration),
        "expected_post_schema_digest": canonical_specialized_schema_digest(),
        "preflight": before,
        "postflight": after,
    }


def validate_migration_definition() -> Mapping[str, Any]:
    """Return the frozen 0013 manifest row after all local bindings validate."""
    target, _binding, manifest_digest = _environment_binding("production")
    migration = next(
        row for row in target["migrations"] if row["migration_id"] == MIGRATION_ID
    )
    return {"manifest_digest": manifest_digest, "migration": dict(migration)}
