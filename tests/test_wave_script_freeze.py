"""New wave runners and proof scorecards are frozen (ADR research recording).

Existing scripts/run_w*.py may remain until staged deletion. Adding new ones
fails this test. Same for docs/proof/w08*_wNN_*.md scorecards.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PROOF = ROOT / "docs" / "proof"

# Snapshot at freeze (2026-08-21). Only shrink this set (staged deletion).
ALLOWED_RUN_W = frozenset(
    {
        "run_w100_peer_daily_dd.py",
        "run_w101_hyps_dd_close.py",
        "run_w102_dispersion_quality.py",
        "run_w102_event_rate_daily_dd.py",
        "run_w103_dispersion_deepen.py",
        "run_w103_repo_gate_deepen.py",
        "run_w103_repo_short_cost.py",
        "run_w104_new_hyps_daily_dd.py",
        "run_w105_funding_surprise_deepdive.py",
        "run_w105_new_hyps_daily_dd.py",
        "run_w105_research_family_register.py",
        "run_w106_funding_surprise_ls.py",
        "run_w106_new_hyps_daily_dd.py",
        "run_w106_research_family_append.py",
        "run_w107_curve_steepen_deepdive.py",
        "run_w107_funding_surprise_adaptive.py",
        "run_w107_new_hyps_daily_dd.py",
        "run_w107_research_family_append.py",
        "run_w90_llm_cf_mass_eval.py",
        "run_w90_llm_hyp_cf_eval.py",
        "run_w91_real_cf_mass_eval.py",
        "run_w92_options_vol_cf_eval.py",
        "run_w92_options_vol_cf_mass_eval.py",
        "run_w93_opt225_diff_windows.py",
        "run_w93_thicken_cf_panels.py",
        "run_w94_opt_skew_windows.py",
        "run_w94_thick_factor_windows.py",
        "run_w95_factor_failure_decomp.py",
        "run_w95_promising_reeval.py",
        "run_w95_shape_deepdive.py",
        "run_w95_shape_factor_decomp.py",
        "run_w96_hyps_and_defaults.py",
        "run_w97_survivor_deep_eval.py",
        "run_w98_xs_rank_ls_sticky_deep.py",
        "run_w98_xs_sticky_deepdive.py",
        "run_w99_sticky_daily_dd.py",
    }
)


def test_no_new_run_w_scripts() -> None:
    found = {p.name for p in SCRIPTS.glob("run_w*.py")}
    extra = sorted(found - ALLOWED_RUN_W)
    missing_ok = ALLOWED_RUN_W - found  # staged deletion is allowed
    assert extra == [], (
        "New scripts/run_wNN_*.py is forbidden "
        "(docs/architecture/adr_research_recording.md). "
        f"extra={extra} (deletions ok: {sorted(missing_ok)})"
    )


def test_no_new_wave_proof_scorecards_this_commit_tree() -> None:
    """Ban newly added w0820e+ / w0821+ scorecard filenames.

    Existing w0815–w0820d proofs stay. A new ``w0820e_*`` or ``w0821*_wNN_``
    file is a scorecard warehouse and must not be added.
    """
    banned: list[str] = []
    for p in PROOF.glob("w08*.md"):
        name = p.name
        if name.startswith("w0820e_") or name.startswith("w0821"):
            banned.append(name)
        if name.startswith("w0822") or name.startswith("w0823"):
            banned.append(name)
    assert banned == [], (
        "New wave proof scorecards are forbidden. Use research.eval_registry. "
        f"banned={banned}"
    )
