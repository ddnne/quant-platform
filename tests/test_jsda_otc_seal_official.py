"""OTC sealer refresh takes local index_text; unproved raw stays PARTIAL.

Missing --index-text is fail-closed empty, not calendar COMPLETE.
Early 21-column 2002-08-02/05 rows parse, but stay REPROOF_REQUIRED without
trusted raw reconciliation.
Does not fetch live JSDA HTML. Does not invent COMPLETE.
"""

from __future__ import annotations

import csv
import importlib.util
import inspect
import io
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "jsda_otc_seal_official.py"
_FIXTURE = _REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"
_CSV_FULL = _REPO / "tests" / "fixtures" / "jsda_otc_reference_headerless.csv"
EARLY_LAYOUT_REPROOF_DAYS = ("2002-08-02", "2002-08-05")
WEEKEND_IN_TINY_SPAN = "2002-08-03"
V2_REQUIRED = 8784


def _load_mod():
    name = "jsda_otc_seal_official_mod"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seal():
    return _load_mod()


def test_argparse_index_text_is_optional_path(seal) -> None:
    parser = seal._build_parser()
    omitted = parser.parse_args(["--log-dir", "logs"])
    assert omitted.index_text is None
    supplied = parser.parse_args(
        [
            "--log-dir",
            "logs",
            "--index-text",
            "tests/fixtures/jsda_otc_official_index_tiny.html",
        ]
    )
    assert supplied.index_text == (
        "tests/fixtures/jsda_otc_official_index_tiny.html"
    )
    action = next(
        item for item in parser._actions if "--index-text" in item.option_strings
    )
    assert action.required is False
    assert action.default is None


def test_read_index_text_omitted_blank_fixture(seal, tmp_path: Path) -> None:
    assert seal._read_index_text(None) is None
    assert seal._read_index_text("") is None
    assert seal._read_index_text("   ") is None
    blank = tmp_path / "blank.html"
    blank.write_text("   \n", encoding="utf-8")
    assert seal._read_index_text(blank) is None
    html = seal._read_index_text(_FIXTURE)
    assert html is not None
    assert html.strip() != ""
    assert "https://" not in html
    assert "2002.8.2" in html
    assert "2002.8.5" in html
    assert "2002.8.6" in html


def test_read_index_text_missing_path_raises(seal, tmp_path: Path) -> None:
    missing = tmp_path / "no_such_official_index.html"
    assert not missing.exists()
    with pytest.raises(FileNotFoundError):
        seal._read_index_text(missing)


def test_refresh_otc_coverage_always_passes_index_text(seal, monkeypatch) -> None:
    captured: dict = {}

    def fake_refresh(conn, db_path, **kw):
        captured["kwargs"] = kw
        captured["index_text"] = kw.get("index_text", "MISSING_KEY")
        return []

    monkeypatch.setattr(seal, "refresh_coverage_ledger", fake_refresh)
    seal.refresh_otc_coverage(object(), "db.sqlite", index_text=None)
    assert "index_text" in captured["kwargs"]
    assert captured["index_text"] is None
    assert captured["index_text"] != V2_REQUIRED
    html = _FIXTURE.read_text(encoding="utf-8")
    seal.refresh_otc_coverage(object(), "db.sqlite", index_text=html)
    assert captured["index_text"] == html
    assert captured["kwargs"]["datasets"] == [seal.OTC_DATASET]


def test_early_layout_requires_trusted_digest_count_release(seal) -> None:
    assert seal.EARLY_LAYOUT_RECONCILIATION_PROOF == {}
    assert set(EARLY_LAYOUT_REPROOF_DAYS) == set(
        seal.EARLY_LAYOUT_REPROOF_DAYS
    )
    for day in EARLY_LAYOUT_REPROOF_DAYS:
        assert seal._early_layout_reproof_required(
            day, "sha256:" + "ab" * 32, 4200
        ) is True
        assert seal._early_layout_reproof_required(day, None, 4200) is True
        assert seal._early_layout_reproof_required(
            day, "sha256:" + "ab" * 32, 0
        ) is True
    assert seal._early_layout_reproof_required(
        "2002-08-06", "sha256:" + "cd" * 32, 3167
    ) is False


def test_inventory_scope_defaults_official_archive_index_day(
    seal, tmp_path: Path,
) -> None:
    conn = sqlite3.connect(tmp_path / "scope.sqlite")
    conn.execute(
        "CREATE TABLE coverage_segments ("
        "dataset TEXT, segment_id TEXT, expected_scope TEXT,"
        "segment_start TEXT, segment_end TEXT)"
    )
    conn.commit()
    scope, start, end = seal.inventory_scope(conn, "2002-08-02")
    assert start == end == "2002-08-02"
    assert scope["segment_granularity"] == "official_archive_index_day"
    assert scope["segment_granularity"] != "official_archive_day"
    assert scope["coverage_mode"] == "official_archive_index_reconciled"
    conn.close()


def _synthetic_early_layout_body() -> bytes:
    source = _CSV_FULL.read_text(encoding="utf-8")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in csv.reader(io.StringIO(source)):
        writer.writerow(row[:21])
    return buffer.getvalue().encode("cp932")


def test_seal_day_parser_capable_stays_unsealed_without_trusted_reproof(
    seal, tmp_path: Path,
) -> None:
    body = _synthetic_early_layout_body()
    n = (seal.FULL_OK_MIN // len(body)) + 2
    raw = body * n
    assert len(raw) > seal.FULL_OK_MIN
    path = tmp_path / "S020802.csv"
    path.write_bytes(raw)
    for day in EARLY_LAYOUT_REPROOF_DAYS:
        quote_day = "2002-08-01" if day == "2002-08-02" else "2002-08-02"
        result = seal.seal_day(
            None,
            day,
            path,
            "",
            quote_effective_date=quote_day,
        )
        assert result["status"] == "REPROOF_REQUIRED"
        assert result["reason"] == "TRUSTED_RAW_RECONCILIATION_REQUIRED"
        assert result["status"] != "PARSE_ZERO"
        assert result["status"] != "SEALED"
        assert result["status"] != "COMPLETE"
        assert result["segment_id"] == day
        assert int(result["raw"]) > 0
        assert str(result["digest"]).startswith("sha256:")


def test_seal_day_rejects_publication_label_as_quote_day(
    seal, tmp_path: Path,
) -> None:
    path = tmp_path / "S020802.csv"
    path.write_bytes(b"x" * (seal.FULL_OK_MIN + 1))
    result = seal.seal_day(
        None,
        "2002-08-02",
        path,
        "",
        quote_effective_date="2002-08-02",
    )
    assert result == {
        "segment_id": "2002-08-02",
        "status": "QUOTE_EFFECTIVE_DATE_UNRESOLVED",
    }


def test_official_publication_labels_resolve_to_prior_quote_day(seal) -> None:
    resolved = seal.resolve_quote_effective_dates(
        (), stored_labels=("2002-08-02", "2002-08-05", "2002-08-06")
    )
    assert resolved == {
        "2002-08-02": "2002-08-01",
        "2002-08-05": "2002-08-02",
        "2002-08-06": "2002-08-05",
    }


def test_seal_source_does_not_fetch_live_html_or_invent_complete(seal) -> None:
    src = Path(inspect.getsourcefile(seal)).read_text(encoding="utf-8")
    assert "index_text=index_text" in src
    assert "def refresh_otc_coverage" in src
    assert "_early_layout_reproof_required" in inspect.getsource(seal.seal_day)
    assert "urllib" not in src
    assert "requests." not in src
    assert "urlopen" not in src
    assert seal.OTC_GRAIN == "official_archive_index_day"
    assert seal.EARLY_LAYOUT_RECONCILIATION_PROOF == {}
    assert WEEKEND_IN_TINY_SPAN not in seal.EARLY_LAYOUT_REPROOF_DAYS
    assert "open_governed_receipt_service" not in src
    assert "record_persisted_success" not in src
    assert "bulk_insert_day" not in src
    assert "TRUSTED_COLLECTION" not in src


def test_recovery_sealer_records_only_failed_reproof_evidence(
    seal, tmp_path: Path,
) -> None:
    body = _CSV_FULL.read_bytes()
    raw = body * ((seal.FULL_OK_MIN // len(body)) + 2)
    path = tmp_path / "S020806.csv"
    path.write_bytes(raw)
    store = seal.SqliteStore(tmp_path / "recovery.sqlite")
    try:
        result = seal.seal_day(
            store,
            "2002-08-06",
            path,
            "https://www.jsda.or.jp/example/S020806.csv",
            quote_effective_date="2002-08-05",
        )
        assert result["status"] == "REPROOF_REQUIRED"
        assert result["reason"] == "GOVERNED_INGESTION_REPLAY_REQUIRED"
        row = store._conn.execute(  # noqa: SLF001
            "SELECT status,error,digests_json,structured_row_count "
            "FROM collection_receipts WHERE dataset=? AND segment_id=? "
            "ORDER BY run_id DESC LIMIT 1",
            (seal.OTC_DATASET, "2002-08-06"),
        ).fetchone()
        assert row is not None
        assert row[0] == "FAILED"
        assert str(row[1]).startswith("REPROOF_REQUIRED:")
        digests = json.loads(str(row[2]))
        assert digests["eligibility"] == "RECOVERED_RAW_ONLY"
        assert digests["quote_effective_date"] == "2002-08-05"
        assert "signature" not in digests
        assert int(row[3]) == 0
        facts = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM jsda_otc_bond_reference_prices "
            "WHERE publication_label_date='2002-08-06'"
        ).fetchone()[0]
        assert int(facts) == 0
    finally:
        store.close()
