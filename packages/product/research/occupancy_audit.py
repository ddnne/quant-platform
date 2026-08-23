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


__all__ = [
    "classify_occupancy_maps",
    "classify_occupancy_pair",
    "merge_occupancy_cell_dumps",
    "occupancy_from_cells_file",
]
