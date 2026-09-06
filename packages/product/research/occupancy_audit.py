"""Both-track occupancy classify helpers. Does not GO.

Cell dumps live at data/ops/research_eval/{job_id}_cells.json (fanout-owned).
Do not overwrite that file with pack['cells'] (often empty).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.occupancy_guards import (
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
    """Merge occupancy-audit cell dumps into mid/liq maps. Later mtime wins."""
    mid: dict[str, float] = {}
    liq: dict[str, float] = {}
    paths = sorted(
        Path(root).glob(glob), key=lambda p: (p.stat().st_mtime, p.name)
    )
    for path in paths:
        occ = occupancy_from_cells_file(path)
        name = path.name
        if "liq_large" in name:
            liq.update(occ)
        elif "mid_n_explore" in name:
            mid.update(occ)
    return {"mid_n_explore": mid, "liq_large": liq}


def _ops_root(root: Path | None) -> Path:
    if root is not None:
        ops = Path(root)
        ops.mkdir(parents=True, exist_ok=True)
        return ops
    from qp_paths import repo_root

    ops = repo_root() / "data" / "ops" / "research_eval"
    ops.mkdir(parents=True, exist_ok=True)
    return ops


def _float_occ_map(raw: Mapping[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, val in dict(raw or {}).items():
        lid = str(key).strip()
        if not lid:
            continue
        try:
            out[lid] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def load_ops_occupancy(root: str | Path | None = None) -> dict[str, dict[str, float]]:
    """Latest occupancy_maps json, overlay cell dumps newer than maps. Not GO.

    Maps-only would drop occupancy written after the last wave pack.
    Does not fan out.
    """
    from qp_paths import repo_root

    ops = Path(root) if root is not None else repo_root() / "data" / "ops" / "research_eval"
    maps = sorted(
        ops.glob("eval-occupancy-maps-*.json"),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    mid: dict[str, float] = {}
    liq: dict[str, float] = {}
    maps_mtime = 0.0
    for path in reversed(maps):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        got_mid = _float_occ_map(raw.get("mid_n_explore"))
        got_liq = _float_occ_map(raw.get("liq_large"))
        if got_mid and got_liq:
            mid, liq = got_mid, got_liq
            maps_mtime = path.stat().st_mtime
            break
    for path in sorted(
        ops.glob("eval-occupancy-audit-*_cells.json"),
        key=lambda p: (p.stat().st_mtime, p.name),
    ):
        if path.stat().st_mtime + 1e-9 < maps_mtime:
            continue
        occ = occupancy_from_cells_file(path)
        name = path.name
        if "liq_large" in name:
            liq.update(occ)
        elif "mid_n_explore" in name:
            mid.update(occ)
    if mid or liq:
        return {"mid_n_explore": mid, "liq_large": liq}
    return merge_occupancy_cell_dumps(ops)


def _track_from_cells_name(name: str) -> str | None:
    if "liq_large" in name:
        return "liq_large"
    if "mid_n_explore" in name:
        return "mid_n_explore"
    return None


def merge_daily_path_cells_for_ids(
    root: str | Path,
    logic_ids: Sequence[str],
    *,
    glob: str = "*_cells.json",
) -> dict[str, list[dict[str, Any]]]:
    """Later files win per (track, logic_id, window). Keeps net_daily. Not a pass."""
    want = {str(x).strip() for x in logic_ids if str(x).strip()}
    by_track: dict[str, dict[tuple[str, str], dict[str, Any]]] = {
        "mid_n_explore": {},
        "liq_large": {},
    }
    for path in sorted(Path(root).glob(glob)):
        track = _track_from_cells_name(path.name)
        if track is None:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, list):
            continue
        slot = by_track[track]
        for cell in raw:
            if not isinstance(cell, dict):
                continue
            lid = str(cell.get("logic_id") or "").strip()
            if lid not in want:
                continue
            nd = cell.get("net_daily")
            if not isinstance(nd, list) or len(nd) < 2:
                continue
            wid = str(cell.get("window_id") or cell.get("window") or "").strip()
            if not wid:
                continue
            slot[(lid, wid)] = cell
    return {
        track: list(slot.values())
        for track, slot in by_track.items()
    }


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


def usable_eval_snapshot(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Inventory v1 + usable-read v3 + cost-risk + drift. Not a pass.

    Does not fan out occupancy. Does not GO. Catalog SoT is the compiled map.
    """
    from research.holding_metrics import DEFAULT_ONE_WAY_COST
    from research.unique_logic.worker_bodies import (
        CHEAP_PB_PRIMARY_GATE_CAP,
        countable_thesis_ids,
        usable_inventory,
        usable_inventory_read,
        usable_series_breakdown,
    )

    inv = usable_inventory(occupancy_by_track)
    read = usable_inventory_read(occupancy_by_track)
    drift = occupancy_recorded_drift(
        occupancy_by_track, sorted(countable_thesis_ids())
    )
    usable = set(inv.get("usable_ids") or ())
    mid = dict(occupancy_by_track.get("mid_n_explore") or {})
    liq = dict(occupancy_by_track.get("liq_large") or {})

    def _summ(mp: Mapping[str, float]) -> dict[str, float | int]:
        xs = sorted(float(mp[i]) for i in usable if i in mp)
        n = len(xs)
        if not n:
            return {"n": 0}
        return {
            "n": n,
            "min": round(xs[0], 4),
            "p50": round(xs[n // 2], 4),
            "max": round(xs[-1], 4),
            "mean": round(sum(xs) / n, 4),
        }

    cost = {
        "version": "usable-cost-risk/v1",
        "n_usable": inv["n_usable"],
        "occupancy": {"mid_n_explore": _summ(mid), "liq_large": _summ(liq)},
        "one_way_cost": float(DEFAULT_ONE_WAY_COST),
        "fake_split": False,
        "pri_series": read["pri_series"],
        "n_ands": read["n_ands"],
        "cheap_pb_primary_share": read["cheap_pb_primary_share"],
        "go": False,
        "not_a_pass": True,
    }
    read_pack = dict(read)
    read_pack.update(
        {
            "drift": drift,
            "cheap_pb_primary_cap": CHEAP_PB_PRIMARY_GATE_CAP,
            "do_not_silent_unpark": True,
        }
    )
    return {
        "inventory": inv,
        "usable_read": read_pack,
        "series": usable_series_breakdown(occupancy_by_track),
        "cost_risk": cost,
        "go": False,
        "not_a_pass": True,
    }


def write_usable_eval_snapshot(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
    *,
    wave: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Write a local replay snapshot. This legacy path is never R2 authority."""
    from research.unique_logic.catalog import write_combo_thesis_jsonl

    snap = usable_eval_snapshot(occupancy_by_track)
    ops = _ops_root(root)
    inv_job = f"eval-usable-inventory-{wave}"
    read_job = f"eval-usable-inventory-read-{wave}"
    series_job = f"eval-usable-series-{wave}"
    cost_job = f"eval-usable-cost-risk-{wave}"
    jsonl_job = f"eval-combo-jsonl-{wave}"
    read = dict(snap["usable_read"])
    read["job_id"] = read_job
    series = dict(snap["series"])
    series["job_id"] = series_job
    files = {
        inv_job: (ops / f"{inv_job}.json", json.dumps(snap["inventory"], ensure_ascii=True)),
        read_job: (ops / f"{read_job}.json", json.dumps(read, ensure_ascii=True, default=str)),
        series_job: (ops / f"{series_job}.json", json.dumps(series, ensure_ascii=True, default=str)),
        cost_job: (ops / f"{cost_job}.json", json.dumps(snap["cost_risk"], ensure_ascii=True)),
    }
    for path, body in files.values():
        path.write_text(body, encoding="utf-8")
    jsonl = write_combo_thesis_jsonl(ops / f"{jsonl_job}.jsonl")
    return {
        "wave": wave,
        "n_usable": snap["inventory"]["n_usable"],
        "inventory_job": inv_job,
        "usable_read_job": read_job,
        "series_job": series_job,
        "cost_risk_job": cost_job,
        "jsonl": jsonl,
        "puts": [],
        "go": False,
        "not_a_pass": True,
        "yaml_still_present": False,
    }


def write_eval_wave_pack(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
    *,
    wave: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Snapshot plus drift / unique22 park / reconstitution detect. Not GO.

    Does not fan out occupancy. Does not apply reconstitution. Does not inject.
    """
    from research.combo_basket_catalog import (
        RECONSTITUTION_APPLY,
        active_reconstitution_plan,
        reconstitution_occupancy_preview,
        usable_sleeve_coverage,
    )
    from research.eval_flags import CATALOG_AND_PLUS_N_STOPPED
    from research.unique_logic.worker_bodies import (
        UNIQUE22_PARK_REASONS,
        countable_thesis_ids,
        unique22_occupancy_equal_lifted,
        unique22_occupancy_park,
    )

    snap = write_usable_eval_snapshot(occupancy_by_track, wave=wave, root=root)
    ops = _ops_root(root)
    drift = occupancy_recorded_drift(
        occupancy_by_track, sorted(countable_thesis_ids())
    )
    drift_job = f"eval-occupancy-drift-{wave}"
    park = unique22_occupancy_park()
    lifted = unique22_occupancy_equal_lifted()
    u22_job = f"eval-unique22-park-{wave}"
    recon_job = f"eval-reconstitution-plan-{wave}"
    sleeve_job = f"eval-series-sleeve-{wave}"
    maps_job = f"eval-occupancy-maps-{wave}"
    mid = _float_occ_map(occupancy_by_track.get("mid_n_explore"))
    liq = _float_occ_map(occupancy_by_track.get("liq_large"))
    recon_sleeves: list[dict[str, Any]] = []
    for p in active_reconstitution_plan():
        nested = p.get("nested_parents") or []
        n_nested = p.get("nested_parent_count")
        if n_nested is None:
            n_nested = len(nested)
        drop_p = p.get("drop_parents_keep_children") or {}
        drop_c = p.get("drop_children_keep_parents") or {}
        recon_sleeves.append(
            {
                "basket_id": p["basket_id"],
                "primary": p.get("primary"),
                "needs_reconstitution": p.get("needs_reconstitution"),
                "nested_parent_count": int(n_nested),
                "nested_pairs": [
                    {"parent": x.get("parent"), "child": x.get("child")}
                    for x in nested
                    if isinstance(x, Mapping)
                ],
                "drop_parents_n": len(drop_p.get("members") or []),
                "drop_children_n": len(drop_c.get("members") or []),
                "apply_reject": False,
            }
        )
    extras = {
        maps_job: {
            "job_id": maps_job,
            "n_mid": len(mid),
            "n_liq": len(liq),
            "mid_n_explore": mid,
            "liq_large": liq,
            "go": False,
            "not_a_pass": True,
        },
        drift_job: {
            **dict(drift),
            "job_id": drift_job,
            "do_not_silent_unpark": True,
        },
        u22_job: {
            "job_id": u22_job,
            "n_parked": len(park),
            "n_lifted": len(lifted),
            "parked": sorted(park),
            "lifted": sorted(lifted),
            "reasons": dict(UNIQUE22_PARK_REASONS),
            "do_not_silent_unpark": True,
            "go": False,
            "not_a_pass": True,
        },
        recon_job: {
            "job_id": recon_job,
            "apply": bool(RECONSTITUTION_APPLY),
            "sleeves": recon_sleeves,
            "occupancy_preview": reconstitution_occupancy_preview(
                occupancy_by_track
            ),
            "go": False,
            "not_a_pass": True,
        },
        sleeve_job: {
            "job_id": sleeve_job,
            **usable_sleeve_coverage(occupancy_by_track),
            "apply": bool(RECONSTITUTION_APPLY),
            "go": False,
            "not_a_pass": True,
        },
    }
    for job, body in extras.items():
        path = ops / f"{job}.json"
        raw = json.dumps(body, ensure_ascii=True, default=str)
        path.write_text(raw, encoding="utf-8")
    return {
        **snap,
        "occupancy_maps_job": maps_job,
        "drift_job": drift_job,
        "unique22_job": u22_job,
        "reconstitution_job": recon_job,
        "series_sleeve_job": sleeve_job,
        "n_unique22_parked": len(park),
        "n_unique22_lifted": len(lifted),
        "n_mid": len(mid),
        "n_liq": len(liq),
        "puts": [],
        "catalog_and_plus_n_stopped": bool(CATALOG_AND_PLUS_N_STOPPED),
        "reconstitution_apply": bool(RECONSTITUTION_APPLY),
        "go": False,
        "not_a_pass": True,
    }


from research.occupancy_audit_run import (  # noqa: E402
    run_eval_wave,
    run_occupancy_track,
)


__all__ = [
    "classify_occupancy_maps",
    "classify_occupancy_pair",
    "load_ops_occupancy",
    "merge_daily_path_cells_for_ids",
    "merge_occupancy_cell_dumps",
    "occupancy_from_cells_file",
    "occupancy_recorded_drift",
    "run_eval_wave",
    "run_occupancy_track",
    "usable_eval_snapshot",
    "write_usable_eval_snapshot",
    "write_eval_wave_pack",
]
