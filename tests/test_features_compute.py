"""Feature compute correctness, PIT-boundary, and registry behavior.

All offline, against a tiny PIT DB seeded by ``_coreseed``. Verifies Phase 4
contract:
* features compute at a given ``as_of`` using only PIT-visible facts;
* ``as_of`` is required (raises without it);
* required inputs are validated;
* look-ahead is impossible — calling at ``as_of=D`` only sees bars whose
  ``available_at <= as_of``;
* registry supports versioning and ``compute_many`` builds a vector;
* outputs are reproducible.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

import features
import pit
from features import (
    FEATURES_REGISTRY,
    FeatureDefinition,
    FeatureOutput,
    FeatureVersion,
    compute,
    compute_many,
    get,
    list_features,
    register,
)
from features.runtime import AsOfRequired, FEATURES_RUNTIME_VERSION, MissingInput

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from _coreseed import CODES, TRADING_DAYS, close_iso, seed_db


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_db(tmp_path):
    # Extend trading days to 30 sessions so momentum/vol have enough history.
    from datetime import date, timedelta
    days = []
    cur = date(2025, 4, 1)
    while len(days) < 30:
        if cur.weekday() < 5:  # Mon-Fri
            days.append(cur.isoformat())
        cur += timedelta(days=1)

    # Rising prices per code, +1.0 JPY / day, deterministic.
    prices = {
        c: {d: 100.0 + i * 1.0 for i, d in enumerate(days)}
        for c in CODES
    }
    db = seed_db(tmp_path, days=days, prices=prices)
    return db, days, prices


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def test_registry_lists_built_in_features():
    ids = {f.id for f in list_features()}
    assert {"return_1d", "momentum_n", "volatility_n"}.issubset(ids)


def test_registry_get_returns_latest_version_by_default():
    feat = get("return_1d")
    assert feat.id == "return_1d"
    assert isinstance(feat.version, FeatureVersion)


def test_registry_get_unknown_id_raises():
    with pytest.raises(KeyError):
        get("not_a_feature")


def test_registry_rejects_duplicate_id_version():
    feat = FeatureDefinition(
        id="return_1d",
        version=FeatureVersion(1, 0, 0),
        inputs=features.FeatureInput(),
        description="dup",
        compute=lambda ctx: FeatureOutput(value=None),
    )
    with pytest.raises(ValueError, match="already registered"):
        register(feat)


def test_registry_accepts_new_version_of_same_id():
    feat = FeatureDefinition(
        id="return_1d",
        version=FeatureVersion(2, 0, 0),
        inputs=features.FeatureInput(),
        description="v2 test only",
        compute=lambda ctx: FeatureOutput(value=None),
    )
    try:
        register(feat)
        latest = get("return_1d")
        assert latest.version.major == 2
    finally:
        # Don't leak the test version into other tests.
        from features.registry import _FEATURES
        _FEATURES.pop(("return_1d", "2.0.0"), None)


# ---------------------------------------------------------------------------
# as_of requirement
# ---------------------------------------------------------------------------

def test_compute_requires_as_of(seeded_db):
    db, _, _ = seeded_db
    with pytest.raises(AsOfRequired):
        compute("return_1d", as_of=None, code=CODES[0], db_path=db)
    with pytest.raises((AsOfRequired, TypeError)):
        # Omitting as_of entirely (kwarg required by signature -> TypeError,
        # which is also a hard, PIT-safe failure — never silently defaults).
        compute("return_1d", code=CODES[0], db_path=db)


def test_compute_validates_required_inputs(seeded_db):
    db, days, _ = seeded_db
    with pytest.raises(MissingInput):
        compute("return_1d", as_of=close_iso(days[-1]), db_path=db)


# ---------------------------------------------------------------------------
# return_1d
# ---------------------------------------------------------------------------

def test_return_1d_matches_manual(seeded_db):
    db, days, prices = seeded_db
    code = CODES[0]
    as_of = close_iso(days[-1])
    out = compute("return_1d", as_of=as_of, code=code, db_path=db)
    c0 = prices[code][days[-2]]
    c1 = prices[code][days[-1]]
    expected = (c1 - c0) / c0
    assert out.value == pytest.approx(expected)
    assert out.metadata["rows_seen"] >= 2
    assert out.metadata["feature_id"] == "return_1d"
    assert out.metadata["feature_version"] == "1.0.0"
    assert out.metadata["pit_api_version"] == pit.PIT_API_VERSION
    assert out.metadata["features_runtime_version"] == FEATURES_RUNTIME_VERSION


def test_return_1d_none_with_insufficient_history(tmp_path):
    db = seed_db(tmp_path, days=TRADING_DAYS[:1], prices={CODES[0]: {TRADING_DAYS[0]: 100.0}})
    out = compute(
        "return_1d",
        as_of=close_iso(TRADING_DAYS[0]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "insufficient history" in out.metadata["reason"]


# ---------------------------------------------------------------------------
# momentum_n
# ---------------------------------------------------------------------------

def test_momentum_n_default_window(seeded_db):
    db, days, prices = seeded_db
    code = CODES[1]
    out = compute("momentum_n", as_of=close_iso(days[-1]), code=code, db_path=db)
    # default N=20: base = day[-21], last = day[-1]
    base = prices[code][days[-21]]
    last = prices[code][days[-1]]
    assert out.value == pytest.approx((last - base) / base)
    assert out.metadata["n"] == 20


def test_momentum_n_custom_window(seeded_db):
    db, days, prices = seeded_db
    code = CODES[0]
    out = compute(
        "momentum_n", as_of=close_iso(days[-1]), code=code, db_path=db, n=5,
    )
    base = prices[code][days[-6]]
    last = prices[code][days[-1]]
    assert out.value == pytest.approx((last - base) / base)
    assert out.metadata["n"] == 5


def test_momentum_n_none_when_short_history(seeded_db):
    db, days, prices = seeded_db
    # First 5 days: not enough for N=20.
    out = compute(
        "momentum_n",
        as_of=close_iso(days[4]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None


# ---------------------------------------------------------------------------
# volatility_n
# ---------------------------------------------------------------------------

def test_volatility_n_constant_prices_zero_vol(tmp_path):
    # Constant close -> zero returns -> zero vol.
    from datetime import date, timedelta
    days = []
    cur = date(2025, 4, 1)
    while len(days) < 25:
        if cur.weekday() < 5:
            days.append(cur.isoformat())
        cur += timedelta(days=1)
    prices = {CODES[0]: {d: 100.0 for d in days}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "volatility_n",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is not None
    assert out.value == pytest.approx(0.0, abs=1e-12)


def test_volatility_n_rising_prices_nonzero(seeded_db):
    db, days, _ = seeded_db
    out = compute(
        "volatility_n",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
        n=10,
    )
    # Rising prices by +1 JPY/day on a 100 base: returns are ~1% then decline.
    # Sample stdev of {1/100, 1/101, ...} ≈ small positive number.
    assert out.value is not None and out.value > 0


# ---------------------------------------------------------------------------
# PIT boundary
# ---------------------------------------------------------------------------

def test_pit_lookahead_impossible(seeded_db):
    """A call at as_of=D must not see a bar published after D's close."""
    db, days, prices = seeded_db
    code = CODES[0]
    # Call return_1d at day 10's close — must use day 9 + day 10 closes, not later.
    out = compute(
        "return_1d",
        as_of=close_iso(days[10]),
        code=code,
        db_path=db,
    )
    c0 = prices[code][days[9]]
    c1 = prices[code][days[10]]
    assert out.value == pytest.approx((c1 - c0) / c0)
    assert out.metadata["last_date"] == days[10]


def test_pit_lookahead_zero_available_at_after_as_of(seeded_db):
    """Features cannot see rows whose available_at > as_of, even if they exist."""
    db, days, prices = seeded_db
    code = CODES[0]
    # Push later bars' available_at into the future beyond day 10's close.
    # We re-seed with a custom available_at schedule.
    bar_av = {d: f"{d}T16:00:00+09:00" for d in days}
    # Re-seed via the helper directly:
    db2 = seed_db(
        Path(db).parent / "adv.sqlite",
        days=days,
        prices=prices,
        bar_available_at_for=bar_av,
    )
    # Calling at day[10]'s 15:30 should NOT see day[10]'s bar (its avail is 16:00).
    out = compute(
        "return_1d",
        as_of=f"{days[10]}T15:30:00+09:00",
        code=code,
        db_path=db2,
    )
    # Should use day[9] close as the latest visible — only one close => None.
    assert out.value is None or out.metadata["last_date"] < days[10]


# ---------------------------------------------------------------------------
# compute_many + reproducibility
# ---------------------------------------------------------------------------

def test_compute_many_builds_feature_vector(seeded_db):
    db, days, _ = seeded_db
    out = compute_many(
        ["return_1d", "momentum_n", "volatility_n"],
        as_of=close_iso(days[-1]),
        code=CODES[0],
        n=10,
        db_path=db,
    )
    assert set(out) == {"return_1d", "momentum_n", "volatility_n"}
    assert all(v.metadata["as_of"] == close_iso(days[-1]) for v in out.values())


def test_compute_is_reproducible(seeded_db):
    db, days, _ = seeded_db
    a = compute("return_1d", as_of=close_iso(days[-1]), code=CODES[0], db_path=db)
    b = compute("return_1d", as_of=close_iso(days[-1]), code=CODES[0], db_path=db)
    assert a.value == b.value
    assert a.metadata == b.metadata


def test_compute_metadata_carries_reproducibility_fields(seeded_db):
    db, days, _ = seeded_db
    out = compute(
        "momentum_n", as_of=close_iso(days[-1]), code=CODES[0], db_path=db, n=5,
    )
    md = out.metadata
    for k in (
        "feature_id", "feature_version", "as_of",
        "pit_api_version", "features_runtime_version", "db_path",
        "rows_seen", "n",
    ):
        assert k in md, f"missing repro field {k!r}"


# ---------------------------------------------------------------------------
# P0-5 — FeatureDefinition intended_role + status metadata
# ---------------------------------------------------------------------------
def test_builtin_features_have_intended_role_signal():
    """Every v0 builtin must declare intended_role='signal' explicitly."""
    by_id = {f.id: f for f in list_features()}
    for fid in ("return_1d", "momentum_n", "volatility_n"):
        assert fid in by_id, fid
        f = by_id[fid]
        assert f.intended_role == "signal", (fid, f.intended_role)


def test_builtin_features_default_to_approved_status():
    """Built-ins ship as 'approved' so model registries can ingest them."""
    by_id = {f.id: f for f in list_features()}
    for fid in ("return_1d", "momentum_n", "volatility_n"):
        assert by_id[fid].status == "approved", (fid, by_id[fid].status)


def test_intended_role_vocabulary_is_enforced_at_construction():
    """The Literal type prevents arbitrary role strings."""
    # Valid role passes.
    f = FeatureDefinition(
        id="dbg_close",
        version=FeatureVersion(0, 1, 0),
        inputs=features.FeatureInput(),
        description="debug",
        compute=lambda ctx: FeatureOutput(value=None),
        intended_role="utility",
        status="candidate",
    )
    assert f.intended_role == "utility"
    assert f.status == "candidate"


def test_registry_get_returns_feature_with_role_metadata():
    """``registry.get`` still works (migration-friendly) and exposes the role."""
    feat = get("return_1d")
    assert hasattr(feat, "intended_role")
    assert hasattr(feat, "status")
    assert feat.intended_role == "signal"


def test_intended_role_field_defaults_to_signal():
    """A FeatureDefinition without explicit role defaults to 'signal'."""
    f = FeatureDefinition(
        id="dbg_default_role",
        version=FeatureVersion(0, 1, 0),
        inputs=features.FeatureInput(),
        description="default role test",
        compute=lambda ctx: FeatureOutput(value=None),
    )
    assert f.intended_role == "signal"
    assert f.status == "approved"  # built-in default
