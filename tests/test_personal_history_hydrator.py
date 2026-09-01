"""Behavioral contract for the compact personal DRAFT history hydrator."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
import json
import math
from pathlib import Path
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace
from typing import Mapping, Sequence

import pytest

from data_contracts.identity import canonical_json, session_close_jst
from data_contracts.personal_history_compact import (
    DEFAULT_DAILY_MIN_OBSERVED_BAR_RATIO,
    DEFAULT_TINY_MISSING_OBSERVED_BARS,
    PERSONAL_HISTORY_COMPACT_BARS_COLUMNS,
    PERSONAL_HISTORY_COMPACT_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS,
)
from data_contracts.source_capability import source_capability_contract_for
from features import FUNDAMENTAL_RATIO_MODES, PitFundamentalRatio
from features.ratio_features import _FINS_ALIASES
from ingestion.jquants.normalize import normalize_generic
from ingestion.personal_history import (
    DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW,
    DEFAULT_GENERIC_JSON_STORAGE_BYTES_PER_ROW,
    DEFAULT_MAX_DATABASE_BYTES,
    DEFAULT_MIN_OBSERVED_BAR_RATIO,
    DEFAULT_TOPIX_CODE_ESTIMATE,
    MASTER_AVAILABILITY_POLICY,
    PERSONAL_HISTORY_FORMAT,
    PERSONAL_HISTORY_SCOPE_DIGEST,
    PERSONAL_HISTORY_SCOPE_ID,
    PERSONAL_HISTORY_SCOPE_VERSION,
    PersonalHistoryError,
    PersonalHistoryHydrator,
    personal_snapshot_data_floor,
    _PERSONAL_FINS_FEATURE_ALIASES,
    _allowed_missing_observed_bars,
    _compact_bars,
    _compact_calendar,
    _compact_fins,
    _compact_master,
    _estimated_fact_write_bytes,
    assert_personal_history_database,
    build_personal_history_plan,
)
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
        omit_bars: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        self.fail_once = fail_once
        self.omit_bars = omit_bars
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
            if (day, code) in self.omit_bars:
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


def _compact_master_rows(store: SqliteStore) -> list[dict]:
    return [
        dict(row)
        for row in store._conn.execute(
            "SELECT * FROM personal_history_compact_master "
            "ORDER BY snapshot_date,code"
        )
    ]


def _compact_bar_rows(store: SqliteStore) -> list[dict]:
    return [
        dict(row)
        for row in store._conn.execute(
            "SELECT * FROM personal_history_compact_bars ORDER BY date,code"
        )
    ]


def _without_rowid_sql(store: SqliteStore, table: str) -> str:
    return str(
        store._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
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
    assert summary.actual_lookback_sessions == 1
    assert summary.lookback_truncated is False
    assert summary.bar_start == "2025-01-03"
    assert summary.period_start == "2025-01-06"
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

    assert _rows(store, "equities_master") == []
    master = _compact_master_rows(store)
    # First observed seed plus the one membership change; unchanged daily
    # snapshots are compressed away.
    snapshots = Counter(row["snapshot_date"] for row in master)
    assert snapshots == {"2025-01-02": 2, "2025-01-07": 3}
    assert all(
        row["event_time"][:10] == row["snapshot_date"]
        and row["available_at"] == f"{row['snapshot_date']}T08:00:00+09:00"
        and row["ingested_at"] >= row["available_at"]
        for row in master
    )
    seed = {
        row["code"]: row
        for row in master
        if row["snapshot_date"] == "2025-01-02"
    }
    assert set(seed) == {"1001", "1002"}
    assert seed["1001"]["sector_33_code"] == "0050"
    assert seed["1001"]["sector_17_code"] == "1"
    assert seed["1001"]["scale_category"] == "TOPIX Core30"
    assert seed["1001"]["market_code"] == "0111"
    assert seed["1001"]["source_scale_category"] == "TOPIX Core30"

    assert _rows(store, "equities_bars_daily") == []
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_records_revisions "
        "WHERE dataset='equities_bars_daily'"
    ).fetchone()[0] == 0
    assert store._conn.execute(
        "SELECT COUNT(*) FROM jquants_daily_bars"
    ).fetchone()[0] == 0
    bars = _compact_bar_rows(store)
    assert bars
    for row in bars:
        close = session_close_jst(row["date"])
        assert row["event_time"] == close
        assert row["available_at"] == close
        assert row["ingested_at"] >= close
        assert row["close"] is not None
        assert row["market_cap"] is not None
        ordinal = int(row["close"]) - 100
        assert row["morning_adjustment_close"] == float(10 + ordinal)
        assert row["afternoon_adjustment_close"] == float(20 + ordinal)
        assert row["morning_turnover_value"] == float(100 * ordinal)
        assert row["afternoon_turnover_value"] == float(200 * ordinal)
        assert row["morning_adjustment_volume"] == float(10 * ordinal)
        assert row["afternoon_adjustment_volume"] == float(20 * ordinal)
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
    compact_count_after = len(_compact_bar_rows(store))
    assert compact_count_after > 0
    assert _rows(store, "equities_bars_daily") == []
    assert store.count("jquants_daily_bars") == 0

    calls_before_noop = Counter(client.calls)
    noop = hydrator.hydrate()
    assert noop.written_rows == 0
    assert noop.skipped_segments == sum(noop.segment_counts.values())
    assert client.calls == calls_before_noop
    assert store.count("jquants_records") == row_count_after
    assert len(_compact_bar_rows(store)) == compact_count_after
    assert row_count_after + compact_count_after >= row_count_before
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
        "personal-draft-history/v5",
        "personal-draft-history/v6",
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


def test_compact_tables_are_without_rowid_and_keyed(tmp_path):
    store = SqliteStore(tmp_path / "ddl.sqlite")
    PersonalHistoryHydrator(client=_HistoryClient(), store=store, plan=_plan())
    master_sql = _without_rowid_sql(store, "personal_history_compact_master")
    bars_sql = _without_rowid_sql(store, "personal_history_compact_bars")
    assert "WITHOUT ROWID" in master_sql.upper()
    assert "WITHOUT ROWID" in bars_sql.upper()
    assert "PRIMARY KEY (snapshot_date, code)" in " ".join(master_sql.split())
    assert "PRIMARY KEY (code, date)" in " ".join(bars_sql.split())
    master_cols = {
        row[1]
        for row in store._conn.execute(
            "PRAGMA table_info(personal_history_compact_master)"
        )
    }
    bar_cols = {
        row[1]
        for row in store._conn.execute(
            "PRAGMA table_info(personal_history_compact_bars)"
        )
    }
    assert set(PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS) <= master_cols
    assert set(PERSONAL_HISTORY_COMPACT_BARS_COLUMNS) <= bar_cols
    store.close()


def _personal_history_manifest_format(store: SqliteStore) -> str | None:
    exists = store._conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='personal_history_manifest'"
    ).fetchone()
    if exists is None:
        return None
    row = store._conn.execute(
        "SELECT format FROM personal_history_manifest WHERE singleton=1"
    ).fetchone()
    return None if row is None else str(row[0])


@pytest.mark.parametrize(
    "ddl",
    (
        """
        CREATE TABLE personal_history_compact_bars (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            available_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            close INTEGER NOT NULL,
            volume REAL,
            turnover_value REAL,
            adjustment_close REAL,
            adjustment_volume REAL,
            morning_adjustment_close REAL,
            afternoon_adjustment_close REAL,
            morning_turnover_value REAL,
            afternoon_turnover_value REAL,
            morning_adjustment_volume REAL,
            afternoon_adjustment_volume REAL,
            market_cap REAL,
            PRIMARY KEY (code, date)
        ) WITHOUT ROWID
        """,
        """
        CREATE TABLE personal_history_compact_master (
            snapshot_date TEXT,
            code TEXT,
            event_time TEXT NOT NULL,
            available_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            market_code TEXT,
            sector_17_code TEXT,
            sector_33_code TEXT,
            scale_category TEXT,
            source_scale_category TEXT,
            PRIMARY KEY (snapshot_date, code)
        )
        """,
        """
        CREATE TABLE personal_history_compact_bars (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            available_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            close REAL,
            volume REAL,
            turnover_value REAL,
            adjustment_close REAL,
            adjustment_volume REAL,
            morning_adjustment_close REAL,
            afternoon_adjustment_close REAL,
            morning_turnover_value REAL,
            afternoon_turnover_value REAL,
            morning_adjustment_volume REAL,
            afternoon_adjustment_volume REAL,
            market_cap REAL,
            PRIMARY KEY (code, date)
        ) WITHOUT ROWID
        """,
        """
        CREATE TABLE personal_history_compact_master (
            snapshot_date TEXT NOT NULL,
            code TEXT NOT NULL,
            event_time TEXT NOT NULL,
            available_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            market_code TEXT,
            sector_17_code TEXT,
            sector_33_code TEXT,
            scale_category TEXT,
            source_scale_category TEXT,
            PRIMARY KEY (code, snapshot_date)
        ) WITHOUT ROWID
        """,
        """
        CREATE TABLE personal_history_compact_master (
            snapshot_date TEXT NOT NULL,
            code TEXT NOT NULL,
            event_time TEXT NOT NULL,
            available_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            market_code TEXT,
            sector_17_code TEXT,
            sector_33_code TEXT,
            scale_category TEXT,
            source_scale_category TEXT
        )
        """,
        """
        CREATE TABLE personal_history_compact_master (
            snapshot_date TEXT NOT NULL,
            code TEXT NOT NULL,
            event_time TEXT NOT NULL,
            available_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            market_code TEXT,
            sector_17_code TEXT,
            sector_33_code TEXT,
            scale_category TEXT,
            source_scale_category TEXT,
            PRIMARY KEY (snapshot_date, code)
        )
        """,
    ),
    ids=(
        "wrong-type",
        "nullable-pk",
        "nullable-non-null-field",
        "wrong-pk-order",
        "missing-pk",
        "ordinary-rowid",
    ),
)
def test_lookalike_compact_tables_do_not_stamp_v7_manifest(tmp_path, ddl):
    store = SqliteStore(tmp_path / "lookalike.sqlite")
    store._conn.execute(ddl)
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="builder DDL"):
        PersonalHistoryHydrator(
            client=_HistoryClient(), store=store, plan=_plan()
        )
    assert _personal_history_manifest_format(store) is None
    store.close()


def test_preexisting_builder_compact_ddl_stamps_v7_manifest(tmp_path):
    store = SqliteStore(tmp_path / "real-ddl.sqlite")
    for _table, create_sql in PERSONAL_HISTORY_COMPACT_CREATE_SQL:
        store._conn.execute(create_sql)
    store._conn.commit()
    PersonalHistoryHydrator(client=_HistoryClient(), store=store, plan=_plan())
    assert _personal_history_manifest_format(store) == PERSONAL_HISTORY_FORMAT
    store.close()


def test_direct_compact_write_is_atomic_with_checkpoint_counts(tmp_path):
    store = SqliteStore(tmp_path / "direct-write.sqlite")
    summary = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    ).hydrate()
    assert _rows(store, "equities_master") == []
    assert _rows(store, "equities_bars_daily") == []
    expected_master = int(
        store._conn.execute(
            "SELECT COALESCE(SUM(rows_written),0) FROM personal_history_segments "
            "WHERE dataset='equities_master' "
            "AND state IN ('OBSERVED','OBSERVED_EMPTY')"
        ).fetchone()[0]
    )
    expected_bars = int(
        store._conn.execute(
            "SELECT COALESCE(SUM(rows_written),0) FROM personal_history_segments "
            "WHERE dataset='equities_bars_daily' "
            "AND state IN ('OBSERVED','OBSERVED_EMPTY')"
        ).fetchone()[0]
    )
    master = _compact_master_rows(store)
    bars = _compact_bar_rows(store)
    assert len(master) == expected_master == 5
    assert len(bars) == expected_bars
    assert expected_bars > 0
    assert summary.written_rows == expected_master + expected_bars + sum(
        int(row["rows_written"])
        for row in store._conn.execute(
            "SELECT rows_written FROM personal_history_segments "
            "WHERE dataset IN ('markets_calendar','fins_summary') "
            "AND state IN ('OBSERVED','OBSERVED_EMPTY')"
        )
    )
    first_bar = next(
        row
        for row in bars
        if row["date"] == "2025-01-06" and row["code"] == "1001"
    )
    assert first_bar["close"] == 101.0
    assert first_bar["morning_adjustment_close"] == 11.0
    store.close()


def test_failed_compact_insert_rolls_back_and_checkpoints_failed(tmp_path):
    store = SqliteStore(tmp_path / "fail-insert.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    )
    store._conn.execute(
        "CREATE TRIGGER reject_compact_bar BEFORE INSERT ON "
        "personal_history_compact_bars "
        "BEGIN SELECT RAISE(ABORT, 'injected compact failure'); END"
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="injected compact failure"):
        hydrator.hydrate()
    assert _compact_bar_rows(store) == []
    assert _rows(store, "equities_bars_daily") == []
    failed = store._conn.execute(
        "SELECT state FROM personal_history_segments "
        "WHERE dataset='equities_bars_daily' AND state='FAILED'"
    ).fetchone()
    assert failed is not None
    assert failed[0] == "FAILED"
    store.close()


def test_resume_does_not_duplicate_compact_rows_on_pk_conflict(tmp_path):
    store = SqliteStore(tmp_path / "pk-conflict.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    )
    hydrator.hydrate()
    before_bars = _compact_bar_rows(store)
    before_master = _compact_master_rows(store)
    store._conn.execute(
        "UPDATE personal_history_segments SET state='FAILED' "
        "WHERE dataset='equities_bars_daily' AND segment_id='bars:2025-01-06'"
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="UNIQUE constraint"):
        hydrator.hydrate()
    assert _compact_bar_rows(store) == before_bars
    assert _compact_master_rows(store) == before_master
    failed = store._conn.execute(
        "SELECT state FROM personal_history_segments "
        "WHERE dataset='equities_bars_daily' AND segment_id='bars:2025-01-06'"
    ).fetchone()
    assert failed[0] == "FAILED"
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
    written = hydrator._insert_compact_facts("equities_bars_daily", rows)
    hydrator._connection.commit()
    assert written == 1
    bars = _compact_bar_rows(store)
    assert len(bars) == 1
    assert bars[0]["adjustment_close"] == 102.0
    assert bars[0]["morning_adjustment_close"] is None
    assert bars[0]["afternoon_adjustment_close"] is None
    assert bars[0]["morning_turnover_value"] is None
    assert bars[0]["afternoon_turnover_value"] is None
    assert bars[0]["morning_adjustment_volume"] is None
    assert bars[0]["afternoon_adjustment_volume"] is None
    store.close()


def _membership_change_planning_allowance(estimated_sessions: int) -> int:
    return min(
        estimated_sessions + 1,
        max(24, math.ceil((estimated_sessions + 1) / 2)),
    )


def _expected_plan_bytes(plan) -> int:
    sessions = plan.estimated_trading_sessions
    change_days = _membership_change_planning_allowance(sessions)
    effective_start = max(
        date.fromisoformat(plan.period_start),
        date.fromisoformat(personal_snapshot_data_floor()),
    )
    generic_json_rows = (
        (date.fromisoformat(plan.period_end) - effective_start).days + 1
    ) * 100
    bar_rows = sessions * DEFAULT_TOPIX_CODE_ESTIMATE
    master_rows = DEFAULT_TOPIX_CODE_ESTIMATE * change_days
    assert plan.estimated_structured_rows == bar_rows + master_rows + generic_json_rows
    return (
        (bar_rows + master_rows) * DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW
        + generic_json_rows * DEFAULT_GENERIC_JSON_STORAGE_BYTES_PER_ROW
    )


def test_plan_membership_change_allowance_is_period_dependent() -> None:
    short = build_personal_history_plan(
        period_start="2025-01-06",
        period_end="2025-01-10",
        lookback_sessions=0,
        today=date(2025, 2, 1),
    )
    long = build_personal_history_plan(
        period_start="2008-01-01",
        period_end="2026-08-31",
        lookback_sessions=252,
        today=date(2026, 8, 31),
    )
    assert short.period_start == "2025-01-06"
    assert short.period_start > personal_snapshot_data_floor()
    assert short.estimated_trading_sessions == 5
    assert _membership_change_planning_allowance(5) == 6
    assert short.estimated_bytes == _expected_plan_bytes(short)
    assert _membership_change_planning_allowance(
        long.estimated_trading_sessions
    ) == math.ceil((long.estimated_trading_sessions + 1) / 2)
    assert long.estimated_bytes == _expected_plan_bytes(long)
    constant_master_bytes = (
        DEFAULT_TOPIX_CODE_ESTIMATE * 24 * DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW
    )
    assert long.estimated_bytes > constant_master_bytes


def test_plan_admits_2008_2026_under_five_gib() -> None:
    plan = build_personal_history_plan(
        period_start="2008-01-01",
        period_end="2026-08-31",
        lookback_sessions=252,
        today=date(2026, 8, 31),
    )
    effective_start = max(
        date.fromisoformat(plan.period_start),
        date.fromisoformat(personal_snapshot_data_floor()),
    )
    generic_json_rows = (
        date.fromisoformat(plan.period_end) - effective_start
    ).days + 1
    generic_json_rows *= 100
    compact_rows = plan.estimated_structured_rows - generic_json_rows
    assert plan.estimated_bytes == (
        compact_rows * DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW
        + generic_json_rows * DEFAULT_GENERIC_JSON_STORAGE_BYTES_PER_ROW
    )
    assert plan.estimated_trading_sessions == 4736
    assert plan.estimated_bytes == _expected_plan_bytes(plan)
    assert plan.estimated_bytes < DEFAULT_MAX_DATABASE_BYTES
    assert DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW == 256
    assert DEFAULT_GENERIC_JSON_STORAGE_BYTES_PER_ROW == 1024


def test_bar_breadth_failure_is_checkpointed_without_complete_claim(tmp_path):
    store = SqliteStore(tmp_path / "thin.sqlite")
    # 2025-01-07 has three expected TOPIX codes; two missing exceeds the
    # small-universe absolute tolerance of one.
    client = _HistoryClient(
        omit_bars=frozenset(
            {("2025-01-07", "1001"), ("2025-01-07", "1002")}
        )
    )
    with pytest.raises(PersonalHistoryError, match="observed ratio"):
        PersonalHistoryHydrator(client=client, store=store, plan=_plan()).hydrate()
    checkpoint = store._conn.execute(
        "SELECT state,completeness_claim FROM personal_history_segments "
        "WHERE segment_id='bars:2025-01-07'"
    ).fetchone()
    assert tuple(checkpoint) == ("FAILED", "NONE")
    manifest = store._conn.execute(
        "SELECT status,completeness_claim,last_error FROM personal_history_manifest"
    ).fetchone()
    assert manifest["status"] == "BUILDING"
    assert manifest["completeness_claim"] == "NONE"
    assert "observed ratio" in manifest["last_error"]
    assert "allowed-missing" in manifest["last_error"]
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


def test_compact_bars_tolerate_one_missing_code_without_imputing() -> None:
    trading_day = "2025-01-06"
    observed = ("1001", "1002", "1003", "1004", "1005")
    omitted = "1006"
    rows = _compact_bars(
        [
            {"Code": code, "Date": trading_day, "Close": 100 + index}
            for index, code in enumerate(observed, start=1)
        ],
        trading_day=trading_day,
        scope_union=frozenset({*observed, omitted}),
        ingested_at="2025-01-06T16:00:00+09:00",
    )
    payloads = [json.loads(row["payload"]) for row in rows]
    assert [item["Code"] for item in payloads] == list(observed)
    assert [item["Close"] for item in payloads] == [101, 102, 103, 104, 105]
    assert all(item["Code"] != omitted for item in payloads)
    assert len(payloads) == 5


def test_compact_bars_reject_two_missing_codes_in_small_universe() -> None:
    trading_day = "2025-01-06"
    observed = ("1001", "1002", "1003", "1004")
    scope = frozenset({*observed, "1005", "1006"})
    with pytest.raises(
        PersonalHistoryError,
        match=r"observed ratio 4/6 is below 0\.995000 \(missing 2, allowed-missing 1\)",
    ):
        _compact_bars(
            [
                {"Code": code, "Date": trading_day, "Close": 100}
                for code in observed
            ],
            trading_day=trading_day,
            scope_union=scope,
            ingested_at="2025-01-06T16:00:00+09:00",
        )


def test_compact_bars_reject_broad_universe_below_daily_floor() -> None:
    trading_day = "2025-01-06"
    codes = [f"{ordinal:04d}" for ordinal in range(400)]
    with pytest.raises(
        PersonalHistoryError,
        match=r"observed ratio 395/400 is below 0\.995000 \(missing 5, allowed-missing 4\)",
    ):
        _compact_bars(
            [
                {"Code": code, "Date": trading_day, "Close": 100}
                for code in codes[5:]
            ],
            trading_day=trading_day,
            scope_union=frozenset(codes),
            ingested_at="2025-01-06T16:00:00+09:00",
        )


def test_compact_bars_minimum_ratio_one_is_strict() -> None:
    trading_day = "2025-01-06"
    with pytest.raises(
        PersonalHistoryError,
        match=r"observed ratio 5/6 is below 1\.000000 \(missing 1, allowed-missing 0\)",
    ):
        _compact_bars(
            [
                {"Code": code, "Date": trading_day, "Close": 100}
                for code in ("1001", "1002", "1003", "1004", "1005")
            ],
            trading_day=trading_day,
            scope_union=frozenset(
                {"1001", "1002", "1003", "1004", "1005", "1006"}
            ),
            ingested_at="2025-01-06T16:00:00+09:00",
            minimum_ratio=1.0,
        )


def test_allowed_missing_bars_uses_daily_floor_not_absolute_two() -> None:
    assert DEFAULT_TINY_MISSING_OBSERVED_BARS == 1
    assert DEFAULT_DAILY_MIN_OBSERVED_BAR_RATIO == 0.99
    assert DEFAULT_MIN_OBSERVED_BAR_RATIO == 0.995
    ratio = DEFAULT_MIN_OBSERVED_BAR_RATIO
    assert _allowed_missing_observed_bars(357, ratio) == 3
    assert _allowed_missing_observed_bars(6, ratio) == 1
    assert _allowed_missing_observed_bars(199, ratio) == 1
    assert _allowed_missing_observed_bars(200, ratio) == 2
    assert _allowed_missing_observed_bars(400, ratio) == 4
    assert _allowed_missing_observed_bars(600, ratio) == 6
    assert _allowed_missing_observed_bars(1113, ratio) == 11
    assert _allowed_missing_observed_bars(357, 1.0) == 0
    assert _allowed_missing_observed_bars(1113, 1.0) == 0


def _compact_observed_subset(
    *,
    expected: int,
    omit: int,
    trading_day: str = "2008-07-30",
) -> tuple[list[str], list[dict]]:
    codes = [f"{ordinal:04d}" for ordinal in range(expected)]
    observed = codes[omit:]
    rows = _compact_bars(
        [
            {"Code": code, "Date": trading_day, "Close": 100}
            for code in observed
        ],
        trading_day=trading_day,
        scope_union=frozenset(codes),
        ingested_at=f"{trading_day}T16:00:00+09:00",
    )
    return observed, rows


def test_compact_bars_tolerate_two_missing_codes_at_355_of_357() -> None:
    observed, rows = _compact_observed_subset(expected=357, omit=2)
    payloads = [json.loads(row["payload"]) for row in rows]
    omitted = {f"{ordinal:04d}" for ordinal in range(2)}
    assert [item["Code"] for item in payloads] == observed
    assert all(item["Code"] not in omitted for item in payloads)
    assert len(payloads) == 355


def test_compact_bars_tolerate_three_missing_codes_at_354_of_357() -> None:
    observed, rows = _compact_observed_subset(expected=357, omit=3)
    payloads = [json.loads(row["payload"]) for row in rows]
    assert [item["Code"] for item in payloads] == observed
    assert len(payloads) == 354


def test_compact_bars_reject_four_missing_codes_at_353_of_357() -> None:
    with pytest.raises(
        PersonalHistoryError,
        match=r"observed ratio 353/357 is below 0\.995000 \(missing 4, allowed-missing 3\)",
    ):
        _compact_observed_subset(expected=357, omit=4)


def test_compact_bars_tolerate_1105_of_1113_without_imputing() -> None:
    observed, rows = _compact_observed_subset(
        expected=1113, omit=8, trading_day="2008-08-08"
    )
    payloads = [json.loads(row["payload"]) for row in rows]
    omitted = {f"{ordinal:04d}" for ordinal in range(8)}
    assert [item["Code"] for item in payloads] == observed
    assert all(item["Code"] not in omitted for item in payloads)
    assert len(payloads) == 1105


def _one_bar(**overrides: object) -> dict:
    body: dict[str, object] = {
        "Code": "1001",
        "Date": "2025-01-06",
        "Close": 101,
    }
    body.update(overrides)
    return body


def _compact_one_bar(
    source: Mapping[str, object], *, ingested_at: str | None = None
) -> dict:
    day = str(source["Date"])
    rows = _compact_bars(
        [source],
        trading_day=day,
        scope_union=frozenset({str(source["Code"])}),
        ingested_at=ingested_at or f"{day}T16:00:00+09:00",
    )
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("Close", "garbage", "finite"),
        ("Volume", {"nested": 1}, "finite"),
        ("Close", True, "finite"),
        ("Volume", False, "finite"),
        ("AdjustmentClose", True, "finite"),
        ("Close", float("nan"), "finite"),
        ("AdjustmentClose", float("nan"), "finite"),
        ("Volume", float("nan"), "finite"),
        ("Close", float("inf"), "finite"),
        ("Close", float("-inf"), "finite"),
        ("TurnoverValue", float("inf"), "finite"),
        ("Close", "NaN", "finite"),
        ("Close", "Infinity", "finite"),
        ("Close", "-Infinity", "finite"),
        ("Close", "1e999", "finite"),
        ("MarketCapitalization", "1e999", "finite"),
        ("Volume", "1e999", "finite"),
        ("Close", 0, "strictly positive"),
        ("Close", -1, "strictly positive"),
        ("AdjustmentClose", 0, "strictly positive"),
        ("MorningAdjustmentClose", -0.01, "strictly positive"),
        ("AfternoonAdjustmentClose", 0, "strictly positive"),
        ("AdjustmentFactor", 0, "strictly positive"),
        ("AdjustmentFactor", -1, "strictly positive"),
        ("Volume", -1, "non-negative"),
        ("AdjustmentVolume", -1, "non-negative"),
        ("MorningAdjustmentVolume", -0.1, "non-negative"),
        ("AfternoonAdjustmentVolume", -1, "non-negative"),
        ("TurnoverValue", -0.01, "non-negative"),
        ("MorningTurnoverValue", -1, "non-negative"),
        ("AfternoonTurnoverValue", -1, "non-negative"),
        ("MarketCapitalization", -1, "non-negative"),
    ),
)
def test_compact_bars_reject_invalid_numeric_source(
    field: str, value: object, match: str
) -> None:
    with pytest.raises(PersonalHistoryError, match=match):
        _compact_one_bar(_one_bar(**{field: value}))


def test_compact_bars_preserve_original_numeric_values_and_convert_strings() -> None:
    payload = json.loads(
        _compact_one_bar(
            _one_bar(
                Close=101,
                AdjustmentClose=101.25,
                Volume=0,
                TurnoverValue="1500",
                MarketCapitalization="1.5e6",
                AdjustmentFactor="1",
            )
        )["payload"]
    )
    assert payload["Close"] == 101
    assert payload["AdjustmentClose"] == 101.25
    assert payload["Volume"] == 0
    assert payload["TurnoverValue"] == 1500
    assert payload["MarketCapitalization"] == 1_500_000.0
    assert payload["AdjustmentFactor"] == 1


@pytest.mark.parametrize(
    "trading_day",
    ("2024-11-04", "2024-11-05"),
)
def test_compact_bars_use_official_session_close_pre_and_post_change(
    trading_day: str,
) -> None:
    expected = session_close_jst(trading_day)
    assert expected.endswith(
        "T15:00:00+09:00" if trading_day < "2024-11-05" else "T15:30:00+09:00"
    )
    row = _compact_one_bar(_one_bar(Date=trading_day))
    assert row["event_time"] == expected
    assert row["available_at"] == expected
    assert row["ingested_at"] >= expected


@pytest.mark.parametrize("snapshot_day", ("2024-11-04", "2024-11-05"))
def test_compact_master_uses_snapshot_date_0800_jst(snapshot_day: str) -> None:
    rows, _digest = _compact_master(
        [
            {
                "Code": "1001",
                "Date": snapshot_day,
                "Mkt": "0111",
                "ScaleCat": "TOPIX Core30",
            }
        ],
        snapshot_day=snapshot_day,
        ingested_at=f"{snapshot_day}T08:01:00+09:00",
    )
    assert len(rows) == 1
    assert rows[0]["event_time"][:10] == snapshot_day
    assert rows[0]["available_at"] == f"{snapshot_day}T08:00:00+09:00"
    assert rows[0]["ingested_at"] >= rows[0]["available_at"]


@pytest.mark.parametrize(
    ("sql", "params", "match"),
    (
        (
            "UPDATE personal_history_compact_bars "
            "SET event_time=?, available_at=? WHERE date='2025-01-06'",
            ("2025-01-06T15:00:00+09:00", "2025-01-06T15:00:00+09:00"),
            "official session close",
        ),
        (
            "UPDATE personal_history_compact_bars SET ingested_at=? "
            "WHERE date='2025-01-06'",
            ("2025-01-06T15:00:00+09:00",),
            "ingested_at",
        ),
        (
            "UPDATE personal_history_compact_bars SET ingested_at=? "
            "WHERE date='2025-01-06'",
            ("2025-01-06T15:30:00Z",),
            "ingested_at",
        ),
        (
            "UPDATE personal_history_compact_master SET available_at=? "
            "WHERE snapshot_date='2025-01-02'",
            ("2025-01-02T09:00:00+09:00",),
            "08:00 JST",
        ),
        (
            "UPDATE personal_history_compact_master SET event_time=? "
            "WHERE snapshot_date='2025-01-02'",
            ("2025-01-03T00:00:00+09:00",),
            "event_time date",
        ),
        (
            "UPDATE personal_history_compact_master SET ingested_at=? "
            "WHERE snapshot_date='2025-01-02'",
            ("2025-01-02T07:00:00+09:00",),
            "ingested_at",
        ),
    ),
)
def test_compact_v7_sql_timestamp_invariants_reject_anomalies(
    tmp_path, sql: str, params: tuple[str, ...], match: str
) -> None:
    store = SqliteStore(tmp_path / "timestamp-invariants.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    )
    hydrator.hydrate()
    store._conn.execute(sql, params)
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match=match):
        hydrator._assert_compact_v7_timestamps()
    store.close()


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


def _markets_calendar_official_floor() -> str:
    return source_capability_contract_for(
        "markets_calendar"
    ).earliest_official_availability


def test_plan_clamps_old_s1_calendar_start_to_canonical_contract_floor() -> None:
    plan = build_personal_history_plan(
        period_start="2009-06-01",
        period_end="2014-07-15",
        lookback_sessions=252,
        today=date(2014, 7, 15),
    )
    assert plan.calendar_start == _markets_calendar_official_floor()
    assert plan.calendar_start <= plan.period_end


def test_plan_does_not_clamp_later_calendar_start() -> None:
    plan = build_personal_history_plan(
        period_start="2025-01-06",
        period_end="2025-01-08",
        lookback_sessions=1,
        today=date(2025, 2, 1),
    )
    assert plan.calendar_start > _markets_calendar_official_floor()


def test_plan_rejects_period_end_before_profile_floor() -> None:
    floor = date.fromisoformat(personal_snapshot_data_floor())
    calendar_floor = date.fromisoformat(_markets_calendar_official_floor())
    assert floor > calendar_floor
    with pytest.raises(PersonalHistoryError, match="personal snapshot data floor"):
        build_personal_history_plan(
            period_start=(floor - timedelta(days=30)).isoformat(),
            period_end=(floor - timedelta(days=1)).isoformat(),
            lookback_sessions=0,
            today=floor,
        )


class _FloorHistoryClient:
    """Synthetic 2008 client. Weekday calendar; no real market data."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.master_floor = source_capability_contract_for(
            "equities_master"
        ).earliest_official_availability
        self.profile_floor = personal_snapshot_data_floor()
        self.calendar_floor = source_capability_contract_for(
            "markets_calendar"
        ).earliest_official_availability

    def fetch_dataset_evidenced(self, dataset: str, **params):
        recorded = {key: str(value) for key, value in params.items()}
        self.calls.append((dataset, recorded))
        if dataset == "markets_calendar":
            start = str(params["from"])
            end = str(params["to"])
            assert start >= self.calendar_floor
            rows = _HistoryClient._calendar(start, end)
        elif dataset == "equities_master":
            day = str(params["date"])
            if day < self.master_floor:
                raise AssertionError(f"master queried before floor: {day}")
            rows = [
                {
                    "Code": "1001",
                    "Date": day,
                    "Mkt": "0111",
                    "S17": "1",
                    "S33": "0050",
                    "ScaleCat": "TOPIX Core30",
                },
                {
                    "Code": "1002",
                    "Date": day,
                    "Mkt": "0112",
                    "S17": "1",
                    "S33": "0050",
                    "ScaleCat": "TOPIX Small 1",
                },
            ]
        elif dataset == "fins_summary":
            code = str(params["code"])
            rows = [
                {
                    "Code": code,
                    "DiscDate": self.profile_floor,
                    "DiscTime": "09:00:00",
                    "DiscNo": f"disc-{code}",
                    "EarningsPerShare": 1.25,
                }
            ]
        elif dataset == "equities_bars_daily":
            day = str(params["date"])
            if day < self.profile_floor:
                raise AssertionError(f"bars queried before profile floor: {day}")
            rows = [
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
                }
                for ordinal, code in enumerate(("1001", "1002"), start=1)
            ]
        else:  # pragma: no cover
            raise AssertionError(dataset)
        body = json.dumps({"data": rows}, separators=(",", ":")).encode()
        page = _Page(
            request_path=f"/v2/{dataset}",
            request_params=MappingProxyType(dict(params)),
            response_status=200,
            response_body=body,
        )
        return _Fetch(tuple(rows), (page,))


def test_2008_jan1_request_truncates_lookback_to_profile_floor(tmp_path):
    profile_floor = personal_snapshot_data_floor()
    master_floor = source_capability_contract_for(
        "equities_master"
    ).earliest_official_availability
    fins_floor = source_capability_contract_for(
        "fins_summary"
    ).earliest_official_availability
    assert profile_floor == fins_floor
    assert master_floor < profile_floor
    plan = build_personal_history_plan(
        period_start="2008-01-01",
        period_end="2008-07-08",
        lookback_sessions=252,
        calendar_window_days=366,
        today=date(2008, 8, 1),
    )
    assert plan.period_start == "2008-01-01"
    assert plan.period_end == "2008-07-08"
    assert plan.lookback_sessions == 252
    assert plan.calendar_start == _markets_calendar_official_floor()
    assert plan.estimated_trading_sessions == 2
    assert plan.estimated_bytes == _expected_plan_bytes(plan)
    store = SqliteStore(tmp_path / "floor-2008.sqlite")
    client = _FloorHistoryClient()
    hydrator = PersonalHistoryHydrator(
        client=client, store=store, plan=plan
    )
    summary = hydrator.hydrate()
    manifest = store._conn.execute(
        "SELECT status,plan_json FROM personal_history_manifest"
    ).fetchone()
    assert manifest["status"] == "COMPLETE_DRAFT"
    stored_plan = json.loads(manifest["plan_json"])
    assert stored_plan["period_start"] == "2008-01-01"
    assert stored_plan["lookback_sessions"] == 252
    assert summary.status == "COMPLETE_DRAFT"
    assert summary.period_start == "2008-01-01"
    assert summary.actual_lookback_sessions == 0
    assert summary.lookback_truncated is True
    assert summary.bar_start == "2008-07-07"
    master_days = [
        params["date"]
        for dataset, params in client.calls
        if dataset == "equities_master"
    ]
    bar_days = [
        params["date"]
        for dataset, params in client.calls
        if dataset == "equities_bars_daily"
    ]
    assert master_days
    assert min(master_days) >= master_floor
    assert min(master_days) == "2008-07-04"
    assert bar_days == ["2008-07-07", "2008-07-08"]
    assert min(bar_days) >= profile_floor
    compact_days = {row["date"] for row in _compact_bar_rows(store)}
    assert compact_days == {"2008-07-07", "2008-07-08"}
    calls_after = list(client.calls)
    resumed = hydrator.hydrate()
    assert resumed.bar_start == summary.bar_start
    assert resumed.actual_lookback_sessions == summary.actual_lookback_sessions
    assert resumed.lookback_truncated is True
    assert client.calls == calls_after
    store.close()


def test_later_lookback_zero_starts_at_requested_period(tmp_path):
    plan = build_personal_history_plan(
        period_start="2025-01-06",
        period_end="2025-01-08",
        lookback_sessions=0,
        calendar_window_days=366,
        today=date(2025, 2, 1),
    )
    assert plan.period_start == "2025-01-06"
    assert plan.estimated_trading_sessions == 3
    store = SqliteStore(tmp_path / "lookback-zero.sqlite")
    client = _HistoryClient()
    summary = PersonalHistoryHydrator(
        client=client, store=store, plan=plan
    ).hydrate()
    bar_days = sorted(
        identity
        for dataset, identity in client.calls
        if dataset == "equities_bars_daily"
    )
    assert bar_days[0] == "2025-01-06"
    assert summary.bar_start == "2025-01-06"
    assert summary.actual_lookback_sessions == 0
    assert summary.lookback_truncated is False
    store.close()


class _SkipThenFailClosedClient(_HistoryClient):
    @staticmethod
    def _master(day: str) -> list[dict]:
        if day >= "2025-01-08":
            return [
                {
                    "Code": "1004",
                    "Date": day,
                    "Mkt": "0111",
                    "S17": "1",
                    "S33": "0050",
                    "ScaleCat": "TOPIX Core30",
                }
            ]
        return _HistoryClient._master(day)

    @staticmethod
    def _fins(code: str) -> list[dict]:
        if code not in {"1001", "1002", "1003"}:
            return []
        return [
            {
                "Code": code,
                "DiscDate": "2025-01-06",
                "DiscNo": f"disc-{code}",
                "EarningsPerShare": 123.4,
            }
        ]


def test_leading_empty_fins_membership_is_skipped_then_fail_closed(tmp_path):
    store = SqliteStore(tmp_path / "skip-then-fail.sqlite")
    client = _SkipThenFailClosedClient()
    with pytest.raises(
        PersonalHistoryError, match="PIT-visible fins is empty for 2025-01-08"
    ):
        PersonalHistoryHydrator(client=client, store=store, plan=_plan()).hydrate()
    bar_days = sorted(
        identity
        for dataset, identity in client.calls
        if dataset == "equities_bars_daily"
    )
    assert "2025-01-03" not in bar_days
    assert "2025-01-06" not in bar_days
    assert "2025-01-07" in bar_days
    assert store._conn.execute(
        "SELECT status FROM personal_history_manifest"
    ).fetchone()[0] == "BUILDING"
    store.close()


class _RedundantLaterFinsClient(_HistoryClient):
    @staticmethod
    def _fins(code: str) -> list[dict]:
        rows = _HistoryClient._fins(code)
        if not rows:
            return rows
        extra = []
        for ordinal, source in enumerate(rows, start=2):
            extra.append(
                {
                    **source,
                    "DiscDate": "2025-01-08",
                    "DiscTime": "16:00:00",
                    "DiscNo": f"{source['DiscNo']}-later-{ordinal}",
                }
            )
        return rows + extra


class _StableMasterClient(_HistoryClient):
    @staticmethod
    def _master(day: str) -> list[dict]:
        rows = _HistoryClient._master("2025-01-02")
        return [{**row, "Date": day} for row in rows]


def test_later_fins_rows_do_not_change_first_visible_bar_universe(tmp_path):
    baseline_store = SqliteStore(tmp_path / "baseline-universe.sqlite")
    redundant_store = SqliteStore(tmp_path / "redundant-fins.sqlite")
    PersonalHistoryHydrator(
        client=_HistoryClient(), store=baseline_store, plan=_plan()
    ).hydrate()
    PersonalHistoryHydrator(
        client=_RedundantLaterFinsClient(), store=redundant_store, plan=_plan()
    ).hydrate()

    def _bar_membership(store: SqliteStore) -> list[tuple[str, str, int]]:
        return [
            (str(row["query_start"]), str(row["membership_digest"]), int(row["expected_rows"]))
            for row in store._conn.execute(
                "SELECT query_start,membership_digest,expected_rows "
                "FROM personal_history_segments "
                "WHERE dataset='equities_bars_daily' "
                "AND state IN ('OBSERVED','OBSERVED_EMPTY') "
                "ORDER BY query_start"
            )
        ]

    baseline = _bar_membership(baseline_store)
    redundant = _bar_membership(redundant_store)
    assert baseline
    assert redundant == baseline
    hydrator = PersonalHistoryHydrator(
        client=_RedundantLaterFinsClient(),
        store=redundant_store,
        plan=_plan(),
    )
    first = hydrator._first_visible_fins_by_code()
    assert first["1001"] == "2024-12-02T09:00:00+09:00"
    assert first["1002"] == "2025-01-04T00:00:00+09:00"
    assert first["1003"] == "2025-01-07T09:00:00+09:00"
    baseline_store.close()
    redundant_store.close()


def test_unchanged_pit_universe_reuses_membership_digest(tmp_path):
    store = SqliteStore(tmp_path / "stable-master.sqlite")
    PersonalHistoryHydrator(
        client=_StableMasterClient(), store=store, plan=_plan()
    ).hydrate()
    rows = list(
        store._conn.execute(
            "SELECT query_start,membership_digest,expected_rows "
            "FROM personal_history_segments "
            "WHERE dataset='equities_bars_daily' "
            "AND state IN ('OBSERVED','OBSERVED_EMPTY') "
            "AND query_start IN ('2025-01-06','2025-01-07','2025-01-08') "
            "ORDER BY query_start"
        )
    )
    assert [str(row["query_start"]) for row in rows] == [
        "2025-01-06",
        "2025-01-07",
        "2025-01-08",
    ]
    digests = {str(row["membership_digest"]) for row in rows}
    assert len(digests) == 1
    assert next(iter(digests)).startswith("sha256:")
    assert {int(row["expected_rows"]) for row in rows} == {2}
    codes = {
        str(row["code"])
        for row in store._conn.execute(
            "SELECT DISTINCT code FROM personal_history_compact_bars "
            "WHERE date='2025-01-06'"
        )
    }
    assert codes == {"1001", "1002"}
    store.close()


@pytest.mark.parametrize(
    "payload",
    (
        "not-json",
        '[{"Code":"1001"}]',
    ),
)
def test_first_visible_fins_fail_closed_on_invalid_payload(tmp_path, payload):
    store = SqliteStore(tmp_path / "invalid-fins.sqlite")
    hydrator = PersonalHistoryHydrator(
        client=_HistoryClient(), store=store, plan=_plan()
    )
    hydrator.hydrate()
    store._conn.execute(
        "UPDATE jquants_records SET payload=? "
        "WHERE source='jquants' AND dataset='fins_summary'",
        (payload,),
    )
    store._conn.commit()
    with pytest.raises(PersonalHistoryError, match="payload is invalid"):
        hydrator._first_visible_fins_by_code()
    store.close()


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
