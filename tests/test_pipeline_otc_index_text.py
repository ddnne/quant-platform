"""Pipeline plans OTC from already-held year-index HTML, not calendar.

Missing index_text is fail-closed empty required set, not 8784 weekends.
Fixture HTML lists 2002-08-02/05/06 and excludes weekend 2002-08-03.
Does not fetch live HTML. Does not invent COMPLETE.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from data_contracts import coverage_contract_for
from ingestion.pipeline import (
    _index_text_for_plan,
    _plan_required_segments,
)
from ingestion.pipeline_receipts import emit_catalog_job_receipt
from storage.sqlite_store import SqliteStore

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "jsda_otc_official_index_tiny.html"

DATASET = "jsda_otc_bond_reference_prices"
LISTED_TINY_DAYS = ("2002-08-02", "2002-08-05", "2002-08-06")
WEEKEND_IN_TINY_SPAN = "2002-08-03"
V2_REQUIRED = 8784


def _calendar_days(start: str, end: str) -> list[str]:
    cursor = date.fromisoformat(start)
    last = date.fromisoformat(end)
    out: list[str] = []
    while cursor <= last:
        out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def test_pipeline_otc_plan_without_index_text_is_empty() -> None:
    policy = coverage_contract_for(DATASET)
    assert _index_text_for_plan(policy) is None
    assert _index_text_for_plan(policy, None) is None
    assert _index_text_for_plan(policy, "") is None
    assert _index_text_for_plan(policy, "   ") is None
    planned = _plan_required_segments(policy, "2002-08-06", source="jsda")
    ids = [seg.segment_id for seg in planned]
    assert planned == []
    assert ids == []
    assert WEEKEND_IN_TINY_SPAN not in ids
    assert len(ids) != V2_REQUIRED
    assert all(seg.segment_id != "COMPLETE" for seg in planned)


def test_pipeline_otc_plan_with_fixture_html_lists_publication_days_not_weekend() -> None:
    policy = coverage_contract_for(DATASET)
    html = FIXTURE.read_text(encoding="utf-8")
    assert "https://" not in html
    assert _index_text_for_plan(policy, html) == html
    planned = _plan_required_segments(
        policy, "2002-08-06", source="jsda", index_text=html,
    )
    ids = [seg.segment_id for seg in planned]
    calendar = _calendar_days("2002-08-02", "2002-08-06")
    assert ids == list(LISTED_TINY_DAYS)
    assert WEEKEND_IN_TINY_SPAN not in ids
    assert WEEKEND_IN_TINY_SPAN in calendar
    assert date.fromisoformat(WEEKEND_IN_TINY_SPAN).weekday() >= 5
    assert len(ids) != len(calendar)
    assert len(ids) != V2_REQUIRED
    assert all(seg.segment_id != "COMPLETE" for seg in planned)


def test_catalog_receipt_without_official_index_creates_no_required_state(
    tmp_path: Path,
) -> None:
    store = SqliteStore(tmp_path / "otc-no-index.sqlite")
    try:
        emit_catalog_job_receipt(
            store,
            job=SimpleNamespace(
                dataset_id=DATASET,
                params={"from": "2002-08-02", "to": "2002-08-06"},
            ),
            collection_context=SimpleNamespace(
                checked_at="2026-08-26T00:00:00+00:00"
            ),
            persisted_collection=object(),
            receipt_service=object(),
        )
        segment_count = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM coverage_segments WHERE dataset=?",
            (DATASET,),
        ).fetchone()[0]
        receipt_count = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM collection_receipts WHERE dataset=?",
            (DATASET,),
        ).fetchone()[0]
    finally:
        store.close()
    assert segment_count == 0
    assert receipt_count == 0
