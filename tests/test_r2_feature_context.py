"""R2 structured history → FeatureContext: schema, PIT, DEFER hard reject."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from tests.research_eval_util import (
    _aa_row,
    _history_bar,
    _history_topix,
    _r2_bar_line as _bar_line,
    _r2_catalog_line as _catalog_line,
    _s1_two_day_map,
    _weekdays,
)
from research.r2_feature_context import (
    AVAILABLE_AT_REPAIR_POLICY,
    BRIDGE_EXPAND_DATASETS,
    COMPLETE_21_R2_INVENTORY,
    HISTORY_SOURCE_R2,
    MULTI_SIGNAL_HISTORY_DATASETS,
    R2FeatureContextError,
    S1_SIGNAL_HISTORY_DATASETS,
    available_at_policy_document,
    build_r2_feature_context,
    can_build_40d_asof,
    extract_r2_history_feature_rows,
    filter_history_rows,
    normalize_r2_history_row,
    parse_r2_structured_line,
    r2_inventory_document,
    repair_available_at_research,
    resolve_history_source,
    schema_mapping_document,
    write_r2_inventory_json,
)


def test_t1_inventory_covers_complete_21_and_excludes_defer():
    doc = r2_inventory_document()
    assert doc["complete_21_count"] == 21
    assert len(doc["complete_21"]) == 21
    assert doc["permanent_defer_count"] == 4
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


def test_t2_schema_mapping_has_s1_datasets():
    doc = schema_mapping_document()
    assert "equities_bars_daily" in doc["s1_column_map"]
    assert "indices_bars_daily_topix" in doc["s1_column_map"]
    assert "markets_calendar" in doc["s1_column_map"]
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


def test_extract_r2_history_filters_window_and_codes():
    raw = _s1_two_day_map(
        close0=100.0,
        close1=110.0,
        vol0=100.0,
        vol1=150.0,
        extra_bars=(
            _bar_line("13010", "2026-05-30", close=90.0),
            _bar_line("72030", "2026-06-02", close=2000.0),
            _bar_line("13010", "2026-06-20", close=120.0),
        ),
    )
    out = extract_r2_history_feature_rows(
        list(S1_SIGNAL_HISTORY_DATASETS),
        period_start="2026-06-01",
        period_end="2026-06-10",
        codes=["13010"],
        raw_lines_by_dataset=raw,
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
        raw_lines_by_dataset=_s1_two_day_map(
            close0=100.0, close1=110.0, vol0=100.0, vol1=150.0
        ),
    )
    rows = extract["rows_by_dataset"]
    as_of = "2026-06-03T15:30:00+09:00"
    ctx = build_r2_feature_context(rows, as_of=as_of, inputs={"code": "13010"})
    bars = ctx.get_equity_bars_daily(code="13010")
    assert bars.metadata["plane"] == "R2_history"
    assert bars.metadata["source"] == "cloudflare_r2_structured"
    assert len(bars.rows) == 2


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


def test_t4_pit_excludes_future_available_at():
    rows = {
        "equities_bars_daily": [
            _history_bar("13010", "2026-06-02", 100.0, 100.0),
            _history_bar("13010", "2026-06-03", 110.0, 150.0),
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
            _history_bar("13010", "2026-06-02", 1.0, available_at=None),
            _history_bar("13010", "2026-06-03", 2.0),
        ]
    }
    ctx = build_r2_feature_context(
        smuggled, as_of="2026-06-03T15:30:00+09:00"
    )
    assert len(ctx.get_equity_bars_daily(code="13010").rows) == 1


def test_filter_history_rows_require_available_at():
    rows = [
        _aa_row("2026-06-02", available_at=None, code="1"),
        _aa_row(
            "2026-06-02",
            available_at="2026-06-02T15:30:00+09:00",
            code="1",
        ),
    ]
    assert len(filter_history_rows(rows, require_available_at=True)) == 1


def test_r2_extract_is_not_local_sot():
    extract = extract_r2_history_feature_rows(
        ["equities_bars_daily", "markets_calendar"],
        period_start="2026-06-01",
        period_end="2026-06-10",
        codes=["13010"],
        raw_lines_by_dataset=_s1_two_day_map(include_topix=False),
    )
    assert extract["local_sot"] is False
    assert extract["disposable_mirror"] is False
    assert not hasattr(extract_r2_history_feature_rows, "materialize_disposable_sqlite_mirror")


def test_can_build_40d_asof_code_path_yes():
    cap = can_build_40d_asof(None)
    assert cap["can_build_40d_asof"] is True
    assert cap["code_path"] is True


def test_can_build_40d_asof_with_rows():
    days = _weekdays(date(2026, 4, 1), 45)
    bars = [_history_bar("13010", d, 100.0 + i) for i, d in enumerate(days)]
    topix = [_history_topix(d) for d in days]
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
        _aa_row(
            "2024-10-01",
            available_at="2026-08-11T18:00:00+09:00",
            holiday_division="1",
        ),
        _aa_row("2024-10-02", available_at=None),
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
        _aa_row(
            "2024-10-01",
            event_time="2024-10-01T15:00:00+09:00",
            available_at="2024-10-05T15:00:00+09:00",
            Code="13010",
        )
    ]
    fr = repair_available_at_research(fins, dataset="fins_summary", policy="auto")
    assert fr["n_fixed"] == 0
    assert fr["rows"][0]["available_at"] == "2024-10-05T15:00:00+09:00"

    # margin: 2026 ingest stamp on 2022 event → research repair
    margin = [
        _aa_row(
            "2022-10-07",
            event_time="2022-10-07T15:00:00+09:00",
            available_at="2026-08-13T23:41:27+09:00",
            Code="13010",
        )
    ]
    mr = repair_available_at_research(
        margin, dataset="markets_margin_interest", policy="auto"
    )
    assert mr["n_fixed"] == 1
    assert mr["repair_applied"] == "archive_ingest_pollution"
    assert mr["rows"][0]["available_at"] == "2022-10-07T15:00:00+09:00"
    assert mr["look_ahead"] is False


def test_multisignal_history_datasets_cover_s1_plus_expand():
    assert set(MULTI_SIGNAL_HISTORY_DATASETS) >= {
        "equities_bars_daily",
        "fins_summary",
        "markets_margin_interest",
    }
