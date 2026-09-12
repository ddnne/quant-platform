"""Shared DataPlane financial catalog state: compute read and owner evidence."""

from __future__ import annotations

import json
import sqlite3
import tracemalloc
from dataclasses import fields
from itertools import combinations
from pathlib import Path

import pytest

import features
import pit.financial_observations as financial_observations
import pit.query as query_module
from _coreseed import close_iso, morning_iso, write_snapshot_observation_clock
from features.complete21_min_parsers import _latest_fins_per_share_observation
from pit import (
    FinancialCatalogState,
    SnapshotNotReady,
    get_financial_state,
    get_jquants_records,
)
from pit.api import _owned_financial_selection
from pit.financial_observations import (
    FINANCIAL_SELECTION_EVIDENCE_FORMAT,
    latest_fins_per_share_observation,
)
from pit.query import bind_external_readonly_connection, connect_readonly
from storage.sqlite_store import SqliteStore

CODE = "8697"
COUNT_ONLY = "all_visible_existence_and_count"
PER_SHARE = "latest_qualifying_bps_preferred_else_eps"
CLOCK = "2025-04-21T15:30:00+09:00"
TIE_AT = "2025-04-03T09:00:00+09:00"
ORIGINAL_AT = "2025-04-08T09:00:00+09:00"
AMENDED_AT = "2025-04-10T09:00:00+09:00"


def _nk(disc: str, day: str) -> str:
    return json.dumps(
        {"Code": CODE, "Date": day, "DiscNo": disc},
        sort_keys=True,
        separators=(",", ":"),
    )


def _catalog_row(
    *,
    disc: str,
    day: str,
    payload: str | dict,
    raw_payload: str | dict | None = None,
    event_time: str | None = None,
    available_at: str | None = None,
    ingested_at: str | None = None,
) -> dict[str, str | bytes]:
    stamp = event_time or f"{day}T12:00:00+09:00"
    if isinstance(payload, (str, bytes)):
        payload_text = payload
    else:
        payload_text = json.dumps(payload, ensure_ascii=False)
    if raw_payload is None:
        raw_text = payload_text
    elif isinstance(raw_payload, (str, bytes)):
        raw_text = raw_payload
    else:
        raw_text = json.dumps(raw_payload, ensure_ascii=False)
    return {
        "source": "jquants",
        "dataset": "fins_summary",
        "natural_key": _nk(disc, day),
        "event_time": stamp,
        "available_at": available_at or stamp,
        "ingested_at": ingested_at or stamp,
        "payload": payload_text,
        "raw_payload": raw_text,
    }


def _catalog_db(tmp_path: Path) -> Path:
    path = tmp_path / "fins.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _catalog_row(
                disc="old-seed",
                day="2024-01-01",
                event_time="2024-01-01T15:00:00+09:00",
                payload={
                    "Code": CODE,
                    "BPS": 80.0,
                    "CurPerEn": "2023-12-31",
                    "DiscDate": "2024-01-15",
                },
            ),
            _catalog_row(
                disc="empty",
                day="2025-03-01",
                payload={},
                raw_payload={
                    "Code": CODE,
                    "BPS": 999.0,
                    "CurPerEn": "2025-09-30",
                },
            ),
            _catalog_row(
                disc="malformed",
                day="2025-03-01",
                payload="not-json",
                raw_payload={
                    "Code": CODE,
                    "EPS": 3.0,
                    "DiscDate": "2025-07-01",
                },
            ),
            _catalog_row(
                disc="double",
                day="2025-03-01",
                payload=json.dumps("{}"),
                raw_payload={"Code": CODE, "BPS": 50.0, "CurPerEn": "2025-06-30"},
            ),
            _catalog_row(
                disc="eps",
                day="2025-04-01",
                event_time="2025-04-01T15:00:00+09:00",
                payload={
                    "Code": CODE,
                    "EPS": 12.0,
                    "CurPerEn": "2025-03-31",
                    "DiscDate": "2025-04-01",
                },
            ),
            _catalog_row(
                disc="amend",
                day="2025-04-08",
                event_time=ORIGINAL_AT,
                available_at=ORIGINAL_AT,
                ingested_at=ORIGINAL_AT,
                payload={"Code": CODE, "BPS": 10.0, "CurPerEn": "2025-03-31"},
            ),
        ],
    )
    store.upsert(
        "jquants_records",
        [
            _catalog_row(
                disc="amend",
                day="2025-04-08",
                event_time=ORIGINAL_AT,
                available_at=AMENDED_AT,
                ingested_at=AMENDED_AT,
                payload={"Code": CODE, "BPS": 20.0, "CurPerEn": "2025-03-31"},
            )
        ],
    )
    tie = _catalog_row(
        disc="tie",
        day="2025-04-03",
        event_time=TIE_AT,
        available_at=TIE_AT,
        ingested_at=TIE_AT,
        payload={"Code": CODE, "BPS": 1.0, "CurPerEn": "2025-03-31"},
    )
    store.upsert("jquants_records", [tie])
    archive = dict(tie)
    archive["payload"] = json.dumps(
        {"Code": CODE, "BPS": 9.0, "CurPerEn": "2025-03-31"},
        ensure_ascii=False,
    )
    archive["raw_payload"] = archive["payload"]
    cols = (
        "source",
        "dataset",
        "natural_key",
        "event_time",
        "available_at",
        "ingested_at",
        "payload",
        "raw_payload",
    )
    store._conn.execute(
        "INSERT INTO jquants_records_revisions ("
        + ",".join(cols)
        + ") VALUES ("
        + ",".join("?" for _ in cols)
        + ")",
        [archive[name] for name in cols],
    )
    store._conn.commit()
    write_snapshot_observation_clock(store, CLOCK)
    store.close()
    return path


def _read(path: Path, as_of: str, state: str):
    return get_financial_state(
        as_of,
        dataset="fins_summary",
        code=CODE,
        initial_visible_state=state,
        db_path=path,
    )


def _owned(path: Path, as_of: str, state: str):
    return _owned_financial_selection(
        as_of,
        dataset="fins_summary",
        code=CODE,
        initial_visible_state=state,
        db_path=path,
    )


@pytest.mark.parametrize("initial_visible_state", (COUNT_ONLY, PER_SHARE))
def test_ordinary_and_private_owner_agree_on_revisions_ties_and_clocks(
    tmp_path, initial_visible_state
) -> None:
    path = _catalog_db(tmp_path)
    as_of = close_iso("2025-04-20")
    ordinary = _owned(path, as_of, initial_visible_state)
    conn = connect_readonly(path)
    try:
        conn.execute("BEGIN")
        with bind_external_readonly_connection(
            path, conn, identity_check=lambda: None
        ):
            private = _owned(path, as_of, initial_visible_state)
    finally:
        conn.close()
    assert ordinary.state == private.state == _read(path, as_of, initial_visible_state)
    assert ordinary.evidence == private.evidence
    assert ordinary.evidence.format == FINANCIAL_SELECTION_EVIDENCE_FORMAT
    assert ordinary.evidence.digest.startswith("sha256:")
    if initial_visible_state == PER_SHARE:
        assert ordinary.state.observation is not None
        assert ordinary.state.observation["bps"] == 20.0
        assert ordinary.evidence.selected_natural_key == _nk("amend", "2025-04-08")
        assert ordinary.selected_product_digest == private.selected_product_digest
    else:
        assert ordinary.state.parsed_row_count is None
        assert ordinary.state.observation is None
        assert ordinary.evidence.selected_natural_key is None


def test_selected_product_digest_tracks_bps_winner_not_later_eps_row() -> None:
    bps_row = _catalog_row(
        disc="bps",
        day="2023-01-10",
        payload={
            "Code": CODE,
            "BPS": 100.0,
            "CurPerEn": "2022-12-31",
            "DiscDate": "2023-01-10",
        },
        event_time="2023-01-10T12:00:00+09:00",
    )
    eps_row = _catalog_row(
        disc="eps",
        day="2023-02-10",
        payload={
            "Code": CODE,
            "EPS": 10.0,
            "CurPerEn": "2023-01-31",
            "DiscDate": "2023-02-10",
        },
        event_time="2023-02-10T12:00:00+09:00",
    )
    count_row = _catalog_row(
        disc="sales",
        day="2023-03-10",
        payload={"Code": CODE, "NetSales": 1.0, "CurPerEn": "2023-03-31"},
        event_time="2023-03-10T12:00:00+09:00",
    )
    owned = financial_observations._owned_selection_from_raw_rows(
        iter((bps_row, eps_row, count_row)),
        dataset="fins_summary",
        code=CODE,
        initial_visible_state=PER_SHARE,
    )
    assert owned.state.observation is not None
    assert owned.state.observation["mode"] == "bps_over_price"
    assert owned.state.observation["bps"] == 100.0
    assert owned.state.parsed_row_count == 3
    assert owned.evidence.selected_natural_key == _nk("bps", "2023-01-10")
    assert owned.selected_product_digest == (
        financial_observations._product_digest_from_raw(bps_row)
    )
    assert owned.selected_product_digest != (
        financial_observations._product_digest_from_raw(eps_row)
    )
    assert owned.visible_identities == (
        (_nk("bps", "2023-01-10"), "2023-01-10"),
        (_nk("eps", "2023-02-10"), "2023-02-10"),
        (_nk("sales", "2023-03-10"), "2023-03-10"),
    )
    assert owned.payload_column_evidence == {
        "payload": "present_value",
        "raw_payload": "present_value",
    }


def test_payload_clock_and_count_invariants(tmp_path) -> None:
    path = _catalog_db(tmp_path)
    close_day = close_iso("2025-04-01")
    am_day = morning_iso("2025-04-01")
    rows = get_jquants_records(
        as_of=close_day, dataset="fins_summary", code=CODE, db_path=path
    )
    per_share = _read(path, close_day, PER_SHARE)
    count_only = _read(path, close_day, COUNT_ONLY)
    expected = latest_fins_per_share_observation(list(rows.rows))
    assert expected == _latest_fins_per_share_observation(list(rows.rows))
    assert dict(per_share.observation) == expected
    assert expected is not None
    assert expected["bps"] == 80.0
    assert expected["split_safety_anchor"] == "2023-12-31"
    assert expected["mode"] == "bps_over_price"
    assert count_only.visible_row_count == len(rows.rows) == 5
    assert per_share.parsed_row_count == expected["fins_rows"] == 3
    assert count_only.parsed_row_count is None
    assert _read(path, am_day, COUNT_ONLY).visible_row_count == 4
    before = _read(path, "2025-04-04T15:30:00+09:00", PER_SHARE)
    assert before.observation is not None
    assert before.observation["bps"] == 1.0
    after = _read(path, close_iso("2025-04-20"), PER_SHARE)
    assert after.observation is not None
    assert after.observation["bps"] == 20.0
    field_names = {item.name for item in fields(FinancialCatalogState)}
    assert "selected_natural_key" not in field_names
    assert "selection_evidence_digest" not in field_names
    assert not hasattr(per_share, "rows")
    assert not hasattr(per_share, "selected_natural_key")
    assert "selection_evidence_digest" not in per_share.__slots__


def test_count_only_skips_numeric_parse_and_overflow(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "huge.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _catalog_row(
                disc="huge",
                day="2025-04-01",
                payload='{"Code":"8697","Date":"2025-04-01","BPS":'
                + str(10**400)
                + "}",
            )
        ],
    )
    write_snapshot_observation_clock(store, CLOCK)
    store.close()
    as_of = close_iso("2025-04-01")
    calls = []
    real = financial_observations._as_float_or_none

    def tracked(value):
        calls.append(value)
        return real(value)

    monkeypatch.setattr(financial_observations, "_as_float_or_none", tracked)
    counted = _read(path, as_of, COUNT_ONLY)
    assert counted.visible_row_count == 1
    assert calls == []
    monkeypatch.setattr(
        financial_observations, "_as_float_or_none", real
    )
    with pytest.raises(OverflowError):
        _read(path, as_of, PER_SHARE)


def test_nonfinite_raw_text_does_not_poison_evidence() -> None:
    raw = {
        "available_at": "2025-04-01T15:00:00+09:00",
        "event_time": "2025-04-01T15:00:00+09:00",
        "ingested_at": "2025-04-01T15:00:00+09:00",
        "natural_key": _nk("inf", "2025-04-01"),
        "payload": '{"BPS":Infinity}',
        "raw_payload": None,
        "source": "jquants",
    }
    owned = financial_observations._owned_selection_from_raw_rows(
        iter((raw,)),
        dataset="fins_summary",
        code=CODE,
        initial_visible_state=PER_SHARE,
    )
    assert owned.evidence.digest.startswith("sha256:")
    assert owned.state.observation is not None
    assert owned.state.observation["bps"] == float("inf")


def test_stream_does_not_fetchall_materialize_history(tmp_path, monkeypatch) -> None:
    path = _catalog_db(tmp_path)
    data_fetchalls: list[str] = []
    real_connect = query_module.connect_readonly

    class _ExecuteProxy:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        class _CursorProxy:
            def __init__(self, cursor, sql: str) -> None:
                self._cursor = cursor
                self._sql = sql

            def fetchall(self):
                data_fetchalls.append(self._sql)
                return self._cursor.fetchall()

            def __iter__(self):
                return iter(self._cursor)

            def __getattr__(self, name):
                return getattr(self._cursor, name)

        def execute(self, sql, parameters=()):
            cursor = self._conn.execute(sql, parameters)
            if "FROM pit_ranked" in sql or (
                "FROM jquants_records WHERE" in sql and "LIMIT 1" not in sql
            ):
                return self._CursorProxy(cursor, sql)
            return cursor

        def __getattr__(self, name):
            return getattr(self._conn, name)

    def tracked(db_path=None):
        return _ExecuteProxy(real_connect(db_path))

    monkeypatch.setattr(query_module, "connect_readonly", tracked)
    state = _read(path, close_iso("2025-04-20"), COUNT_ONLY)
    assert state.visible_row_count >= 1
    assert data_fetchalls == []

    def synthetic_rows(count: int, payload_size: int):
        for index in range(count):
            marker = f"{index:08d}"
            payload = marker + ("x" * (payload_size - len(marker)))
            yield {
                "available_at": "2025-04-01T15:00:00+09:00",
                "event_time": "2025-04-01T15:00:00+09:00",
                "ingested_at": "2025-04-01T15:00:00+09:00",
                "natural_key": f"k{index:04d}",
                "payload": payload,
                "raw_payload": "{}",
                "source": "jquants",
            }

    def peak_bytes(count: int, payload_size: int) -> int:
        tracemalloc.start()
        try:
            owned = financial_observations._owned_selection_from_raw_rows(
                synthetic_rows(count, payload_size),
                dataset="fins_summary",
                code=CODE,
                initial_visible_state=COUNT_ONLY,
            )
            assert owned.state.visible_row_count == count
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    small_n, large_n, payload_size = 25, 250, 4096
    small_peak = peak_bytes(small_n, payload_size)
    large_peak = peak_bytes(large_n, payload_size)
    extra_if_history_retained = (large_n - small_n) * payload_size
    assert large_peak < extra_if_history_retained
    assert large_peak - small_peak < extra_if_history_retained // 2


def test_preready_rejects_before_query(tmp_path) -> None:
    path = tmp_path / "preready.sqlite"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
        "snapshot_ready INTEGER, publication_state TEXT)"
    )
    connection.execute(
        "INSERT INTO local_snapshot_policy VALUES (1, 1, 0, 'BUILDING')"
    )
    connection.commit()
    connection.close()
    with pytest.raises(SnapshotNotReady):
        get_financial_state(
            close_iso("2025-04-01"),
            dataset="fins_summary",
            code=CODE,
            initial_visible_state=COUNT_ONLY,
            db_path=path,
        )


def test_owned_transaction_closes_new_connection_if_ownership_lookup_fails(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "owned.sqlite"
    store = SqliteStore(path)
    write_snapshot_observation_clock(store, CLOCK)
    store.close()
    opened: list[sqlite3.Connection] = []
    real_connect = query_module.connect_readonly

    def tracked(db_path=None):
        conn = real_connect(db_path)
        opened.append(conn)
        return conn

    monkeypatch.setattr(query_module, "connect_readonly", tracked)

    def boom(_path):
        raise RuntimeError("ownership lookup failed")

    monkeypatch.setattr(query_module, "_uses_external_read_transaction", boom)
    with pytest.raises(RuntimeError, match="ownership lookup failed"):
        with query_module._owned_pinned_transaction(path):
            raise AssertionError("must not enter body")
    assert opened
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1")


def test_feature_results_match_catalog_counts_without_owner_fields(
    tmp_path,
) -> None:
    path = _catalog_db(tmp_path)
    store = SqliteStore(path)
    store.upsert(
        "jquants_daily_bars",
        [
            {
                "source": "jquants",
                "code": CODE,
                "date": day,
                "event_time": f"{day}T15:30:00+09:00",
                "available_at": f"{day}T15:30:00+09:00",
                "ingested_at": f"{day}T15:30:00+09:00",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1_000.0,
                "adjustment_close": 100.0,
                "adjustment_volume": 1_000.0,
            }
            for day in ("2023-12-31", "2025-04-01")
        ],
    )
    store.close()
    as_of = close_iso("2025-04-01")
    disclosure = features.compute(
        "disclosure_flag_fins", as_of=as_of, code=CODE, db_path=path
    )
    value = features.compute(
        "retrospective_split_safe_fundamental_value_score",
        as_of=as_of,
        code=CODE,
        db_path=path,
    )
    rows = get_jquants_records(
        as_of=as_of, dataset="fins_summary", code=CODE, db_path=path
    )
    assert disclosure.value == 1.0
    assert disclosure.metadata["rows_seen"] == len(rows.rows) == 5
    assert "selection_evidence_digest" not in disclosure.metadata
    assert "selected_natural_key" not in disclosure.metadata
    observation = latest_fins_per_share_observation(list(rows.rows))
    assert observation is not None
    assert value.value == pytest.approx(observation["bps"] / 100.0)
    assert value.metadata["bps"] == observation["bps"]
    assert value.metadata["split_safety_anchor"] == observation["split_safety_anchor"]
    assert "selection_evidence_digest" not in value.metadata


EPS_JSON = '{"EPS":5,"DisclosedDate":"2023-01-01"}'
BPS_JSON = '{"BPS":10,"DisclosedDate":"2023-01-01"}'
_TYPED_PAYLOADS = {
    "text": EPS_JSON,
    "utf8_blob": EPS_JSON.encode("utf-8"),
    "non_utf8_blob": b"\xff\xfe\x00not-utf8",
}


def _typed_payload_db(tmp_path: Path, payload: str | bytes) -> Path:
    path = tmp_path / "typed.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _catalog_row(
                disc="typed",
                day="2023-01-01",
                event_time="2023-01-01T15:00:00+09:00",
                payload=payload,
                raw_payload=json.loads(BPS_JSON),
            )
        ],
    )
    write_snapshot_observation_clock(store, CLOCK)
    store.close()
    return path


@pytest.mark.parametrize("kind", tuple(_TYPED_PAYLOADS))
def test_sqlite_text_blob_matches_legacy_and_count_only(tmp_path, kind) -> None:
    path = _typed_payload_db(tmp_path, _TYPED_PAYLOADS[kind])
    as_of = close_iso("2023-01-01")
    rows = get_jquants_records(
        as_of=as_of, dataset="fins_summary", code=CODE, db_path=path
    )
    expected = latest_fins_per_share_observation(list(rows.rows))
    owned = _owned(path, as_of, PER_SHARE)
    counted = _read(path, as_of, COUNT_ONLY)
    assert counted.visible_row_count == 1
    assert owned.state.visible_row_count == 1
    assert owned.state.observation == expected
    if kind == "text":
        assert expected is not None
        assert expected["mode"] == "eps_over_price"
        assert expected["eps"] == 5.0
    else:
        assert expected is not None
        assert expected["mode"] == "bps_over_price"
        assert expected["bps"] == 10.0


def test_differing_storage_compute_cannot_share_source_digest(tmp_path) -> None:
    as_of = close_iso("2023-01-01")
    owned = {
        kind: _owned(
            _typed_payload_db(tmp_path / kind, payload), as_of, PER_SHARE
        )
        for kind, payload in _TYPED_PAYLOADS.items()
    }
    computes = {
        kind: dict(item.state.observation or {}) for kind, item in owned.items()
    }
    digests = {kind: item.evidence.digest for kind, item in owned.items()}
    assert computes["text"] != computes["utf8_blob"]
    assert len(set(digests.values())) == len(digests)
    for left, right in combinations(owned, 2):
        if computes[left] != computes[right]:
            assert digests[left] != digests[right]


def test_financial_state_binds_exact_nonblank_code(tmp_path) -> None:
    path = tmp_path / "code.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _catalog_row(
                disc="exact",
                day="2025-04-01",
                payload={"Code": CODE, "BPS": 7.0, "CurPerEn": "2025-03-31"},
            )
        ],
    )
    write_snapshot_observation_clock(store, CLOCK)
    store.close()
    as_of = close_iso("2025-04-01")
    padded = CODE + " "
    padded_catalog = get_jquants_records(
        as_of=as_of, dataset="fins_summary", code=padded, db_path=path
    )
    padded_state = get_financial_state(
        as_of,
        dataset="fins_summary",
        code=padded,
        initial_visible_state=COUNT_ONLY,
        db_path=path,
    )
    exact_catalog = get_jquants_records(
        as_of=as_of, dataset="fins_summary", code=CODE, db_path=path
    )
    exact_state = get_financial_state(
        as_of,
        dataset="fins_summary",
        code=CODE,
        initial_visible_state=COUNT_ONLY,
        db_path=path,
    )
    assert padded_catalog.rows == []
    assert padded_state.visible_row_count == 0
    assert len(exact_catalog.rows) == exact_state.visible_row_count == 1
    with pytest.raises(ValueError, match="code is required"):
        get_financial_state(
            as_of,
            dataset="fins_summary",
            code="  ",
            initial_visible_state=COUNT_ONLY,
            db_path=path,
        )
