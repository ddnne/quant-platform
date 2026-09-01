"""Personal DRAFT ingestion stays local, unsigned, and PIT-safe."""

from __future__ import annotations

import builtins
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from ingestion.common.http import HttpResponse
from ingestion.jquants.normalize import normalize_generic
from ingestion.pipeline import run_jquants
from scripts.run_ingestion_once import main
from storage.sqlite_store import SqliteStore


REPO_ROOT = Path(__file__).resolve().parents[1]


class _CatalogHttp:
    name = "local"

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def get(self, url, *, headers=None, params=None, timeout=30.0):
        del headers, params, timeout
        return HttpResponse(
            200,
            {"content-type": "application/json"},
            json.dumps({"data": self._rows}).encode("utf-8"),
            url,
        )


def test_personal_draft_commits_exact_pit_rows_and_unsigned_raw_manifest(
    tmp_path, monkeypatch
):
    source_row = {"Code": "8697", "Date": "2025-04-01", "Close": 100}
    http = _CatalogHttp([source_row])
    store = SqliteStore(tmp_path / "personal.sqlite")

    real_import = builtins.__import__

    def _reject_authority_import(name, *args, **kwargs):
        if name.endswith("runtime_authority"):
            raise AssertionError("personal DRAFT must not import receipt authority")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _reject_authority_import)
    reports = run_jquants(
        http=http,
        store=store,
        api_key="test-key",
        data_base=tmp_path,
        today=datetime(2025, 4, 2, 9, 0, 0),
        datasets=["equities_bars_daily"],
        mode="backfill",
        date_from="2025-04-01",
        date_to="2025-04-01",
        max_workers=1,
        personal_draft=True,
    )

    assert len(reports) == 1
    assert reports[0].ok
    assert reports[0].registered == 1
    actual = store.fetch_all("jquants_records")
    expected = normalize_generic(
        [source_row],
        dataset="equities_bars_daily",
        ingested_at=actual[0]["ingested_at"],
    )
    assert actual == expected

    manifest_path = Path(reports[0].raw_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == (
        "jquants-personal-draft-raw-manifest/v1"
    )
    assert manifest["research_state"] == "PERSONAL_DRAFT"
    assert manifest["completeness_claim"] == "NONE"
    assert manifest["trusted_receipt"] == "NOT_ISSUED"
    assert manifest_path.stat().st_mode & 0o222 == 0
    assert len(manifest["pages"]) == 1
    raw_page = Path(manifest["pages"][0]["raw_path"])
    assert raw_page.is_file()
    assert raw_page.stat().st_mode & 0o222 == 0

    assert store.fetch_all("collection_receipts") == []
    assert store.fetch_all("coverage_segments") == []
    assert store.fetch_all("dataset_coverage") == []
    assert store.fetch_all("snapshot_publications") == []
    store.close()


@pytest.mark.parametrize(
    "argv, message",
    [
        (
            [
                "--personal-draft",
                "--source",
                "jquants",
                "--runtime",
                "cloudflare",
                "--dataset",
                "markets_calendar",
            ],
            "requires --runtime local",
        ),
        (
            ["--personal-draft", "--source", "jquants", "--runtime", "local"],
            "requires at least one --dataset",
        ),
        (
            [
                "--personal-draft",
                "--source",
                "jquants",
                "--runtime",
                "local",
                "--dataset",
                " , ",
            ],
            "requires at least one non-empty --dataset",
        ),
        (
            [
                "--personal-draft",
                "--source",
                "all",
                "--runtime",
                "local",
                "--dataset",
                "markets_calendar",
            ],
            "requires --source jquants",
        ),
    ],
)
def test_personal_draft_cli_rejects_ambiguous_or_nonlocal_use(
    argv, message, capsys
):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_personal_draft_pipeline_requires_local_catalog_mode(tmp_path):
    store = SqliteStore(tmp_path / "validation.sqlite")
    http = _CatalogHttp([])
    with pytest.raises(ValueError, match="runtime=local"):
        run_jquants(
            http=http,
            store=store,
            api_key="test-key",
            data_base=tmp_path,
            today=datetime(2025, 4, 2, 9, 0, 0),
            runtime="cloudflare",
            datasets=["markets_calendar"],
            personal_draft=True,
        )
    with pytest.raises(ValueError, match="explicit catalog datasets"):
        run_jquants(
            http=http,
            store=store,
            api_key="test-key",
            data_base=tmp_path,
            today=datetime(2025, 4, 2, 9, 0, 0),
            personal_draft=True,
        )
    store.close()


def test_personal_draft_cli_refuses_governed_default_database(
    tmp_path, capsys
):
    governed = tmp_path / "structured" / "ingestion.sqlite"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--personal-draft",
                "--source",
                "jquants",
                "--runtime",
                "local",
                "--dataset",
                "markets_calendar",
                "--data-dir",
                str(tmp_path),
                "--db",
                str(governed),
            ]
        )
    assert exc.value.code == 2
    assert "refuses the governed ingestion.sqlite" in capsys.readouterr().err


def test_personal_draft_refuses_database_with_governed_evidence(tmp_path):
    store = SqliteStore(tmp_path / "managed.sqlite")
    store._conn.execute(
        "INSERT INTO local_snapshot_policy(singleton) VALUES (1)"
    )
    store._conn.commit()

    with pytest.raises(ValueError, match="managed/governed database"):
        run_jquants(
            http=_CatalogHttp([]),
            store=store,
            api_key="test-key",
            data_base=tmp_path,
            today=datetime(2025, 4, 2, 9, 0, 0),
            datasets=["markets_calendar"],
            personal_draft=True,
        )
    store.close()


def test_pipeline_import_does_not_load_receipt_authority() -> None:
    program = r'''
import sys
sys.path[:0] = sys.argv[1:]
import ingestion.pipeline
if "ingestion.runtime_authority" in sys.modules:
    raise AssertionError("personal-capable pipeline eagerly loaded receipt authority")
'''
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            program,
            str(REPO_ROOT),
            str(REPO_ROOT / "packages" / "data_plane"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_historical_wrapper_propagates_personal_mode_and_dedicated_db(
    tmp_path, monkeypatch, capsys
):
    from scripts import run_historical_backfill as historical

    monkeypatch.setattr(historical, "LOG_ROOT", tmp_path / "logs")
    code = historical.main(
        [
            "--personal-draft",
            "--runtime",
            "local",
            "--dataset",
            "markets_calendar",
            "--from-date",
            "2021-08-27",
            "--to-date",
            "2021-08-31",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "--personal-draft" in output
    assert "personal-ingestion.sqlite" in output
