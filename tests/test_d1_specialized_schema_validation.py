"""Adversarial tests for the read-only specialized D1 schema contract."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Callable

import pytest

from scripts.d1_specialized_schema_validation import (
    EXPECTED_DDL_SHA256,
    MIGRATION_0013,
    MIGRATION_FILENAME,
    SpecializedSchemaError,
    build_local_validation_evidence,
    canonical_specialized_schema,
    canonical_specialized_schema_digest,
    specialized_schema_inventory,
    validate_applied_specialized_schema,
    validate_migration_definition,
    validate_preflight_specialized_schema,
)


def _connection_with_0013(*, record_history: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION_0013.read_text(encoding="utf-8"))
    if record_history:
        conn.executescript(
            """
            CREATE TABLE d1_migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO d1_migrations (name) VALUES (?)",
            (MIGRATION_FILENAME,),
        )
    return conn


def _table_contract(table: str) -> tuple[str, tuple[str, ...]]:
    manifest = canonical_specialized_schema()[table]
    table_sql = next(
        str(row["sql"])
        for row in manifest["sqlite_master"]
        if row["type"] == "table" and row["name"] == table
    )
    index_sql = tuple(
        str(row["sql"])
        for row in manifest["sqlite_master"]
        if row["type"] == "index" and row["sql"] is not None
    )
    return table_sql, index_sql


def _replace_listed_info_table(
    conn: sqlite3.Connection,
    mutate: Callable[[str], str],
) -> None:
    table_sql, indexes = _table_contract("jquants_listed_info")
    conn.execute("DROP TABLE jquants_listed_info")
    conn.execute(mutate(table_sql))
    for index_sql in indexes:
        conn.execute(index_sql)


def _extra_check(sql: str) -> str:
    return sql.replace(
        "PRIMARY KEY (source, code, snapshot_date)",
        "CHECK (length(code) > 0), PRIMARY KEY (source, code, snapshot_date)",
    )


def _extra_default(sql: str) -> str:
    return sql.replace(
        "company_name TEXT,",
        "company_name TEXT DEFAULT 'unknown',",
    )


def _extra_collation(sql: str) -> str:
    return sql.replace("company_name TEXT,", "company_name TEXT COLLATE NOCASE,")


def _extra_generated_column(sql: str) -> str:
    return sql.replace(
        "PRIMARY KEY (source, code, snapshot_date)",
        "derived_code TEXT GENERATED ALWAYS AS (code) VIRTUAL, "
        "PRIMARY KEY (source, code, snapshot_date)",
    )


def _extra_foreign_key(sql: str) -> str:
    return sql.replace(
        "PRIMARY KEY (source, code, snapshot_date)",
        "FOREIGN KEY (code) REFERENCES jquants_listed_info(code), "
        "PRIMARY KEY (source, code, snapshot_date)",
    )


def _strict_table(sql: str) -> str:
    return sql + " STRICT"


def _without_rowid_table(sql: str) -> str:
    return sql + " WITHOUT ROWID"


def test_0013_is_exact_blob_and_canonical_manifest_chain() -> None:
    assert hashlib.sha256(MIGRATION_0013.read_bytes()).hexdigest() == EXPECTED_DDL_SHA256
    definition = validate_migration_definition()
    migration = definition["migration"]
    assert migration == {
        "migration_id": "quant-ingest:0013_restore_specialized_jquants_schema",
        "path": (
            "platform/workers/ingestion-premium/migrations/"
            "0013_restore_specialized_jquants_schema.sql"
        ),
        "checksum": f"sha256:{EXPECTED_DDL_SHA256}",
        "order": 13,
        "depends_on": "quant-ingest:0012_jsda_observation_identity",
    }
    assert str(definition["manifest_digest"]).startswith("sha256:")


def test_0013_exact_schema_matches_0001_plus_0004_contract() -> None:
    conn = _connection_with_0013()
    try:
        assert specialized_schema_inventory(conn) == canonical_specialized_schema()
        state = validate_preflight_specialized_schema(
            conn, environment="production"
        )
        assert set(state["table_status"].values()) == {"EXACT"}
        assert state["schema_digest"] == canonical_specialized_schema_digest()
        assert state["history_observation"] == "NOT_RECORDED"
    finally:
        conn.close()


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(_extra_check, id="check"),
        pytest.param(_extra_default, id="default"),
        pytest.param(_extra_collation, id="collation"),
        pytest.param(_extra_generated_column, id="generated-hidden"),
        pytest.param(_extra_foreign_key, id="foreign-key"),
        pytest.param(_strict_table, id="strict"),
        pytest.param(_without_rowid_table, id="without-rowid"),
    ],
)
def test_table_semantic_drift_is_rejected(
    mutation: Callable[[str], str],
) -> None:
    conn = _connection_with_0013()
    try:
        _replace_listed_info_table(conn, mutation)
        with pytest.raises(SpecializedSchemaError, match="malformed"):
            validate_preflight_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


@pytest.mark.parametrize("kind", ["partial", "expression"])
def test_index_predicate_and_expression_drift_are_rejected(kind: str) -> None:
    conn = _connection_with_0013()
    try:
        conn.execute("DROP INDEX ix_master_available_at")
        suffix = (
            "(code, available_at) WHERE available_at <> ''"
            if kind == "partial"
            else "(lower(code), available_at)"
        )
        conn.execute(
            "CREATE INDEX ix_master_available_at "
            f"ON jquants_listed_info {suffix}"
        )
        with pytest.raises(SpecializedSchemaError, match="malformed"):
            validate_preflight_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_extra_trigger_is_rejected() -> None:
    conn = _connection_with_0013()
    try:
        conn.execute(
            "CREATE TRIGGER unexpected_specialized_write "
            "AFTER INSERT ON jquants_listed_info BEGIN SELECT 1; END"
        )
        with pytest.raises(SpecializedSchemaError, match="malformed"):
            validate_preflight_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_temp_shadow_cannot_hide_the_main_schema() -> None:
    conn = _connection_with_0013()
    try:
        conn.execute("CREATE TEMP TABLE jquants_listed_info (forged TEXT)")
        with pytest.raises(ValueError, match="temporary object shadows"):
            validate_preflight_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_canonical_index_name_cannot_be_owned_by_an_unrelated_table() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE unrelated (code TEXT, available_at TEXT);
            CREATE INDEX ix_master_available_at
                ON unrelated (code, available_at);
            """
        )
        with pytest.raises(SpecializedSchemaError, match="wrong owner"):
            validate_preflight_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_attached_table_index_and_history_deputies_fail_when_main_is_absent() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("ATTACH DATABASE ':memory:' AS deputy")
        conn.executescript(
            """
            CREATE TABLE deputy.jquants_listed_info (
                code TEXT,
                available_at TEXT
            );
            CREATE INDEX deputy.ix_master_available_at
                ON jquants_listed_info (code, available_at);
            CREATE TABLE deputy.d1_migrations (name TEXT NOT NULL UNIQUE);
            INSERT INTO deputy.d1_migrations (name)
                VALUES ('0013_restore_specialized_jquants_schema.sql');
            """
        )
        with pytest.raises(SpecializedSchemaError, match="attached SQLite"):
            validate_preflight_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_attached_table_index_and_history_deputies_fail_when_main_is_exact() -> None:
    conn = _connection_with_0013(record_history=True)
    try:
        conn.execute("ATTACH DATABASE ':memory:' AS deputy")
        conn.executescript(
            """
            CREATE TABLE deputy.jquants_listed_info (
                code TEXT,
                available_at TEXT
            );
            CREATE INDEX deputy.ix_master_available_at
                ON jquants_listed_info (code, available_at);
            CREATE TABLE deputy.d1_migrations (name TEXT NOT NULL UNIQUE);
            INSERT INTO deputy.d1_migrations (name)
                VALUES ('0013_restore_specialized_jquants_schema.sql');
            """
        )
        with pytest.raises(SpecializedSchemaError, match="attached SQLite"):
            validate_applied_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_applied_history_never_skips_missing_table_postflight() -> None:
    conn = _connection_with_0013(record_history=True)
    try:
        conn.execute("DROP TABLE jquants_market_calendar")
        with pytest.raises(
            SpecializedSchemaError,
            match="recorded 0013 fails mandatory exact-schema postflight",
        ):
            validate_preflight_specialized_schema(
                conn, environment="production"
            )
        with pytest.raises(
            SpecializedSchemaError,
            match="recorded 0013 fails mandatory exact-schema postflight",
        ):
            validate_applied_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_postflight_requires_history_even_when_schema_is_exact() -> None:
    conn = _connection_with_0013()
    try:
        with pytest.raises(SpecializedSchemaError, match="not recorded"):
            validate_applied_specialized_schema(
                conn, environment="production"
            )
    finally:
        conn.close()


def test_staging_history_cannot_be_substituted_with_production_history() -> None:
    conn = _connection_with_0013(record_history=True)
    try:
        with pytest.raises(SpecializedSchemaError, match="not recorded"):
            validate_applied_specialized_schema(
                conn, environment="staging"
            )
        conn.executescript(
            """
            CREATE TABLE d1_migrations_ingestion (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT INTO d1_migrations_ingestion (name) VALUES (?)",
            (MIGRATION_FILENAME,),
        )
        state = validate_applied_specialized_schema(
            conn, environment="staging"
        )
        assert state["history_observation"] == "RECORDED"
    finally:
        conn.close()


def test_local_evidence_binds_identity_chain_and_pre_post_digests() -> None:
    preflight = sqlite3.connect(":memory:")
    postflight = _connection_with_0013(record_history=True)
    try:
        evidence = build_local_validation_evidence(
            preflight,
            postflight,
            environment="production",
        )
        assert evidence["schema_version"] == (
            "d1-specialized-schema-local-validation/v1"
        )
        assert evidence["evidence_scope"] == "LOCAL_SQLITE_VALIDATION_ONLY"
        assert evidence["remote_applied_state"] == "UNVERIFIED"
        assert evidence["target"]["environment"] == "production"
        assert evidence["target"]["expected_database_name"] == "quant-ingest"
        assert evidence["target"]["expected_database_id"] == (
            "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
        )
        assert evidence["target"]["identity_observation"] == (
            "CANONICAL_EXPECTATION_NOT_LIVE_VERIFIED"
        )
        assert evidence["migration"]["order"] == 13
        assert evidence["migration"]["depends_on"].endswith(
            "0012_jsda_observation_identity"
        )
        assert evidence["preflight"]["schema_digest"] != (
            evidence["postflight"]["schema_digest"]
        )
        assert evidence["postflight"]["schema_digest"] == (
            evidence["expected_post_schema_digest"]
        )
        assert set(evidence["preflight"]["table_status"].values()) == {"ABSENT"}
        assert set(evidence["postflight"]["table_status"].values()) == {"EXACT"}
        json.dumps(evidence, allow_nan=False)
    finally:
        preflight.close()
        postflight.close()


def test_unsupported_environment_cannot_select_an_unbound_identity() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(SpecializedSchemaError, match="unsupported D1 environment"):
            validate_preflight_specialized_schema(conn, environment="preview")
    finally:
        conn.close()
