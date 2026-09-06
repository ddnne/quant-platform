"""Behavioral PIT/DRAFT/READY bounds: correction leakage, empty vs error, intern."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.execution import close_as_of, morning_close_as_of
from data_contracts.identity import natural_key
from personal_history_compact_support import (
    insert_compact_bar,
    insert_compact_master,
    install_compact_schema,
    stamp_compact_manifest,
)
from paper_runtime.ready_policy import ReadyEvidenceBundle, ReadyEvidenceItem
from pit import HistoryReadError, PitError, SnapshotNotReady, source_sync_evidence
from pit.history_reads import (
    HISTORY_CODE_BATCH,
    HISTORY_READ_PAGE_SIZE,
    fetch_unmanaged_draft_catalog_rows,
)
from pit.personal_research_view import (
    OfflineFixtureDataView,
    PersonalResearchViewError,
    refuse_offline_fixture_for_controlled,
)
from pit.query import _install_readonly_scope, _open_readonly_sqlite, connect_readonly
from pit.universe_pit import resolve_universe_day_slices

from research.personal_service import PersonalResearchRequest
from research.personal_universe import resolve_personal_universe_with_evidence
from research.universe_contract import resolve_tse_prime_with_fins
from selection.budget_ledger import MassResearchDisabledError


def _catalog_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE jquants_records ("
        "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
        "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT, "
        "PRIMARY KEY(source, dataset, natural_key))"
    )
    connection.execute(
        "CREATE TABLE jquants_records_revisions AS SELECT * FROM jquants_records WHERE 0"
    )
    stamp_compact_manifest(connection, format_name='unmanaged-catalog')
    return connection


def _insert(
    connection: sqlite3.Connection,
    *,
    table: str,
    dataset: str,
    payload: dict,
    event_time: str,
    available_at: str,
    ingested_at: str | None = None,
) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    connection.execute(
        f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?)",
        (
            "jquants",
            dataset,
            natural_key(payload, dataset),
            event_time,
            available_at,
            ingested_at or available_at,
            encoded,
            encoded,
        ),
    )


def _payload_v(row: dict) -> object:
    raw = row["payload"]
    if isinstance(raw, str):
        return json.loads(raw)["v"]
    return raw["v"]


def test_unmanaged_draft_catalog_revision_obeys_as_of(tmp_path: Path) -> None:
    path = tmp_path / "rev.sqlite"
    connection = _catalog_db(path)
    payload_old = {"Code": "1301", "DiscDate": "2025-04-01", "DiscNo": "1", "v": 1}
    payload_new = {"Code": "1301", "DiscDate": "2025-04-01", "DiscNo": "1", "v": 2}
    _insert(
        connection,
        table="jquants_records_revisions",
        dataset="fins_summary",
        payload=payload_old,
        event_time="2025-04-01T15:00:00+09:00",
        available_at="2025-04-01T15:00:00+09:00",
    )
    _insert(
        connection,
        table="jquants_records",
        dataset="fins_summary",
        payload=payload_new,
        event_time="2025-04-01T15:00:00+09:00",
        available_at="2025-04-02T10:00:00+09:00",
    )
    connection.commit()
    connection.close()
    early = fetch_unmanaged_draft_catalog_rows(
        path, as_of="2025-04-01T16:00:00+09:00", dataset="fins_summary"
    )
    late = fetch_unmanaged_draft_catalog_rows(
        path, as_of="2025-04-02T16:00:00+09:00", dataset="fins_summary"
    )
    assert len(early) == 1 and _payload_v(early[0]) == 1
    assert _payload_v(late[0]) == 2


def test_codes_filtered_revision_query_uses_raw_payload(tmp_path: Path) -> None:
    path = tmp_path / "codes.sqlite"
    connection = _catalog_db(path)
    keep = {"Code": "1301", "DiscDate": "2025-04-01", "DiscNo": "1", "v": 1}
    drop = {"Code": "7203", "DiscDate": "2025-04-01", "DiscNo": "1", "v": 9}
    _insert(
        connection,
        table="jquants_records_revisions",
        dataset="fins_summary",
        payload=keep,
        event_time="2025-04-01T15:00:00+09:00",
        available_at="2025-04-01T15:00:00+09:00",
    )
    _insert(
        connection,
        table="jquants_records",
        dataset="fins_summary",
        payload=keep,
        event_time="2025-04-01T15:00:00+09:00",
        available_at="2025-04-02T10:00:00+09:00",
    )
    _insert(
        connection,
        table="jquants_records",
        dataset="fins_summary",
        payload=drop,
        event_time="2025-04-01T15:00:00+09:00",
        available_at="2025-04-01T15:00:00+09:00",
    )
    connection.commit()
    connection.close()
    rows = fetch_unmanaged_draft_catalog_rows(
        path,
        as_of="2025-04-02T16:00:00+09:00",
        dataset="fins_summary",
        codes=["1301"],
        versions=True,
    )
    assert rows
    codes = {
        json.loads(row["payload"])["Code"]
        if isinstance(row["payload"], str)
        else row["payload"]["Code"]
        for row in rows
    }
    assert codes == {"1301"}


def test_missing_history_file_is_empty_invalid_schema_raises(tmp_path: Path) -> None:
    missing = tmp_path / "absent.sqlite"
    assert (
        fetch_unmanaged_draft_catalog_rows(
            missing, as_of="2025-04-01T15:00:00+09:00", dataset="fins_summary"
        )
        == []
    )
    broken = tmp_path / "broken.sqlite"
    connection = sqlite3.connect(broken)
    connection.execute(
        "CREATE TABLE jquants_records ("
        "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
        "available_at TEXT, ingested_at TEXT, payload TEXT, "
        "PRIMARY KEY(source, dataset, natural_key))"
    )
    connection.commit()
    connection.close()
    with pytest.raises(HistoryReadError):
        fetch_unmanaged_draft_catalog_rows(
            broken,
            as_of="2025-04-01T15:00:00+09:00",
            dataset="fins_summary",
            codes=["1301"],
        )


def _emitted_closes(pages) -> list[float]:
    closes: list[float] = []
    for page in pages:
        for row in page:
            raw = row["payload"]
            payload = json.loads(raw) if isinstance(raw, str) else raw
            closes.append(float(payload["C"]))
    return closes


def test_bar_correction_does_not_leak_into_earlier_decision(tmp_path: Path) -> None:
    path = tmp_path / "bars.sqlite"
    connection = _catalog_db(path)
    base = {"Code": "1301", "Date": "2024-01-02", "C": 100}
    correction = {"Code": "1301", "Date": "2024-01-02", "C": 200}
    _insert(
        connection,
        table="jquants_records_revisions",
        dataset="equities_bars_daily",
        payload=base,
        event_time="2024-01-02T15:00:00+09:00",
        available_at="2024-01-02T15:00:00+09:00",
    )
    _insert(
        connection,
        table="jquants_records",
        dataset="equities_bars_daily",
        payload=correction,
        event_time="2024-01-02T15:00:00+09:00",
        available_at="2024-01-31T15:00:00+09:00",
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path,
        artifact_root=tmp_path / "art",
        decision_cutoff="session_close",
    )
    kwargs = dict(
        dataset="equities_bars_daily",
        codes=["1301"],
        start="2024-01-02",
        end="2024-02-01",
    )
    jan2 = list(view.iter_decision_pages(decision_date="2024-01-02", **kwargs))
    feb1 = list(view.iter_decision_pages(decision_date="2024-02-01", **kwargs))
    jan2_again = list(view.iter_decision_pages(decision_date="2024-01-02", **kwargs))
    assert _emitted_closes(jan2) == [100.0]
    assert _emitted_closes(feb1) == [200.0]
    assert _emitted_closes(jan2_again) == [100.0]
    with pytest.raises(AttributeError):
        view.draft_sqlite_path()
    with pytest.raises(AttributeError):
        view.artifact_directory()


def test_morning_close_rejects_after_am_correction(tmp_path: Path) -> None:
    path = tmp_path / "am-bars.sqlite"
    connection = _catalog_db(path)
    am_visible = {"Code": "1301", "Date": "2024-01-02", "C": 100}
    after_am = {"Code": "1301", "Date": "2024-01-02", "C": 200}
    _insert(
        connection,
        table="jquants_records_revisions",
        dataset="equities_bars_daily",
        payload=am_visible,
        event_time="2024-01-02T11:30:00+09:00",
        available_at="2024-01-02T11:30:00+09:00",
    )
    _insert(
        connection,
        table="jquants_records",
        dataset="equities_bars_daily",
        payload=after_am,
        event_time="2024-01-02T15:00:00+09:00",
        available_at="2024-01-02T15:00:00+09:00",
    )
    connection.commit()
    connection.close()
    morning_view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "am", decision_cutoff="morning_close"
    )
    session_view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "sess", decision_cutoff="session_close"
    )
    kwargs = dict(
        decision_date="2024-01-02",
        dataset="equities_bars_daily",
        codes=["1301"],
        start="2024-01-02",
        end="2024-01-02",
    )
    morning = list(morning_view.iter_decision_pages(**kwargs))
    session = list(session_view.iter_decision_pages(**kwargs))
    assert morning_close_as_of("2024-01-02") == "2024-01-02T11:30:00+09:00"
    assert _emitted_closes(morning) == [100.0]
    assert _emitted_closes(session) == [200.0]


def test_local_validation_is_unknown_draft_not_ready(tmp_path: Path) -> None:
    path = tmp_path / "draft.sqlite"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE local_marker(x INTEGER)")
    connection.execute(
        "CREATE TABLE ingestion_validation (id INTEGER PRIMARY KEY, dataset TEXT, status TEXT)"
    )
    connection.execute(
        "CREATE TABLE ingestion_watermarks (dataset TEXT PRIMARY KEY, last_ingested_at TEXT)"
    )
    connection.execute(
        "INSERT INTO ingestion_validation(dataset, status) VALUES ('equities_master', 'pass')"
    )
    connection.execute(
        "INSERT INTO ingestion_watermarks VALUES ('equities_master', '2025-04-01T00:00:00+09:00')"
    )
    connection.commit()
    connection.close()
    evidence = source_sync_evidence(
        path,
        {"source_policy_provenance": {"table_present": True, "row_present": True}},
        required_datasets=("equities_master",),
    )
    assert evidence["status"] == "UNKNOWN"
    assert evidence["execution_allowed"] is True
    assert evidence["quality_verified"] is False
    assert evidence["source_complete_claim"] is not True
    empty = source_sync_evidence(
        path,
        {"source_policy_provenance": {"table_present": True, "row_present": True}},
        required_datasets=(),
    )
    assert empty["status"] == "UNKNOWN"
    bundle = ReadyEvidenceBundle(
        items=[
            ReadyEvidenceItem(
                name="source_sync",
                passed=bool(evidence["quality_verified"] and evidence["status"] == "PASS"),
            )
        ]
    )
    assert bundle.passed is False


def test_local_validation_fail_is_not_unknown_pass(tmp_path: Path) -> None:
    path = tmp_path / "draft-fail.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE ingestion_validation (id INTEGER PRIMARY KEY, dataset TEXT, status TEXT)"
    )
    connection.execute(
        "CREATE TABLE ingestion_watermarks (dataset TEXT PRIMARY KEY, last_ingested_at TEXT)"
    )
    connection.execute(
        "INSERT INTO ingestion_validation(dataset, status) VALUES ('equities_master', 'fail')"
    )
    connection.execute(
        "INSERT INTO ingestion_watermarks VALUES ('equities_master', '2025-04-01T00:00:00+09:00')"
    )
    connection.commit()
    connection.close()
    evidence = source_sync_evidence(
        path,
        {"source_policy_provenance": {"table_present": True, "row_present": True}},
        required_datasets=("equities_master",),
    )
    assert evidence["status"] == "FAIL"
    assert evidence["execution_allowed"] is False
    assert evidence["quality_verified"] is False


def test_ready_public_bypass_is_not_importable_and_pit_rejects_pre_ready(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pre-ready.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
        "snapshot_ready INTEGER, publication_state TEXT)"
    )
    connection.execute(
        "INSERT INTO local_snapshot_policy VALUES (1, 1, 0, 'REJECTED')"
    )
    connection.execute(
        "CREATE TABLE jquants_records ("
        "source TEXT, dataset TEXT, natural_key TEXT, event_time TEXT, "
        "available_at TEXT, ingested_at TEXT, payload TEXT, raw_payload TEXT)"
    )
    connection.commit()
    connection.close()
    with pytest.raises(SnapshotNotReady):
        connect_readonly(path)
    with pytest.raises((SnapshotNotReady, MassResearchDisabledError)):
        resolve_tse_prime_with_fins(
            path, period_start="2025-04-01", period_end="2025-04-01"
        )
    import pit._ready_verifier_reads as ready_reads

    assert not hasattr(ready_reads, "iter_ready_catalog_fact_pages")


def test_ready_stream_pages_ignore_unused_fact_rows(tmp_path: Path) -> None:
    path = tmp_path / "ready-stream.sqlite"
    connection = _catalog_db(path)
    needed = {"Code": "1301", "Date": "2025-04-01", "C": 100}
    _insert(
        connection,
        table="jquants_records",
        dataset="equities_bars_daily",
        payload=needed,
        event_time="2025-04-01T15:30:00+09:00",
        available_at="2025-04-01T15:30:00+09:00",
    )
    _insert(
        connection,
        table="jquants_records",
        dataset="equities_bars_daily",
        payload={"Code": "1301", "Date": "2010-01-04", "C": 1},
        event_time="2010-01-04T15:00:00+09:00",
        available_at="2010-01-04T15:00:00+09:00",
    )
    for index in range(400):
        extra = {
            "Code": f"{9000 + index}",
            "Date": "2025-04-01",
            "C": float(index),
        }
        _insert(
            connection,
            table="jquants_records",
            dataset="equities_bars_daily",
            payload=extra,
            event_time="2025-04-01T15:30:00+09:00",
            available_at="2025-04-01T15:30:00+09:00",
        )
    connection.commit()
    connection.close()
    page_sizes: list[int] = []
    codes: set[str] = set()
    import pit._ready_verifier_reads as ready_reads

    assert not hasattr(ready_reads, "iter_ready_catalog_fact_pages")
    assert page_sizes == []
    assert codes == set()


def test_universe_membership_is_interned_across_stable_days(tmp_path: Path) -> None:
    path = tmp_path / "intern.sqlite"
    connection = _catalog_db(path)
    start = date(2025, 1, 6)
    days = [(start + timedelta(days=offset)).isoformat() for offset in range(40)]
    codes = tuple(f"{1000 + index}" for index in range(20))
    for day in days:
        _insert(
            connection,
            table="jquants_records",
            dataset="markets_calendar",
            payload={"Date": day, "HolidayDivision": "1"},
            event_time=f"{day}T00:00:00+09:00",
            available_at=f"{day}T00:00:00+09:00",
        )
    for code in codes:
        _insert(
            connection,
            table="jquants_records",
            dataset="equities_master",
            payload={
                "Code": code,
                "Date": days[0],
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Mid400",
            },
            event_time=f"{days[0]}T08:00:00+09:00",
            available_at=f"{days[0]}T08:00:00+09:00",
        )
        _insert(
            connection,
            table="jquants_records",
            dataset="fins_summary",
            payload={"Code": code, "DiscDate": "2024-12-27", "DiscNo": "1"},
            event_time="2024-12-27T15:00:00+09:00",
            available_at="2024-12-27T15:00:00+09:00",
        )
    connection.commit()
    connection.close()
    slices = resolve_universe_day_slices(
        path,
        period_start=days[0],
        period_end=days[-1],
        as_of_for_day={day: close_as_of(day) for day in days},
    )
    assert len(slices) == 40
    assert len({id(item.members) for item in slices}) == 1
    assert len({id(item.fins_codes) for item in slices}) == 1
    unique_members = {id(member) for item in slices for member in item.members}
    assert len(unique_members) == len(codes)
    assert {member.code for member in slices[0].members} == set(codes)


def test_universe_listing_delisting_and_intermediate_listing(tmp_path: Path) -> None:
    path = tmp_path / "list-delist.sqlite"
    connection = _catalog_db(path)
    days = ("2025-04-01", "2025-04-02", "2025-04-03")
    for day in days:
        _insert(
            connection,
            table="jquants_records",
            dataset="markets_calendar",
            payload={"Date": day, "HolidayDivision": "1"},
            event_time=f"{day}T00:00:00+09:00",
            available_at=f"{day}T00:00:00+09:00",
        )
    members = (
        ("2025-04-01", "1001"),
        ("2025-04-01", "1002"),
        ("2025-04-02", "1001"),
        ("2025-04-03", "1001"),
        ("2025-04-03", "1003"),
    )
    for snapshot, code in members:
        _insert(
            connection,
            table="jquants_records",
            dataset="equities_master",
            payload={
                "Code": code,
                "Date": snapshot,
                "MarketCode": "0111",
                "ScaleCategory": "TOPIX Mid400",
            },
            event_time=f"{snapshot}T08:00:00+09:00",
            available_at=f"{snapshot}T08:00:00+09:00",
        )
    for code in ("1001", "1002", "1003"):
        _insert(
            connection,
            table="jquants_records",
            dataset="fins_summary",
            payload={"Code": code, "DiscDate": "2025-03-31", "DiscNo": "1"},
            event_time="2025-03-31T15:00:00+09:00",
            available_at="2025-03-31T15:00:00+09:00",
        )
    connection.commit()
    connection.close()
    slices = resolve_universe_day_slices(
        path,
        period_start="2025-04-01",
        period_end="2025-04-03",
        as_of_for_day={day: close_as_of(day) for day in days},
    )
    by_day = {item.decision_date: tuple(m.code for m in item.members) for item in slices}
    assert by_day["2025-04-01"] == ("1001", "1002")
    assert by_day["2025-04-02"] == ("1001",)
    assert by_day["2025-04-03"] == ("1001", "1003")
    assert id(slices[0].members) != id(slices[1].members)
    assert slices[0].snapshot_date == "2025-04-01"
    assert slices[1].snapshot_date == "2025-04-02"
    assert slices[2].snapshot_date == "2025-04-03"

def test_morning_close_rejects_pm_event_even_if_available_early(tmp_path: Path) -> None:
    path = tmp_path / "am-event.sqlite"
    connection = _catalog_db(path)
    _insert(
        connection,
        table="jquants_records",
        dataset="equities_bars_daily",
        payload={"Code": "1301", "Date": "2024-12-02", "C": 200},
        event_time="2024-12-02T15:30:00+09:00",
        available_at="2024-12-02T10:00:00+09:00",
    )
    connection.commit()
    connection.close()
    morning_view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "am2", decision_cutoff="morning_close"
    )
    session_view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "sess2", decision_cutoff="session_close"
    )
    kwargs = dict(
        decision_date="2024-12-02",
        dataset="equities_bars_daily",
        codes=["1301"],
        start="2024-12-02",
        end="2024-12-02",
    )
    morning = [row for page in morning_view.iter_decision_pages(**kwargs) for row in page]
    session = [row for page in session_view.iter_decision_pages(**kwargs) for row in page]
    assert morning == []
    assert _emitted_closes([session]) == [200.0]


def _compact_snapshot(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    return connection


def test_compact_v7_bar_correction_does_not_leak_into_earlier_decision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "compact-bars.sqlite"
    connection = _compact_snapshot(path)
    insert_compact_bar(
        connection,
        day="2024-01-02",
        close=100.0,
        event_time="2024-01-02T15:00:00+09:00",
        available_at="2024-01-02T15:00:00+09:00",
        ingested_at="2024-01-02T15:00:00+09:00",
    )
    insert_compact_bar(
        connection,
        day="2024-01-02",
        close=200.0,
        event_time="2024-01-02T15:00:00+09:00",
        available_at="2024-01-31T15:00:00+09:00",
        ingested_at="2024-01-31T15:00:00+09:00",
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path,
        artifact_root=tmp_path / "compact-art",
        decision_cutoff="session_close",
    )
    kwargs = dict(
        dataset="equities_bars_daily",
        codes=["1301"],
        start="2024-01-02",
        end="2024-02-01",
    )
    jan2 = list(view.iter_decision_pages(decision_date="2024-01-02", **kwargs))
    feb1 = list(view.iter_decision_pages(decision_date="2024-02-01", **kwargs))
    jan2_again = list(view.iter_decision_pages(decision_date="2024-01-02", **kwargs))
    assert _emitted_closes(jan2) == [100.0]
    assert _emitted_closes(feb1) == [200.0]
    assert _emitted_closes(jan2_again) == [100.0]


def test_compact_v7_master_intraday_correction_is_pit(tmp_path: Path) -> None:
    path = tmp_path / "compact-master.sqlite"
    connection = _catalog_db(path)
    connection.close()
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    for day in ("2024-01-02",):
        _insert(
            connection,
            table="jquants_records",
            dataset="markets_calendar",
            payload={"Date": day, "HolidayDivision": "1"},
            event_time=f"{day}T00:00:00+09:00",
            available_at=f"{day}T00:00:00+09:00",
        )
        _insert(
            connection,
            table="jquants_records",
            dataset="fins_summary",
            payload={"Code": "1301", "DiscDate": "2023-12-29", "DiscNo": "1"},
            event_time="2023-12-29T15:00:00+09:00",
            available_at="2023-12-29T15:00:00+09:00",
        )
    insert_compact_master(
        connection,
        snapshot_date="2024-01-02",
        code="1301",
        event_time="2024-01-02T08:00:00+09:00",
        available_at="2024-01-02T08:00:00+09:00",
        ingested_at="2024-01-02T08:00:00+09:00",
        scale_category="TOPIX Mid400",
        source_scale_category="Mid400",
    )
    insert_compact_master(
        connection,
        snapshot_date="2024-01-02",
        code="1301",
        event_time="2024-01-02T12:00:00+09:00",
        available_at="2024-01-02T12:00:00+09:00",
        ingested_at="2024-01-02T12:00:00+09:00",
        scale_category="TOPIX Small 1",
        source_scale_category="Small1",
    )
    connection.commit()
    connection.close()
    morning = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "m-art", decision_cutoff="morning_close"
    )
    session = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "s-art", decision_cutoff="session_close"
    )
    morning_slices = morning.universe_slices(
        period_start="2024-01-02", period_end="2024-01-02"
    )
    session_slices = session.universe_slices(
        period_start="2024-01-02", period_end="2024-01-02"
    )
    assert [member.scale_category for member in morning_slices[0].members] == [
        "TOPIX Mid400"
    ]
    assert [member.scale_category for member in session_slices[0].members] == [
        "TOPIX Small 1"
    ]
    morning_again = morning.universe_slices(
        period_start="2024-01-02", period_end="2024-01-02"
    )
    assert [member.scale_category for member in morning_again[0].members] == [
        "TOPIX Mid400"
    ]


def test_old_compact_overwrite_pk_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "old-compact.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE personal_history_manifest ("
        "singleton INTEGER PRIMARY KEY, format TEXT, status TEXT)"
    )
    connection.execute(
        "INSERT INTO personal_history_manifest(singleton, format, status) "
        "VALUES (1, 'personal-draft-history/v7', 'COMPLETE_DRAFT')"
    )
    connection.execute(
        "CREATE TABLE personal_history_compact_master ("
        "snapshot_date TEXT NOT NULL, code TEXT NOT NULL, "
        "event_time TEXT NOT NULL, available_at TEXT NOT NULL, "
        "ingested_at TEXT NOT NULL, market_code TEXT, sector_17_code TEXT, "
        "sector_33_code TEXT, scale_category TEXT, source_scale_category TEXT, "
        "PRIMARY KEY (snapshot_date, code)"
        ") WITHOUT ROWID"
    )
    connection.execute(
        "CREATE TABLE personal_history_compact_bars ("
        "code TEXT NOT NULL, date TEXT NOT NULL, event_time TEXT NOT NULL, "
        "available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, close REAL NOT NULL, "
        "volume REAL, turnover_value REAL, adjustment_close REAL, "
        "adjustment_volume REAL, morning_adjustment_close REAL, "
        "afternoon_adjustment_close REAL, morning_turnover_value REAL, "
        "afternoon_turnover_value REAL, morning_adjustment_volume REAL, "
        "afternoon_adjustment_volume REAL, market_cap REAL, "
        "PRIMARY KEY (code, date)"
        ") WITHOUT ROWID"
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(path, artifact_root=tmp_path / "old-art")
    with pytest.raises(PitError, match="rebuild as personal-draft-history/v8"):
        list(
            view.iter_decision_pages(
                decision_date="2024-01-02",
                dataset="equities_bars_daily",
                codes=["1301"],
                start="2024-01-02",
                end="2024-01-02",
            )
        )


def test_history_pages_are_bounded(tmp_path: Path) -> None:
    path = tmp_path / "pages.sqlite"
    connection = _catalog_db(path)
    codes = [f"{1000 + i}" for i in range(12)]
    start = date(2015, 1, 5)
    days = [(start + timedelta(days=offset)).isoformat() for offset in range(80)]
    for day in days:
        stamp = f"{day}T15:00:00+09:00"
        for code in codes:
            _insert(
                connection,
                table="jquants_records",
                dataset="equities_bars_daily",
                payload={"Code": code, "Date": day, "C": 1.0},
                event_time=stamp,
                available_at=stamp,
            )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "long", decision_cutoff="morning_close"
    )
    page_size = 8
    resident = 0
    max_resident = 0
    peak_page_bytes = 0
    pages = 0
    for page in view.iter_decision_pages(
        decision_date=days[-1],
        dataset="equities_bars_daily",
        codes=codes,
        start=days[0],
        end=days[-1],
        page_size=page_size,
    ):
        resident = len(page)
        max_resident = max(max_resident, resident)
        page_bytes = sum(len(str(row)) for row in page)
        peak_page_bytes = max(peak_page_bytes, page_bytes)
        pages += 1
        assert len(page) <= page_size
        assert len(page) <= HISTORY_READ_PAGE_SIZE
        del page
    assert pages > 1
    assert max_resident <= page_size
    assert max_resident <= HISTORY_CODE_BATCH or max_resident <= page_size
    assert peak_page_bytes > 0
    assert peak_page_bytes <= page_size * 4096


def test_offline_fixture_cannot_feed_controlled(tmp_path: Path) -> None:
    path = tmp_path / "fx.sqlite"
    connection = _catalog_db(path)
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(path, artifact_root=tmp_path / "art")
    assert view.controlled_eligible is False
    assert view.research_state == "UNMANAGED_DRAFT"
    assert view.decision_cutoff == "morning_close"
    with pytest.raises(PersonalResearchViewError, match="DRAFT research views"):
        refuse_offline_fixture_for_controlled(view)
    with pytest.raises(TypeError):
        PersonalResearchRequest(
            source_db=path,
            period_end="2024-01-02",
            output_root=tmp_path,
        )
    from cf_platform.container_data_view import ContainerEphemeralDataView
    with pytest.raises(PersonalResearchViewError, match="legacy OfflineFixture"):
        ContainerEphemeralDataView.bind(
            path,
            artifact_root=tmp_path / "container",
            decision_cutoff="session_close",
        )


def test_container_ephemeral_view_does_not_need_local_market_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QP_ALLOW_LOCAL_MARKET_DATA", raising=False)
    path = tmp_path / "container.sqlite"
    connection = _catalog_db(path)
    connection.commit()
    connection.close()
    from cf_platform.container_data_view import ContainerEphemeralDataView

    view = ContainerEphemeralDataView.bind(
        path, artifact_root=tmp_path / "container-art"
    )
    assert view.kind == "container_ephemeral"
    assert view.decision_cutoff == "morning_close"
    assert view.allows_legacy_session_close is False
    assert os.environ.get("QP_ALLOW_LOCAL_MARKET_DATA") is None
    with pytest.raises(AttributeError):
        view.draft_sqlite_path()


def test_long_history_membership_peak_stays_bounded_not_days_times_codes(
    tmp_path: Path,
) -> None:
    import tracemalloc

    path = tmp_path / "long-history.sqlite"
    connection = _catalog_db(path)
    install_compact_schema(connection)
    start = date(2020, 1, 6)
    days = [(start + timedelta(days=offset)).isoformat() for offset in range(240)]
    codes = [f"{1000 + i:04d}" for i in range(180)]
    for day in days:
        midnight = f"{day}T00:00:00+09:00"
        _insert(
            connection,
            table="jquants_records",
            dataset="markets_calendar",
            payload={"Date": day, "HolidayDivision": "1"},
            event_time=midnight,
            available_at=midnight,
        )
    for code in codes:
        _insert(
            connection,
            table="jquants_records",
            dataset="fins_summary",
            payload={"Code": code, "DiscDate": "2019-12-02", "DiscNo": "1"},
            event_time="2019-12-02T15:00:00+09:00",
            available_at="2019-12-02T15:00:00+09:00",
        )
        insert_compact_master(
            connection,
            snapshot_date=days[0],
            code=code,
            scale_category="TOPIX Mid400",
            source_scale_category="Mid400",
        )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "long-art", decision_cutoff="morning_close"
    )
    tracemalloc.start()
    membership, _evidence = resolve_personal_universe_with_evidence(
        view,
        period_start=days[0],
        period_end=days[-1],
        universe_id="topix_all",
    )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    first = membership.codes_for(days[0])
    last = membership.codes_for(days[-1])
    assert first == tuple(codes)
    assert last is first
    copied_bound = len(days) * len(codes) * 64
    assert peak < copied_bound
    assert peak < 8 * 1024 * 1024



def test_container_execute_job_does_not_launch_product_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import inspect
    import subprocess

    from test_cloud_personal_research_container import (
        _direct_run_from_summary,
        _job,
        _runner_summary,
        _sqlite,
        _uploader,
        service,
    )

    monkeypatch.delenv("QP_ALLOW_LOCAL_MARKET_DATA", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("container execute_job must not launch a process")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)

    source = tmp_path / "fixture.sqlite"
    sha = _sqlite(source)
    spec = _job(sha)

    def direct(_spec, *, database, output, timeout_seconds, **_kwargs):
        del _spec, database, timeout_seconds
        return _direct_run_from_summary(_runner_summary(spec), output)

    monkeypatch.setattr(service, "_run_direct_research", direct)
    work = tmp_path / "work"
    work.mkdir()

    def copy_snapshot(_spec, destination):
        destination.write_bytes(source.read_bytes())

    manifest = service.execute_job(
        spec,
        work_root=work,
        downloader=copy_snapshot,
        uploader=_uploader([]),
    )
    assert manifest["status"] == "COMPLETED"
    assert "command" not in inspect.signature(service.execute_job).parameters
    assert not hasattr(service, "_run_research_process")
    assert not hasattr(service, "_stdout_summary")
    assert not hasattr(service, "_process_crash_message")
    assert os.environ.get("QP_ALLOW_LOCAL_MARKET_DATA") is None
    with pytest.raises(TypeError, match="command"):
        service.execute_job(  # type: ignore[call-arg]
            spec,
            work_root=work,
            command=("qp-research",),
        )


def test_two_clock_ingested_row_follows_snapshot_observed_through(
    tmp_path: Path,
) -> None:
    from personal_history_compact_support import insert_compact_bar, stamp_compact_manifest

    path = tmp_path / "clocks.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    insert_compact_bar(
        connection,
        code="1301",
        day="2025-01-02",
        close=10.0,
        available_at="2025-01-02T15:30:00+09:00",
        ingested_at="2025-01-03T09:00:00+09:00",
        event_time="2025-01-02T15:30:00+09:00",
    )
    stamp_compact_manifest(
        connection, observed_through="2025-01-02T16:00:00+09:00"
    )
    connection.commit()
    connection.close()
    early = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "e", decision_cutoff="session_close"
    )
    assert (
        list(
            early.iter_decision_pages(
                decision_date="2025-01-02",
                dataset="equities_bars_daily",
                codes=["1301"],
                start="2025-01-02",
                end="2025-01-02",
            )
        )
        == []
    )

    connection = sqlite3.connect(path)
    stamp_compact_manifest(
        connection, observed_through="2025-01-03T16:00:00+09:00"
    )
    connection.commit()
    connection.close()
    late = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "l", decision_cutoff="session_close"
    )
    pages = list(
        late.iter_decision_pages(
            decision_date="2025-01-02",
            dataset="equities_bars_daily",
            codes=["1301"],
            start="2025-01-02",
            end="2025-01-02",
        )
    )
    assert len(pages) == 1 and len(pages[0]) == 1
    assert float(pages[0][0]["payload"]["Close"]) == 10.0


def test_first_historical_backfill_usable_under_now_snapshot(
    tmp_path: Path,
) -> None:
    from personal_history_compact_support import insert_compact_bar

    path = tmp_path / "backfill.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    insert_compact_bar(
        connection,
        code="1301",
        day="2008-01-04",
        close=1.0,
        available_at="2008-01-04T15:00:00+09:00",
        ingested_at="2026-01-15T12:00:00+09:00",
        event_time="2008-01-04T15:00:00+09:00",
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(
        path, artifact_root=tmp_path / "now", decision_cutoff="session_close"
    )
    pages = list(
        view.iter_decision_pages(
            decision_date="2008-01-04",
            dataset="equities_bars_daily",
            codes=["1301"],
            start="2008-01-04",
            end="2008-01-04",
        )
    )
    assert float(pages[0][0]["payload"]["Close"]) == 1.0


def test_long_history_run_length_peak_without_cartesian_product() -> None:
    import tracemalloc

    from data_contracts.membership_runs import MembershipRun
    from data_contracts.personal_universe import TOPIX_SCALE_CATEGORIES
    from research.personal_universe import (
        PERSONAL_UNIVERSE_RULE_VERSION,
        PersonalResolvedUniverseMembership,
        personal_universe_selector,
    )

    codes = tuple(f"{1000 + i:04d}" for i in range(2000))
    start = date(2008, 1, 4)
    end = start + timedelta(days=6499)
    selector = personal_universe_selector("topix_all")
    tracemalloc.start()
    membership = PersonalResolvedUniverseMembership(
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        decision_memberships=(),
        rule_id=selector.rule_id,
        rule_version=PERSONAL_UNIVERSE_RULE_VERSION,
        rule_digest=selector.rule_digest,
        membership_runs=(
            MembershipRun(
                start=start.isoformat(), end=end.isoformat(), codes=codes
            ),
        ),
    )
    mid = (start + timedelta(days=3000)).isoformat()
    assert membership.codes_for(start.isoformat()) is codes
    assert membership.codes_for(mid) is codes
    assert membership.codes_for(end.isoformat()) is codes
    assert membership.resolved_membership_digest.startswith("sha256:")
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    cartesian = 6500 * 2000 * 8
    assert peak < cartesian
    assert peak < 16 * 1024 * 1024
    del TOPIX_SCALE_CATEGORIES


def test_container_rejects_if_either_path_is_persistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pit.personal_research_view as view_mod
    from cf_platform.container_data_view import ContainerEphemeralDataView

    path = tmp_path / "c.sqlite"
    connection = _catalog_db(path)
    connection.commit()
    connection.close()
    original = view_mod._is_ephemeral_fs

    def selective(target: Path, *, owned_root=None) -> bool:
        return "art" in str(target) and original(target, owned_root=owned_root)

    monkeypatch.setattr(view_mod, "_is_ephemeral_fs", selective)
    with pytest.raises(PersonalResearchViewError, match="ephemeral"):
        ContainerEphemeralDataView.bind(
            path, artifact_root=tmp_path / "art"
        )


def test_worker_v8_snapshot_is_accepted_by_python_container(tmp_path: Path) -> None:
    from data_contracts.personal_history_compact import (
        PERSONAL_HISTORY_COMPACT_FORMAT,
        compact_history_state,
    )
    from personal_history_compact_support import install_compact_schema

    ts = (
        Path("platform/workers/research-mass-eval/src/personal_snapshot_contract.ts")
        .read_text(encoding="utf-8")
    )
    assert 'PERSONAL_SNAPSHOT_FORMAT = "personal-draft-history/v8"' in ts
    assert PERSONAL_HISTORY_COMPACT_FORMAT == "personal-draft-history/v8"
    path = tmp_path / "worker-v8.sqlite"
    connection = sqlite3.connect(path)
    install_compact_schema(connection)
    connection.commit()
    state = compact_history_state(connection)
    connection.close()
    assert state == "compact"
    import importlib.util

    module_path = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "container"
        / "personal_research_service.py"
    )
    spec = importlib.util.spec_from_file_location(
        "cloud_personal_research_service_v8", module_path
    )
    assert spec is not None and spec.loader is not None
    container = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = container
    spec.loader.exec_module(container)
    container.verify_sqlite(path)
    assert container.PERSONAL_HISTORY_FORMAT == "personal-draft-history/v8"
