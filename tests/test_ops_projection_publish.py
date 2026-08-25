"""Behavioral tests for immutable Ops Projection publication."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from data_contracts.coverage import all_coverage_contracts, coverage_policy_binding
from ops import projection_signing
from ops.projection_meta import build_projection_metadata
from ops.projection_content import (
    PROJECTED_CONTENT_TABLES,
    build_projection_content_manifest,
)
from ops.projection_signing import (
    OpsProjectionSignatureError,
    PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST,
    PINNED_OPS_PROJECTION_REGISTRY_GENERATION,
    open_ops_projection_signing_service,
    sha256_digest,
    verify_pinned_ops_projection,
)
from scripts import publish_ops_projection as publisher
from scripts import sync_d1_to_sqlite as sync_script
from scripts.export_ops_projection import (
    _render_projection_bundle_for_test,
    _render_trusted_projection_bundle,
    render_projection_bundle,
)
from storage.sqlite_store import SqliteStore
from tests.ops_projection_signing_support import (
    TestOpsProjectionSigningKey,
    make_test_ops_projection_verifier,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "platform/workers/quant-ops-mcp/migrations/projection/0001_ops_projection.sql"


def test_projection_content_digest_matches_worker_storage_representation() -> None:
    rows = {table: [] for table in PROJECTED_CONTENT_TABLES}
    rows["endpoint_inventory"] = [
        {
            "projection_generation_id": "g",
            "dataset_id": "日本株",
            "research_eligible": True,
            "enabled": False,
            "weight": 1.0,
            "note": "東京",
        }
    ]
    manifest, _digest = build_projection_content_manifest(rows)
    assert manifest["endpoint_inventory"]["content_digest"] == (
        "sha256:76195ac60aedf9a62db147dd1c8914282617553423c5d0fb918627447aac7d61"
    )
    rows["endpoint_inventory"][0]["weight"] = 1.25
    with pytest.raises(ValueError, match="non-integral REAL"):
        build_projection_content_manifest(rows)


def _source(path: Path) -> None:
    store = SqliteStore(path)
    coverage_rows = []
    for contract in all_coverage_contracts():
        observed = contract.dataset_id == "equities_bars_daily"
        coverage_rows.append(
            (
                contract.dataset_id,
                "PARTIAL",
                coverage_policy_binding(contract.dataset_id)["policy_version"],
                contract.collection_scope,
                contract.history_target_start,
                contract.history_target_end_rule,
                contract.coverage_mode,
                contract.expected_frequency,
                contract.universe_rule,
                int(contract.raw_retention_required),
                int(contract.structured_reconciliation_required),
                contract.governance_tier,
                "2008-05-07" if observed else None,
                "2026-08-24" if observed else None,
                10 if observed else 0,
                10,
                "2026-08-25T00:00:00Z",
                "{}",
            )
        )
    store._conn.executemany(  # noqa: SLF001
        """INSERT INTO dataset_coverage
           (dataset,status,policy_version,collection_scope,
            history_target_start,history_target_end_rule,coverage_mode,
            expected_frequency,universe_rule,raw_retention_required,
            structured_reconciliation_required,governance_tier,
            observed_start,observed_end,row_count,source_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        coverage_rows,
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO coverage_segments
           (source,dataset,segment_id,policy_version,segment_start,segment_end,
            expected_scope,expected_items,status,receipt_run_id,evaluated_at,
            detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "jquants", "equities_bars_daily", "2008-05",
            "collection-coverage/v3", "2008-05-07", "2008-05-31", "{}", 1,
            "PARTIAL", 10, "2026-08-25T00:00:00Z", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()


def _target() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return conn


def _bundle(path: Path, generation: str):
    return render_projection_bundle(
        path,
        generation_id=generation,
        producer_commit_sha="d" * 40,
        refresh_status="success",
        last_success_at="2026-08-25T00:01:00Z",
    )


def test_render_is_append_only_and_pointer_is_last(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    sql = _bundle(source, "projgen-one").sql
    assert "DELETE FROM" not in sql
    assert "INSERT OR REPLACE" not in sql
    statements = [line for line in sql.splitlines() if line and line != "COMMIT;"]
    open_index = next(
        index for index, statement in enumerate(statements)
        if statement.startswith("INSERT INTO ops_projection_generation")
    )
    metadata_index = next(
        index for index, statement in enumerate(statements)
        if statement.startswith("INSERT INTO ops_projection_metadata")
    )
    seal_index = next(
        index for index, statement in enumerate(statements)
        if statement.startswith("UPDATE ops_projection_generation")
    )
    assert open_index < metadata_index < seal_index < len(statements) - 1
    assert statements[-1].startswith("INSERT INTO ops_projection_active")


def test_two_generations_preserve_prior_rows_and_flip_pointer(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    first = _bundle(source, "projgen-first")
    second = _bundle(source, "projgen-second")
    target = _target()
    target.executescript(first.sql)
    target.executescript(second.sql)
    assert target.execute("SELECT COUNT(*) FROM dataset_coverage").fetchone() == (
        2 * len(all_coverage_contracts()),
    )
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == ("projgen-second",)
    assert target.execute(
        "SELECT COUNT(*) FROM dataset_coverage WHERE projection_generation_id=?",
        ("projgen-first",),
    ).fetchone() == (len(all_coverage_contracts()),)
    target.close()


def test_published_sql_storage_rows_rehash_to_the_signed_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    bundle = _bundle(source, "projgen-storage-parity")
    target = _target()
    target.executescript(bundle.sql)
    stored: dict[str, list[dict[str, object]]] = {}
    for table in PROJECTED_CONTENT_TABLES:
        cursor = target.execute(
            f"SELECT * FROM {table} WHERE projection_generation_id=?",  # noqa: S608
            (bundle.generation_id,),
        )
        columns = [str(item[0]) for item in cursor.description or ()]
        stored[table] = [dict(zip(columns, row, strict=True)) for row in cursor]
    manifest, digest = build_projection_content_manifest(stored)
    assert digest == bundle.content_digest
    assert {table: row["row_count"] for table, row in manifest.items()} == dict(
        bundle.row_counts
    )
    target.close()


def test_incomplete_generation_cannot_replace_active_pointer(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    first = _bundle(source, "projgen-active")
    incomplete = _bundle(source, "projgen-incomplete")
    lines = [
        line for line in incomplete.sql.splitlines()
        if not line.startswith("INSERT INTO dataset_coverage ")
    ]
    target = _target()
    target.executescript(first.sql)
    target.executescript("\n".join(lines) + "\n")
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == ("projgen-active",)
    assert target.execute(
        "SELECT status FROM ops_projection_generation WHERE generation_id=?",
        ("projgen-incomplete",),
    ).fetchone() == ("OPEN",)
    target.close()


def test_signed_pointer_update_atomically_rejects_cursor_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    signer = TestOpsProjectionSigningKey(
        "ops-projection-test-v1", Ed25519PrivateKey.generate()
    )

    def set_cursor(value: int) -> None:
        with sqlite3.connect(source) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sync_change_state "
                "(feed,last_applied_change_seq,updated_at) VALUES (?,?,?)",
                ("jquants_records", value, "2026-08-25T00:00:00Z"),
            )

    cursor = 12
    monkeypatch.setattr(
        sync_script,
        "_authenticated_export_cursor_chain_from_conn",
        lambda _conn: (cursor, cursor),
    )
    set_cursor(cursor)
    first = _render_projection_bundle_for_test(
        source,
        source_cursor=cursor,
        export_cursor=cursor,
        projection_signer=signer,
        generation_id="projgen-cursor-12",
        producer_commit_sha="a" * 40,
        _test_enforce_trusted_guards=True,
    )
    target = _target()
    target.executescript(first.sql)

    cursor = 11
    set_cursor(cursor)
    replay = _render_projection_bundle_for_test(
        source,
        source_cursor=cursor,
        export_cursor=cursor,
        projection_signer=signer,
        generation_id="projgen-cursor-11",
        producer_commit_sha="b" * 40,
        _test_enforce_trusted_guards=True,
    )
    target.executescript(replay.sql)
    assert target.execute(
        "SELECT generation_id FROM ops_projection_active WHERE singleton=1"
    ).fetchone() == ("projgen-cursor-12",)
    assert target.execute(
        "SELECT status FROM ops_projection_generation WHERE generation_id=?",
        ("projgen-cursor-11",),
    ).fetchone() == ("SEALED",)
    target.close()


def test_latest_successful_receipt_supersedes_old_failed_attempt(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    receipt = """INSERT INTO collection_receipts
      (source,dataset,segment_id,segment_start,segment_end,expected_scope,
       expected_items,observed_items,raw_page_count,raw_row_count,
       structured_row_count,pagination_exhausted,digests_json,run_id,status,
       error,checked_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    store._conn.execute(  # noqa: SLF001
        receipt,
        (
            "jquants", "equities_bars_daily", "2008-05", "2008-05-07",
            "2008-05-31", "{}", 1, 0, 0, 0, 0, 0, "{}", 10, "FAILED",
            "timeout", "2026-08-24T00:00:00Z",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        receipt,
        (
            "jquants", "equities_bars_daily", "2008-05", "2008-05-07",
            "2008-05-31", "{}", 1, 10, 1, 10, 10, 1, "{}", 11, "SUCCESS",
            None, "2026-08-25T00:00:00Z",
        ),
    )
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO raw_retention_manifests
           (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,
            data_digest,completeness,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "equities_bars_daily", 11, "raw/success.json", 1, 10, 100,
            "sha256:success", "ACQUIRED", "2026-08-25T00:00:00Z",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    bundle = _bundle(source, "projgen-raw")
    target = _target()
    target.executescript(bundle.sql)
    assert target.execute(
        "SELECT source,run_id,completeness,reason FROM raw_retention_manifests "
        "WHERE projection_generation_id=?",
        (bundle.generation_id,),
    ).fetchone() == (
        "jquants", 11, "ACQUIRED", "latest authoritative segment receipt"
    )
    target.close()


def test_storage_aggregate_has_no_default_cutoff(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    target = _target()
    bundle = _bundle(source, "projgen-storage")
    target.executescript(bundle.sql)
    payload = json.loads(
        target.execute(
            "SELECT payload_json FROM ops_storage_plane_status "
            "WHERE projection_generation_id=?",
            (bundle.generation_id,),
        ).fetchone()[0]
    )
    assert payload["hot_window"] == {
        "cutoff": None,
        "reason": "publisher did not receive an explicit storage hot cutoff",
        "status": "NOT_PROJECTED",
    }
    target.close()


def test_explicit_hot_cutoff_is_materialized_at_publish_time(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    store = SqliteStore(source)
    store._conn.execute(  # noqa: SLF001
        """INSERT INTO jquants_records
           (source,dataset,natural_key,event_time,available_at,ingested_at,
            payload,raw_payload) VALUES (?,?,?,?,?,?,?,?)""",
        (
            "jquants", "equities_bars_daily", '{"Code":"1"}', "2026-08-24",
            "2026-08-24T15:30:00Z", "2026-08-25T00:00:00Z", "{}", "{}",
        ),
    )
    store._conn.commit()  # noqa: SLF001
    store.close()
    bundle = render_projection_bundle(
        source,
        generation_id="projgen-hot",
        producer_commit_sha="e" * 40,
        storage_hot_cutoff="2026-08-01",
    )
    target = _target()
    target.executescript(bundle.sql)
    payload = json.loads(
        target.execute("SELECT payload_json FROM ops_storage_plane_status").fetchone()[0]
    )
    assert payload["hot_window"]["status"] == "MATERIALIZED"
    assert payload["hot_window"]["cutoff"] == "2026-08-01"
    assert payload["hot_window"]["bars_hot"] == 1
    target.close()


def test_publish_dry_run_does_not_write_artifacts(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    output = tmp_path / "ops/projection.sql"
    meta = tmp_path / "ops/projection.json"
    assert publisher.main(
        [f"--db={source}", f"--output={output}", f"--meta-output={meta}", "--dry-run"]
    ) == 0
    assert not output.exists()
    assert not meta.exists()
    rendered = capsys.readouterr().out
    assert '"generation_id"' in rendered
    assert '"source_db_digest"' in rendered


def test_publish_writes_content_addressed_generation_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    output = tmp_path / "ops/projection.sql"
    meta = tmp_path / "ops/projection.json"
    assert publisher.main(
        [f"--db={source}", f"--output={output}", f"--meta-output={meta}"]
    ) == 0
    document = json.loads(meta.read_text(encoding="utf-8"))
    assert document["generation_id"].startswith("projgen-")
    assert document["source_db_digest"].startswith("sha256:")
    assert document["row_counts"]["ops_projection_metadata"] == 1
    assert "DELETE FROM" not in output.read_text(encoding="utf-8")


def test_signed_projection_envelope_binds_content_cursors_and_gate_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    private = Ed25519PrivateKey.generate()
    signer = TestOpsProjectionSigningKey("ops-projection-test-v1", private)
    bundle = _render_projection_bundle_for_test(
        source,
        generation_id="projgen-signed",
        producer_commit_sha="f" * 40,
        source_cursor=12,
        export_cursor=11,
        projection_signer=signer,
    )
    registry = make_test_ops_projection_verifier(private)
    assert bundle.signed_envelope is not None
    schema = json.loads(
        (ROOT / "specs/ops_projection/signed_envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(bundle.signed_envelope)
    envelope = registry.verify(bundle.signed_envelope)
    assert envelope["generation_id"] == "projgen-signed"
    assert envelope["content_digest"] == bundle.content_digest
    assert envelope["source_cursor"] == 12
    assert envelope["export_cursor"] == 11
    assert envelope["applied_cursor"] is None
    assert envelope["coverage_status_digest"].startswith("sha256:")
    assert envelope["projection_status"] in {"FRESH", "STALE"}
    assert envelope["dataset_coverage"]["equities_bars_daily"]["status"] == "PARTIAL"
    assert envelope["b0_status"] == "UNKNOWN"
    assert envelope["b4_status"] == "UNKNOWN"
    assert set(envelope["evidence_digests"]) == {
        "coverage", "raw_retention", "ready", "storage", "sync", "validation"
    }
    derived = registry.verified_dataset_evidence(
        bundle.signed_envelope, ["equities_bars_daily"]
    )["equities_bars_daily"]
    assert derived["status"] == "PARTIAL"
    assert derived["coverage_mode"] == next(
        row.coverage_mode
        for row in all_coverage_contracts()
        if row.dataset_id == "equities_bars_daily"
    )
    assert derived["source_generation"] == 12
    assert derived["export_cursor"] == 11
    assert derived["applied_cursor"] is None

    tampered = json.loads(json.dumps(bundle.signed_envelope))
    tampered["envelope"]["applied_cursor"] = 12
    with pytest.raises(OpsProjectionSignatureError, match="signature is invalid"):
        registry.verify(tampered)

    former = json.loads(json.dumps(bundle.signed_envelope))
    former["issuer_key_id"] = "ops-projection-20260825-v1"
    with pytest.raises(OpsProjectionSignatureError, match="issuer is not trusted"):
        verify_pinned_ops_projection(former)


def test_trusted_renderer_rejects_generic_sqlite_path_and_caller_claims(
    tmp_path: Path,
) -> None:
    source = tmp_path / "manual.sqlite"
    _source(source)
    signer = TestOpsProjectionSigningKey(
        "ops-projection-test-v1", Ed25519PrivateKey.generate()
    )
    with pytest.raises(RuntimeError, match="PENDING full-source authority"):
        _render_trusted_projection_bundle(
            source,
            projection_signer=signer,
            generation_id="projgen-forged",
            producer_commit_sha="f" * 40,
        )
    with pytest.raises(ValueError, match="authenticated current D1 export"):
        sync_script.open_authenticated_applied_mirror(source)


@pytest.mark.parametrize("dry_run", [False, True])
def test_remote_publish_requires_dedicated_ops_projection_signer_before_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    output = tmp_path / "projection.sql"
    meta = tmp_path / "projection.json"
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (1, 1)
    )
    monkeypatch.setattr(
        publisher,
        "read_remote_active_cursor",
        lambda: pytest.fail("remote probe happened before authority gate"),
    )
    argv = [
        f"--db={source}",
        f"--output={output}",
        f"--meta-output={meta}",
        "--refresh-coverage",
        "--apply-remote",
    ]
    if dry_run:
        argv.append("--dry-run")
    assert publisher.main(argv) == 6
    assert not output.exists()
    assert not meta.exists()


def test_remote_publish_rejects_arbitrary_db_before_signing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "manual.sqlite"
    _source(source)
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (9, 9)
    )
    assert publisher.main([f"--db={source}", "--apply-remote"]) == 7


@pytest.mark.parametrize(
    "forbidden",
    [
        ["--source-cursor", "9"],
        ["--export-cursor", "9"],
        ["--projection-signing-key", "/tmp/fake.pem"],
        ["--projection-signing-key-id", "fake-key"],
        ["--force-apply-remote"],
    ],
)
def test_publisher_has_no_public_evidence_or_signer_override(
    forbidden: list[str],
) -> None:
    with pytest.raises(SystemExit):
        publisher.main(forbidden)


def test_remote_probe_uses_pinned_ops_wrangler_and_withholds_output(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    secret = "provider-secret-must-not-appear"
    calls = []

    def fail(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=1, stdout=secret, stderr=secret)

    monkeypatch.setattr(publisher.subprocess, "run", fail)
    assert publisher.count_remote_complete() is None
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err
    argv, kwargs = calls[0]
    assert argv[0] == str(publisher.OPS_WRANGLER_BIN.resolve())
    assert "npx" not in argv
    assert argv[1:4] == ["d1", "execute", "quant-ops-projection"]
    assert argv[argv.index("--env") + 1] == "production"
    assert kwargs["cwd"] == str(publisher.OPS_WRANGLER_CWD)
    assert kwargs["capture_output"] is True


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"active_count": 0}, 0),
        (
            {
                "active_count": 1,
                "source_cursor": 8,
                "export_cursor": 8,
                "applied_cursor": 8,
            },
            8,
        ),
        (
            {
                "active_count": 1,
                "source_cursor": 8,
                "export_cursor": 7,
                "applied_cursor": 8,
            },
            None,
        ),
        (
            {
                "active_count": 1,
                "source_cursor": None,
                "export_cursor": None,
                "applied_cursor": None,
            },
            None,
        ),
    ],
)
def test_remote_active_cursor_requires_exact_chain(
    monkeypatch: pytest.MonkeyPatch, row: dict[str, object], expected: int | None
) -> None:
    monkeypatch.setattr(
        publisher.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"results": [row]}]),
            stderr="",
        ),
    )
    assert publisher.read_remote_active_cursor() == expected


@pytest.mark.parametrize("remote_cursor", [None, 5])
def test_remote_publish_rejects_unknown_or_regressing_active_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_cursor: int | None,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (4, 4)
    )
    monkeypatch.setattr(
        publisher,
        "open_ops_projection_signing_service",
        lambda: TestOpsProjectionSigningKey(
            "ops-projection-test-v1", Ed25519PrivateKey.generate()
        ),
    )
    monkeypatch.setattr(
        publisher, "read_remote_active_cursor", lambda: remote_cursor
    )
    assert publisher.main([f"--db={source}", "--apply-remote"]) == 7


def test_production_projection_package_is_verify_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUANT_OPS_PROJECTION_SIGNING_KEY_PEM", "ignored")
    monkeypatch.setenv("QUANT_RECEIPT_SIGNING_KEY_PEM", "ignored")
    monkeypatch.setenv("QUANT_READINESS_SIGNING_KEY_FILE", "/tmp/ignored")
    assert open_ops_projection_signing_service() is None
    assert not hasattr(projection_signing, "OpsProjectionSigningKey")
    assert not hasattr(projection_signing, "OpsProjectionPublicKeyRegistry")
    assert not hasattr(projection_signing, "load_ops_projection_signer")
    assert not hasattr(projection_signing, "DEFAULT_SIGNING_KEY_PATH")
    assert not hasattr(projection_signing, "DEFAULT_VERIFY_REGISTRY_PATH")
    assert not hasattr(projection_signing, "parse_projection_key_registry")
    assert not hasattr(projection_signing, "verify_projection_with_registry")


def test_pinned_registry_binds_full_document_body_generation_and_prior_audit() -> None:
    current_path = ROOT / "specs/ops_projection/verify_public_keys.json"
    audit_path = ROOT / "specs/ops_projection/verify_public_keys.generation-1.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert current["generation"] == PINNED_OPS_PROJECTION_REGISTRY_GENERATION
    assert current["prior_registry_digest"] == PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST
    assert PINNED_OPS_PROJECTION_PRIOR_REGISTRY_DIGEST == sha256_digest(audit)
    assert current["registry_digest"] == PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST
    assert PINNED_OPS_PROJECTION_REGISTRY_BODY_DIGEST == sha256_digest(
        {key: value for key, value in current.items() if key != "registry_digest"}
    )
    assert sha256_digest(current) == PINNED_OPS_PROJECTION_REGISTRY_DOCUMENT_DIGEST
    assert audit["purpose"] == "ops_projection_registry_audit"
    assert audit["authority_status"] == "REVOKED"
    assert current["authority_status"] == "PENDING"
    assert [row["status"] for row in current["keys"]] == ["revoked", "pending"]


def test_generation_one_audit_and_attacker_registry_cannot_replace_pinned_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_path = ROOT / "specs/ops_projection/verify_public_keys.generation-1.json"
    monkeypatch.setattr(
        projection_signing, "_PINNED_VERIFY_REGISTRY_PATH", audit_path
    )
    with pytest.raises(OpsProjectionSignatureError, match="digest mismatch"):
        verify_pinned_ops_projection({})

    current = json.loads(
        (ROOT / "specs/ops_projection/verify_public_keys.json").read_text(
            encoding="utf-8"
        )
    )
    current["purpose"] = "attacker_selected_verification"
    current["registry_digest"] = sha256_digest(
        {key: value for key, value in current.items() if key != "registry_digest"}
    )
    attacker = tmp_path / "attacker-ops-registry.json"
    attacker.write_text(json.dumps(current), encoding="utf-8")
    monkeypatch.setattr(
        projection_signing, "_PINNED_VERIFY_REGISTRY_PATH", attacker
    )
    with pytest.raises(OpsProjectionSignatureError, match="digest mismatch"):
        verify_pinned_ops_projection({})


@pytest.mark.parametrize(
    "extra",
    [
        ["--snapshot-dir", "/tmp/caller-snapshot"],
        ["--otc-index-html", "/tmp/caller-index.html"],
        ["--storage-hot-cutoff", "2026-01-01"],
    ],
)
def test_remote_publish_rejects_caller_selected_evidence_paths_and_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str],
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (1, 1)
    )
    assert publisher.main([f"--db={source}", "--apply-remote", *extra]) == 7


def test_failed_refresh_never_publishes_fresh_or_applies(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)

    def fail(*_args, **_kwargs):
        raise RuntimeError("ledger failure")

    monkeypatch.setattr(publisher, "GOVERNED_LOCAL_DB", source.resolve())
    monkeypatch.setattr(
        publisher, "_authenticated_export_cursor_chain", lambda _path: (1, 1)
    )
    monkeypatch.setattr("storage.coverage_ledger.refresh_coverage_ledger", fail)
    monkeypatch.setattr(publisher, "count_local_complete", lambda _path: 0)
    monkeypatch.setattr(publisher, "count_remote_complete", lambda **_kwargs: 0)
    monkeypatch.setattr(publisher, "read_remote_active_cursor", lambda: 1)
    monkeypatch.setattr(
        publisher,
        "open_ops_projection_signing_service",
        lambda **_kwargs: TestOpsProjectionSigningKey(
            "ops-projection-test-v1", Ed25519PrivateKey.generate()
        ),
    )
    output = tmp_path / "ops/projection.sql"
    meta = tmp_path / "ops/projection.json"
    assert publisher.main(
        [
            f"--db={source}", f"--output={output}", f"--meta-output={meta}",
            "--refresh-coverage", "--apply-remote",
        ]
    ) == 4
    assert not output.exists()
    assert not meta.exists()


def test_projection_metadata_requires_successful_refresh_for_fresh(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    _source(source)
    assert build_projection_metadata(source, refresh_status="skipped")["status"] == "STALE"
    assert build_projection_metadata(source, refresh_status="success")["status"] == "FRESH"
