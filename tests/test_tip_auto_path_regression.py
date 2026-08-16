"""W73 / w0816g — tip auto-collect path regression guards.

Locks:
* tip-only policy forbids history_reprobe / history densify for bars_am (+ OTC)
* seal/issue path calls sync_dataset_coverage_from_segments (aggregate sync)
* history densify is not invoked on tip-only datasets via issue/restore scripts
"""

from __future__ import annotations

import ast
from pathlib import Path

from data_contracts import (
    TIP_ONLY_POLICY,
    history_densify_forbidden,
    history_reprobe_forbidden,
    is_tip_only_policy,
    tip_only_policy_for,
)

REPO = Path(__file__).resolve().parents[1]

ISSUE_SIGNED = REPO / "scripts" / "issue_signed_receipts_for_segments.py"
ISSUE_PARALLEL = REPO / "scripts" / "issue_receipts_parallel.py"
RESTORE = REPO / "scripts" / "restore_local_complete_from_receipt.py"
SYNC_CLI = REPO / "scripts" / "sync_dataset_coverage_from_segments.py"

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


def _script_calls_name(path: Path, func_name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == func_name:
                return True
            if isinstance(fn, ast.Attribute) and fn.attr == func_name:
                return True
    return False


def _script_imports_name(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == name:
                    return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == name or alias.name.endswith(f".{name}"):
                    return True
    return False


# --- 6. seal/issue path calls aggregate sync --------------------------------


def test_issue_signed_receipts_calls_aggregate_sync():
    src = ISSUE_SIGNED.read_text(encoding="utf-8")
    assert "sync_dataset_coverage_from_segments" in src
    assert _script_imports_name(ISSUE_SIGNED, "sync_dataset_coverage_from_segments")
    assert _script_calls_name(ISSUE_SIGNED, "sync_dataset_coverage_from_segments")
    # tip-path commentary retained
    assert "tip auto-collect" in src.lower() or "W72" in src


def test_issue_receipts_parallel_calls_aggregate_sync():
    src = ISSUE_PARALLEL.read_text(encoding="utf-8")
    assert "sync_dataset_coverage_from_segments" in src
    assert _script_imports_name(ISSUE_PARALLEL, "sync_dataset_coverage_from_segments")
    assert _script_calls_name(ISSUE_PARALLEL, "sync_dataset_coverage_from_segments")
    assert "Post-seal surgical sync_dataset_coverage_from_segments" in src


def test_restore_path_calls_aggregate_sync():
    src = RESTORE.read_text(encoding="utf-8")
    assert "sync_dataset_coverage_from_segments" in src
    assert _script_calls_name(RESTORE, "sync_dataset_coverage_from_segments")


def test_issue_paths_do_not_invoke_history_densify_or_reprobe():
    """Static guard: seal/issue scripts never call densify/reprobe helpers."""
    forbidden_tokens = (
        "history_reprobe",
        "history_densify",
        "bulk_densify",
        "cf_premium_backfill",
        "run_historical_backfill",
    )
    for path in (ISSUE_SIGNED, ISSUE_PARALLEL, RESTORE):
        src = path.read_text(encoding="utf-8")
        lower = src.lower()
        # Aggregate sync is required; densify/backfill must not be.
        assert "sync_dataset_coverage_from_segments" in src
        for tok in forbidden_tokens:
            # Allow comments that say FORBIDDEN / not densify, but no call sites.
            # Reject function-call style usage.
            assert f"{tok}(" not in src
            assert f"call_{tok}" not in lower
        # No import of densify planner entrypoints
        tree = ast.parse(src, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "backfill_planner" not in mod
                assert "cf_premium_backfill" not in mod
                for alias in node.names:
                    assert "densify" not in alias.name.lower()
                    assert "reprobe" not in alias.name.lower()


def test_sync_cli_doc_forbids_mass_ready():
    src = SYNC_CLI.read_text(encoding="utf-8")
    assert "Mass / READY remain OFF" in src or "Mass / READY" in src
    assert "never invents segments" in src.lower() or "never invents" in src
