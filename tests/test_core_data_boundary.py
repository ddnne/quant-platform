"""Core data boundary: facts enter only via ``pit``; no direct SQLite/HTTP.

Two layers of enforcement:

1. **Static import ban** — scan every ``core/**/*.py`` for forbidden data
   dependencies (``sqlite3``, ``storage``, ``httpx``, ``requests``, raw
   ``urllib``/``socket``). The engine may import :mod:`pit` and the shared JST
   time helpers — nothing else that reads facts.
2. **Runtime pit spy** — run a real backtest with the PIT getters wrapped to
   record calls, and assert facts were read through ``pit.get_*``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import core
import pit
from core import run_backtest, standard_cost
from core.strategies.buy_hold import BuyHold

from _coreseed import CODES, TRADING_DAYS, seed_db

CORE_DIR = Path(core.__file__).resolve().parent

# Modules that read facts or hit the network — forbidden inside ``core/``.
# ``pit`` itself is allowed (it IS the boundary); ``pit.query`` is allowed for
# the pure path helper ``resolve_db_path``.
FORBIDDEN_SUBSTRINGS = [
    "import sqlite3",
    "from sqlite3",
    "import storage",
    "from storage",
    "import httpx",
    "from httpx",
    "import requests",
    "from requests",
    "import urllib",
    "from urllib",
    "import socket",
]


def _core_python_files() -> list[Path]:
    return sorted(p for p in CORE_DIR.rglob("*.py"))


def test_core_modules_do_not_import_forbidden_data_paths():
    """No ``core/`` source imports sqlite/storage/http clients."""
    offenders: list[str] = []
    for path in _core_python_files():
        text = path.read_text(encoding="utf-8")
        for bad in FORBIDDEN_SUBSTRINGS:
            # skip line comments so a docstring/mention doesn't false-positive
            for line in text.splitlines():
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if bad in line:
                    offenders.append(f"{path.relative_to(CORE_DIR.parent)}: {line.strip()}")
    assert not offenders, "forbidden fact/network imports in core/:\n" + "\n".join(offenders)


def test_core_reads_facts_through_pit(tmp_path, monkeypatch):
    """A backtest exercises pit.get_market_calendar / get_equity_master / bars."""
    db = seed_db(tmp_path)
    calls: dict[str, int] = {
        "calendar": 0,
        "master": 0,
        "bars": 0,
    }

    real_calendar = pit.get_market_calendar
    real_master = pit.get_equity_master
    real_bars = pit.get_equity_bars_daily

    def spy_calendar(*a, **k):
        calls["calendar"] += 1
        return real_calendar(*a, **k)

    def spy_master(*a, **k):
        calls["master"] += 1
        return real_master(*a, **k)

    def spy_bars(*a, **k):
        calls["bars"] += 1
        return real_bars(*a, **k)

    # core.engine / core.universe look these up on the shared `pit` module at
    # call time, so patching the module attributes is enough.
    monkeypatch.setattr(pit, "get_market_calendar", spy_calendar)
    monkeypatch.setattr(pit, "get_equity_master", spy_master)
    monkeypatch.setattr(pit, "get_equity_bars_daily", spy_bars)

    res = run_backtest(
        BuyHold(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        universe=tuple(CODES),
        cost_model=standard_cost(),
    )
    assert calls["calendar"] >= 1
    assert calls["master"] >= 1
    assert calls["bars"] >= 1
    # Engine read at least the universe codes' bars.
    assert res.metadata["execution_mode"] == "next_close"


def test_strategy_context_carries_no_db_handle(tmp_path):
    """BarContext exposes data, not a database/PIT handle the strategy could abuse."""
    db = seed_db(tmp_path)
    seen: dict = {}

    class Snoop:
        strategy_id = "snoop"
        params = {}

        def on_bar(self, ctx):
            seen["attrs"] = set(ctx.__dataclass_fields__.keys())
            return []

    run_backtest(
        Snoop(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        universe=tuple(CODES),
    )
    # No field on the context is a pit/db/sqlite handle.
    assert seen["attrs"] == {
        "as_of", "date", "universe", "positions", "cash", "equity",
        "prices", "bars", "master",
    }
    assert "db_path" not in seen["attrs"]
    assert "conn" not in seen["attrs"]


def test_context_feature_accessor_injects_as_of_and_runtime_db(tmp_path):
    """Strategies name feature inputs, while core owns PIT scope parameters."""
    db = seed_db(tmp_path)
    seen: list[tuple[str, str]] = []

    class FeatureUser:
        strategy_id = "feature_user"
        params = {}

        def on_bar(self, ctx):
            output = ctx.feature("return_1d", code=CODES[0])
            seen.append((output.metadata["as_of"], output.metadata["db_path"]))
            with pytest.raises(TypeError, match="runtime-scoped"):
                ctx.feature("return_1d", code=CODES[0], db_path="other.sqlite")
            with pytest.raises(TypeError, match="runtime-scoped"):
                ctx.compute_feature("return_1d", code=CODES[0], as_of="future")
            return []

    run_backtest(
        FeatureUser(),
        TRADING_DAYS[0],
        TRADING_DAYS[-1],
        db_path=db,
        universe=tuple(CODES),
    )

    assert len(seen) == len(TRADING_DAYS)
    assert [as_of for as_of, _ in seen] == [
        f"{day}T15:30:00+09:00" for day in TRADING_DAYS
    ]
    assert {path for _, path in seen} == {str(db.resolve())}
