"""OTC sealer refresh takes local index_text; PARSE_ZERO stays PARTIAL.

Missing --index-text is fail-closed empty, not calendar COMPLETE.
PARSE_ZERO 2002-08-02/05 stay unsealed without in-repo digest+count.
Does not fetch live JSDA HTML. Does not invent COMPLETE.
"""

from __future__ import annotations

import importlib.util
import inspect
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "jsda_otc_seal_official.py"
_FIXTURE = _REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"
_CSV_23 = _REPO / "tests" / "fixtures" / "jsda_otc_reference_headerless_23col.csv"
PARSE_ZERO_DAYS = ("2002-08-02", "2002-08-05")
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


def test_parse_zero_days_unproven_without_digest_count(seal) -> None:
    assert seal.PARSE_ZERO_SEAL_PROOF == {}
    assert set(PARSE_ZERO_DAYS) == set(seal.PARSE_ZERO_DAYS)
    for day in PARSE_ZERO_DAYS:
        assert seal._parse_zero_unproven(day, "sha256:" + "ab" * 32, 4200) is True
        assert seal._parse_zero_unproven(day, None, 4200) is True
        assert seal._parse_zero_unproven(day, "sha256:" + "ab" * 32, 0) is True
    assert seal._parse_zero_unproven("2002-08-06", "sha256:" + "cd" * 32, 3167) is False


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


def test_seal_day_parse_zero_stays_unsealed_without_proof(
    seal, tmp_path: Path,
) -> None:
    lines = [ln for ln in _CSV_23.read_text(encoding="utf-8").splitlines() if ln.strip()]
    body = (lines[0] + "\n" + lines[1] + "\n").encode("cp932")
    n = (seal.FULL_OK_MIN // len(body)) + 2
    raw = body * n
    assert len(raw) > seal.FULL_OK_MIN
    path = tmp_path / "S020802.csv"
    path.write_bytes(raw)
    for day in PARSE_ZERO_DAYS:
        result = seal.seal_day(None, day, path, "", None)
        assert result["status"] == "PARSE_ZERO"
        assert result["status"] != "SEALED"
        assert result["status"] != "COMPLETE"
        assert result["segment_id"] == day
        assert int(result["raw"]) > 0
        assert str(result["digest"]).startswith("sha256:")


def test_seal_source_does_not_fetch_live_html_or_invent_complete(seal) -> None:
    src = Path(inspect.getsourcefile(seal)).read_text(encoding="utf-8")
    assert "index_text=index_text" in src
    assert "def refresh_otc_coverage" in src
    assert "_parse_zero_unproven" in inspect.getsource(seal.seal_day)
    assert "urllib" not in src
    assert "requests." not in src
    assert "urlopen" not in src
    assert seal.OTC_GRAIN == "official_archive_index_day"
    assert seal.PARSE_ZERO_SEAL_PROOF == {}
    assert WEEKEND_IN_TINY_SPAN not in seal.PARSE_ZERO_DAYS
