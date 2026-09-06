"""Strong invariants for Python/Worker identity and the D1 v2 rebuild.

Worker rebuild (canonical ``naturalKey``, atomic swap, post-publish READY
audit, ``requireNaturalKeysV2Ready``) is executed in
``platform/workers/ingestion-premium/src/natural_key_migration.test.ts``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest

from data_contracts.identity import available_at_for, canonical_json, natural_key


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "platform/workers/ingestion-premium"
CONTRACT = ROOT / "packages/data_plane/data_contracts/jquants_premium_core.json"
_CANONICAL_VECTORS_PATH = (
    ROOT / "specs" / "authorities" / "jquants_acquisition_canonical_vectors.json"
)


def test_canonical_json_matches_shared_ecmascript_number_vectors() -> None:
    document = json.loads(_CANONICAL_VECTORS_PATH.read_text(encoding="utf-8"))
    assert document["number_rendering"] == "ECMASCRIPT_JSON_STRINGIFY"
    number_vectors = [
        row
        for row in document["vectors"]
        if row.get("family") == "ecmascript-json-number"
    ]
    assert [row["id"] for row in number_vectors] == [
        "js-number-ordinary-fractions",
        "js-number-zero",
        "js-number-exponent-thresholds",
        "js-number-binary64-integers",
        "js-number-array-object",
    ]
    for vector in number_vectors:
        rendered = canonical_json(vector["value"])
        assert rendered == vector["canonical_json"]
        digest = "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        assert digest == vector["sha256_digest"]

    # JSON documents cannot preserve IEEE -0; construct it directly.
    assert canonical_json(-0.0) == "0"
    assert canonical_json({"x": -0.0}) == '{"x":0}'
    assert canonical_json(2**53 + 1) == "9007199254740992"
    assert canonical_json([0.45, 0.11, -0.45, 0.045]) == "[0.45,0.11,-0.45,0.045]"


def test_python_and_worker_share_canonical_identity_and_availability_semantics():
    document = json.loads(CONTRACT.read_text(encoding="utf-8"))
    by_id = {item["dataset_id"]: item for item in document["datasets"]}
    ingested_at = "2025-04-02T09:00:00+09:00"
    vectors = [
        (
            "equities_bars_daily",
            {
                "Code": "8697",
                "Date": "2025-04-01",
                "Close": 100,
                # Untrusted metadata must influence neither policy selection
                # nor the complete-key identity.
                "available_at": "1999-01-01T00:00:00+09:00",
            },
        ),
        (
            "markets_short_ratio",
            {"Date": "2025-04-01", "S33": "0050", "Name": "電気・ガス"},
        ),
        (
            "markets_short_ratio",
            {
                "Date": "2025-04-01",
                "S33": None,
                "Ratio": 1.25,
                "available_at": "1999-01-01T00:00:00+09:00",
            },
        ),
    ]
    request = [
        {"dataset": dataset, "row": row, "spec": by_id[dataset], "ingested": ingested_at}
        for dataset, row in vectors
    ]
    identity_url = (WORKER / "src/identity.ts").as_uri()
    script = f"""
      import fs from 'node:fs';
      import {{ naturalKey, pickAvailableAt }} from {json.dumps(identity_url)};
      const items = JSON.parse(fs.readFileSync(0, 'utf8'));
      const out = [];
      for (const item of items) {{
        try {{
          out.push({{
            status: 'accepted',
            key: await naturalKey(item.row, item.spec),
            available_at: pickAvailableAt(item.row, item.spec, item.ingested),
          }});
        }} catch (error) {{
          out.push({{
            status: 'rejected',
            error: error instanceof Error ? error.message : String(error),
          }});
        }}
      }}
      process.stdout.write(JSON.stringify(out));
    """
    completed = subprocess.run(
        [
            "node",
            "--no-warnings",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            script,
        ],
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=True,
    )
    worker_results = json.loads(completed.stdout)
    python_results = []
    for dataset, row in vectors:
        try:
            python_results.append(
                {
                    "status": "accepted",
                    "key": natural_key(row, dataset),
                    "available_at": available_at_for(row, dataset, ingested_at),
                }
            )
        except ValueError as error:
            python_results.append(
                {"status": "rejected", "error": str(error)}
            )
    assert worker_results == python_results
    assert python_results[-1] == {
        "status": "rejected",
        "error": (
            "governed natural-key field S33 is absent; "
            "structured product is rejected"
        ),
    }
    with pytest.raises(ValueError, match="governed natural-key field S33"):
        natural_key(vectors[-1][1], vectors[-1][0])


def test_d1_0005_defers_identity_to_application_rebuild_without_mutating_live_rows():
    migrations = WORKER / "migrations"
    conn = sqlite3.connect(":memory:")
    for name in (
        "0001_init.sql",
        "0002_watermarks.sql",
        "0003_change_feed.sql",
        "0004_revision_identity_v2.sql",
    ):
        conn.executescript((migrations / name).read_text(encoding="utf-8"))

    payload = json.dumps(
        {"Date": "2025-04-01", "S33": None, "Ratio": 1.25},
        separators=(",", ":"),
    )
    legacy_key = '{"Date":"2025-04-01","S33":null}'
    conn.execute(
        "INSERT INTO jquants_records "
        "(source,dataset,natural_key,event_time,available_at,ingested_at,payload,raw_payload) "
        "VALUES ('jquants','markets_short_ratio',?,?,?,?,?,?)",
        (
            legacy_key,
            "2025-04-01T00:00:00+09:00",
            "2025-04-02T09:00:00+09:00",
            "2025-04-02T09:00:00+09:00",
            payload,
            payload,
        ),
    )
    migration_sql = (migrations / "0005_natural_keys_v2.sql").read_text(
        encoding="utf-8"
    )
    conn.executescript(migration_sql)

    executable_sql = "\n".join(
        line for line in migration_sql.splitlines() if not line.lstrip().startswith("--")
    )
    assert "json_object(" not in executable_sql
    assert "SET natural_key" not in executable_sql
    assert conn.execute(
        "SELECT natural_key FROM jquants_records"
    ).fetchone()[0] == legacy_key
    assert conn.execute(
        "SELECT state FROM natural_key_migrations "
        "WHERE migration_id='jquants-premium-natural-keys-v2'"
    ).fetchone()[0] == "PENDING"
    stage_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%nk_v2%stage'"
        )
    }
    assert stage_tables == {
        "jquants_records_nk_v2_versions_stage",
        "jquants_records_nk_v2_primary_stage",
        "jquants_records_nk_v2_revisions_stage",
        "ingestion_change_log_nk_v2_stage",
    }
