"""Behavioral contract for the compact personal DRAFT history hydrator."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace
from typing import Mapping, Sequence

import pytest

from data_contracts.identity import canonical_json
from features import FUNDAMENTAL_RATIO_MODES, PitFundamentalRatio
from features.ratio_features import _FINS_ALIASES
from ingestion.jquants.normalize import normalize_generic
from ingestion.personal_history import (
    MASTER_AVAILABILITY_POLICY,
    PERSONAL_HISTORY_FORMAT,
    PERSONAL_HISTORY_SCOPE_DIGEST,
    PERSONAL_HISTORY_SCOPE_ID,
    PERSONAL_HISTORY_SCOPE_VERSION,
    PersonalHistoryError,
    PersonalHistoryHydrator,
    _PERSONAL_FINS_FEATURE_ALIASES,
    _compact_bars,
    _compact_calendar,
    _compact_fins,
    _compact_master,
    _estimated_fact_write_bytes,
    assert_personal_history_database,
    build_personal_history_plan,
)
from pit.api import get_equity_bars_daily, get_equity_master
from scripts.hydrate_personal_history import (
    DEFAULT_RPM,
    _effective_rpm,
    _parser,
    main as cli_main,
)
from storage.sqlite_store import SqliteStore


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class _Page:
    request_path: str
    request_params: MappingProxyType
    response_status: int
    response_body: bytes
    pagination_in: str | None = None
    pagination_out: str | None = None


@dataclass(frozen=True)
class _Fetch:
    rows: tuple[dict, ...]
    pages: tuple[_Page, ...]


class _HistoryClient:
    def __init__(
        self,
        *,
        fail_once: tuple[str, str] | None = None,
        omit_bar: tuple[str, str] | None = None,
    ) -> None:
        self.fail_once = fail_once
        self.omit_bar = omit_bar
        self.failed = False
        self.calls: Counter[tuple[str, str]] = Counter()

    @staticmethod
    def _calendar(start: str, end: str) -> list[dict]:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
        rows: list[dict] = []
        current = first
        while current <= last:
            rows.append(
                {
                    "Date": current.isoformat(),
                    "HolidayDivision": "1" if current.weekday() < 5 else "0",
                }
            )
            current += timedelta(days=1)
        return rows

    @staticmethod
    def _master(day: str) -> list[dict]:
        topix = ["1001", "1002"] if day < "2025-01-07" else ["1001", "1002", "1003"]
        return [
            {
                "Code": code,
                "Date": day,
                "Mkt": {"1001": "0111", "1002": "0112", "1003": "0113"}[code],
                "S17": "1",
                "S33": "0050" if code != "1003" else "1050",
                "ScaleCat": "TOPIX Core30" if code == "1001" else "TOPIX Small 1",
            }
            for code in topix
        ] + [
            {"Code": "9001", "Date": day, "Mkt": "0112", "ScaleCat": "-"}
        ]

    @staticmethod
    def _fins(code: str) -> list[dict]:
        disclosure = {
            "1001": ("2024-12-02", "09:00:00"),
            "1002": ("2025-01-03", None),
            "1003": ("2025-01-07", "09:00:00"),
        }.get(code)
        if disclosure is None:
            return []
        day, clock = disclosure
        return [
            {
                "Code": code,
                "DiscDate": day,
                "DiscTime": clock,
                "DiscNo": f"disc-{code}",
                "EarningsPerShare": 123.4,
                "Narrative": "must-not-be-kept",
            }
        ]

    def _bars(self, day: str) -> list[dict]:
        rows = []
        for ordinal, code in enumerate(("1001", "1002", "1003", "9001"), start=1):
            if self.omit_bar == (day, code):
                continue
            rows.append(
                {
                    "Code": code,
                    "Date": day,
                    "Close": 100 + ordinal,
                    "AdjustmentClose": 100 + ordinal,
                    "Volume": 1_000 * ordinal,
                    "AdjustmentVolume": 1_000 * ordinal,
                    "TurnoverValue": 1_000_000 * ordinal,
                    "MktCap": 10_000_000 * ordinal,
                    "MAdjC": 10 + ordinal,
                    "AAdjC": 20 + ordinal,
                    "MVa": 100 * ordinal,
                    "AVa": 200 * ordinal,
                    "MAdjVo": 10 * ordinal,
                    "AAdjVo": 20 * ordinal,
                    "Open": 90,
                    "CompanyName": "must-not-be-kept",
                }
            )
        return rows

    def fetch_dataset_evidenced(self, dataset: str, **params):
        identity = str(params.get("date") or params.get("code") or params.get("from"))
        key = (dataset, identity)
        self.calls[key] += 1
        if self.fail_once == key and not self.failed:
            self.failed = True
            raise OSError("injected transient failure")
        if dataset == "markets_calendar":
            rows = self._calendar(str(params["from"]), str(params["to"]))
        elif dataset == "equities_master":
            rows = self._master(str(params["date"]))
        elif dataset == "fins_summary":
            rows = self._fins(str(params["code"]))
        elif dataset == "equities_bars_daily":
            rows = self._bars(str(params["date"]))
        else:  # pragma: no cover - test catches an unexpected surface
            raise AssertionError(dataset)
        body = json.dumps({"data": rows}, separators=(",", ":")).encode()
        page = _Page(
            request_path=f"/v2/{dataset}",
            request_params=MappingProxyType(dict(params)),
            response_status=200,
            response_body=body,
        )
        return _Fetch(tuple(rows), (page,))


def _plan():
    return build_personal_history_plan(
        period_start="2025-01-06",
        period_end="2025-01-08",
        lookback_sessions=1,
        calendar_window_days=366,
        today=date(2025, 2, 1),
    )


def _rows(store: SqliteStore, dataset: str) -> list[dict]:
    return store.fetch_where(
        "jquants_records", "source='jquants' AND dataset=?", (dataset,)
    )


def test_compact_master_keeps_dated_factor_classifications() -> None:
    base = {
        "Code": "1001",
        "Date": "2025-01-06",
        "Mkt": "0111",
        "S17": "1",
        "S33": "0050",
        "ScaleCat": "TOPIX Core30",
    }
    first, first_digest = _compact_master(
        [base],
        snapshot_day="2025-01-06",
        ingested_at="2025-01-06T08:01:00+09:00",
    )
    payload = json.loads(first[0]["payload"])
    assert payload == {
        "Code": "1001",
        "Date": "2025-01-06",
        "MarketCode": "0111",
        "ScaleCategory": "TOPIX Core30",
        "SourceScaleCategory": "TOPIX Core30",
        "Sector17Code": "1",
        "Sector33Code": "0050",
    }

    _, changed_digest = _compact_master(
        [{**base, "S33": "1050"}],
        snapshot_day="2025-01-06",
        ingested_at="2025-01-06T08:01:00+09:00",
    )
    assert changed_digest != first_digest


@pytest.mark.parametrize(
    ("snapshot_day", "market_code"),
    (("2021-04-01", "0101"), ("2022-04-04", "0112")),
)
def test_compact_master_keeps_topix_members_outside_prime_market_code(
    snapshot_day: str, market_code: str
) -> None:
    rows, _digest = _compact_master(
        [
            {
                "Code": "1002",
                "Date": snapshot_day,
                "Mkt": market_code,
                "ScaleCat": "TOPIX Small 1",
            },
            {
                "Code": "9001",
                "Date": snapshot_day,
                "Mkt": "0112",
                "ScaleCat": "-",
            },
        ],
        snapshot_day=snapshot_day,
        ingested_at=f"{snapshot_day}T08:01:00+09:00",
    )

    assert len(rows) == 1
    payload = json.loads(rows[0]["payload"])
    assert payload["Code"] == "1002"
    assert payload["MarketCode"] == market_code
    assert payload["ScaleCategory"] == "TOPIX Small 1"


def _typed_bars(store: SqliteStore) -> list[dict]:
    return store.fetch_where(
        "jquants_daily_bars", "source='jquants'", ()
    )


def test_hydrator_pit_timing_compression_compaction_and_draft_boundary(tmp_path):
    db = tmp_path / "personal-history.sqlite"
    store = SqliteStore(db)
    client = _HistoryClient()
    summary = PersonalHistoryHydrator(
        client=client, store=store, plan=_plan()
    ).hydrate()

    assert summary.completeness_claim == "NONE"
    assert summary.controlled_live_eligibility == "FORBIDDEN"
    manifest = store._conn.execute(
        "SELECT * FROM personal_history_manifest"
    ).fetchone()
    assert manifest["status"] == "COMPLETE_DRAFT"
    assert manifest["master_availability_policy"] == MASTER_AVAILABILITY_POLICY
    assert manifest["master_revision_pit"] == 0
    assert manifest["history_scope_id"] == PERSONAL_HISTORY_SCOPE_ID
    assert manifest["history_scope_version"] == PERSONAL_HISTORY_SCOPE_VERSION
    assert manifest["history_scope_digest"] == PERSONAL_HISTORY_SCOPE_DIGEST

    calendar = _rows(store, "markets_calendar")
    assert calendar
    assert all(row["available_at"] == row["event_time"] for row in calendar)

    master = _rows(store, "equities_master")
    # First observed seed plus the one membership change; unchanged daily
    # snapshots are compressed away.
    snapshots = Counter(row["event_time"][:10] for row in master)
    assert snapshots == {"2025-01-02": 2, "2025-01-07": 3}
    assert all(row["raw_payload"] is None for row in master)
    assert all(
        row["available_at"] == f"{row['event_time'][:10]}T08:00:00+09:00"
        for row in master
    )

    before = get_equity_master(
        as_of="2025-01-02T07:59:59+09:00", db_path=db
    )
    at_open = get_equity_master(
        as_of="2025-01-02T08:00:00+09:00", db_path=db
    )
    at_close = get_equity_master(
        as_of="2025-01-02T15:00:00+09:00", db_path=db
    )
    assert before.rows == []
    assert {row["code"] for row in at_open.rows} == {"1001", "1002"}
    assert {row["code"] for row in at_close.rows} == {"1001", "1002"}
    by_code = {row["code"]: row for row in at_close.rows}
    assert by_code["1001"]["sector_33_code"] == "0050"
    assert by_code["1001"]["sector_17_code"] == "1"
    assert by_code["1001"]["scale_category"] == "TOPIX Core30"

    assert _rows(store, "equities_bars_daily") == []
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records_revisions "
        "WHERE dataset='equities_bars_daily'"
    ).fetchone()[0] == 0
    bars = _typed_bars(store)
    assert bars
    assert all(row["raw_payload"] is None for row in bars)
    for row in bars:
        assert row["open"] is None
        assert row["high"] is None
        assert row["low"] is None
        assert row["close"] is not None
        assert row["market_cap"] is not None
        ordinal = int(row["close"]) - 100
        assert row["morning_adjustment_close"] == float(10 + ordinal)
        assert row["afternoon_adjustment_close"] == float(20 + ordinal)
        assert row["morning_turnover_value"] == float(100 * ordinal)
        assert row["afternoon_turnover_value"] == float(200 * ordinal)
        assert row["morning_adjustment_volume"] == float(10 * ordinal)
        assert row["afternoon_adjustment_volume"] == float(20 * ordinal)
    pit_bars = get_equity_bars_daily(
        as_of="2025-01-08T15:30:00+09:00", db_path=db
    )
    assert len(pit_bars.rows) == len(bars)
    assert all(row["raw_payload"] is None for row in pit_bars.rows)
    assert all(row["raw_payload"] is None for row in _rows(store, "fins_summary"))
    for row in _rows(store, "fins_summary"):
        payload = json.loads(row["payload"])
        assert "Narrative" not in payload
        assert payload["Code"] in {"1001", "1002", "1003"}
        assert "DiscDate" in payload
        assert "DiscNo" in payload
        assert "EarningsPerShare" in payload
    missing_time = next(
        row
        for row in _rows(store, "fins_summary")
        if json.loads(row["payload"])["Code"] == "1002"
    )
    assert missing_time["available_at"] == "2025-01-04T00:00:00+09:00"
    assert "DiscTime" not in json.loads(missing_time["payload"])
    assert manifest["fins_availability_policy"].startswith(
        "explicit_disc_timestamp_else_next_calendar_day"
    )

    segment = store._conn.execute(
        "SELECT * FROM personal_history_segments "
        "WHERE dataset='equities_bars_daily' ORDER BY segment_id LIMIT 1"
    ).fetchone()
    evidence = json.loads(segment["page_evidence_json"])
    assert evidence[0]["row_count"] == 4
    assert evidence[0]["row_count"] == segment["rows_fetched"]
    assert len(evidence[0]["sha256"]) == 64
    assert segment["selection_evidence_json"] is None
    assert segment["completeness_claim"] == "NONE"
    assert segment["observed_ratio"] == 1.0
    assert str(segment["facts_digest"]).startswith("sha256:")

    for table in (
        "collection_receipts",
        "coverage_segments",
        "dataset_coverage",
        "ingestion_validation",
        "ingestion_watermarks",
        "local_snapshot_policy",
        "snapshot_publications",
    ):
        exists = store._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if exists:
            assert store._conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
    store.close()


def test_resume_is_idempotent_and_refetches_only_failed_segment(tmp_path):
    db = tmp_path / "resume.sqlite"
    store = SqliteStore(db)
    client = _HistoryClient(
        fail_once=("equities_bars_daily", "2025-01-06")
    )
    hydrator = PersonalHistoryHydrator(client=client, store=store, plan=_plan())

    with pytest.raises(PersonalHistoryError, match="injected transient failure"):
        hydrator.hydrate()
    failed = store._conn.execute(
        "SELECT state,attempts FROM personal_history_segments "
        "WHERE dataset='equities_bars_daily' AND segment_id='bars:2025-01-06'"
    ).fetchone()
    assert tuple(failed) == ("FAILED", 1)
    row_count_before = store.count("jquants_records")
    calls_before = Counter(client.calls)

    summary = hydrator.hydrate()
    assert summary.written_rows > 0
    retried = store._conn.execute(
        "SELECT state,attempts FROM personal_history_segments "
        "WHERE dataset='equities_bars_daily' AND segment_id='bars:2025-01-06'"
    ).fetchone()
    assert tuple(retried) == ("OBSERVED", 2)
    for key, count in calls_before.items():
        expected_increment = 1 if key == (
            "equities_bars_daily",
            "2025-01-06",
        ) else 0
        assert client.calls[key] == count + expected_increment
    row_count_after = store.count("jquants_records")
    typed_count_after = store.count("jquants_daily_bars")
    assert typed_count_after > 0
    assert _rows(store, "equities_bars_daily") == []

    calls_before_noop = Counter(client.calls)
    noop = hydrator.hydrate()
    assert noop.written_rows == 0
    assert noop.skipped_segments == sum(noop.segment_counts.values())
    assert client.calls == calls_before_noop
    assert store.count("jquants_records") == row_count_after
    assert store.count("jquants_daily_bars") == typed_count_after
    assert row_count_after + typed_count_after >= row_count_before
    store.close()


def test_older_compact_format_cannot_resume_without_refetch(tmp_path) -> None:
    store = SqliteStore(tmp_path / "old-format.sqlite")
    PersonalHistoryHydrator(client=_HistoryClient(), store=store, plan=_plan())
    assert store._conn.execute(
        "SELECT format FROM personal_history_manifest WHERE singleton=1"
    ).fetchone()[0] == PERSONAL_HISTORY_FORMAT
    for older in (
        "personal-draft-history/v1",
        "personal-draft-history/v3",
        "personal-draft-history/v4",
    ):
        store._conn.execute(
            "UPDATE personal_history_manifest SET format=? WHERE singleton=1",
            (older,),
        )
        store._conn.commit()

        with pytest.raises(PersonalHistoryError, match="older compact format"):
            PersonalHistoryHydrator(
                client=_HistoryClient(), store=store, plan=_plan()
            )

    store.close()


def test_typed_bar_materialization_is_atomic_and_idempotent(tmp_path):
    store = SqliteStore(tmp_path / "materialize.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    )
    rows = _compact_bars(
        [
            {
                "Code": "1001",
                "Date": "2025-01-06",
                "Close": 101,
                "AdjustmentClose": 102,
                "Volume": 1_000,
                "AdjustmentVolume": 900,
                "TurnoverValue": 100_000,
                "MAdjC": 51,
                "AAdjC": 61,
                "MVa": 10_000,
                "AVa": 20_000,
                "MAdjVo": 90,
                "AAdjVo": 110,
            }
        ],
        trading_day="2025-01-06",
        scope_union=frozenset({"1001"}),
        ingested_at="2025-01-06T16:00:00+09:00",
    )
    store.upsert("jquants_records", rows)
    store._conn.execute(
        "INSERT INTO personal_history_segments ("
        "dataset,segment_id,query_start,query_end,query_params,state,"
        "pit_policy,rows_fetched,rows_written) "
        "VALUES ('equities_bars_daily','bars:2025-01-06',"
        "'2025-01-06','2025-01-06','{}','OBSERVED',?,1,1)",
        ("canonical_session_close/v1",),
    )
    store._conn.execute(
        "CREATE TRIGGER reject_typed_bar BEFORE INSERT ON jquants_daily_bars "
        "BEGIN SELECT RAISE(ABORT, 'injected typed failure'); END"
    )
    store._conn.commit()

    with pytest.raises(PersonalHistoryError, match="injected typed failure"):
        hydrator._materialize_typed_bars()
    assert len(_rows(store, "equities_bars_daily")) == 1
    assert _typed_bars(store) == []

    store._conn.execute("DROP TRIGGER reject_typed_bar")
    store._conn.commit()
    assert hydrator._materialize_typed_bars() == 1
    assert _rows(store, "equities_bars_daily") == []
    bars = _typed_bars(store)
    assert len(bars) == 1
    assert bars[0]["close"] == 101.0
    assert bars[0]["adjustment_close"] == 102.0
    assert bars[0]["morning_adjustment_close"] == 51.0
    assert bars[0]["afternoon_adjustment_close"] == 61.0
    assert bars[0]["morning_turnover_value"] == 10_000.0
    assert bars[0]["afternoon_turnover_value"] == 20_000.0
    assert bars[0]["morning_adjustment_volume"] == 90.0
    assert bars[0]["afternoon_adjustment_volume"] == 110.0
    assert bars[0]["raw_payload"] is None
    assert hydrator._materialize_typed_bars() == 0
    assert _typed_bars(store) == bars

    store._conn.execute(
        "INSERT INTO jquants_daily_bars ("
        "source,code,date,event_time,available_at,ingested_at,close,raw_payload) "
        "VALUES ('jquants','9999','2025-01-07','2025-01-07T15:00:00+09:00',"
        "'2025-01-07T15:00:00+09:00','2025-01-07T16:00:00+09:00',99,NULL)"
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="completed checkpoints"):
        hydrator._validate_draft_boundary()
    store._conn.execute(
        "DELETE FROM jquants_daily_bars WHERE code='9999'"
    )
    store._conn.execute(
        "INSERT INTO jquants_daily_bars_revisions "
        "SELECT * FROM jquants_daily_bars WHERE code='1001'"
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="revisions are forbidden"):
        hydrator._validate_draft_boundary()
    store.close()


def test_session_columns_do_not_fall_back_to_full_day_adjustment(tmp_path):
    store = SqliteStore(tmp_path / "full-day-only.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    )
    rows = _compact_bars(
        [
            {
                "Code": "1001",
                "Date": "2025-01-06",
                "Close": 101,
                "AdjustmentClose": 102,
                "Volume": 1_000,
                "TurnoverValue": 100_000,
            }
        ],
        trading_day="2025-01-06",
        scope_union=frozenset({"1001"}),
        ingested_at="2025-01-06T16:00:00+09:00",
    )
    payload = json.loads(rows[0]["payload"])
    assert "MorningAdjustmentClose" not in payload
    assert "AfternoonAdjustmentClose" not in payload
    store.upsert("jquants_records", rows)
    store._conn.execute(
        "INSERT INTO personal_history_segments ("
        "dataset,segment_id,query_start,query_end,query_params,state,"
        "pit_policy,rows_fetched,rows_written) "
        "VALUES ('equities_bars_daily','bars:2025-01-06',"
        "'2025-01-06','2025-01-06','{}','OBSERVED',?,1,1)",
        ("canonical_session_close/v1",),
    )
    store._conn.commit()
    assert hydrator._materialize_typed_bars() == 1
    bars = _typed_bars(store)
    assert len(bars) == 1
    assert bars[0]["adjustment_close"] == 102.0
    assert bars[0]["morning_adjustment_close"] is None
    assert bars[0]["afternoon_adjustment_close"] is None
    assert bars[0]["morning_turnover_value"] is None
    assert bars[0]["afternoon_turnover_value"] is None
    assert bars[0]["morning_adjustment_volume"] is None
    assert bars[0]["afternoon_adjustment_volume"] is None
    store.close()


def test_typed_bar_materialization_rejects_partial_generic_mixture(tmp_path):
    store = SqliteStore(tmp_path / "partial-mixture.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    )
    rows = _compact_bars(
        [
            {"Code": "1001", "Date": "2025-01-06", "Close": 101},
            {"Code": "1002", "Date": "2025-01-06", "Close": 102},
        ],
        trading_day="2025-01-06",
        scope_union=frozenset({"1001", "1002"}),
        ingested_at="2025-01-06T16:00:00+09:00",
    )
    store.upsert("jquants_records", rows)
    store._conn.execute(
        "INSERT INTO personal_history_segments ("
        "dataset,segment_id,query_start,query_end,query_params,state,"
        "pit_policy,rows_fetched,rows_written) "
        "VALUES ('equities_bars_daily','bars:2025-01-06',"
        "'2025-01-06','2025-01-06','{}','OBSERVED',?,2,2)",
        ("canonical_session_close/v1",),
    )
    store._conn.commit()
    assert hydrator._materialize_typed_bars() == 2
    assert len(_typed_bars(store)) == 2

    store.upsert("jquants_records", rows[:1])
    with pytest.raises(PersonalHistoryError, match="generic bar count"):
        hydrator._materialize_typed_bars()
    assert len(_rows(store, "equities_bars_daily")) == 1
    assert len(_typed_bars(store)) == 2
    store.close()


def test_bar_breadth_failure_is_checkpointed_without_complete_claim(tmp_path):
    store = SqliteStore(tmp_path / "thin.sqlite")
    client = _HistoryClient(omit_bar=("2025-01-06", "1002"))
    with pytest.raises(PersonalHistoryError, match="observed ratio"):
        PersonalHistoryHydrator(client=client, store=store, plan=_plan()).hydrate()
    checkpoint = store._conn.execute(
        "SELECT state,completeness_claim FROM personal_history_segments "
        "WHERE segment_id='bars:2025-01-06'"
    ).fetchone()
    assert tuple(checkpoint) == ("FAILED", "NONE")
    manifest = store._conn.execute(
        "SELECT status,completeness_claim,last_error FROM personal_history_manifest"
    ).fetchone()
    assert manifest["status"] == "BUILDING"
    assert manifest["completeness_claim"] == "NONE"
    assert "observed ratio" in manifest["last_error"]
    store.close()


def test_null_close_is_dropped_and_breadth_guard_decides() -> None:
    codes = frozenset(f"{ordinal:04d}" for ordinal in range(200))
    rows = [
        {
            "Code": code,
            "Date": "2025-01-06",
            "Close": None if code == "0000" else 100,
        }
        for code in sorted(codes)
    ]
    normalized = _compact_bars(
        rows,
        trading_day="2025-01-06",
        scope_union=codes,
        ingested_at="2025-02-01T12:00:00+09:00",
    )
    assert len(normalized) == 199
    assert all(json.loads(row["payload"])["Code"] != "0000" for row in normalized)


def test_partial_calendar_window_is_not_silently_observed() -> None:
    with pytest.raises(PersonalHistoryError, match="does not match"):
        _compact_calendar(
            [{"Date": "2025-01-01", "HolidayDivision": "0"}],
            "2025-02-01T12:00:00+09:00",
            expected_start="2025-01-01",
            expected_end="2025-01-02",
        )


def test_managed_database_is_rejected_before_hydrator_writes(tmp_path):
    db = tmp_path / "managed.sqlite"
    store = SqliteStore(db)
    store._conn.execute("INSERT INTO local_snapshot_policy(singleton) VALUES (1)")
    store._conn.commit()
    store.close()

    with pytest.raises(PersonalHistoryError, match="managed/governed"):
        assert_personal_history_database(
            db, governed_default=tmp_path / "ingestion.sqlite"
        )


def test_free_space_guard_stops_before_fetch_or_observed_checkpoint(tmp_path):
    store = SqliteStore(tmp_path / "capacity.sqlite")
    client = _HistoryClient()
    hydrator = PersonalHistoryHydrator(
        client=client,
        store=store,
        plan=_plan(),
        minimum_free_bytes=10**18,
    )
    with pytest.raises(PersonalHistoryError, match="free-space guard"):
        hydrator.hydrate()
    assert client.calls == Counter()
    assert store._conn.execute(
        "SELECT COUNT(*) FROM personal_history_segments"
    ).fetchone()[0] == 0
    manifest = store._conn.execute(
        "SELECT status,completeness_claim FROM personal_history_manifest"
    ).fetchone()
    assert tuple(manifest) == ("BUILDING", "NONE")
    store.close()


def test_sqlite_hard_limit_and_final_wal_truncate_are_active(tmp_path):
    db = tmp_path / "bounded.sqlite"
    store = SqliteStore(db)
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(),
        store=store,
        plan=_plan(),
        wal_checkpoint_segments=1,
    )
    summary = hydrator.hydrate()
    page_size = store._conn.execute("PRAGMA page_size").fetchone()[0]
    max_pages = store._conn.execute("PRAGMA max_page_count").fetchone()[0]
    assert max_pages * page_size <= 5 * 1024**3
    assert Path(str(db) + "-wal").stat().st_size == 0
    footprint = sum(
        path.stat().st_size if path.exists() else 0
        for path in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm"))
    )
    assert summary.database_bytes == footprint
    store.close()


def test_dry_run_does_not_fetch_or_create_database(tmp_path, monkeypatch, capsys):
    db = tmp_path / "never-created.sqlite"

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run crossed the fetch/write boundary")

    monkeypatch.setattr(
        "scripts.hydrate_personal_history.make_jquants_http", forbidden
    )
    monkeypatch.setattr("scripts.hydrate_personal_history.SqliteStore", forbidden)
    assert cli_main(
        [
            "--from-date",
            "2025-01-01",
            "--to-date",
            "2025-01-31",
            "--db",
            str(db),
        ]
    ) == 0
    assert not db.exists()
    output = capsys.readouterr().out
    assert '"completeness_claim": "NONE"' in output
    assert '"requests_per_minute": 30.0' in output
    assert "dry-run complete" in output


def test_plan_rejects_future_reversed_and_excessive_lookback() -> None:
    with pytest.raises(PersonalHistoryError, match="future"):
        build_personal_history_plan(
            period_start="2025-01-01",
            period_end="2025-02-01",
            today=date(2025, 1, 31),
        )
    with pytest.raises(PersonalHistoryError, match="before"):
        build_personal_history_plan(
            period_start="2025-02-01",
            period_end="2025-01-01",
            today=date(2025, 2, 1),
        )
    with pytest.raises(PersonalHistoryError, match="lookback"):
        build_personal_history_plan(
            period_start="2025-01-01",
            period_end="2025-01-31",
            lookback_sessions=253,
            today=date(2025, 2, 1),
        )


def test_saved_proxy_rate_is_clamped_but_direct_rate_is_not() -> None:
    assert DEFAULT_RPM == 30.0
    help_text = " ".join(_parser().format_help().split())
    assert "default: conservative 30 rpm" in help_text
    assert _effective_rpm(DEFAULT_RPM, via_proxy=True) == 30
    assert _effective_rpm(DEFAULT_RPM, via_proxy=False) == 30
    assert _effective_rpm(120, via_proxy=True) == 60
    assert _effective_rpm(120, via_proxy=False) == 120


def test_personal_history_import_does_not_load_authority_modules() -> None:
    program = r'''
import sys
sys.path[:0] = sys.argv[1:]
import ingestion.personal_history
for name in (
    "ingestion.runtime_authority",
    "ingestion.pipeline_receipts",
    "research.readiness",
    "research.ready_manifest",
):
    if name in sys.modules:
        raise AssertionError(name)
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
    assert completed.returncode == 0, completed.stderr


_FINS_INGESTED = "2026-01-15T00:00:00+09:00"
_FINS_PERIOD_END = "2025-12-31"
_DROPPED_FINS_FIELDS = frozenset(
    {
        "CompanyName",
        "CoName",
        "CurrentFiscalYearStartDate",
        "NetAssets",
        "OperatingProfit",
        "Narrative",
    }
)
_RATIO_BARS = tuple(
    {
        "code": "8697",
        "date": day,
        "close": 100.0,
        "adjustment_close": 100.0,
        "volume": 1_000.0,
        "adjustment_volume": 1_000.0,
    }
    for day in ("2025-03-28", "2025-05-12")
)


def _fat_fins(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "Code": "8697",
        "DiscDate": "2025-05-02",
        "DisclosedDate": "2025-05-02",
        "DiscTime": "15:00:00",
        "DisclosedTime": "15:00:00",
        "DiscNo": "disc-1",
        "BPS": 80.0,
        "BookValuePerShare": 80.0,
        "EPS": 12.0,
        "EarningsPerShare": 12.0,
        "ROE": 0.11,
        "ReturnOnEquity": 0.11,
        "Sales": 130.0,
        "NetSales": 130.0,
        "NP": 20.0,
        "Profit": 20.0,
        "TA": 440.0,
        "TotalAssets": 440.0,
        "Eq": 200.0,
        "Equity": 200.0,
        "EqAR": 0.45,
        "EquityToAssetRatio": 0.45,
        "CurPerType": "1Q",
        "TypeOfCurrentPeriod": "1Q",
        "CurPerEn": "2025-03-31",
        "CurrentPeriodEndDate": "2025-03-31",
        "DocType": "1QFinancialStatements_Consolidated_JP",
        "TypeOfDocument": "1QFinancialStatements_Consolidated_JP",
        "CompanyName": "must-not-be-kept",
        "CoName": "must-not-be-kept",
        "CurrentFiscalYearStartDate": "2025-01-01",
        "NetAssets": 999.0,
        "OperatingProfit": 50.0,
    }
    body.update(overrides)
    return body


def _legacy_full_copy_fins(source: Mapping[str, object]) -> dict:
    disc_date = str(source.get("DiscDate") or source.get("DisclosedDate") or "")[:10]
    disc_time = str(source.get("DiscTime") or source.get("DisclosedTime") or "").strip()
    item = dict(source)
    item["Code"] = str(source.get("Code") or "").strip()
    item["DiscDate"] = disc_date
    item["DiscNo"] = str(source.get("DiscNo") or "").strip()
    if disc_time:
        item["DiscTime"] = disc_time
        available_at = f"{disc_date}T{disc_time}+09:00"
    else:
        item.pop("DiscTime", None)
        item.pop("DisclosedTime", None)
        available_at = (
            date.fromisoformat(disc_date) + timedelta(days=1)
        ).isoformat() + "T00:00:00+09:00"
    one = normalize_generic(
        [item],
        dataset="fins_summary",
        ingested_at=_FINS_INGESTED,
        available_at=available_at,
    )[0]
    one["raw_payload"] = None
    return one


def _compact_one(source: Mapping[str, object]) -> dict:
    rows = _compact_fins(
        [source],
        _FINS_INGESTED,
        expected_code=str(source["Code"]),
        period_end=_FINS_PERIOD_END,
    )
    assert len(rows) == 1
    return rows[0]


def _payload(row: Mapping[str, object]) -> dict:
    return json.loads(str(row["payload"]))


def _identity(row: Mapping[str, object]) -> tuple[object, object, object]:
    return row["natural_key"], row["available_at"], row["event_time"]


def _assert_stored_fractions(row: Mapping[str, object]) -> dict:
    raw = str(row["payload"])
    payload = _payload(row)
    assert '"EqAR":0.45' in raw
    assert '"ROE":0.11' in raw
    assert payload["EqAR"] == 0.45
    assert payload["ROE"] == 0.11
    return payload


def _ratio_from_stored(mode: str, stored: list[dict], bars: Sequence[dict]):
    fins = [
        {
            "payload": _payload(row),
            "event_time": row["event_time"],
            "available_at": row["available_at"],
            "natural_key": row["natural_key"],
        }
        for row in stored
    ]

    def _bars(**kwargs):
        rows = list(bars)
        start = kwargs.get("from_event")
        end = kwargs.get("to_event")
        if start:
            rows = [row for row in rows if str(row.get("date"))[:10] >= start]
        if end:
            rows = [row for row in rows if str(row.get("date"))[:10] <= end]
        if kwargs.get("latest_n") is not None:
            rows = rows[-int(kwargs["latest_n"]) :]
        return SimpleNamespace(rows=rows)

    return PitFundamentalRatio.compute(
        SimpleNamespace(
            get_input=lambda name, default=None: {
                "code": "8697",
                "mode": mode,
            }.get(name, default),
            get_equity_bars_daily=_bars,
            get_jquants_records=lambda **kwargs: SimpleNamespace(rows=list(fins)),
        )
    )


def test_compact_fins_keeps_research_surface_and_drops_source_bloat() -> None:
    kept = {key for aliases in _PERSONAL_FINS_FEATURE_ALIASES for key in aliases}
    kept.update({"Code", "DiscDate", "DiscTime", "DiscNo"})
    assert {key for aliases in _FINS_ALIASES.values() for key in aliases} <= kept

    entropy = "".join(f"{index:08x}" for index in range(25_000))
    source = _fat_fins(Narrative=entropy)
    compact = _compact_one(source)
    legacy = _legacy_full_copy_fins(source)
    payload = _assert_stored_fractions(compact)
    legacy_payload = _assert_stored_fractions(legacy)

    assert set(payload) == kept
    assert _DROPPED_FINS_FIELDS.isdisjoint(payload)
    assert compact["raw_payload"] is None
    assert _identity(compact) == _identity(legacy)
    assert compact["natural_key"] == canonical_json(
        {"Code": "8697", "DiscDate": "2025-05-02", "DiscNo": "disc-1"}
    )
    assert compact["available_at"] == "2025-05-02T15:00:00+09:00"
    assert {key: legacy_payload[key] for key in payload} == payload
    assert "Narrative" in legacy_payload
    compact_estimate = _estimated_fact_write_bytes([compact])
    assert compact_estimate == _estimated_fact_write_bytes([_compact_one(_fat_fins())])
    assert compact_estimate < len(entropy) < _estimated_fact_write_bytes([legacy])
    assert compact_estimate * 8 < _estimated_fact_write_bytes([legacy])

    missing_time = _fat_fins()
    del missing_time["DiscTime"]
    del missing_time["DisclosedTime"]
    compact_missing = _compact_one(missing_time)
    missing_payload = _payload(compact_missing)
    assert _identity(compact_missing) == _identity(_legacy_full_copy_fins(missing_time))
    assert compact_missing["available_at"] == "2025-05-03T00:00:00+09:00"
    assert "DiscTime" not in missing_payload
    assert "DisclosedTime" not in missing_payload
    _assert_stored_fractions(compact_missing)

    v1_only = {
        "Code": "8697",
        "DisclosedDate": "2025-02-01",
        "DisclosedTime": "09:00:00",
        "DiscNo": "n1",
        "BookValuePerShare": 80.0,
        "EarningsPerShare": 12.0,
        "ReturnOnEquity": 0.11,
        "NetSales": 200.0,
        "Profit": 20.0,
        "TotalAssets": 400.0,
        "Equity": 180.0,
        "EquityToAssetRatio": 0.45,
        "TypeOfCurrentPeriod": "FY",
        "CurrentPeriodEndDate": "2024-12-31",
        "TypeOfDocument": "FYFinancialStatements_Consolidated_JP",
        "CompanyName": "drop-me",
    }
    v1_payload = _payload(_compact_one(v1_only))
    assert v1_payload["DiscDate"] == "2025-02-01"
    assert v1_payload["DiscTime"] == "09:00:00"
    assert v1_payload["BookValuePerShare"] == 80.0
    assert v1_payload["EquityToAssetRatio"] == 0.45
    assert v1_payload["ReturnOnEquity"] == 0.11
    assert "BPS" not in v1_payload
    assert v1_payload["NetSales"] == 200.0
    assert "CompanyName" not in v1_payload


def test_fundamental_ratio_modes_match_compact_and_full_copy_stored_rows() -> None:
    prior = _fat_fins(
        DiscDate="2024-05-01",
        DisclosedDate="2024-05-01",
        DiscNo="disc-0",
        Sales=100.0,
        NetSales=100.0,
        TA=400.0,
        TotalAssets=400.0,
        CurPerEn="2024-03-31",
        CurrentPeriodEndDate="2024-03-31",
    )
    current = _fat_fins()
    compact_rows = [_compact_one(source) for source in (prior, current)]
    legacy_rows = [_legacy_full_copy_fins(source) for source in (prior, current)]
    _assert_stored_fractions(compact_rows[-1])
    _assert_stored_fractions(legacy_rows[-1])
    for mode in sorted(FUNDAMENTAL_RATIO_MODES):
        compact = _ratio_from_stored(mode, compact_rows, _RATIO_BARS)
        legacy = _ratio_from_stored(mode, legacy_rows, _RATIO_BARS)
        assert compact.value == legacy.value, mode
        assert compact.value is not None, mode
        assert compact.metadata["statement_available_at"] == legacy.metadata[
            "statement_available_at"
        ]
