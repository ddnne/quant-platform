"""Features data boundary: facts enter only via ``pit``; no direct SQLite/HTTP.

Mirrors ``tests/test_core_data_boundary.py``: static import ban + runtime
PIT-spy. Features may import :mod:`pit` for reads and stdlib helpers — they
must not open SQLite, hit the network, or import :mod:`storage`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import features
import pit

FEATURES_DIR = Path(features.__file__).resolve().parent

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


def _features_python_files() -> list[Path]:
    return sorted(p for p in FEATURES_DIR.rglob("*.py"))


def test_features_modules_do_not_import_forbidden_data_paths():
    offenders: list[str] = []
    for path in _features_python_files():
        text = path.read_text(encoding="utf-8")
        for bad in FORBIDDEN_SUBSTRINGS:
            for line in text.splitlines():
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if bad in line:
                    offenders.append(
                        f"{path.relative_to(FEATURES_DIR.parent)}: {line.strip()}"
                    )
    assert not offenders, (
        "forbidden fact/network imports in features/:\n" + "\n".join(offenders)
    )


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
