"""Hydrator-to-reader vintage PIT: real hydrator inputs, not hand timestamps."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pytest

from data_contracts.identity import session_close_jst
from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_FORMAT,
    PERSONAL_HISTORY_COMPACT_PREVIOUS_FORMAT,
    PERSONAL_HISTORY_COMPACT_REBUILD_REASON,
)
from ingestion.personal_history import (
    DEFAULT_REVISION_WINDOW_CALENDAR_DAYS,
    REVISION_COVERAGE_BOUNDED_WINDOW,
    REVISION_COVERAGE_WINDOW_COMPLETE,
    PersonalHistoryHydrator,
    build_personal_history_plan,
)
from pit.errors import PitError
from pit.personal_research_view import OfflineFixtureDataView
from storage.sqlite_store import SqliteStore

from test_personal_history_hydrator import _HistoryClient


def _plan():
    return build_personal_history_plan(
        period_start="2025-01-02",
        period_end="2025-01-02",
        lookback_sessions=0,
        calendar_window_days=366,
        today=date(2025, 3, 20),
    )


class _RevisionClient(_HistoryClient):
    def __init__(self) -> None:
        super().__init__()
        self.bar_close = 100.0
        self.scale = "TOPIX Core30"

    def _master(self, day: str) -> list[dict]:
        rows = super()._master(day)
        for row in rows:
            if row["Code"] == "1001":
                row["ScaleCat"] = self.scale
        return rows

    def _bars(self, day: str) -> list[dict]:
        rows = super()._bars(day)
        for row in rows:
            if row["Code"] == "1001":
                row["Close"] = self.bar_close
                row["AdjustmentClose"] = self.bar_close
        return rows


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, stamp: str) -> None:
    monkeypatch.setattr("ingestion.personal_history.now_iso", lambda: stamp)


def _hydrate(tmp_path: Path, client: _RevisionClient) -> tuple[Path, object]:
    db = tmp_path / "personal-history.sqlite"
    store = SqliteStore(db)
    summary = PersonalHistoryHydrator(
        client=client, store=store, plan=_plan()
    ).hydrate()
    store.close()
    return db, summary


def _bar_closes(view: OfflineFixtureDataView, decision: str) -> list[float]:
    closes: list[float] = []
    for page in view.iter_decision_pages(
        decision_date=decision,
        dataset="equities_bars_daily",
        codes=["1001"],
        start="2025-01-02",
        end="2025-01-02",
    ):
        for row in page:
            payload = row["payload"]
            closes.append(float(payload["Close"]))
    return closes


def _master_scale(view: OfflineFixtureDataView) -> list[str]:
    slices = view.universe_slices(period_start="2025-01-02", period_end="2025-01-02")
    return [
        member.scale_category
        for member in slices[0].members
        if member.code == "1001"
    ]


def test_hydrator_bar_correction_is_visible_only_after_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _RevisionClient()
    _freeze_clock(monkeypatch, "2025-01-02T16:00:00+09:00")
    db, summary = _hydrate(tmp_path, client)
    assert summary.revision_coverage == REVISION_COVERAGE_WINDOW_COMPLETE
    assert DEFAULT_REVISION_WINDOW_CALENDAR_DAYS == 40
    view = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "art", decision_cutoff="session_close"
    )
    assert _bar_closes(view, "2025-01-02") == [100.0]

    client.bar_close = 200.0
    _freeze_clock(monkeypatch, "2025-01-31T10:00:00+09:00")
    store = SqliteStore(db)
    second = PersonalHistoryHydrator(
        client=client, store=store, plan=_plan()
    ).hydrate()
    store.close()
    assert second.written_rows >= 1
    view = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "art2", decision_cutoff="session_close"
    )
    assert _bar_closes(view, "2025-01-02") == [100.0]
    assert _bar_closes(view, "2025-02-01") == [200.0]
    assert _bar_closes(view, "2025-01-02") == [100.0]

    conn = sqlite3.connect(db)
    vintages = conn.execute(
        "SELECT COUNT(*) FROM personal_history_compact_bars "
        "WHERE code='1001' AND date='2025-01-02'"
    ).fetchone()[0]
    conn.close()
    assert vintages == 2

    _freeze_clock(monkeypatch, "2025-01-31T11:00:00+09:00")
    store = SqliteStore(db)
    third = PersonalHistoryHydrator(
        client=client, store=store, plan=_plan()
    ).hydrate()
    store.close()
    conn = sqlite3.connect(db)
    store_count = conn.execute(
        "SELECT COUNT(*) FROM personal_history_compact_bars "
        "WHERE code='1001' AND date='2025-01-02'"
    ).fetchone()[0]
    conn.close()
    assert store_count == 2
    assert third.revision_coverage == REVISION_COVERAGE_WINDOW_COMPLETE

    client.bar_close = 100.0
    _freeze_clock(monkeypatch, "2025-01-31T12:00:00+09:00")
    store = SqliteStore(db)
    fourth = PersonalHistoryHydrator(
        client=client, store=store, plan=_plan()
    ).hydrate()
    store.close()
    assert fourth.written_rows >= 1
    view = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "art3", decision_cutoff="session_close"
    )
    assert _bar_closes(view, "2025-01-02") == [100.0]
    assert _bar_closes(view, "2025-02-01") == [100.0]
    assert _bar_closes(view, "2025-01-02") == [100.0]
    conn = sqlite3.connect(db)
    vintages = conn.execute(
        "SELECT COUNT(*) FROM personal_history_compact_bars "
        "WHERE code='1001' AND date='2025-01-02'"
    ).fetchone()[0]
    conn.close()
    assert vintages == 3


def test_hydrator_master_noon_correction_keeps_morning_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _RevisionClient()
    _freeze_clock(monkeypatch, "2025-01-02T08:00:00+09:00")
    db, _summary = _hydrate(tmp_path, client)
    morning = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "m", decision_cutoff="morning_close"
    )
    session = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "s", decision_cutoff="session_close"
    )
    assert _master_scale(morning) == ["TOPIX Core30"]

    client.scale = "TOPIX Small 1"
    _freeze_clock(monkeypatch, "2025-01-02T12:00:00+09:00")
    store = SqliteStore(db)
    PersonalHistoryHydrator(client=client, store=store, plan=_plan()).hydrate()
    store.close()
    morning = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "m2", decision_cutoff="morning_close"
    )
    session = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "s2", decision_cutoff="session_close"
    )
    assert _master_scale(morning) == ["TOPIX Core30"]
    assert _master_scale(session) == ["TOPIX Small 1"]
    assert _master_scale(morning) == ["TOPIX Core30"]


def test_correction_outside_revision_window_stays_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _RevisionClient()
    _freeze_clock(monkeypatch, "2025-01-02T16:00:00+09:00")
    db, first = _hydrate(tmp_path, client)
    assert first.revision_coverage == REVISION_COVERAGE_WINDOW_COMPLETE
    client.bar_close = 300.0
    _freeze_clock(monkeypatch, "2025-03-20T10:00:00+09:00")
    store = SqliteStore(db)
    stale = PersonalHistoryHydrator(
        client=client, store=store, plan=_plan()
    ).hydrate()
    store.close()
    assert stale.revision_coverage == REVISION_COVERAGE_BOUNDED_WINDOW
    view = OfflineFixtureDataView.bind(
        db, artifact_root=tmp_path / "stale", decision_cutoff="session_close"
    )
    assert _bar_closes(view, "2025-03-20") == [100.0]


def test_old_v7_compact_fails_closed_with_rebuild_reason(tmp_path: Path) -> None:
    import sqlite3

    from personal_history_compact_support import stamp_compact_manifest

    path = tmp_path / "v7.sqlite"
    connection = sqlite3.connect(path)
    stamp_compact_manifest(connection, PERSONAL_HISTORY_COMPACT_PREVIOUS_FORMAT)
    connection.execute(
        "CREATE TABLE personal_history_compact_master ("
        "snapshot_date TEXT NOT NULL, code TEXT NOT NULL, "
        "event_time TEXT NOT NULL, available_at TEXT NOT NULL, "
        "ingested_at TEXT NOT NULL, market_code TEXT, sector_17_code TEXT, "
        "sector_33_code TEXT, scale_category TEXT, source_scale_category TEXT, "
        "PRIMARY KEY (snapshot_date, code, available_at, ingested_at)"
        ") WITHOUT ROWID"
    )
    connection.execute(
        "CREATE TABLE personal_history_compact_bars ("
        "code TEXT NOT NULL, date TEXT NOT NULL, event_time TEXT NOT NULL, "
        "available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
        "close REAL NOT NULL, volume REAL, turnover_value REAL, "
        "adjustment_close REAL, adjustment_volume REAL, "
        "morning_adjustment_close REAL, afternoon_adjustment_close REAL, "
        "morning_turnover_value REAL, afternoon_turnover_value REAL, "
        "morning_adjustment_volume REAL, afternoon_adjustment_volume REAL, "
        "market_cap REAL, "
        "PRIMARY KEY (code, date, available_at, ingested_at)"
        ") WITHOUT ROWID"
    )
    connection.commit()
    connection.close()
    view = OfflineFixtureDataView.bind(path, artifact_root=tmp_path / "v7-art")
    with pytest.raises(PitError, match=PERSONAL_HISTORY_COMPACT_REBUILD_REASON):
        list(
            view.iter_decision_pages(
                decision_date="2025-01-02",
                dataset="equities_bars_daily",
                codes=["1001"],
                start="2025-01-02",
                end="2025-01-02",
            )
        )
    assert PERSONAL_HISTORY_COMPACT_FORMAT == "personal-draft-history/v8"
    assert session_close_jst("2025-01-02") == "2025-01-02T15:30:00+09:00"
