"""Features runtime boundary: facts enter through scoped PIT capabilities.

The centralized plane dependency test owns the import graph.  These tests
observe PIT reads and ensure feature code receives scoped getters and inputs,
not a database path or unrestricted mapping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import features
import pit

def test_features_runtime_does_not_resolve_db_when_pit_spy_set(
    tmp_path, monkeypatch
):
    """A feature compute call routes bar reads through pit.get_equity_bars_daily."""
    # Build a tiny DB via _coreseed.
    import sys
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _coreseed import CODES, TRADING_DAYS, seed_db

    db = seed_db(tmp_path)
    calls = {"bars": 0}

    real_bars = pit.get_equity_bars_daily

    def spy_bars(*a, **k):
        calls["bars"] += 1
        return real_bars(*a, **k)

    monkeypatch.setattr(pit, "get_equity_bars_daily", spy_bars)

    out = features.compute(
        "return_1d",
        as_of=f"{TRADING_DAYS[-1]}T15:30:00+09:00",
        code=CODES[0],
        db_path=db,
    )
    assert calls["bars"] >= 1
    assert out.metadata["feature_id"] == "return_1d"
    assert out.metadata["pit_api_version"] == pit.PIT_API_VERSION


def test_feature_context_exposes_scoped_getters_not_db_path_or_input_mapping(
    tmp_path,
):
    import sys
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _coreseed import CODES, TRADING_DAYS, seed_db

    db = seed_db(tmp_path)
    seen: dict[str, object] = {}

    def inspect_context(ctx):
        seen["db_path"] = hasattr(ctx, "db_path")
        seen["inputs"] = hasattr(ctx, "inputs")
        seen["code"] = ctx.get_input("code")
        seen["default"] = ctx.get_input("optional", 7)
        return features.FeatureOutput(value=1.0)

    definition = features.FeatureDefinition(
        id="feature_context_shape_fixture",
        version=features.FeatureVersion(1),
        inputs=features.FeatureInput(required_kwargs=("code",)),
        description="context capability shape",
        compute=inspect_context,
        intended_role="utility",
    )
    features.compute(
        definition,
        as_of=f"{TRADING_DAYS[-1]}T15:30:00+09:00",
        code=CODES[0],
        db_path=db,
    )

    assert seen == {
        "db_path": False,
        "inputs": False,
        "code": CODES[0],
        "default": 7,
    }
