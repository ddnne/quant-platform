"""write_collection_receipts plans OTC from local index HTML, not calendar.

Missing --index-text / QP_INDEX_TEXT is fail-closed empty required set.
Fixture HTML lists 2002-08-02/05/06 and excludes weekend 2002-08-03.
Never downloads the official index. Does not invent COMPLETE.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "write_collection_receipts.py"
FIXTURE = REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"

DATASET = "jsda_otc_bond_reference_prices"
LISTED_TINY_DAYS = ("2002-08-02", "2002-08-05", "2002-08-06")
WEEKEND_IN_TINY_SPAN = "2002-08-03"
V2_REQUIRED = 8784


def _load_mod():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    name = "write_collection_receipts"
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _calendar_days(start: str, end: str) -> list[str]:
    cursor = date.fromisoformat(start)
    last = date.fromisoformat(end)
    out: list[str] = []
    while cursor <= last:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


@pytest.fixture
def receipts():
    return _load_mod()


def test_no_index_path_empty_otc_required_set(receipts) -> None:
    assert receipts._read_index_text(None) is None
    planned = receipts._plan_segments(DATASET, "2002-08-06", "jsda")
    ids = [seg.segment_id for seg in planned]
    assert planned == []
    assert ids == []
    assert WEEKEND_IN_TINY_SPAN not in ids
    assert len(ids) != V2_REQUIRED
    assert all(seg.segment_id != "COMPLETE" for seg in planned)


def test_missing_index_path_is_fail_closed_empty(receipts) -> None:
    text = receipts._read_index_text("/no/such/official-index.html")
    assert text is None
    planned = receipts._plan_segments(
        DATASET, "2002-08-06", "jsda", index_text=text,
    )
    ids = [seg.segment_id for seg in planned]
    assert ids == []
    assert WEEKEND_IN_TINY_SPAN not in ids
    assert len(ids) != V2_REQUIRED


def test_blank_index_file_is_fail_closed_empty(receipts, tmp_path: Path) -> None:
    blank = tmp_path / "blank.html"
    blank.write_text("   \n", encoding="utf-8")
    text = receipts._read_index_text(blank)
    assert text is None
    planned = receipts._plan_segments(
        DATASET, "2002-08-06", "jsda", index_text=text,
    )
    ids = [seg.segment_id for seg in planned]
    assert ids == []
    assert WEEKEND_IN_TINY_SPAN not in ids


def test_fixture_html_lists_publication_days_not_weekend(receipts) -> None:
    html = receipts._read_index_text(FIXTURE)
    assert html is not None
    assert "https://" not in html
    planned = receipts._plan_segments(
        DATASET, "2002-08-06", "jsda", index_text=html,
    )
    ids = [seg.segment_id for seg in planned]
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    assert ids == list(LISTED_TINY_DAYS)
    assert WEEKEND_IN_TINY_SPAN not in ids
    assert WEEKEND_IN_TINY_SPAN in calendar
    assert date.fromisoformat(WEEKEND_IN_TINY_SPAN).weekday() >= 5
    assert len(ids) != len(calendar)
    assert len(ids) != V2_REQUIRED
    assert all(status != "COMPLETE" for status in ids)


def test_list_segments_without_index_is_empty_otc(
    receipts, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QP_INDEX_TEXT", raising=False)
    db = tmp_path / "empty.sqlite"
    db.write_bytes(b"")
    rc = receipts.main([
        "--db", str(db),
        "--dataset", DATASET,
        "--target-end", "2002-08-06",
        "--list-segments",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2002-08-02" not in out
    assert WEEKEND_IN_TINY_SPAN not in out
    assert "COMPLETE" not in out


def test_list_segments_with_fixture_index_excludes_weekend(
    receipts, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QP_INDEX_TEXT", raising=False)
    db = tmp_path / "empty.sqlite"
    db.write_bytes(b"")
    rc = receipts.main([
        "--db", str(db),
        "--dataset", DATASET,
        "--target-end", "2002-08-06",
        "--index-text", str(FIXTURE),
        "--list-segments",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    for day in LISTED_TINY_DAYS:
        assert day in out
    assert WEEKEND_IN_TINY_SPAN not in out
    assert "COMPLETE" not in out


def test_env_qp_index_text_reads_local_html(
    receipts, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QP_INDEX_TEXT", str(FIXTURE))
    db = tmp_path / "empty.sqlite"
    db.write_bytes(b"")
    rc = receipts.main([
        "--db", str(db),
        "--dataset", DATASET,
        "--target-end", "2002-08-06",
        "--list-segments",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    for day in LISTED_TINY_DAYS:
        assert day in out
    assert WEEKEND_IN_TINY_SPAN not in out


def test_cli_index_text_overrides_env(
    receipts, tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch,
) -> None:
    blank = tmp_path / "blank.html"
    blank.write_text("\n", encoding="utf-8")
    monkeypatch.setenv("QP_INDEX_TEXT", str(FIXTURE))
    db = tmp_path / "empty.sqlite"
    db.write_bytes(b"")
    rc = receipts.main([
        "--db", str(db),
        "--dataset", DATASET,
        "--target-end", "2002-08-06",
        "--index-text", str(blank),
        "--list-segments",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2002-08-02" not in out
    assert WEEKEND_IN_TINY_SPAN not in out
