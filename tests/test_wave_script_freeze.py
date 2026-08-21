"""New wave runners and proof scorecards are frozen (ADR research recording).

Existing scripts/run_w*.py may remain until staged deletion. Adding new ones
fails this test. Same for docs/proof/w08*_wNN_*.md scorecards.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PROOF = ROOT / "docs" / "proof"

# Snapshot after staged deletion (2026-08-21). Only shrink this set.
# Kept because packages/tests still import them (not importer-zero).
ALLOWED_RUN_W = frozenset(
    {
        "run_w100_peer_daily_dd.py",
        "run_w102_dispersion_quality.py",
        "run_w102_event_rate_daily_dd.py",
        "run_w103_dispersion_deepen.py",
        "run_w104_new_hyps_daily_dd.py",
        "run_w105_new_hyps_daily_dd.py",
        "run_w105_research_family_register.py",
        "run_w106_funding_surprise_ls.py",
        "run_w106_new_hyps_daily_dd.py",
        "run_w106_research_family_append.py",
        "run_w107_funding_surprise_adaptive.py",
        "run_w107_new_hyps_daily_dd.py",
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


def test_residual_is_live_flags_only() -> None:
    """Git residual must not restate experiment history (R2/D1 is SoT)."""
    residual = ROOT / "docs" / "phase62_residual_status.md"
    text = residual.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) <= 80, f"residual grew back into a warehouse n={len(lines)}"
    banned = (
        "W90 underneath",
        "W107 ALL-TRACK",
        "worst **−",
        "Batch11",
    )
    hits = [b for b in banned if b in text]
    assert hits == [], f"residual must stay live flags only; banned={hits}"
    assert "daily_path_eval" in text
    assert "eval_registry" in text
    assert "NO-GO" in text
