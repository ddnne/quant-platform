"""Behavioral invariants for tip-only acquisition policy."""

from __future__ import annotations

from data_contracts import (
    TIP_ONLY_POLICY,
    history_densify_forbidden,
    history_reprobe_forbidden,
    is_tip_only_policy,
    tip_only_policy_for,
)

BARS_AM = "equities_bars_daily_am"
OTC = "jsda_otc_bond_reference_prices"


# --- 5. tip-only policy forbids history_reprobe for bars_am ----------------


def test_bars_am_history_reprobe_forbidden():
    assert is_tip_only_policy(BARS_AM)
    policy = tip_only_policy_for(BARS_AM)
    assert policy is not None
    assert policy["history_reprobe"] == "FORBIDDEN"
    assert policy["history"] == "DEFER"
    assert history_reprobe_forbidden(BARS_AM) is True
    # LIVE_API_EMPTY evidence retained in policy reason
    assert "LIVE_API_EMPTY" in str(policy.get("history_reason", ""))


def test_otc_bulk_densify_and_reprobe_forbidden():
    assert is_tip_only_policy(OTC)
    policy = tip_only_policy_for(OTC)
    assert policy is not None
    assert policy["bulk_densify"] == "FORBIDDEN"
    assert policy["seal_gate"] == "FULL_OK"
    assert history_reprobe_forbidden(OTC) is True
    assert history_densify_forbidden(OTC) is True


# --- 7. history densify not invoked on tip-only datasets -------------------


def test_tip_only_history_densify_forbidden():
    assert history_densify_forbidden(BARS_AM) is True
    bars = tip_only_policy_for(BARS_AM)
    assert bars is not None
    assert bars["history_densify"] == "FORBIDDEN"
    assert bars["empty_raw_complete"] == "FORBIDDEN"
    assert bars["dataset_complete_invent"] == "FORBIDDEN"

    # Non tip-only residuals are not under densify-forbidden map by this helper
    # (master/earn_cal densify still residual-banned via permanent DEFER / SoT,
    # but not via TIP_ONLY_POLICY densify keys).
    assert history_densify_forbidden("equities_master") is False
    assert history_densify_forbidden("fins_earnings_date") is False


def test_tip_only_policy_map_exact_two():
    assert set(TIP_ONLY_POLICY) == {BARS_AM, OTC}
