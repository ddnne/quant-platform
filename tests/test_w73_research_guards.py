"""W73 / w0816g — research guards (maintain): S1–S5 rejected · no READY/Mass · no new signs."""

from __future__ import annotations

from research.baseline_catalog import (
    MASS_GENERATE_SIGNALS,
    MASS_RESEARCH,
    PHASE7,
    READY_DECLARED,
    REJECTED_SIMPLE_DAILY_SIGN_BASELINES,
    RESEARCH_STATUS_REJECTED,
    SIGNAL_ID_S1,
    SIGNAL_ID_S2,
    SIGNAL_ID_S3,
    SIGNAL_ID_S4,
    SIGNAL_ID_S5,
    assert_catalog_closed_to_ready_mass,
    is_research_baseline_rejected,
    rejected_baseline_catalog,
)
from research.eval_harness import (
    MASS_RESEARCH as HARNESS_MASS,
    PHASE7 as HARNESS_PHASE7,
    run_standard_research_eval,
)


def test_s1_to_s5_still_research_baseline_rejected():
    ids = (SIGNAL_ID_S1, SIGNAL_ID_S2, SIGNAL_ID_S3, SIGNAL_ID_S4, SIGNAL_ID_S5)
    for sid in ids:
        assert is_research_baseline_rejected(sid) is True
    cat = rejected_baseline_catalog()
    assert set(cat["signal_ids"]) == set(ids)
    assert len(REJECTED_SIMPLE_DAILY_SIGN_BASELINES) == 5
    for sid in ids:
        entry = cat["baselines"][sid]
        assert entry["research_status"] == RESEARCH_STATUS_REJECTED
        assert entry["ready_declared"] is False
        assert entry["mass_research"] == "NO-GO"
        assert entry["phase7"] == "OFF"


def test_standard_eval_never_sets_ready_or_mass():
    out = run_standard_research_eval(dry_run=True)
    assert out["ready_declared"] is False
    assert out["operational_go"] is False
    assert out["mass_research"] == "NO-GO"
    assert out["phase7"] == "OFF"
    assert out["connected_to_ready"] is False
    assert out["connected_to_mass"] is False
    assert out["research_candidate"] is False
    assert out["new_signals_registered"] is False
    assert HARNESS_MASS == "NO-GO"
    assert HARNESS_PHASE7 == "OFF"
    # Catalog freezes
    assert READY_DECLARED is False
    assert MASS_RESEARCH == "NO-GO"
    assert PHASE7 == "OFF"
    assert MASS_GENERATE_SIGNALS is False
    assert_catalog_closed_to_ready_mass()


def test_no_new_simple_daily_sign_baselines():
    """W73 maintain: catalog stays at exactly S1–S5 rejected; no mass-minted signs."""
    cat = rejected_baseline_catalog()
    assert len(cat["signal_ids"]) == 5
    assert set(cat["hyp_ids"]) == {"S1", "S2", "S3", "S4", "S5"}
    assert MASS_GENERATE_SIGNALS is False
    out = run_standard_research_eval(dry_run=True)
    assert out["new_signals_registered"] is False
    assert out.get("densify") is False
