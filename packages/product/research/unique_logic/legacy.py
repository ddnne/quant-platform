"""Transitional imports of wave-script unique_logic evaluators.

Factory and catalog runners should import from here, not ``scripts/run_w*``.
New evaluators belong in this package, not a new run_w file.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "scripts").is_dir():
            return parent
    raise RuntimeError("quant-platform repo root not found")


def _ensure_scripts_path() -> Path:
    scripts = _repo_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    return scripts


def wave_eval_modules() -> dict[str, Any]:
    """Load existing wave modules once (deprecated location)."""
    _ensure_scripts_path()
    import run_w104_new_hyps_daily_dd as w104  # noqa: WPS433
    import run_w105_new_hyps_daily_dd as w105  # noqa: WPS433
    import run_w106_funding_surprise_ls as w106  # noqa: WPS433
    import run_w106_new_hyps_daily_dd as w106b  # noqa: WPS433
    import run_w107_funding_surprise_adaptive as w107c  # noqa: WPS433
    import run_w107_new_hyps_daily_dd as w107b  # noqa: WPS433

    return {
        "w104": w104,
        "w105": w105,
        "w106": w106,
        "w106b": w106b,
        "w107b": w107b,
        "w107c": w107c,
    }


def all_unique_logic_specs() -> list[dict[str, Any]]:
    mods = wave_eval_modules()
    out: list[dict[str, Any]] = []
    for key in ("w104", "w105", "w106b", "w107b"):
        out.extend(list(getattr(mods[key], "NEW_UNIQUE_LOGIC", ()) or ()))
    out.extend(list(getattr(mods["w106"], "NEW_LS_VARIANTS", ()) or ()))
    out.extend(list(getattr(mods["w107c"], "ADAPTIVE_VARIANTS", ()) or ()))
    return out
