"""Both-track occupancy classify helpers. Does not GO.

Cell dumps live at data/ops/research_eval/{job_id}_cells.json (fanout-owned).
Do not overwrite that file with pack['cells'] (often empty).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.unique_logic.worker_bodies import (
    classify_occupancy_pair,
    mean_occupancy_by_logic,
)


def occupancy_from_cells_file(path: str | Path) -> dict[str, float]:
    """Mean occupancy from a fanout cells.json. Missing file → empty."""
    p = Path(path)
    if not p.is_file():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return {}
    return mean_occupancy_by_logic(raw)


def merge_occupancy_cell_dumps(
    root: str | Path,
    *,
    glob: str = "eval-occupancy-audit-*_cells.json",
) -> dict[str, dict[str, float]]:
    """Merge occupancy-audit cell dumps into mid/liq maps. Later files win."""
    mid: dict[str, float] = {}
    liq: dict[str, float] = {}
    for path in sorted(Path(root).glob(glob)):
        occ = occupancy_from_cells_file(path)
        name = path.name
        if "liq_large" in name:
            liq.update(occ)
        elif "mid_n_explore" in name:
            mid.update(occ)
    return {"mid_n_explore": mid, "liq_large": liq}


def classify_occupancy_maps(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
    logic_ids: Sequence[str],
) -> dict[str, Any]:
    """Band each id. Does not mutate park/thin sets. Does not GO."""
    mid = dict(occupancy_by_track.get("mid_n_explore") or {})
    liq = dict(occupancy_by_track.get("liq_large") or {})
    by_band: dict[str, list[str]] = {
        "near_empty_park": [],
        "always_on_park": [],
        "thin_sleeve_exclude": [],
        "material": [],
        "mixed_always": [],
        "unclassified": [],
    }
    pairs: dict[str, dict[str, float | None]] = {}
    for lid in logic_ids:
        a = mid.get(lid)
        b = liq.get(lid)
        band = classify_occupancy_pair(a, b)
        by_band.setdefault(band, []).append(lid)
        pairs[lid] = {"mid_n_explore": a, "liq_large": b}
    return {
        "version": "occupancy-classify/v1",
        "n": len(list(logic_ids)),
        "by_band": {k: v for k, v in by_band.items()},
        "n_by_band": {k: len(v) for k, v in by_band.items()},
        "pairs": pairs,
        "go": False,
        "not_a_pass": True,
    }


def occupancy_recorded_drift(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
    logic_ids: Sequence[str],
) -> dict[str, Any]:
    """Compare classify bands to recorded park/thin sets. Does not unpark."""
    from research.unique_logic.constants import (
        ALWAYS_ON_PARK_IDS,
        NEAR_EMPTY_PARK_IDS,
        THIN_SLEEVE_EXCLUDE_IDS,
    )

    cls = classify_occupancy_maps(occupancy_by_track, logic_ids)
    classified_empty = set(cls["by_band"].get("near_empty_park") or [])
    classified_thin = set(cls["by_band"].get("thin_sleeve_exclude") or [])
    classified_always = set(cls["by_band"].get("always_on_park") or [])
    return {
        "empty_not_recorded": sorted(classified_empty - set(NEAR_EMPTY_PARK_IDS)),
        "thin_not_recorded": sorted(classified_thin - set(THIN_SLEEVE_EXCLUDE_IDS)),
        "always_not_recorded": sorted(classified_always - set(ALWAYS_ON_PARK_IDS)),
        "recorded_empty_not_classified": sorted(
            set(NEAR_EMPTY_PARK_IDS) & set(logic_ids) - classified_empty
        ),
        "go": False,
        "not_a_pass": True,
        "do_not_silent_unpark": True,
    }


def run_occupancy_track(
    *,
    job_id: str,
    logic_ids: Sequence[str],
    track: str,
    max_workers: int = 8,
    timeout: int = 300,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """One-track occupancy fanout. Does not overwrite cells.json. Does not GO."""
    from research.cf_daily_path_job import run_cf_daily_path_fanout
    from research.cf_mass_eval_job import (
        DEFAULT_MAX_DAYS,
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        PANELS_CACHE_PREFIX,
        panels_cache_id,
    )
    from research.eval_tracks import eval_track

    ids = [str(x) for x in logic_ids if str(x).strip()]
    spec = eval_track(track)
    max_codes = int(spec["max_codes"])
    cid = panels_cache_id(
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        max_codes=max_codes,
        max_days=DEFAULT_MAX_DAYS,
        track=track,
    )
    prefix = f"{PANELS_CACHE_PREFIX}/{cid}/panels"
    pack = run_cf_daily_path_fanout(
        job_id=job_id,
        logic_ids=ids,
        max_codes=max_codes,
        max_days=DEFAULT_MAX_DAYS,
        track=track,
        skip_stage=True,
        panels_prefix=prefix,
        mode="r2_panels",
        write_artifacts=bool(write_artifacts),
        timeout=int(timeout),
        max_workers=int(max_workers),
    )
    occ = dict(pack.get("occupancy_by_logic") or {})
    table_path = Path(pack.get("table_path") or "")
    if not occ and table_path.is_file():
        occ = occupancy_from_cells_file(table_path)
    missing = [x for x in ids if x not in occ]
    return {
        "job_id": job_id,
        "eval_track": track,
        "occupancy": occ,
        "missing": missing,
        "n_cells": pack.get("n_cells"),
        "n_complete": pack.get("n_daily_path_complete"),
        "n_errors": pack.get("n_errors"),
        "errors": pack.get("errors"),
        "table_path": pack.get("table_path"),
        "go": False,
        "not_a_pass": True,
    }


__all__ = [
    "classify_occupancy_maps",
    "classify_occupancy_pair",
    "merge_occupancy_cell_dumps",
    "occupancy_from_cells_file",
    "occupancy_recorded_drift",
    "run_occupancy_track",
]
