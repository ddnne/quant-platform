"""Refuse AND growth, known-thin rewrites, empty/always-on batches. Not GO.

Live flags stay in ``eval_flags``. Counting stays in ``worker_bodies``.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from research.eval_flags import (
    CATALOG_AND_PLUS_N_STOPPED,
    CATALOG_YAML_COUNT_AT_STOP,
    EVENT_THREE_AND_PLUS_N_STOPPED,
)
from research.unique_logic.catalog import catalog_dir, load_catalog_specs, spec_gates
from research.unique_logic.constants import (
    ALWAYS_ON_OCCUPANCY_WARN,
    KNOWN_THIN_UNUSED_GATE_SETS,
    NEAR_EMPTY_OCCUPANCY,
    NEAR_EMPTY_PARK_IDS,
    USABLE_OCCUPANCY_MIN,
)

CHEAP_PB_PRIMARY_GATE_CAP: float = 0.20


class CheapPbPrimaryCapError(ValueError):
    """New batch exceeds cheap_pb-as-primary-gate cap. Not a pass."""


class CatalogAndPlusNStoppedError(ValueError):
    """Catalog AND +N is frozen. Flip only with a dated brief. Not a pass."""


class KnownThinRewriteError(ValueError):
    """Known-thin unused gate-set was rewritten into the catalog. Not a pass."""


class EventThreeAndBatchError(ValueError):
    """New batch uses 3-AND while EVENT_THREE_AND_PLUS_N_STOPPED. Not a pass."""


class NearEmptyBatchError(ValueError):
    """New batch has occupancy ≤ near_empty threshold. Not a pass."""


class AlwaysOnBatchError(ValueError):
    """New batch has occupancy ≥ always_on threshold. Not a pass."""


def primary_gate_of(spec: Mapping[str, Any]) -> str | None:
    gates = spec_gates(spec)
    return gates[0] if gates else None


def assert_catalog_and_plus_n_stopped() -> dict[str, Any]:
    """Refuse yaml growth while CATALOG_AND_PLUS_N_STOPPED. Does not GO."""
    n = len(list(catalog_dir().glob("*.yaml")))
    out = {
        "stopped": bool(CATALOG_AND_PLUS_N_STOPPED),
        "n": n,
        "freeze": int(CATALOG_YAML_COUNT_AT_STOP),
        "ok": True,
        "go": False,
        "not_a_pass": True,
    }
    if not CATALOG_AND_PLUS_N_STOPPED:
        return out
    if n != int(CATALOG_YAML_COUNT_AT_STOP):
        raise CatalogAndPlusNStoppedError(
            f"catalog yaml n={n} != freeze {int(CATALOG_YAML_COUNT_AT_STOP)}; "
            "dated brief must flip CATALOG_AND_PLUS_N_STOPPED to add AND YAML"
        )
    return out


def assert_known_thin_unused_absent(
    specs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refuse catalog rows whose gates match known-thin unused 2-ANDs."""
    rows = list(specs) if specs is not None else list(load_catalog_specs())
    hits: list[str] = []
    for spec in rows:
        if not isinstance(spec, Mapping):
            continue
        gates = frozenset(spec_gates(spec))
        if gates in KNOWN_THIN_UNUSED_GATE_SETS:
            lid = str(spec.get("logic_id") or "").strip()
            if lid:
                hits.append(lid)
    out = {
        "n": len(rows),
        "hits": hits,
        "ok": not hits,
        "go": False,
        "not_a_pass": True,
    }
    if hits:
        raise KnownThinRewriteError(
            "known-thin unused gate-sets present in catalog: " + ",".join(hits)
        )
    return out


def assert_new_batch_not_event_three_and(
    specs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Refuse a new batch of 3-AND event/surprise while stopped. Does not GO."""
    rows = [s for s in specs if isinstance(s, Mapping)]
    hits = [
        str(s.get("logic_id") or "")
        for s in rows
        if len(spec_gates(s)) >= 3
    ]
    hits = [h for h in hits if h]
    out = {
        "stopped": bool(EVENT_THREE_AND_PLUS_N_STOPPED),
        "n": len(rows),
        "n_three_and": len(hits),
        "ok": True,
        "go": False,
        "not_a_pass": True,
    }
    if EVENT_THREE_AND_PLUS_N_STOPPED and hits:
        raise EventThreeAndBatchError(
            "3-AND new batch while EVENT_THREE_AND_PLUS_N_STOPPED: "
            + ",".join(hits[:8])
        )
    return out


def assert_new_batch_cheap_pb_cap(
    specs: Sequence[Mapping[str, Any]],
    *,
    cap: float = CHEAP_PB_PRIMARY_GATE_CAP,
) -> dict[str, Any]:
    """Refuse a new batch whose cheap_pb primary share is not strictly below cap.

    Existing catalog is not rewritten. Does not GO.
    """
    rows = [s for s in specs if isinstance(s, Mapping)]
    n = len(rows)
    n_pb = 0
    for spec in rows:
        if primary_gate_of(spec) == "cheap_pb":
            n_pb += 1
    share = (n_pb / n) if n else 0.0
    out = {
        "n": n,
        "cheap_pb_primary": n_pb,
        "cheap_pb_primary_share": round(share, 4),
        "cap": float(cap),
        "ok": bool(n == 0 or share < float(cap)),
        "go": False,
        "not_a_pass": True,
    }
    if n and share >= float(cap):
        raise CheapPbPrimaryCapError(
            "cheap_pb primary share "
            f"{share:.4f} >= cap {float(cap):.4f} (n={n} n_pb={n_pb})"
        )
    return out


def recorded_near_empty_ids(
    occupancy_by_logic: Mapping[str, float],
    *,
    threshold: float = NEAR_EMPTY_OCCUPANCY,
) -> frozenset[str]:
    """IDs whose recorded mean occupancy is ≤ threshold. Does not GO."""
    out: set[str] = set()
    for lid, occ in occupancy_by_logic.items():
        name = str(lid).strip()
        if name and float(occ) <= float(threshold):
            out.add(name)
    return frozenset(out)


def recorded_always_on_ids(
    occupancy_by_logic: Mapping[str, float],
    *,
    threshold: float = ALWAYS_ON_OCCUPANCY_WARN,
) -> frozenset[str]:
    """IDs whose recorded mean occupancy is ≥ threshold. Does not GO."""
    out: set[str] = set()
    for lid, occ in occupancy_by_logic.items():
        name = str(lid).strip()
        if name and float(occ) >= float(threshold):
            out.add(name)
    return frozenset(out)


def assert_new_batch_occupancy_not_near_empty(
    occupancy_by_logic: Mapping[str, float],
    *,
    threshold: float = NEAR_EMPTY_OCCUPANCY,
) -> dict[str, Any]:
    """Refuse a new batch that still contains near_empty occupancy. Does not GO."""
    rows = {
        str(lid): float(occ)
        for lid, occ in occupancy_by_logic.items()
        if str(lid).strip()
    }
    empty = sorted(lid for lid, occ in rows.items() if occ <= float(threshold))
    out = {
        "n": len(rows),
        "n_near_empty": len(empty),
        "near_empty_ids": empty,
        "threshold": float(threshold),
        "ok": bool(len(rows) > 0 and not empty),
        "go": False,
        "not_a_pass": True,
    }
    if not rows:
        raise NearEmptyBatchError("occupancy map is empty")
    if empty:
        raise NearEmptyBatchError(
            "near_empty occupancy "
            f"n={len(empty)} threshold={float(threshold):.4f} ids={empty[:12]}"
        )
    return out


def assert_near_empty_park_covers(
    occupancy_by_logic: Mapping[str, float],
    *,
    threshold: float = NEAR_EMPTY_OCCUPANCY,
) -> dict[str, Any]:
    """Park set must include every recorded near_empty id. Does not GO."""
    recorded = recorded_near_empty_ids(
        occupancy_by_logic, threshold=threshold
    )
    parked = NEAR_EMPTY_PARK_IDS
    missing = sorted(recorded - parked)
    extra_in_park = sorted(parked - recorded)
    out = {
        "n_recorded": len(recorded),
        "n_parked": len(parked),
        "missing_from_park": missing,
        "parked_without_this_map": extra_in_park,
        "ok": not missing,
        "go": False,
        "not_a_pass": True,
    }
    if missing:
        raise NearEmptyBatchError(
            "NEAR_EMPTY_PARK_IDS missing recorded near_empty: "
            + ",".join(missing[:12])
        )
    return out


def assert_new_batch_occupancy_not_always_on(
    occupancy_by_logic: Mapping[str, float],
    *,
    threshold: float = ALWAYS_ON_OCCUPANCY_WARN,
) -> dict[str, Any]:
    """Refuse a new batch that contains always-on occupancy. Does not GO."""
    rows = {
        str(lid): float(occ)
        for lid, occ in occupancy_by_logic.items()
        if str(lid).strip()
    }
    sticky = sorted(lid for lid, occ in rows.items() if occ >= float(threshold))
    out = {
        "n": len(rows),
        "n_always_on": len(sticky),
        "always_on_ids": sticky,
        "threshold": float(threshold),
        "ok": bool(len(rows) > 0 and not sticky),
        "go": False,
        "not_a_pass": True,
    }
    if not rows:
        raise AlwaysOnBatchError("occupancy map is empty")
    if sticky:
        raise AlwaysOnBatchError(
            "always_on occupancy "
            f"n={len(sticky)} threshold={float(threshold):.4f} ids={sticky[:12]}"
        )
    return out


def assert_new_batch_occupancy_in_material_band(
    occupancy_by_logic: Mapping[str, float],
    *,
    near_empty: float = NEAR_EMPTY_OCCUPANCY,
    always_on: float = ALWAYS_ON_OCCUPANCY_WARN,
) -> dict[str, Any]:
    """Refuse a new batch outside (near_empty, always_on). Does not GO."""
    lo = assert_new_batch_occupancy_not_near_empty(
        occupancy_by_logic, threshold=near_empty
    )
    hi = assert_new_batch_occupancy_not_always_on(
        occupancy_by_logic, threshold=always_on
    )
    return {
        "n": lo["n"],
        "n_near_empty": lo["n_near_empty"],
        "n_always_on": hi["n_always_on"],
        "near_empty_ids": lo["near_empty_ids"],
        "always_on_ids": hi["always_on_ids"],
        "ok": bool(lo["ok"] and hi["ok"]),
        "go": False,
        "not_a_pass": True,
    }


def cell_occupancy(cell: Mapping[str, Any] | None) -> float | None:
    """Prefer occupancy, then occupancy_frac. Missing → None. Not a pass."""
    if not isinstance(cell, Mapping):
        return None
    raw = cell.get("occupancy")
    if raw is None:
        raw = cell.get("occupancy_frac")
    if raw is None:
        return None
    return float(raw)


def mean_occupancy_by_logic(
    cells: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """Mean occupancy per logic_id from daily_path cells. Missing occupancy skipped."""
    from collections import defaultdict

    by: dict[str, list[float]] = defaultdict(list)
    for cell in cells:
        if not isinstance(cell, Mapping):
            continue
        lid = str(cell.get("logic_id") or "").strip()
        if not lid:
            continue
        raw = cell_occupancy(cell)
        if raw is None:
            continue
        by[lid].append(raw)
    return {lid: (sum(xs) / len(xs)) for lid, xs in by.items() if xs}


def classify_occupancy_pair(
    mid: float | None,
    liq: float | None,
    *,
    near_empty: float = NEAR_EMPTY_OCCUPANCY,
    usable_min: float = USABLE_OCCUPANCY_MIN,
    always_on: float = ALWAYS_ON_OCCUPANCY_WARN,
) -> str:
    """Both-track occupancy band. Does not GO.

    empty+empty → near_empty_park; always+always → always_on_park;
    material+material → material; mixed always → mixed_always;
    mixed empty/thin (max>near_empty), both-thin, mixed thin/material,
    mixed empty/material → thin_sleeve_exclude; missing track → unclassified.
    """
    if mid is None or liq is None:
        return "unclassified"
    lo = min(float(mid), float(liq))
    hi = max(float(mid), float(liq))
    if hi <= float(near_empty):
        return "near_empty_park"
    if lo >= float(always_on):
        return "always_on_park"
    if lo > float(usable_min) and hi < float(always_on):
        return "material"
    if hi >= float(always_on):
        return "mixed_always"
    return "thin_sleeve_exclude"
