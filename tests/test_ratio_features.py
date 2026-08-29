"""Behavioral tests for the bounded personal ratio feature atoms."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from features import (
    FUNDAMENTAL_RATIO_MODES,
    PRICE_RATIO_MODES,
    PitFundamentalRatio,
    RetrospectivePriceRatio,
    compute,
    get,
)
from _coreseed import close_iso, seed_db
from price_basis import PERSONAL_RETROSPECTIVE_ADJUSTED
from storage.sqlite_store import SqliteStore


class _Context:
    def __init__(self, *, inputs, bars=None, fins=None):
        self._inputs = dict(inputs)
        self._bars = list(bars or [])
        self._fins = list(fins or [])

    def get_input(self, name, default=None):
        return self._inputs.get(name, default)

    def get_equity_bars_daily(self, **kwargs):
        rows = list(self._bars)
        start = kwargs.get("from_event")
        end = kwargs.get("to_event")
        if start:
            rows = [row for row in rows if str(row.get("date"))[:10] >= start]
        if end:
            rows = [row for row in rows if str(row.get("date"))[:10] <= end]
        if kwargs.get("latest_n") is not None:
            rows = rows[-int(kwargs["latest_n"]) :]
        return SimpleNamespace(rows=rows)

    def get_jquants_records(self, **kwargs):
        assert kwargs["dataset"] == "fins_summary"
        return SimpleNamespace(rows=list(self._fins))


def _bars(prices, *, turnovers=None, raw_prices=None, start_day=1):
    raw_prices = list(raw_prices or prices)
    turnovers = list(turnovers or [1_000.0] * len(prices))
    return [
        {
            "code": "8697",
            "date": f"2025-01-{index + start_day:02d}",
            "close": raw,
            "adjustment_close": adjusted,
            "turnover_value": turnover,
            "volume": 999_999.0,
        }
        for index, (adjusted, raw, turnover) in enumerate(
            zip(prices, raw_prices, turnovers, strict=True)
        )
    ]


def _price(mode, bars, *, short_n=2, long_n=5):
    return RetrospectivePriceRatio.compute(
        _Context(
            inputs={
                "code": "8697",
                "mode": mode,
                "short_n": short_n,
                "long_n": long_n,
            },
            bars=bars,
        )
    )


def _fins_row(payload, *, available_at=None):
    date = payload.get("DiscDate") or payload.get("DisclosedDate")
    return {
        "payload": dict(payload),
        "event_time": f"{date}T15:00:00+09:00",
        "available_at": available_at or f"{date}T15:00:00+09:00",
        "natural_key": repr(sorted(payload.items())),
    }


def _fundamental(mode, fins, *, bars=None):
    return PitFundamentalRatio.compute(
        _Context(
            inputs={"code": "8697", "mode": mode},
            bars=bars,
            fins=fins,
        )
    )


def test_ratio_features_are_registered_with_closed_v1_contracts() -> None:
    assert get("retrospective_price_ratio", "1.0.0") is RetrospectivePriceRatio
    assert get("pit_fundamental_ratio", "1.0.0") is PitFundamentalRatio
    assert RetrospectivePriceRatio.price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
    assert PitFundamentalRatio.price_basis == PERSONAL_RETROSPECTIVE_ADJUSTED
    assert PRICE_RATIO_MODES == {
        "return_ratio",
        "short_long_momentum",
        "realized_vol_ratio",
        "turnover_ratio",
        "market_cap",
    }
    assert FUNDAMENTAL_RATIO_MODES == {
        "book_to_price",
        "earnings_to_price",
        "roe",
        "net_margin",
        "asset_turnover",
        "equity_ratio",
        "sales_growth",
        "assets_growth",
        "total_assets",
        "net_sales",
    }


def test_return_and_short_long_momentum_are_zero_centered() -> None:
    bars = _bars([100.0, 102.0, 104.0, 103.0, 110.0, 120.0])

    absolute = _price("return_ratio", bars)
    relative = _price("short_long_momentum", bars)

    assert absolute.value == pytest.approx(0.20)
    assert relative.value == pytest.approx(
        (120.0 / 103.0) ** (1.0 / 2.0)
        / ((103.0 / 100.0) ** (1.0 / 3.0))
        - 1.0
    )
    assert absolute.metadata["price_source"] == "vendor_adjustment_close"
    assert relative.metadata["time_semantics"] == "retrospective_not_point_in_time"
    assert relative.metadata["comparison"] == (
        "recent_vs_disjoint_preceding_per_session"
    )


def test_short_long_momentum_detects_recent_acceleration_without_price_cancellation() -> None:
    steady_then_fast = _price(
        "short_long_momentum",
        _bars([100.0, 101.0, 102.0, 103.0, 110.0, 120.0]),
    )
    fast_then_slow = _price(
        "short_long_momentum",
        _bars([100.0, 110.0, 120.0, 130.0, 131.0, 132.0]),
    )

    assert steady_then_fast.value > 0.0
    assert fast_then_slow.value < 0.0


def test_realized_vol_ratio_uses_the_same_adjusted_series() -> None:
    prices = [100.0, 103.0, 99.0, 108.0, 104.0, 120.0]
    output = _price("realized_vol_ratio", _bars(prices))

    def annualized(window):
        returns = [window[i] / window[i - 1] - 1.0 for i in range(1, len(window))]
        mean = sum(returns) / len(returns)
        variance = sum((value - mean) ** 2 for value in returns) / (
            len(returns) - 1
        )
        return math.sqrt(variance) * math.sqrt(252.0)

    expected = annualized(prices[-3:]) / annualized(prices[-6:])
    assert output.value == pytest.approx(expected)
    assert output.metadata["short_volatility"] == pytest.approx(
        annualized(prices[-3:])
    )


def test_turnover_ratio_is_median_based_and_never_falls_back_to_volume() -> None:
    turnovers = [1.0, 2.0, 1_000.0, 4.0, 5.0, 6.0, 7.0]
    output = _price(
        "turnover_ratio",
        _bars([100.0] * len(turnovers), turnovers=turnovers),
        short_n=3,
        long_n=7,
    )

    assert output.value == pytest.approx(6.0 / 5.0)
    assert output.metadata["short_median"] == 6.0
    assert output.metadata["long_median"] == 5.0
    assert output.metadata["turnover_source"] == "TurnoverValue_unadjusted"
    assert output.metadata["volume_fallback"] is False

    missing = _bars([100.0] * 7, turnovers=turnovers)
    missing[-1].pop("turnover_value")
    absent = _price("turnover_ratio", missing, short_n=3, long_n=7)
    assert absent.value is None
    assert "no volume fallback" in absent.metadata["reason"]


def test_price_ratio_fails_closed_for_short_or_unadjusted_history() -> None:
    insufficient = _price("return_ratio", _bars([100.0, 101.0, 102.0]))
    assert insufficient.value is None
    assert "insufficient history" in insufficient.metadata["reason"]

    rows = _bars([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    rows[-1].pop("adjustment_close")
    missing = _price("return_ratio", rows)
    assert missing.value is None
    assert missing.metadata["reason"] == (
        "adjustment_close missing; raw fallback disabled"
    )
    assert missing.metadata["raw_fallback"] is False


@pytest.mark.parametrize("field", ["MarketCapitalization", "MarketCap", "MktCap"])
def test_market_cap_reads_latest_pit_bar_payload_for_sector_ranking(field) -> None:
    rows = _bars([100.0, 101.0])
    rows[0]["raw_payload"] = {field: 90_000.0}
    rows[1]["raw_payload"] = {field: 123_456.0}

    output = _price("market_cap", rows)

    assert output.value == 123_456.0
    assert output.metadata["value_field"] == field
    assert output.metadata["value_source"] == (
        "latest_PIT_visible_bar_payload"
    )
    assert output.metadata["market_cap_proxy"] is False
    assert "sector33 percentile" in output.metadata["relative_size_semantics"]


def test_market_cap_prefers_typed_bar_column_over_payload_alias() -> None:
    rows = _bars([100.0, 101.0])
    rows[-1]["market_cap"] = 222_000.0
    rows[-1]["raw_payload"] = {"MktCap": 111_000.0}

    output = _price("market_cap", rows)

    assert output.value == 222_000.0
    assert output.metadata["value_field"] == "market_cap"
    assert output.metadata["value_source"] == "latest_PIT_visible_typed_bar"


def test_market_cap_does_not_substitute_close_or_other_size_levels() -> None:
    output = _price("market_cap", _bars([100.0, 101.0]))

    assert output.value is None
    assert output.metadata["reason"] == "market cap missing, zero, or invalid"


def test_market_cap_survives_typed_bar_pit_normalization(tmp_path) -> None:
    day = "2025-04-01"
    db = seed_db(
        tmp_path,
        codes=["8697"],
        days=[day],
        prices={"8697": {day: 100.0}},
        adjustment_prices={"8697": {day: 100.0}},
    )
    payload = {"Code": "8697", "Date": day}
    store = SqliteStore(db)
    store.upsert(
        "jquants_daily_bars",
        [
            {
                "source": "jquants",
                "code": "8697",
                "date": day,
                "event_time": close_iso(day),
                "available_at": close_iso(day),
                "ingested_at": close_iso(day),
                "close": 100.0,
                "adjustment_close": 100.0,
                "market_cap": 987_654.0,
                "raw_payload": json.dumps(payload),
            }
        ],
    )
    store.close()

    output = compute(
        "retrospective_price_ratio",
        as_of=close_iso(day),
        db_path=db,
        code="8697",
        mode="market_cap",
        short_n=2,
        long_n=5,
    )

    assert output.value == 987_654.0
    assert output.metadata["value_source"] == "latest_PIT_visible_typed_bar"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("roe", 0.12),
        ("net_margin", 0.10),
        ("asset_turnover", 0.50),
        ("equity_ratio", 0.40),
    ],
)
@pytest.mark.parametrize("short_names", [True, False])
def test_fundamental_ratios_support_short_and_long_jquants_names(
    mode, expected, short_names
) -> None:
    if short_names:
        values = {
            "Sales": 200.0,
            "NP": 20.0,
            "TA": 400.0,
            "Eq": 160.0,
            "EqAR": 0.40,
            "ROE": 0.12,
            "CurPerType": "FY",
            "CurPerEn": "2024-12-31",
            "DocType": "FYFinancialStatements_Consolidated_JP",
        }
    else:
        values = {
            "NetSales": 200.0,
            "Profit": 20.0,
            "TotalAssets": 400.0,
            "Equity": 160.0,
            "EquityToAssetRatio": 0.40,
            "ReturnOnEquity": 0.12,
            "TypeOfCurrentPeriod": "FY",
            "CurrentPeriodEndDate": "2024-12-31",
            "TypeOfDocument": "FYFinancialStatements_Consolidated_JP",
        }
    values.update({"DiscDate": "2025-02-01"})

    output = _fundamental(mode, [_fins_row(values)])

    assert output.value == pytest.approx(expected)
    assert output.metadata["ratio_source"] in {"reported", "same_statement_row"}


def test_fundamental_ratio_does_not_mix_statement_rows() -> None:
    older = _fins_row(
        {
            "DiscDate": "2024-11-01",
            "CurPerType": "2Q",
            "CurPerEn": "2024-09-30",
            "Sales": 100.0,
            "NP": 10.0,
        }
    )
    latest = _fins_row(
        {
            "DiscDate": "2025-02-01",
            "CurPerType": "3Q",
            "CurPerEn": "2024-12-31",
            "NP": 20.0,
        }
    )

    output = _fundamental("net_margin", [older, latest])

    assert output.value is None
    assert output.metadata["numerator"] == 20.0
    assert output.metadata["denominator"] is None
    assert output.metadata["disclosure_date"] == "2025-02-01"


@pytest.mark.parametrize(
    "mode,field,value",
    [("total_assets", "TA", 400.0), ("net_sales", "NetSales", 200.0)],
)
def test_size_levels_are_explicit_rank_inputs_not_fake_market_cap(
    mode, field, value
) -> None:
    row = _fins_row(
        {
            "DiscDate": "2025-02-01",
            "CurPerType": "FY",
            "CurPerEn": "2024-12-31",
            field: value,
        }
    )

    output = _fundamental(mode, [row])

    assert output.value == value
    assert output.metadata["market_cap_proxy"] is False
    assert "sector33 percentile" in output.metadata["relative_size_semantics"]


@pytest.mark.parametrize(
    "mode,value_key,prior,current,expected",
    [
        ("sales_growth", "Sales", 100.0, 130.0, 0.30),
        ("assets_growth", "TA", 400.0, 440.0, 0.10),
    ],
)
def test_growth_uses_prior_comparable_and_skips_same_period_revision(
    mode, value_key, prior, current, expected
) -> None:
    rows = [
        _fins_row(
            {
                "DiscDate": "2024-05-01",
                "CurPerType": "1Q",
                "CurPerEn": "2024-03-31",
                "DocType": "1QFinancialStatements_Consolidated_JP",
                value_key: prior,
            }
        ),
        _fins_row(
            {
                "DiscDate": "2025-03-01",
                "CurPerType": "FY",
                "CurPerEn": "2024-12-31",
                "DocType": "FYFinancialStatements_Consolidated_JP",
                value_key: 999.0,
            }
        ),
        _fins_row(
            {
                "DiscDate": "2025-05-01",
                "CurPerType": "1Q",
                "CurPerEn": "2025-03-31",
                "DocType": "1QFinancialStatements_Consolidated_JP",
                value_key: current - 5.0,
            }
        ),
        _fins_row(
            {
                "DiscDate": "2025-05-02",
                "CurPerType": "1Q",
                "CurPerEn": "2025-03-31",
                "DocType": "1QFinancialStatements_Consolidated_JP",
                value_key: current,
            }
        ),
    ]

    output = _fundamental(mode, rows)

    assert output.value == pytest.approx(expected)
    assert output.metadata["prior_period_end"] == "2024-03-31"
    assert output.metadata["prior_value"] == prior


@pytest.mark.parametrize(
    "mode,numerator_key,numerator",
    [
        ("book_to_price", "BPS", 80.0),
        ("book_to_price", "BookValuePerShare", 80.0),
        ("earnings_to_price", "EPS", 12.0),
        ("earnings_to_price", "EarningsPerShare", 12.0),
    ],
)
def test_per_share_value_reuses_retrospective_split_safety(
    mode, numerator_key, numerator
) -> None:
    statement = _fins_row(
        {
            "DiscDate": "2025-01-02",
            "CurPerType": "FY",
            "CurPerEn": "2024-12-31",
            numerator_key: numerator,
        }
    )
    safe_bars = [
        {
            "code": "8697",
            "date": "2024-12-30",
            "close": 100.0,
            "adjustment_close": 100.0,
            "volume": 1_000.0,
            "adjustment_volume": 1_000.0,
        },
        {
            "code": "8697",
            "date": "2025-01-10",
            "close": 100.0,
            "adjustment_close": 100.0,
            "volume": 1_000.0,
            "adjustment_volume": 1_000.0,
        },
    ]

    output = _fundamental(mode, [statement], bars=safe_bars)

    assert output.value == pytest.approx(numerator / 100.0)
    assert output.metadata["price_source"] == (
        "raw_close_with_retrospective_split_blackout"
    )
    assert output.metadata["split_safety_anchor"] == "2024-12-31"

    split_bars = [dict(row) for row in safe_bars]
    split_bars[0]["adjustment_close"] = 50.0
    split_bars[0]["adjustment_volume"] = 2_000.0
    unsafe = _fundamental(mode, [statement], bars=split_bars)
    assert unsafe.value is None
    assert unsafe.metadata["factor_change_dates"] == ["2025-01-10"]


def test_fundamental_zero_denominator_and_unknown_modes_fail_closed() -> None:
    row = _fins_row(
        {
            "DiscDate": "2025-02-01",
            "Sales": 0.0,
            "NP": 20.0,
            "CurPerType": "FY",
            "CurPerEn": "2024-12-31",
        }
    )
    output = _fundamental("net_margin", [row])
    assert output.value is None
    assert "denominator" in output.metadata["reason"]

    with pytest.raises(ValueError, match="mode must be one of"):
        _fundamental("invented", [row])
    with pytest.raises(ValueError, match="2 <= short_n < long_n"):
        _price("return_ratio", _bars([100.0] * 6), short_n=5, long_n=5)


@pytest.mark.parametrize(
    "short_n,long_n",
    [(2.0, 5), (2, 5.0), ("2", 5), (2, "5"), (True, 5), (2, False)],
)
def test_price_ratio_windows_accept_json_integers_only(short_n, long_n) -> None:
    with pytest.raises(ValueError, match="JSON integers"):
        _price(
            "return_ratio",
            _bars([100.0] * 6),
            short_n=short_n,
            long_n=long_n,
        )
