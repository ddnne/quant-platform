"""Features runtime boundary: facts enter through scoped PIT capabilities.

The centralized plane dependency test owns the import graph.  These tests
observe PIT reads and ensure feature code receives scoped getters and inputs,
not a database path or unrestricted mapping.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import features
import pit

def test_feature_context_reads_declared_fields_and_latest_visible_tail(
    tmp_path, monkeypatch,
):
    import sys
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _coreseed import CODES, TRADING_DAYS, seed_db

    code = CODES[0]
    adjusted = dict(zip(TRADING_DAYS, (100.0, 110.0, 120.0, 150.0)))
    db = seed_db(tmp_path, codes=[code], adjustment_prices={code: adjusted})
    seen: dict[str, object] = {}
    calls = []
    real_bars = pit.get_equity_bars_daily

    def spy_bars(**kwargs):
        calls.append(kwargs)
        return real_bars(**kwargs)

    monkeypatch.setattr(pit, "get_equity_bars_daily", spy_bars)

    def inspect_context(ctx):
        seen["db_path"] = hasattr(ctx, "db_path")
        seen["inputs"] = hasattr(ctx, "inputs")
        seen["code"] = ctx.get_input("code")
        seen["default"] = ctx.get_input("optional", 7)
        rows = ctx.get_equity_bars_daily(code=code).rows
        assert [row["date"] for row in rows] == list(TRADING_DAYS[-2:])
        assert all(set(row) == {"code", "date", "adjustment_close"} for row in rows)
        # Filters may narrow the declared tail, never shift it into old history.
        assert ctx.get_equity_bars_daily(code=code, to_event=TRADING_DAYS[0]).rows == []
        assert ctx.get_equity_bars_daily(
            code=code, to_event=f" {TRADING_DAYS[-2].replace('-', '/')} "
        ).rows == rows[:1]
        with pytest.raises(ValueError, match="declared observation count"):
            ctx.get_equity_bars_daily(code=code, latest_n=3)
        with pytest.raises(ValueError, match="requires one code"):
            ctx.get_equity_bars_daily(codes=[code])
        with pytest.raises(ValueError, match="undeclared fins_summary"):
            ctx.get_jquants_records(dataset="fins_summary", code=code)
        with pytest.raises(ValueError, match="scope does not permit this reader"):
            ctx.get_jquants_records(dataset="equities_bars_daily", code=code)
        with pytest.raises(KeyError):
            _ = rows[-1]["close"]
        return features.FeatureOutput(
            value=rows[-1]["adjustment_close"] / rows[0]["adjustment_close"] - 1.0
        )

    definition = replace(
        features.get("retrospective_split_adjusted_momentum_n", version="1.0.0"),
        id="feature_context_shape_fixture",
        description="context capability shape",
        compute=inspect_context,
    )
    out = features.compute(
        definition,
        as_of=f"{TRADING_DAYS[-1]}T15:30:00+09:00",
        code=code,
        n=1,
        db_path=db,
    )
    assert out.value == pytest.approx(0.25)
    assert len(calls) == 1
    assert calls[0]["latest_n"] == 2
    assert seen == {
        "db_path": False,
        "inputs": False,
        "code": code,
        "default": 7,
    }

    # Dataset membership is required even without detailed field/window scopes.
    # Use an absent DB to prove the undeclared read is refused before storage.
    def undeclared_catalog(ctx):
        ctx.get_jquants_records(dataset="fins_summary", code=code)
        raise AssertionError("undeclared catalog was read")

    unscoped = replace(definition, read_scopes=(), compute=undeclared_catalog)
    with pytest.raises(ValueError, match="undeclared fins_summary"):
        features.compute(
            unscoped, as_of=f"{TRADING_DAYS[-1]}T15:30:00+09:00",
            code=code, n=1, db_path=tmp_path / "absent.sqlite",
        )

    def undeclared_financial(ctx):
        ctx.get_financial_state(
            dataset="fins_summary", code=code,
            initial_visible_state="all_visible_existence_and_count",
        )
        raise AssertionError("undeclared financial state was read")

    with pytest.raises(ValueError, match="undeclared fins_summary"):
        features.compute(
            replace(unscoped, compute=undeclared_financial),
            as_of=f"{TRADING_DAYS[-1]}T15:30:00+09:00",
            code=code, n=1, db_path=tmp_path / "absent.sqlite",
        )
