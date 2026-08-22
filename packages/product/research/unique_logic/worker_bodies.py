"""Worker-body thesis counting. YAML-only clones do not count. Does not GO."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.unique_logic.catalog import catalog_dir, load_catalog_specs
from research.unique_logic.constants import (
    ADAPTIVE_LOGIC_IDS,
    CF_NEW_THESIS_IDS,
    COMBO_EVENT_GATES,
    CS_LOGIC_IDS,
    EVENT_FILTER_LOGIC_IDS,
    EVENT_LOGIC_IDS,
    EVENT_SIDES_LOGIC_IDS,
    ALWAYS_ON_OCCUPANCY_WARN,
    ALWAYS_ON_PARK_IDS,
    NEAR_EMPTY_OCCUPANCY,
    NEAR_EMPTY_PARK_IDS,
    PYTHON_ONLY_EVENT_GATES,
    RESEARCH_UNIQUE_LOGIC_IDS,
)
from research.unique_logic.near_duplicate import is_near_duplicate

_WORKER_DAILY_PATH = (
    repo_root()
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "src"
    / "daily_path.ts"
)
_WORKER_CATALOG_IDS = _WORKER_DAILY_PATH.parent / "catalog_ids.ts"
_EMPTY_CS = frozenset({"", "None", "none"})


def unique_leftover_logic_ids() -> frozenset[str]:
    """Original unique-22 leftover IDs."""
    return (
        EVENT_LOGIC_IDS
        | EVENT_FILTER_LOGIC_IDS
        | EVENT_SIDES_LOGIC_IDS
        | ADAPTIVE_LOGIC_IDS
        | CS_LOGIC_IDS
    )


@lru_cache(maxsize=1)
def unique22_occupancy_equal_lifted() -> frozenset[str]:
    """Leftover unique-22 whose YAML params.gates match comboEventGateOk occupancy."""
    leftover = unique_leftover_logic_ids()
    out: set[str] = set()
    for spec in load_catalog_specs():
        lid = str(spec.get("logic_id") or "")
        if lid not in leftover:
            continue
        params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
        if params.get("gates"):
            out.add(lid)
    return frozenset(out)


@lru_cache(maxsize=1)
def unique22_occupancy_park() -> frozenset[str]:
    """Leftover unique-22 whose occupancy is not combo-equal. Not a candidate.

    Re-audit 2026-08-22: no additional occupancy-equal lifts. Remaining 17 are
    dedicated CS books, sticky surprise-xs, trail-K, side-switch, or
    momentumAt(entryIdx) leftover. Do not silently unpark.
    """
    return unique_leftover_logic_ids() - unique22_occupancy_equal_lifted()


def near_empty_occupancy_park() -> frozenset[str]:
    """Recorded near_empty IDs. Not countable, not basket material. Not a pass."""
    return NEAR_EMPTY_PARK_IDS


def always_on_occupancy_park() -> frozenset[str]:
    """Recorded always-on IDs. Not countable, not basket material. Not a pass."""
    return ALWAYS_ON_PARK_IDS


@lru_cache(maxsize=1)
def _daily_path_src() -> str:
    """daily_path leftover + generated catalog_ids (IDs live in catalog_ids.ts)."""
    body = _WORKER_DAILY_PATH.read_text(encoding="utf-8")
    ids = (
        _WORKER_CATALOG_IDS.read_text(encoding="utf-8")
        if _WORKER_CATALOG_IDS.is_file()
        else ""
    )
    return ids + "\n" + body


def _ts_quoted_ids(src: str, name: str) -> set[str]:
    m = re.search(
        rf"(?:export )?const {name} = (?:new Set\()?\[(.*?)](?: as const)?",
        src,
        flags=re.S,
    )
    if not m:
        return set()
    return set(re.findall(r'"([^"]+)"', m.group(1)))


@lru_cache(maxsize=1)
def combo_cs_gates_implemented() -> frozenset[str]:
    """CS gates with a body in Worker ``comboCsGateOk`` (unknown fails closed)."""
    src = _daily_path_src()
    start = src.find("export function comboCsGateOk(")
    if start < 0:
        return frozenset()
    end = src.find("\nfunction weekdayMon0", start)
    body = src[start:end] if end > start else src[start:]
    return frozenset(re.findall(r'gate === "([^"]+)"', body))


@lru_cache(maxsize=1)
def worker_implemented_logic_ids() -> frozenset[str]:
    """IDs that have Worker bodies. YAML-only clones do not count."""
    src = _daily_path_src()
    worker = (
        _ts_quoted_ids(src, "CF_NEW_EVENT_THESIS_IDS")
        | _ts_quoted_ids(src, "CF_NEW_CS_THESIS_IDS")
        | _ts_quoted_ids(src, "CF_EVENT_LOGIC_IDS")
        | _ts_quoted_ids(src, "CF_UNIQUE_CS_LOGIC_IDS")
    )
    declared = unique_leftover_logic_ids() | set(CF_NEW_THESIS_IDS)
    return frozenset(worker & declared)


def _gates_of(spec: Mapping[str, Any]) -> list[str]:
    params = spec.get("params") if isinstance(spec.get("params"), Mapping) else {}
    raw = params.get("gates") if isinstance(params, Mapping) else None
    if raw is None:
        raw = spec.get("gates")
    if raw in (None, "", "None"):
        return []
    if isinstance(raw, str):
        return [
            x.strip()
            for x in raw.split(",")
            if x.strip() and x.strip() != "None"
        ]
    return [
        str(x).strip()
        for x in list(raw)
        if str(x).strip() and str(x).strip() != "None"
    ]


def _cs_gate_of(spec: Mapping[str, Any]) -> str | None:
    params = spec.get("params") if isinstance(spec.get("params"), Mapping) else {}
    raw = None
    if isinstance(params, Mapping) and "cs_gate" in params:
        raw = params.get("cs_gate")
    elif "cs_gate" in spec:
        raw = spec.get("cs_gate")
    if raw in (None, "", "None", "none"):
        return None
    g = str(raw).strip()
    return None if g in _EMPTY_CS else g


def combo_worker_gates_ok(spec: Mapping[str, Any]) -> bool:
    """True when combo event gates ⊆ COMBO_EVENT_GATES and CS cs_gate is implemented."""
    gates = _gates_of(spec)
    if PYTHON_ONLY_EVENT_GATES.intersection(gates):
        return False
    if any(g not in COMBO_EVENT_GATES for g in gates):
        return False
    cs = _cs_gate_of(spec)
    if cs is None:
        return True
    return cs in combo_cs_gates_implemented() or cs in COMBO_EVENT_GATES


def is_countable_spec(spec: Mapping[str, Any]) -> bool:
    """YAML-like spec counts only with catalog row + Worker body + known gates."""
    lid = str(spec.get("logic_id") or "").strip()
    if not lid:
        return False
    if not (catalog_dir() / f"{lid}.yaml").is_file():
        return False
    if lid not in worker_implemented_logic_ids():
        return False
    if lid not in RESEARCH_UNIQUE_LOGIC_IDS:
        return False
    if is_near_duplicate(lid):
        return False
    if lid in unique22_occupancy_park():
        return False
    if lid in near_empty_occupancy_park():
        return False
    if lid in always_on_occupancy_park():
        return False
    if lid in CF_NEW_THESIS_IDS:
        return combo_worker_gates_ok(spec)
    return True


@lru_cache(maxsize=1)
def countable_thesis_ids() -> frozenset[str]:
    """Catalog + Worker body + implemented gates; YAML clones / near_dup park excluded."""
    out: set[str] = set()
    for spec in load_catalog_specs():
        if is_countable_spec(spec):
            out.add(str(spec["logic_id"]))
    return frozenset(out)


CHEAP_PB_PRIMARY_GATE_CAP: float = 0.20


class CheapPbPrimaryCapError(ValueError):
    """New batch exceeds cheap_pb-as-primary-gate cap. Not a pass."""


def primary_gate_of(spec: Mapping[str, Any]) -> str | None:
    gates = _gates_of(spec)
    return gates[0] if gates else None


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


class NearEmptyBatchError(ValueError):
    """New batch has occupancy ≤ near_empty threshold. Not a pass."""


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
        raw = cell.get("occupancy_frac")
        if raw is None:
            raw = cell.get("occupancy")
        if raw is None:
            continue
        by[lid].append(float(raw))
    return {lid: (sum(xs) / len(xs)) for lid, xs in by.items() if xs}


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


def assert_near_empty_park_covers(
    occupancy_by_logic: Mapping[str, float],
    *,
    threshold: float = NEAR_EMPTY_OCCUPANCY,
) -> dict[str, Any]:
    """Park set must include every recorded near_empty id. Does not GO."""
    recorded = recorded_near_empty_ids(
        occupancy_by_logic, threshold=threshold
    )
    parked = near_empty_occupancy_park()
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


class AlwaysOnBatchError(ValueError):
    """New batch has occupancy ≥ always_on threshold. Not a pass."""


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


def countable_inventory_bias() -> dict[str, Any]:
    """Family / primary-gate / dataset occupancy of countable theses. Not a pass."""
    from collections import Counter

    ids = countable_thesis_ids()
    primary: Counter[str] = Counter()
    all_gates: Counter[str] = Counter()
    prefix: Counter[str] = Counter()
    n_pb = n_pb_primary = n_ac = n_ac_primary = 0
    for spec in load_catalog_specs():
        lid = str(spec.get("logic_id") or "")
        if lid not in ids:
            continue
        prefix[lid.split("_")[0]] += 1
        gates = _gates_of(spec)
        if gates:
            primary[gates[0]] += 1
            for g in gates:
                all_gates[g] += 1
            if "cheap_pb" in gates:
                n_pb += 1
            if gates[0] == "cheap_pb":
                n_pb_primary += 1
            if "afterclose" in gates:
                n_ac += 1
            if gates[0] == "afterclose":
                n_ac_primary += 1
    n = len(ids)
    return {
        "n_countable": n,
        "prefix": dict(prefix),
        "primary_gate": dict(primary),
        "all_gates": dict(all_gates),
        "cheap_pb_in_gates": n_pb,
        "cheap_pb_primary": n_pb_primary,
        "cheap_pb_primary_share": round(n_pb_primary / n, 4) if n else 0.0,
        "cheap_pb_primary_cap": CHEAP_PB_PRIMARY_GATE_CAP,
        "afterclose_in_gates": n_ac,
        "afterclose_primary": n_ac_primary,
        "afterclose_primary_share": round(n_ac_primary / n, 4) if n else 0.0,
        "n_near_empty_parked": len(near_empty_occupancy_park()),
        "n_always_on_parked": len(always_on_occupancy_park()),
        "go": False,
        "not_a_pass": True,
    }


def worker_body_missing(logic_id: str) -> bool:
    """True for unique catalog lids that must not enter the candidate pool."""
    lid = str(logic_id or "").strip()
    if not lid or lid not in RESEARCH_UNIQUE_LOGIC_IDS:
        return False
    if lid in unique22_occupancy_park():
        return False
    if lid in near_empty_occupancy_park():
        return False
    if lid in always_on_occupancy_park():
        return False
    return lid not in countable_thesis_ids()


__all__ = [
    "combo_cs_gates_implemented",
    "combo_worker_gates_ok",
    "CHEAP_PB_PRIMARY_GATE_CAP",
    "CheapPbPrimaryCapError",
    "NearEmptyBatchError",
    "AlwaysOnBatchError",
    "assert_new_batch_cheap_pb_cap",
    "assert_new_batch_occupancy_not_near_empty",
    "assert_new_batch_occupancy_not_always_on",
    "assert_new_batch_occupancy_in_material_band",
    "assert_near_empty_park_covers",
    "recorded_near_empty_ids",
    "recorded_always_on_ids",
    "countable_inventory_bias",
    "countable_thesis_ids",
    "mean_occupancy_by_logic",
    "near_empty_occupancy_park",
    "always_on_occupancy_park",
    "primary_gate_of",
    "is_countable_spec",
    "unique_leftover_logic_ids",
    "worker_body_missing",
    "unique22_occupancy_equal_lifted",
    "unique22_occupancy_park",
    "worker_implemented_logic_ids",
]
