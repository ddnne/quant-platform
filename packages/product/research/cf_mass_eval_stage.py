"""Retired Mass r2_panels staging entrypoints plus shared period normalizer and COMPLETE constants.

build_real_period_panel and stage_real_panels_to_r2 refuse via
refuse_mass_host_entrypoint. They do not stage panels. Universe policy
for remaining constants remains liq_large default (100), never head-N.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from data_contracts.permanent_defer import PERMANENT_DEFER_DATASETS
from research.complete21 import COMPLETE_21_DATASETS


RESEARCH_ARTIFACT_BUCKET: str = "quant-structured"
RESEARCH_ARTIFACT_PREFIX: str = "research/mass_eval"
# liq_large default (100). Never head-N.
DEFAULT_MAX_CODES: int = 100
DEFAULT_MAX_DAYS: int = 120

# COMPLETE 22 = COMPLETE 21 + fins_earnings_date. Permanent DEFER excluded.
COMPLETE_22_DATASETS: tuple[str, ...] = tuple(
    sorted(set(COMPLETE_21_DATASETS) | {"fins_earnings_date"})
)
COMPLETE_22_DATASET_SET: frozenset[str] = frozenset(COMPLETE_22_DATASETS)
PRIMARY_BARS_DATASET: str = "equities_bars_daily"
if len(COMPLETE_22_DATASETS) != 22:
    raise RuntimeError(
        f"COMPLETE_22_DATASETS must have 22 ids, got {len(COMPLETE_22_DATASETS)}"
    )
if COMPLETE_22_DATASET_SET & PERMANENT_DEFER_DATASETS:
    raise RuntimeError(
        "COMPLETE_22_DATASETS must not intersect permanent DEFER: "
        f"{sorted(COMPLETE_22_DATASET_SET & PERMANENT_DEFER_DATASETS)}"
    )


def normalize_period_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    p = dict(raw)
    pid = str(p.get("period_id") or p.get("id") or "period")
    start = p.get("period_start") or p.get("start") or ""
    end = p.get("period_end") or p.get("end") or ""
    year = p.get("year")
    if year is None and start:
        try:
            year = int(str(start)[:4])
        except ValueError:
            year = None
    if year is None:
        for token in pid.replace("-", "_").split("_"):
            if token.startswith("y") and token[1:].isdigit() and len(token) == 5:
                year = int(token[1:])
                break
            if token.isdigit() and len(token) == 4:
                year = int(token)
                break
    out: dict[str, Any] = {"period_id": pid}
    if year is not None:
        out["year"] = int(year)
    if start:
        out["period_start"] = str(start)[:10]
    if end:
        out["period_end"] = str(end)[:10]
    return out


def build_real_period_panel(
    period: Mapping[str, Any],
    *,
    codes: Sequence[str] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    view: Any | None = None,
) -> dict[str, Any]:
    from research.mass_disabled import refuse_mass_host_entrypoint

    refuse_mass_host_entrypoint("build_real_period_panel")


def stage_real_panels_to_r2(
    job_id: str,
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    codes: Sequence[str] | None = None,
    max_codes: int = DEFAULT_MAX_CODES,
    max_days: int = DEFAULT_MAX_DAYS,
    dry_run: bool = False,
    staging_dir: str | Path | None = None,
    r2_put: Callable[..., Mapping[str, Any]] | None = None,
    panels_prefix: str | None = None,
    view: Any | None = None,
) -> dict[str, Any]:
    from research.mass_disabled import refuse_mass_host_entrypoint

    refuse_mass_host_entrypoint("stage_real_panels_to_r2")


__all__ = [
    "COMPLETE_22_DATASETS",
    "COMPLETE_22_DATASET_SET",
    "DEFAULT_MAX_CODES",
    "DEFAULT_MAX_DAYS",
    "PRIMARY_BARS_DATASET",
    "RESEARCH_ARTIFACT_BUCKET",
    "RESEARCH_ARTIFACT_PREFIX",
    "build_real_period_panel",
    "normalize_period_row",
    "stage_real_panels_to_r2",
]
