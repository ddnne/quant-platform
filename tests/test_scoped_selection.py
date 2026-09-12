"""Private DataPlane AM research selection: clocks, backing, and AM allowlist."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from _coreseed import write_snapshot_observation_clock
from data_contracts.identity import natural_key
from data_contracts.read_scopes import (
    DatasetReadRequirement,
    DatasetReadScope,
    VisibleObservationCount,
)
from ops.receipt_product import (
    canonical_product_artifact_bytes,
    product_row_digest,
)
from pit.query import _iter_query_rows, connect_readonly
from pit.scoped_selection import (
    ScopedBarView,
    ScopedFinancialView,
    ScopedSelectionError,
    _owned_scoped_research_owner,
    sqlite_row_code,
    sqlite_row_event_date,
)
from storage.sqlite_store import SqliteStore

CODE = "8697"
PRIOR_DAY = "2025-04-02"
DECISION_DAY = "2025-04-03"
DECISION = f"{DECISION_DAY}T11:30:00+09:00"
OBSERVED = f"{DECISION_DAY}T16:00:00+09:00"
OLD_AT = f"{PRIOR_DAY}T16:00:00+09:00"
NEW_AT = f"{DECISION_DAY}T16:00:00+09:00"
PM_CLOSE = f"{PRIOR_DAY}T15:30:00+09:00"
D_EVENT = f"{DECISION_DAY}T15:30:00+09:00"
PRODUCT_FIELDS = (
    "source",
    "dataset",
    "natural_key",
    "event_time",
    "available_at",
    "ingested_at",
    "payload",
    "raw_payload",
)


def _open_tx(path: Path):
    conn = connect_readonly(path)
    conn.execute("BEGIN")
    return conn


def _pin_owner(conn, *bodies: str):
    return _owned_scoped_research_owner(conn, product_artifact_bodies=bodies)


def _bars_requirement(*, n: int = 2, split_safety: bool = False) -> DatasetReadRequirement:
    return DatasetReadRequirement(
        consumer_kind="feature",
        consumer_id="retrospective_split_adjusted_momentum_n@1.0.0#0",
        clock="bound_decision_visible_view",
        scope=DatasetReadScope(
            dataset_id="equities_bars_daily",
            observation_count=VisibleObservationCount.literal(n),
            split_safety_anchor_interval=split_safety,
            fields=("adjustment_close", "date"),
            optional_fields=("adjustment_volume", "volume") if split_safety else (),
        ),
    )


def _fins_requirement() -> DatasetReadRequirement:
    return DatasetReadRequirement(
        consumer_kind="feature",
        consumer_id="retrospective_split_safe_fundamental_value_score@1.0.0#0",
        clock="bound_decision_visible_view",
        scope=DatasetReadScope(
            dataset_id="fins_summary",
            initial_visible_state="latest_qualifying_bps_preferred_else_eps",
            fields=("payload", "raw_payload"),
        ),
    )


def _catalog_row(
    *,
    dataset: str,
    payload: dict,
    event_time: str,
    available_at: str | None = None,
    ingested_at: str | None = None,
) -> dict[str, str]:
    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    stamp = available_at or event_time
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": natural_key(payload, dataset),
        "event_time": event_time,
        "available_at": stamp,
        "ingested_at": ingested_at or stamp,
        "payload": payload_text,
        "raw_payload": payload_text,
    }


def _daily_bar_row(
    *,
    day: str,
    adjc: float | None,
    code: str = CODE,
) -> dict[str, str]:
    close_event = D_EVENT if day == DECISION_DAY else f"{day}T15:30:00+09:00"
    stamp = D_EVENT if day == DECISION_DAY else f"{day}T16:00:00+09:00"
    return _catalog_row(
        dataset="equities_bars_daily",
        payload={
            "Code": code,
            "Date": day,
            "C": adjc,
            "AdjC": adjc,
            "MC": adjc,
            "MAdjC": adjc,
        },
        event_time=close_event,
        available_at=stamp,
        ingested_at=stamp,
    )


def _product_rows_from_tables(conn, dataset: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for table in ("jquants_records", "jquants_records_revisions"):
        listing = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if listing is None:
            continue
        for raw in conn.execute(
            "SELECT source, dataset, natural_key, event_time, available_at, "
            "ingested_at, payload, COALESCE(raw_payload, '') AS raw_payload "
            f"FROM {table} WHERE dataset=?",
            (dataset,),
        ):
            rows.append({field: str(raw[field] or "") for field in PRODUCT_FIELDS})
    return rows


def _dataset_product_body(conn, dataset: str) -> str:
    return canonical_product_artifact_bytes(
        _product_rows_from_tables(conn, dataset)
    ).decode("utf-8")


def _payload_adjc(row: dict[str, str]) -> float | None:
    payload = json.loads(row["payload"])
    value = payload.get("AdjC")
    return None if value is None else float(value)


def _seed_revision_bars(tmp_path: Path) -> Path:
    path = tmp_path / "scoped.sqlite"
    store = SqliteStore(path)
    prior_old = _catalog_row(
        dataset="equities_bars_daily",
        payload={
            "Code": CODE,
            "Date": PRIOR_DAY,
            "C": 100.0,
            "AdjC": 100.0,
            "MC": 99.0,
            "MAdjC": 99.0,
        },
        event_time=PM_CLOSE,
        available_at=OLD_AT,
        ingested_at=OLD_AT,
    )
    store.upsert("jquants_records", [prior_old])
    prior_new = _catalog_row(
        dataset="equities_bars_daily",
        payload={
            "Code": CODE,
            "Date": PRIOR_DAY,
            "C": 110.0,
            "AdjC": 110.0,
            "MC": 99.0,
            "MAdjC": 99.0,
        },
        event_time=PM_CLOSE,
        available_at=NEW_AT,
        ingested_at=NEW_AT,
    )
    store.upsert("jquants_records", [prior_new])
    same_day = _catalog_row(
        dataset="equities_bars_daily",
        payload={
            "Code": CODE,
            "Date": DECISION_DAY,
            "C": 200.0,
            "AdjC": 200.0,
            "MC": 10.0,
            "MAdjC": 10.0,
            "AAdjC": 999.0,
            "Volume": 123456,
        },
        event_time=D_EVENT,
        available_at=D_EVENT,
        ingested_at=D_EVENT,
    )
    store.upsert("jquants_records", [same_day])
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    return path


def test_prior_rows_rank_at_decision_not_observed_through(tmp_path: Path) -> None:
    path = _seed_revision_bars(tmp_path)
    conn = connect_readonly(path)
    conn.row_factory = __import__("sqlite3").Row
    conn.execute("BEGIN")
    try:
        decision_rows = list(
            _iter_query_rows(
                conn,
                as_of=DECISION,
                table="jquants_records",
                dataset_id="equities_bars_daily",
                extra_where="dataset = ? AND substr(event_time, 1, 10) < ?",
                params=["equities_bars_daily", DECISION_DAY],
                order_by="event_time, natural_key, source",
            )
        )
        assert len(decision_rows) == 1
        payload = json.loads(decision_rows[0]["payload"])
        assert payload["AdjC"] == 100.0

        observed_rows = list(
            _iter_query_rows(
                conn,
                as_of=OBSERVED,
                table="jquants_records",
                dataset_id="equities_bars_daily",
                extra_where="dataset = ? AND substr(event_time, 1, 10) < ?",
                params=["equities_bars_daily", DECISION_DAY],
                order_by="event_time, natural_key, source",
            )
        )
        assert len(observed_rows) == 1
        assert json.loads(observed_rows[0]["payload"])["AdjC"] == 110.0

        stored = _product_rows_from_tables(conn, "equities_bars_daily")
        old_body = canonical_product_artifact_bytes(
            [row for row in stored if _payload_adjc(row) == 100.0]
        ).decode("utf-8")
        new_and_d = canonical_product_artifact_bytes(
            [row for row in stored if _payload_adjc(row) != 100.0]
        ).decode("utf-8")
        owner = _pin_owner(conn, old_body, new_and_d)
        selected = owner.select_am_research_scope(
            requirement=_bars_requirement(n=2),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
        )
        assert isinstance(selected, tuple)
        assert len(selected) == 2
        prior, current = selected
        assert isinstance(prior, ScopedBarView)
        assert prior.date == PRIOR_DAY
        assert prior.adjustment_close == 100.0
        assert prior.contemporaneous_observation_unproven is False
        assert current.date == DECISION_DAY
        assert current.same_day_am is True
        assert current.adjustment_close == 10.0
        assert current.close == 10.0
        assert current.volume is None
        assert current.contemporaneous_observation_unproven is True
        public = json.dumps(
            {
                "code": current.code,
                "date": current.date,
                "natural_key": current.natural_key,
                "close": current.close,
                "adjustment_close": current.adjustment_close,
                "volume": current.volume,
                "adjustment_volume": current.adjustment_volume,
                "field_evidence": dict(current.field_evidence),
                "product_row_digest": current.product_row_digest,
            },
            default=str,
        )
        assert "AAdjC" not in public
        assert "999" not in public
        assert "123456" not in public
        assert "Volume" not in public
        old_digest = product_row_digest(
            next(row for row in stored if _payload_adjc(row) == 100.0)
        )
        assert prior.product_row_digest == old_digest
        with pytest.raises(ScopedSelectionError, match="not backed"):
            _pin_owner(conn, new_and_d).select_am_research_scope(
                requirement=_bars_requirement(n=2),
                decision_as_of=DECISION,
                observed_through=OBSERVED,
                codes=(CODE,),
            )
    finally:
        conn.rollback()
        conn.close()


def test_financial_sqlite_row_without_date_uses_event_time(tmp_path: Path) -> None:
    path = tmp_path / "fins.sqlite"
    store = SqliteStore(path)
    payload = {
        "Code": CODE,
        "DiscDate": "2025-04-01",
        "DiscTime": "12:00:00",
        "DiscNo": "1",
        "BPS": 80.0,
        "CurPerEn": "2025-03-31",
    }
    row = _catalog_row(
        dataset="fins_summary",
        payload=payload,
        event_time="2025-04-01T12:00:00+09:00",
    )
    store.upsert("jquants_records", [row])
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = connect_readonly(path)
    conn.row_factory = __import__("sqlite3").Row
    conn.execute("BEGIN")
    try:
        raw = conn.execute(
            "SELECT source, dataset, natural_key, event_time, available_at, "
            "ingested_at, payload, raw_payload FROM jquants_records "
            "WHERE dataset='fins_summary'"
        ).fetchone()
        assert not hasattr(raw, "get")
        assert sqlite_row_event_date(raw) == "2025-04-01"
        assert sqlite_row_code(raw) == CODE
        body = canonical_product_artifact_bytes(
            _product_rows_from_tables(conn, "fins_summary")
        ).decode("utf-8")
        selected = _pin_owner(conn, body).select_am_research_scope(
            requirement=_fins_requirement(),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
        )
        assert isinstance(selected, ScopedFinancialView)
        assert selected.state.visible_row_count == 1
        assert selected.state.observation is not None
        assert selected.state.observation["bps"] == 80.0
        assert selected.split_safety_anchor == "2025-03-31"
        assert selected.selected_natural_key == row["natural_key"]
        assert selected.selected_product_digest == product_row_digest(
            _product_rows_from_tables(conn, "fins_summary")[0]
        )
    finally:
        conn.rollback()
        conn.close()


def test_complete_master_and_pm_clocks_are_not_silent_skips() -> None:
    master = DatasetReadRequirement(
        consumer_kind="universe",
        consumer_id="tse_prime_with_fins@universe-dependency/v1",
        clock="bound_decision_visible_view",
        scope=DatasetReadScope(
            dataset_id="equities_master",
            initial_visible_state="latest_complete_snapshot_plus_updates",
            fields=("code", "market_code", "snapshot_date"),
        ),
    )
    with pytest.raises(ScopedSelectionError, match="complete-master"):
        _require = __import__(
            "pit.scoped_selection", fromlist=["_require_am_requirement"]
        )._require_am_requirement
        _require(master)
    pm = DatasetReadRequirement(
        consumer_kind="fill_pm_valuation",
        consumer_id="fill@1",
        clock="same_trading_date_pm_close",
        scope=DatasetReadScope(
            dataset_id="equities_bars_daily",
            fields=("adjustment_close", "date"),
        ),
    )
    with pytest.raises(ScopedSelectionError, match="PM valuation"):
        _require(pm)


def test_scale_category_remains_declarable_for_real_consumers() -> None:
    scope = DatasetReadScope(
        dataset_id="equities_master",
        fields=("code", "market_code", "scale_category", "snapshot_date"),
    )
    assert "scale_category" in scope.fields


def test_no_per_share_observation_does_not_force_split_window(
    tmp_path: Path,
) -> None:
    path = tmp_path / "no-value.sqlite"
    store = SqliteStore(path)
    fins = _catalog_row(
        dataset="fins_summary",
        payload={
            "Code": CODE,
            "DiscDate": "2025-04-01",
            "DiscTime": "12:00:00",
            "DiscNo": "1",
            "NetSales": 1.0,
            "CurPerEn": "2025-03-31",
        },
        event_time="2025-04-01T12:00:00+09:00",
    )
    bar = _catalog_row(
        dataset="equities_bars_daily",
        payload={
            "Code": CODE,
            "Date": DECISION_DAY,
            "C": 200.0,
            "AdjC": 200.0,
            "MC": 10.0,
            "MAdjC": 10.0,
        },
        event_time=D_EVENT,
        available_at=D_EVENT,
        ingested_at=D_EVENT,
    )
    store.upsert("jquants_records", [fins, bar])
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = connect_readonly(path)
    conn.row_factory = __import__("sqlite3").Row
    conn.execute("BEGIN")
    try:
        owner = _pin_owner(
            conn,
            _dataset_product_body(conn, "fins_summary"),
            _dataset_product_body(conn, "equities_bars_daily"),
        )
        financial = owner.select_am_research_scope(
            requirement=_fins_requirement(),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
        )
        assert isinstance(financial, ScopedFinancialView)
        assert financial.state.observation is None
        assert financial.state.no_value_reason == "no BPS or EPS"
        assert financial.split_safety_anchor is None
        assert financial.selected_product_digest is None
        assert financial.field_evidence["payload"] == "present_value"
        bars = owner.select_am_research_scope(
            requirement=_bars_requirement(n=1, split_safety=True),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
            split_anchor=financial.split_safety_anchor,
        )
        assert isinstance(bars, tuple)
        assert len(bars) == 1
        assert bars[0].same_day_am is True
        assert not hasattr(bars[0], "afternoon_adjustment_close")
        assert bars[0].volume is None
    finally:
        conn.rollback()
        conn.close()


def test_invalid_split_anchor_does_not_raise_or_open_window(tmp_path: Path) -> None:
    path = tmp_path / "invalid-anchor.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _daily_bar_row(day="2025-03-10", adjc=70.0),
            _daily_bar_row(day="2025-03-20", adjc=80.0),
            _daily_bar_row(day=DECISION_DAY, adjc=10.0),
        ],
    )
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = _open_tx(path)
    try:
        selected = _pin_owner(
            conn, _dataset_product_body(conn, "equities_bars_daily")
        ).select_am_research_scope(
            requirement=_bars_requirement(n=1, split_safety=True),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
            split_anchor="not-a-date",
        )
        assert isinstance(selected, tuple)
        assert len(selected) == 1
        assert selected[0].date == DECISION_DAY
    finally:
        conn.rollback()
        conn.close()


def test_latest_quote_older_than_split_window_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "old-latest.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [_daily_bar_row(day="2024-12-01", adjc=50.0)],
    )
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = _open_tx(path)
    try:
        selected = _pin_owner(
            conn, _dataset_product_body(conn, "equities_bars_daily")
        ).select_am_research_scope(
            requirement=_bars_requirement(n=1, split_safety=True),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
            split_anchor="2025-03-31",
        )
        assert isinstance(selected, tuple)
        assert len(selected) == 1
        assert selected[0].date == "2024-12-01"
        assert selected[0].adjustment_close == 50.0
    finally:
        conn.rollback()
        conn.close()


def test_present_null_latest_observation_counts_for_latest_n(
    tmp_path: Path,
) -> None:
    path = tmp_path / "present-null.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _daily_bar_row(day="2025-04-01", adjc=100.0),
            _daily_bar_row(day=PRIOR_DAY, adjc=None),
        ],
    )
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = _open_tx(path)
    try:
        selected = _pin_owner(
            conn, _dataset_product_body(conn, "equities_bars_daily")
        ).select_am_research_scope(
            requirement=_bars_requirement(n=1),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
        )
        assert isinstance(selected, tuple)
        assert len(selected) == 1
        assert selected[0].date == PRIOR_DAY
        assert selected[0].adjustment_close is None
        assert selected[0].field_evidence["adjustment_close"] == "present_null"
    finally:
        conn.rollback()
        conn.close()


def test_fulfilled_code_is_not_validated_while_waiting_on_another_code(
    tmp_path: Path,
) -> None:
    other = "1332"
    path = tmp_path / "two-code.sqlite"
    store = SqliteStore(path)
    valid_a = _daily_bar_row(day=DECISION_DAY, adjc=10.0)
    valid_b = _daily_bar_row(day="2025-03-01", adjc=9.0, code=other)
    invalid_a = _catalog_row(
        dataset="equities_bars_daily",
        payload={"Code": CODE, "Date": "2025-03-15", "C": 1.0},
        event_time="2025-03-15T15:30:00+09:00",
        available_at="2025-03-15T16:00:00+09:00",
        ingested_at="2025-03-15T16:00:00+09:00",
    )
    store.upsert("jquants_records", [valid_a, invalid_a, valid_b])
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = _open_tx(path)
    try:
        stored = _product_rows_from_tables(conn, "equities_bars_daily")
        body = canonical_product_artifact_bytes(
            [row for row in stored if _payload_adjc(row) is not None]
        ).decode("utf-8")
        selected = _pin_owner(conn, body).select_am_research_scope(
            requirement=_bars_requirement(n=1),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE, other),
        )
        assert isinstance(selected, tuple)
        assert [(row.code, row.date) for row in selected] == [
            (CODE, DECISION_DAY),
            (other, "2025-03-01"),
        ]
    finally:
        conn.rollback()
        conn.close()


def test_full_segment_extra_keys_do_not_expand_research_scope(
    tmp_path: Path,
) -> None:
    extra = "1332"
    path = tmp_path / "extra-keys.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _daily_bar_row(day=DECISION_DAY, adjc=10.0),
            _daily_bar_row(day=DECISION_DAY, adjc=9.0, code=extra),
        ],
    )
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = _open_tx(path)
    try:
        selected = _pin_owner(
            conn, _dataset_product_body(conn, "equities_bars_daily")
        ).select_am_research_scope(
            requirement=_bars_requirement(n=1),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
        )
        assert isinstance(selected, tuple)
        assert len(selected) == 1
        assert selected[0].code == CODE
    finally:
        conn.rollback()
        conn.close()


def test_unpinned_connection_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "unpinned.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [_daily_bar_row(day=PRIOR_DAY, adjc=1.0)],
    )
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = connect_readonly(path)
    try:
        with pytest.raises(ScopedSelectionError, match="active SQLite transaction"):
            _pin_owner(conn, _dataset_product_body(conn, "equities_bars_daily"))
    finally:
        conn.close()


def test_supplied_observed_through_must_match_snapshot_clock(
    tmp_path: Path,
) -> None:
    late = f"{DECISION_DAY}T18:00:00+09:00"
    supplied = f"{DECISION_DAY}T16:00:00+09:00"
    path = tmp_path / "clock-mismatch.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [
            _catalog_row(
                dataset="equities_bars_daily",
                payload={
                    "Code": CODE,
                    "Date": PRIOR_DAY,
                    "C": 50.0,
                    "AdjC": 50.0,
                    "MC": 50.0,
                    "MAdjC": 50.0,
                },
                event_time=PM_CLOSE,
                available_at=OLD_AT,
                ingested_at=f"{DECISION_DAY}T17:00:00+09:00",
            )
        ],
    )
    write_snapshot_observation_clock(store, late)
    store.close()
    conn = _open_tx(path)
    try:
        with pytest.raises(ScopedSelectionError, match="observation clock"):
            _pin_owner(
                conn, _dataset_product_body(conn, "equities_bars_daily")
            ).select_am_research_scope(
                requirement=_bars_requirement(n=1),
                decision_as_of=DECISION,
                observed_through=supplied,
                codes=(CODE,),
            )
    finally:
        conn.rollback()
        conn.close()


def test_fill_am_mark_is_rejected_and_feature_selection_still_works(
    tmp_path: Path,
) -> None:
    path = tmp_path / "am-mark.sqlite"
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        [_daily_bar_row(day=DECISION_DAY, adjc=10.0)],
    )
    write_snapshot_observation_clock(store, OBSERVED)
    store.close()
    conn = _open_tx(path)
    try:
        owner = _pin_owner(
            conn, _dataset_product_body(conn, "equities_bars_daily")
        )
        mark = DatasetReadRequirement(
            consumer_kind="fill_am_mark",
            consumer_id="fill@1",
            clock="bound_decision_visible_view",
            scope=DatasetReadScope(
                dataset_id="equities_bars_daily",
                fields=("adjustment_close", "date"),
            ),
        )
        with pytest.raises(ScopedSelectionError, match="AM mark"):
            owner.select_am_research_scope(
                requirement=mark,
                decision_as_of=DECISION,
                observed_through=OBSERVED,
                codes=(CODE,),
            )
        selected = owner.select_am_research_scope(
            requirement=_bars_requirement(n=1),
            decision_as_of=DECISION,
            observed_through=OBSERVED,
            codes=(CODE,),
        )
        assert isinstance(selected, tuple)
        assert len(selected) == 1
        assert selected[0].same_day_am is True
    finally:
        conn.rollback()
        conn.close()
