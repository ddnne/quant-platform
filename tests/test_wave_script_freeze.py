"""New wave runners and proof scorecards are frozen (ADR research recording).

scripts/run_w*.py are gone (ALLOWED_RUN_W empty). Adding new ones
fails this test. Same for docs/proof/w08*_wNN_*.md scorecards.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PROOF = ROOT / "docs" / "proof"

# Snapshot after unique_logic extract (2026-08-21). Empty = no remaining
# scripts/run_w*.py. New files still fail. Deletions remain allowed.
ALLOWED_RUN_W = frozenset()


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
    assert "PARSE_ZERO" in text
    assert "2002-08-02" in text
    assert "2002-08-05" in text
