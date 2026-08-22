"""COMPLETE 21 min features — registry, promotion pins, runtime gates.

W49–W57 catalog + DEFER-guarded min features. Behavior is split by concern:

* ``test_complete21_min_guards.py`` — dataset / DEFER fail-closed / FeatureContext
* ``test_complete21_min_helpers.py`` — data-free pure helpers
* ``test_complete21_min_compute.py`` — PIT gates + seeded compute

Shared constants/seed helpers: ``tests/complete21_min_util.py``.
This module keeps registration, version pin, MissingInput, and as_of gates.
No READY / Mass / Phase7.
"""

from __future__ import annotations

import pytest

from features import compute, get, get_for_strategy, list_features
from features.registry import FeatureGovernanceError
from features.runtime import AsOfRequired, MissingInput

from tests.complete21_min_util import (
    COMPLETE21_MIN_APPROVED_IDS,
    COMPLETE21_MIN_CANDIDATE_IDS,
    COMPLETE21_MIN_IDS,
    CODES,
    _REQUIRED_INPUT_CASES,
    close_iso,
    seed_db,
)


@pytest.mark.parametrize("fid,required", _REQUIRED_INPUT_CASES)
def test_complete21_min_missing_required_inputs(tmp_path, fid, required):
    """Runtime MissingInput before compute when required kwargs are absent."""
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    with pytest.raises(MissingInput) as exc:
        compute(fid, as_of=close_iso(days[-1]), db_path=db)
    msg = str(exc.value)
    for key in required:
        assert key in msg


def test_complete21_min_requires_as_of(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    with pytest.raises(AsOfRequired):
        compute("volume_change_1d", as_of=None, code=CODES[0], db_path=db)
    with pytest.raises(AsOfRequired):
        compute("return_1d_c21", as_of=None, code=CODES[0], db_path=db)
    with pytest.raises(AsOfRequired):
        compute("margin_alert_flag", as_of=None, code=CODES[0], db_path=db)


def test_complete21_min_w56_promotion_status_and_version_pin():
    """W52–W57: 9 approved (pinned 1.0.0); remaining 1 stays candidate."""
    for fid in COMPLETE21_MIN_APPROVED_IDS:
        feat = get(fid)
        assert feat.status == "approved", fid
        assert str(feat.version) == "1.0.0", fid
    for fid in COMPLETE21_MIN_CANDIDATE_IDS:
        feat = get(fid)
        assert feat.status == "candidate", fid
        assert feat.status != "approved", fid
    assert len(COMPLETE21_MIN_APPROVED_IDS) == 9
    assert len(COMPLETE21_MIN_CANDIDATE_IDS) == 1
    # Policy: return_1d_c21 must remain candidate (twin of v0 return_1d)
    assert get("return_1d_c21").status == "candidate"
    assert "return_1d_c21" not in COMPLETE21_MIN_APPROVED_IDS
    # W54 selective O2 promote
    assert get("repo_rate_level").status == "approved"
    assert get("repo_rate_level").intended_role == "state"
    # W55 selective O2 promote
    assert get("short_ratio_level").status == "approved"
    assert get("short_ratio_level").intended_role == "signal"
    assert "section" in get("short_ratio_level").inputs.required_kwargs
    # W56 optional O2 promote
    assert get("futures_activity_proxy").status == "approved"
    assert get("futures_activity_proxy").intended_role == "state"
    # W57 optional O2 promote
    assert get("margin_alert_flag").status == "approved"
    assert get("margin_alert_flag").intended_role == "signal"
    assert "code" in get("margin_alert_flag").inputs.required_kwargs


def test_get_for_strategy_admits_approved_signal_not_utility_or_candidate():
    """Contract: get_for_strategy admits approved strategy-facing roles only."""
    # volume_change_1d: approved + signal → admitted
    vol = get_for_strategy("volume_change_1d", version="1.0.0")
    assert vol.status == "approved"
    assert vol.intended_role == "signal"
    assert str(vol.version) == "1.0.0"

    # W53 O2 promotes: topix / disclosure / margin also admitted as signal
    topix = get_for_strategy("topix_relative_1d", version="1.0.0")
    assert topix.status == "approved"
    assert topix.intended_role == "signal"
    disc = get_for_strategy("disclosure_flag_fins", version="1.0.0")
    assert disc.status == "approved"
    margin = get_for_strategy("margin_interest_change_1d", version="1.0.0")
    assert margin.status == "approved"

    # W54 O2 promote: repo_rate_level approved + state → admitted (state is default role)
    repo = get_for_strategy("repo_rate_level", version="1.0.0")
    assert repo.status == "approved"
    assert repo.intended_role == "state"
    assert str(repo.version) == "1.0.0"

    # W55 O2 promote: short_ratio_level approved + signal → admitted (section required)
    short = get_for_strategy("short_ratio_level", version="1.0.0")
    assert short.status == "approved"
    assert short.intended_role == "signal"
    assert str(short.version) == "1.0.0"
    assert "section" in short.inputs.required_kwargs

    # W56 optional O2 promote: futures_activity_proxy approved + state → admitted
    fut = get_for_strategy("futures_activity_proxy", version="1.0.0")
    assert fut.status == "approved"
    assert fut.intended_role == "state"
    assert str(fut.version) == "1.0.0"

    # W57 optional O2 promote: margin_alert_flag approved + signal → admitted
    mflag = get_for_strategy("margin_alert_flag", version="1.0.0")
    assert mflag.status == "approved"
    assert mflag.intended_role == "signal"
    assert str(mflag.version) == "1.0.0"
    assert "code" in mflag.inputs.required_kwargs

    # is_trading_day: approved but utility → role gate rejects by default
    with pytest.raises(FeatureGovernanceError, match="utility"):
        get_for_strategy("is_trading_day", version="1.0.0")
    util = get_for_strategy(
        "is_trading_day",
        version="1.0.0",
        allowed_roles=("utility", "signal", "state", "structural"),
    )
    assert util.status == "approved"
    assert util.intended_role == "utility"

    # remaining complete21 min stay candidate → status gate rejects
    with pytest.raises(FeatureGovernanceError, match="candidate"):
        get_for_strategy("return_1d_c21")


def test_complete21_min_features_registered():
    ids = {f.id for f in list_features()}
    assert set(COMPLETE21_MIN_IDS).issubset(ids)
    for fid in COMPLETE21_MIN_IDS:
        feat = get(fid)
        assert "complete21" in feat.tags
        if fid in COMPLETE21_MIN_APPROVED_IDS:
            assert feat.status == "approved", fid
        else:
            assert feat.status == "candidate", fid

