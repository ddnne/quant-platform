"""W59 / w0815az_g1 — R2 structured history → FeatureContext bridge tests.

Covers: T2 schema mapping, T3 loader, T4 PIT available_at, T5 DEFER hard reject.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from research.r2_feature_context import (
    AVAILABLE_AT_REPAIR_POLICY,
    BRIDGE_EXPAND_DATASETS,
    COMPLETE_21_R2_INVENTORY,
    FEATURE_CONTEXT_SCHEMA_MAP,
    HISTORY_SOURCE_R2,
    MULTI_SIGNAL_HISTORY_DATASETS,
    R2FeatureContextError,
    S1_SIGNAL_HISTORY_DATASETS,
    available_at_policy_document,
    build_r2_feature_context,
    can_build_40d_asof,
    extract_r2_history_feature_rows,
    filter_history_rows,
    materialize_disposable_sqlite_mirror,
    normalize_r2_history_row,
    parse_r2_structured_line,
    r2_inventory_document,
    repair_available_at_research,
    resolve_history_source,
    schema_mapping_document,
    write_r2_inventory_json,
)
from research.single_shot_job import (
    DEFAULT_CANDIDATE_FEATURES,
    compute_tip_candidate_features,
    execute_multiday_multisignal_compare,
    execute_multiday_signal_eval,
)


def _bar_line(
    code: str,
    day: str,
    *,
    close: float = 100.0,
    volume: float = 1000.0,
    available_at: str | None = None,
    event_time: str | None = None,
) -> str:
    aa = available_at if available_at is not None else f"{day}T15:30:00+09:00"
    et = event_time if event_time is not None else f"{day}T15:30:00+09:00"
    payload = {
        "Code": code,
        "Date": day,
        "O": close,
        "H": close,
        "L": close,
        "C": close,
        "Vo": volume,
    }
    return json.dumps(
        {
            "source": "jquants",
            "dataset": "equities_bars_daily",
            "natural_key": json.dumps({"Code": code, "Date": day}, sort_keys=True),
            "event_time": et,
            "available_at": aa,
            "ingested_at": "2026-08-12T00:00:00+09:00",
            "payload": payload,
            "raw_payload": payload,
        },
        ensure_ascii=True,
    )


def _topix_line(
    day: str,
    *,
    close: float = 3000.0,
    available_at: str | None = None,
) -> str:
    aa = available_at if available_at is not None else f"{day}T15:30:00+09:00"
    payload = {"Date": day, "C": close, "O": close, "H": close, "L": close}
    return json.dumps(
        {
            "source": "jquants",
            "dataset": "indices_bars_daily_topix",
            "natural_key": json.dumps({"Date": day}, sort_keys=True),
            "event_time": f"{day}T15:30:00+09:00",
            "available_at": aa,
            "ingested_at": "2026-08-12T00:00:00+09:00",
            "payload": payload,
            "raw_payload": payload,
        },
        ensure_ascii=True,
    )


def _cal_line(
    day: str,
    *,
    hol: str = "1",
    available_at: str | None = None,
) -> str:
    aa = available_at if available_at is not None else f"{day}T09:00:00+09:00"
    payload = {"Date": day, "HolDiv": hol}
    return json.dumps(
        {
            "source": "jquants",
            "dataset": "markets_calendar",
            "natural_key": json.dumps({"Date": day}, sort_keys=True),
            "event_time": f"{day}T00:00:00+09:00",
            "available_at": aa,
            "ingested_at": aa,
            "payload": payload,
            "raw_payload": payload,
        },
        ensure_ascii=True,
    )


# ---------------------------------------------------------------------------
# T1 inventory
# ---------------------------------------------------------------------------


def test_t1_inventory_covers_complete_21_and_excludes_defer():
    doc = r2_inventory_document()
    assert doc["complete_21_count"] == 21
    assert len(doc["complete_21"]) == 21
    assert doc["permanent_defer_count"] == 5
    assert set(doc["permanent_defer_excluded"]) == PERMANENT_DEFER_DATASETS
    for ds in S1_SIGNAL_HISTORY_DATASETS:
        inv = COMPLETE_21_R2_INVENTORY[ds]
        assert inv["jsonl_prefix"].startswith("structured/jsonl/")
        assert inv["archive_prefix"].startswith("archive/jquants_records/")
    # DEFER must not appear in COMPLETE inventory
    assert not (set(doc["complete_21"]) & PERMANENT_DEFER_DATASETS)


def test_t1_write_inventory_json(tmp_path: Path):
    out = write_r2_inventory_json(tmp_path / "t1_r2_inventory.json")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["complete_21_count"] == 21
    assert loaded["local_sot"] is False


# ---------------------------------------------------------------------------
# T2 schema
# ---------------------------------------------------------------------------


def test_t2_schema_mapping_has_s1_datasets():
    doc = schema_mapping_document()
    assert "equities_bars_daily" in doc["s1_column_map"]
    assert "indices_bars_daily_topix" in doc["s1_column_map"]
    assert "markets_calendar" in doc["s1_column_map"]
    assert FEATURE_CONTEXT_SCHEMA_MAP["equity_bars_daily"]["dataset"] == (
        "equities_bars_daily"
    )
    assert doc["pit_gate"]["null_available_at"] == "excluded (hard)"


def test_parse_and_normalize_bar_preserves_available_at_code_date():
    line = _bar_line("13010", "2026-06-02", close=110.0, volume=200.0)
    env = parse_r2_structured_line(line)
    assert env is not None
    assert env["dataset"] == "equities_bars_daily"
    assert env["available_at"] == "2026-06-02T15:30:00+09:00"
    row = normalize_r2_history_row(env)
    assert row is not None
    assert row["code"] == "13010"
    assert row["date"] == "2026-06-02"
    assert row["close"] == pytest.approx(110.0)
    assert row["volume"] == pytest.approx(200.0)
    assert row["available_at"] == "2026-06-02T15:30:00+09:00"
    assert row["event_time"] == "2026-06-02T15:30:00+09:00"


def test_parse_payload_as_json_string():
    """Live R2 sometimes stores payload as a JSON string (see W58 samples)."""
    line = json.dumps(
        {
            "source": "jquants",
            "dataset": "equities_bars_daily",
            "natural_key": '{"Code":"13010","Date":"2008-05-07"}',
            "event_time": "2008-05-07T15:00:00+09:00",
            "available_at": "2008-05-07T15:00:00+09:00",
            "ingested_at": "2026-08-12T23:17:26+09:00",
            "payload": json.dumps(
                {"Code": "13010", "Date": "2008-05-07", "C": 176, "Vo": 302000}
            ),
            "raw_payload": None,
        }
    )
    env = parse_r2_structured_line(line)
    assert env is not None
    assert isinstance(env["payload"], dict)
    row = normalize_r2_history_row(env)
    assert row is not None
    assert row["code"] == "13010"
    assert row["close"] == pytest.approx(176.0)


# ---------------------------------------------------------------------------
# T5 DEFER hard reject
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("defer_ds", sorted(PERMANENT_DEFER_DATASETS))
def test_t5_defer_hard_reject_on_extract(defer_ds: str):
    with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
        extract_r2_history_feature_rows(
            ["equities_bars_daily", defer_ds],
            period_start="2026-06-01",
            period_end="2026-06-10",
            raw_lines_by_dataset={"equities_bars_daily": [_bar_line("13010", "2026-06-02")]},
        )


def test_t5_defer_hard_reject_on_build_context():
    with pytest.raises(PermanentDeferHistoryError):
        build_r2_feature_context(
            {"equities_master": [{"code": "x", "available_at": "2026-01-01"}]},
            as_of="2026-08-04T15:30:00+09:00",
        )


def test_t5_defer_hard_reject_on_sqlite_mirror(tmp_path: Path):
    with pytest.raises(PermanentDeferHistoryError):
        materialize_disposable_sqlite_mirror(
            {"fins_earnings_date": [{"available_at": "x"}]},
            db_path=tmp_path / "x.sqlite",
        )


# ---------------------------------------------------------------------------
# T3 extract + FeatureContext + features
# ---------------------------------------------------------------------------


def test_extract_r2_history_filters_window_and_codes():
    lines = [
        _bar_line("13010", "2026-05-30", close=90.0),  # before window
        _bar_line("13010", "2026-06-02", close=100.0, volume=100.0),
        _bar_line("13010", "2026-06-03", close=110.0, volume=150.0),
        _bar_line("72030", "2026-06-02", close=2000.0),  # other code
        _bar_line("13010", "2026-06-20", close=120.0),  # after window
    ]
    topix = [
        _topix_line("2026-06-02", close=3000.0),
        _topix_line("2026-06-03", close=3030.0),
    ]
    cal = [
        _cal_line("2026-06-02"),
        _cal_line("2026-06-03"),
    ]
    out = extract_r2_history_feature_rows(
        list(S1_SIGNAL_HISTORY_DATASETS),
        period_start="2026-06-01",
        period_end="2026-06-10",
        codes=["13010"],
        raw_lines_by_dataset={
            "equities_bars_daily": lines,
            "indices_bars_daily_topix": topix,
            "markets_calendar": cal,
        },
    )
    assert out["history_source"] == HISTORY_SOURCE_R2
    assert out["local_sot"] is False
    assert out["plane"] == "R2_history"
    bars = out["rows_by_dataset"]["equities_bars_daily"]
    assert len(bars) == 2
    assert {r["date"] for r in bars} == {"2026-06-02", "2026-06-03"}
    assert all(r["code"] == "13010" for r in bars)
    assert out["extracted_row_counts"]["indices_bars_daily_topix"] == 2
    assert out["extracted_row_counts"]["markets_calendar"] == 2


def test_build_r2_feature_context_computes_candidates():
    extract = extract_r2_history_feature_rows(
        list(S1_SIGNAL_HISTORY_DATASETS),
        period_start="2026-06-01",
        period_end="2026-06-10",
        codes=["13010"],
        raw_lines_by_dataset={
            "equities_bars_daily": [
                _bar_line("13010", "2026-06-02", close=100.0, volume=100.0),
                _bar_line("13010", "2026-06-03", close=110.0, volume=150.0),
            ],
            "indices_bars_daily_topix": [
                _topix_line("2026-06-02", close=3000.0),
                _topix_line("2026-06-03", close=3030.0),
            ],
            "markets_calendar": [
                _cal_line("2026-06-02"),
                _cal_line("2026-06-03"),
            ],
        },
    )
    rows = extract["rows_by_dataset"]
    as_of = "2026-06-03T15:30:00+09:00"
    ctx = build_r2_feature_context(rows, as_of=as_of, inputs={"code": "13010"})
    bars = ctx.get_equity_bars_daily(code="13010")
    assert bars.metadata["plane"] == "R2_history"
    assert bars.metadata["source"] == "cloudflare_r2_structured"
    assert len(bars.rows) == 2

    result = compute_tip_candidate_features(
        rows,
        as_of=as_of,
        feature_ids=DEFAULT_CANDIDATE_FEATURES,
        codes=["13010"],
        dates=["2026-06-03"],
    )
    by_id = {f["feature_id"]: f for f in result["features"]}
    assert by_id["volume_change_1d"]["sample_values"][0]["value"] == pytest.approx(0.5)
    # equity ret 0.10 - topix ret 0.01 = 0.09
    assert by_id["topix_relative_1d"]["sample_values"][0]["value"] == pytest.approx(0.09)
    assert by_id["is_trading_day"]["sample_values"][0]["value"] == pytest.approx(1.0)


def test_r2_get_channel_via_injectable(tmp_path: Path):
    body = (
        _bar_line("13010", "2026-06-02")
        + "\n"
        + _bar_line("13010", "2026-06-03")
        + "\n"
    ).encode("utf-8")

    def fake_get(bucket: str, key: str) -> bytes:
        assert bucket == "quant-structured"
        assert "equities_bars_daily" in key
        return body

    out = extract_r2_history_feature_rows(
        ["equities_bars_daily"],
        period_start="2026-06-01",
        period_end="2026-06-10",
        codes=["13010"],
        object_keys_by_dataset={
            "equities_bars_daily": [
                "structured/jsonl/equities_bars_daily/dt=2026-06-02/run.jsonl"
            ]
        },
        r2_get=fake_get,
    )
    assert out["extracted_row_counts"]["equities_bars_daily"] == 2


# ---------------------------------------------------------------------------
# T4 PIT — no look-ahead
# ---------------------------------------------------------------------------


def test_t4_pit_excludes_future_available_at():
    rows = {
        "equities_bars_daily": [
            {
                "code": "13010",
                "date": "2026-06-02",
                "close": 100.0,
                "volume": 100.0,
                "available_at": "2026-06-02T15:30:00+09:00",
                "event_time": "2026-06-02T15:30:00+09:00",
            },
            {
                "code": "13010",
                "date": "2026-06-03",
                "close": 110.0,
                "volume": 150.0,
                # T+1 bar not yet available at T close
                "available_at": "2026-06-03T15:30:00+09:00",
                "event_time": "2026-06-03T15:30:00+09:00",
            },
        ]
    }
    as_of_t = "2026-06-02T15:30:00+09:00"
    ctx = build_r2_feature_context(rows, as_of=as_of_t)
    bars = ctx.get_equity_bars_daily(code="13010")
    assert len(bars.rows) == 1
    assert bars.rows[0]["date"] == "2026-06-02"


def test_t4_null_available_at_excluded_on_load_and_context():
    lines = [
        _bar_line("13010", "2026-06-02", available_at=""),
        _bar_line("13010", "2026-06-03"),
    ]
    # empty string available_at on first line
    bad = json.loads(lines[0])
    bad["available_at"] = None
    lines[0] = json.dumps(bad)
    out = extract_r2_history_feature_rows(
        ["equities_bars_daily"],
        period_start="2026-06-01",
        period_end="2026-06-10",
        raw_lines_by_dataset={"equities_bars_daily": lines},
    )
    # filter_history_rows drops null available_at
    assert out["extracted_row_counts"]["equities_bars_daily"] == 1

    # even if smuggled into store, PIT reader drops them
    smuggled = {
        "equities_bars_daily": [
            {
                "code": "13010",
                "date": "2026-06-02",
                "close": 1.0,
                "available_at": None,
            },
            {
                "code": "13010",
                "date": "2026-06-03",
                "close": 2.0,
                "available_at": "2026-06-03T15:30:00+09:00",
            },
        ]
    }
    ctx = build_r2_feature_context(
        smuggled, as_of="2026-06-03T15:30:00+09:00"
    )
    assert len(ctx.get_equity_bars_daily(code="13010").rows) == 1


def test_filter_history_rows_require_available_at():
    rows = [
        {"date": "2026-06-02", "available_at": None, "code": "1"},
        {"date": "2026-06-02", "available_at": "2026-06-02T15:30:00+09:00", "code": "1"},
    ]
    assert len(filter_history_rows(rows, require_available_at=True)) == 1


# ---------------------------------------------------------------------------
# Disposable mirror (not SoT) + 40d capability
# ---------------------------------------------------------------------------


def test_disposable_sqlite_mirror_not_sot(tmp_path: Path):
    extract = extract_r2_history_feature_rows(
        ["equities_bars_daily", "markets_calendar"],
        period_start="2026-06-01",
        period_end="2026-06-10",
        codes=["13010"],
        raw_lines_by_dataset={
            "equities_bars_daily": [
                _bar_line("13010", "2026-06-02"),
                _bar_line("13010", "2026-06-03"),
            ],
            "markets_calendar": [_cal_line("2026-06-02"), _cal_line("2026-06-03")],
        },
    )
    path = materialize_disposable_sqlite_mirror(
        extract["rows_by_dataset"], db_path=tmp_path / "mirror.sqlite"
    )
    assert path.is_file()
    # Mirror exists for pit convenience only — extract still marks local_sot False
    assert extract["local_sot"] is False
    assert extract["disposable_mirror"] is True


def test_can_build_40d_asof_code_path_yes():
    cap = can_build_40d_asof(None)
    assert cap["can_build_40d_asof"] is True
    assert cap["code_path"] is True


def test_can_build_40d_asof_with_rows():
    # 45 trading-ish days synthetic
    days = [f"2026-04-{(i % 28) + 1:02d}" for i in range(45)]
    # make unique sequential-ish by month rollover hack — use iso via ordinal
    from datetime import date, timedelta

    start = date(2026, 4, 1)
    days = [(start + timedelta(days=i)).isoformat() for i in range(60)]
    # keep weekdays only
    days = [d for d in days if date.fromisoformat(d).weekday() < 5][:45]
    bars = [
        {
            "code": "13010",
            "date": d,
            "close": 100.0 + i,
            "available_at": f"{d}T15:30:00+09:00",
        }
        for i, d in enumerate(days)
    ]
    topix = [
        {
            "date": d,
            "close": 3000.0,
            "available_at": f"{d}T15:30:00+09:00",
            "event_time": f"{d}T15:30:00+09:00",
        }
        for d in days
    ]
    cap = can_build_40d_asof(
        {"equities_bars_daily": bars, "indices_bars_daily_topix": topix},
        min_trading_days=40,
    )
    assert cap["can_build_40d_asof"] is True
    assert cap["equities_bars_trading_days"] >= 40


def test_resolve_history_source():
    assert resolve_history_source(None) == "d1_tip"
    assert resolve_history_source("r2") == "r2"
    assert resolve_history_source("d1_tip") == "d1_tip"
    with pytest.raises(R2FeatureContextError):
        resolve_history_source("postgres")


def test_multiday_history_source_r2_does_not_break_default_d1(tmp_path: Path):
    """history_source=r2 with fixtures works; default remains d1_tip path."""
    # Build 8 weekdays of synthetic R2 history for multiday min_days=5
    from datetime import date, timedelta

    start = date(2026, 6, 1)
    days = []
    d = start
    while len(days) < 8:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)

    bar_lines = []
    topix_lines = []
    cal_lines = []
    for i, day in enumerate(days):
        for code in ("13010", "72030", "67580"):
            bar_lines.append(
                _bar_line(
                    code,
                    day,
                    close=100.0 + i,
                    volume=1000.0 + i * 10,
                )
            )
        topix_lines.append(_topix_line(day, close=3000.0 + i))
        cal_lines.append(_cal_line(day))

    puts: list[tuple[str, str]] = []

    def fake_put(bucket: str, key: str, body: bytes, **kwargs):
        puts.append((bucket, key))
        return {"bucket": bucket, "key": key, "status": "dry_run", "bytes": len(body)}

    ex = execute_multiday_signal_eval(
        period_start=days[0],
        period_end=days[-1],
        job_id="w0815az-g1-r2-bridge-test",
        codes=["13010", "72030", "67580"],
        max_days=10,
        min_days=5,
        dry_run=True,
        write_per_day_artifacts=False,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
        r2_raw_lines_by_dataset={
            "equities_bars_daily": bar_lines,
            "indices_bars_daily_topix": topix_lines,
            "markets_calendar": cal_lines,
        },
    )
    assert ex.n_days >= 5
    assert ex.ready_declared is False
    assert ex.mass_research == "NO-GO"
    assert ex.batch_summary["history_source"] == "r2"
    assert ex.batch_summary["tip_plane"] == "R2_history"


# ---------------------------------------------------------------------------
# W60 — bridge expand (margin/short/fins/alert) + multi-signal R2 + aa policy
# ---------------------------------------------------------------------------


def _catalog_line(
    dataset: str,
    day: str,
    *,
    code: str | None = "13010",
    available_at: str | None = None,
    extra_payload: dict | None = None,
) -> str:
    aa = available_at if available_at is not None else f"{day}T15:30:00+09:00"
    payload = {"Date": day, **(extra_payload or {})}
    if code is not None:
        payload["Code"] = code
    nk: dict = {"Date": day}
    if code is not None:
        nk["Code"] = code
    if "S33" in payload:
        nk = {"Date": day, "S33": payload["S33"]}
    return json.dumps(
        {
            "source": "jquants",
            "dataset": dataset,
            "natural_key": json.dumps(nk, sort_keys=True),
            "event_time": f"{day}T15:30:00+09:00",
            "available_at": aa,
            "ingested_at": "2026-08-12T00:00:00+09:00",
            "payload": payload,
            "raw_payload": payload,
        },
        ensure_ascii=True,
    )


def test_bridge_expand_datasets_listed():
    assert "markets_margin_interest" in BRIDGE_EXPAND_DATASETS
    assert "markets_short_ratio" in BRIDGE_EXPAND_DATASETS
    assert "fins_summary" in BRIDGE_EXPAND_DATASETS
    assert "markets_margin_alert" in BRIDGE_EXPAND_DATASETS
    inv = r2_inventory_document()
    assert set(BRIDGE_EXPAND_DATASETS).issubset(set(COMPLETE_21_R2_INVENTORY))
    assert inv["bridge_expand_datasets"] == list(BRIDGE_EXPAND_DATASETS)
    sm = schema_mapping_document()
    for ds in BRIDGE_EXPAND_DATASETS:
        assert ds in sm["bridge_expand_column_map"]


def test_extract_bridge_expand_datasets_normalize_and_pit():
    """Load fins/margin/short/alert via R2 bridge; DEFER still hard-reject."""
    lines = {
        "fins_summary": [
            _catalog_line(
                "fins_summary",
                "2024-10-15",
                code="13010",
                extra_payload={"DiscDate": "2024-10-15", "NetSales": 1},
            ),
            # future available_at — kept in extract window filter by event day,
            # but FeatureContext PIT will hide at earlier as_of
            _catalog_line(
                "fins_summary",
                "2024-10-20",
                code="13010",
                available_at="2024-10-25T15:30:00+09:00",
                extra_payload={"DiscDate": "2024-10-20"},
            ),
        ],
        "markets_margin_interest": [
            _catalog_line(
                "markets_margin_interest",
                "2024-10-15",
                code="13010",
                extra_payload={"LongMarginTradeVolume": 100, "ShortMarginTradeVolume": 50},
            ),
            _catalog_line(
                "markets_margin_interest",
                "2024-10-16",
                code="13010",
                extra_payload={"LongMarginTradeVolume": 110, "ShortMarginTradeVolume": 40},
            ),
        ],
        "markets_short_ratio": [
            _catalog_line(
                "markets_short_ratio",
                "2024-10-15",
                code=None,
                extra_payload={"S33": "0050", "ShortSaleRatio": 0.12},
            ),
        ],
        "markets_margin_alert": [
            _catalog_line(
                "markets_margin_alert",
                "2024-10-15",
                code="13010",
                extra_payload={"PublishDate": "2024-10-15"},
            ),
        ],
    }
    extract = extract_r2_history_feature_rows(
        list(BRIDGE_EXPAND_DATASETS),
        period_start="2024-10-01",
        period_end="2024-10-31",
        codes=["13010"],
        raw_lines_by_dataset=lines,
    )
    assert extract["history_source"] == HISTORY_SOURCE_R2
    assert extract["local_sot"] is False
    assert extract["extracted_row_counts"]["fins_summary"] == 2
    assert extract["extracted_row_counts"]["markets_margin_interest"] == 2
    assert extract["extracted_row_counts"]["markets_short_ratio"] == 1
    assert extract["extracted_row_counts"]["markets_margin_alert"] == 1

    # PIT: at 2024-10-15 close, post-dated fins row must not be visible
    ctx = build_r2_feature_context(
        extract["rows_by_dataset"],
        as_of="2024-10-15T15:30:00+09:00",
        inputs={"code": "13010", "section": "0050"},
    )
    fins = ctx.get_jquants_records(dataset="fins_summary", code="13010")
    assert len(fins.rows) == 1  # only available_at <= as_of
    margin = ctx.get_jquants_records(dataset="markets_margin_interest", code="13010")
    assert len(margin.rows) >= 1
    short = ctx.get_jquants_records(dataset="markets_short_ratio")
    assert len(short.rows) >= 1
    alert = ctx.get_jquants_records(dataset="markets_margin_alert", code="13010")
    assert len(alert.rows) >= 1


def test_available_at_repair_calendar_only_no_lookahead():
    pol = available_at_policy_document()
    assert pol["version"] == AVAILABLE_AT_REPAIR_POLICY["version"]
    assert pol["r2_sot_rewrite"] is False
    assert "calendar_ingest_pollution" in pol["repairs"]
    assert "archive_ingest_pollution" in pol["repairs"]

    cal_rows = [
        {
            "date": "2024-10-01",
            "event_time": "2024-10-01T00:00:00+09:00",
            "available_at": "2026-08-11T18:00:00+09:00",  # ingest pollution
            "holiday_division": "1",
        },
        {
            "date": "2024-10-02",
            "event_time": "2024-10-02T00:00:00+09:00",
            "available_at": None,  # drop
        },
    ]
    repaired = repair_available_at_research(
        cal_rows, dataset="markets_calendar", policy="auto"
    )
    assert repaired["n_fixed"] == 1
    assert repaired["n_dropped_null_aa"] == 1
    assert repaired["rows"][0]["available_at"] == "2024-10-01T00:00:00+09:00"
    assert repaired["look_ahead"] is False

    # fins: short real lag preserved (not archive 2026 pattern)
    fins = [
        {
            "date": "2024-10-01",
            "event_time": "2024-10-01T15:00:00+09:00",
            "available_at": "2024-10-05T15:00:00+09:00",
            "Code": "13010",
        }
    ]
    fr = repair_available_at_research(fins, dataset="fins_summary", policy="auto")
    assert fr["n_fixed"] == 0
    assert fr["rows"][0]["available_at"] == "2024-10-05T15:00:00+09:00"

    # margin: 2026 ingest stamp on 2022 event → research repair
    margin = [
        {
            "date": "2022-10-07",
            "event_time": "2022-10-07T15:00:00+09:00",
            "available_at": "2026-08-13T23:41:27+09:00",
            "Code": "13010",
        }
    ]
    mr = repair_available_at_research(
        margin, dataset="markets_margin_interest", policy="auto"
    )
    assert mr["n_fixed"] == 1
    assert mr["repair_applied"] == "archive_ingest_pollution"
    assert mr["rows"][0]["available_at"] == "2022-10-07T15:00:00+09:00"
    assert mr["look_ahead"] is False


def test_multisignal_history_source_r2(tmp_path: Path):
    """Long-window multi-signal path accepts history_source=r2 fixtures."""
    from datetime import date, timedelta

    start = date(2024, 10, 1)
    days: list[str] = []
    d = start
    while len(days) < 12:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)

    bar_lines = []
    topix_lines = []
    cal_lines = []
    fins_lines = []
    for i, day in enumerate(days):
        for code in ("13010", "72030", "67580"):
            bar_lines.append(
                _bar_line(code, day, close=100.0 + i, volume=1000.0 + i * 50)
            )
        topix_lines.append(_topix_line(day, close=3000.0 + i))
        cal_lines.append(_cal_line(day))
        # sparse disclosure on day 5 for one code
        if i == 5:
            fins_lines.append(
                _catalog_line(
                    "fins_summary",
                    day,
                    code="13010",
                    extra_payload={"DiscDate": day},
                )
            )

    puts: list[tuple[str, str]] = []

    def fake_put(bucket: str, key: str, body: bytes, **kwargs):
        puts.append((bucket, key))
        return {"bucket": bucket, "key": key, "status": "dry_run", "bytes": len(body)}

    ex = execute_multiday_multisignal_compare(
        period_start=days[0],
        period_end=days[-1],
        job_id="w0815ba-g1-multisignal-r2-test",
        codes=["13010", "72030", "67580"],
        max_days=10,
        min_days=5,
        dry_run=True,
        write_per_day_artifacts=False,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
        r2_raw_lines_by_dataset={
            "equities_bars_daily": bar_lines,
            "indices_bars_daily_topix": topix_lines,
            "markets_calendar": cal_lines,
            "fins_summary": fins_lines,
            # margin empty-allowed path: omit channel → allow_empty default
        },
    )
    assert ex.n_days >= 5
    assert ex.ready_declared is False
    assert ex.mass_research == "NO-GO"
    assert ex.phase7 == "OFF"
    assert ex.batch_summary["history_source"] == "r2"
    assert ex.batch_summary["tip_plane"] == "R2_history"
    assert ex.batch_summary["significance_claimed"] is False
    assert ex.batch_summary["edge_claimed"] is False
    assert ex.batch_summary["operational_go"] is False
    table = ex.batch_summary["compare_table"]
    assert len(table) == 3
    sids = {r["signal_id"] for r in table}
    assert "c21_topix_relative_sign" in sids
    assert "c21_volume_change_sign" in sids
    assert "c21_topix_rel_disclosure_filter" in sids
    assert set(MULTI_SIGNAL_HISTORY_DATASETS) >= {
        "equities_bars_daily",
        "fins_summary",
        "markets_margin_interest",
    }
