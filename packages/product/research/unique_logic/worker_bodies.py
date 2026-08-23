"""Worker-body thesis counting. YAML-only clones do not count. Does not GO."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping, Sequence

from qp_paths import repo_root
from research.unique_logic.catalog import catalog_dir, load_catalog_specs
from research.unique_logic.constants import (
    CF_NEW_THESIS_IDS,
    COMBO_EVENT_GATES,
    ALWAYS_ON_OCCUPANCY_WARN,
    ALWAYS_ON_PARK_IDS,
    NEAR_EMPTY_OCCUPANCY,
    NEAR_EMPTY_PARK_IDS,
    PRI_FLOW_GATES,
    PRI_FUND_GATES,
    PRI_RATE_GATES,
    PRI_VOL_GATES,
    PYTHON_ONLY_EVENT_GATES,
    RESEARCH_UNIQUE_LOGIC_IDS,
    THIN_SLEEVE_EXCLUDE_IDS,
    USABLE_OCCUPANCY_MIN,
)
from research.unique_logic.near_duplicate import is_near_duplicate
from research.occupancy_guards import (
    AlwaysOnBatchError,
    CHEAP_PB_PRIMARY_GATE_CAP,
    CatalogAndPlusNStoppedError,
    CheapPbPrimaryCapError,
    EventThreeAndBatchError,
    KnownThinRewriteError,
    NearEmptyBatchError,
    assert_catalog_and_plus_n_stopped,
    assert_known_thin_unused_absent,
    assert_near_empty_park_covers,
    assert_new_batch_cheap_pb_cap,
    assert_new_batch_not_event_three_and,
    assert_new_batch_occupancy_in_material_band,
    assert_new_batch_occupancy_not_always_on,
    assert_new_batch_occupancy_not_near_empty,
    primary_gate_of,
    recorded_always_on_ids,
    recorded_near_empty_ids,
    cell_occupancy,
    classify_occupancy_pair,
    mean_occupancy_by_logic,
)

_WORKER_DAILY_PATH = (
    repo_root()
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "src"
    / "daily_path.ts"
)
_WORKER_COMBO_GATES = _WORKER_DAILY_PATH.parent / "combo_gates.ts"
_WORKER_CATALOG_IDS = _WORKER_DAILY_PATH.parent / "catalog_ids.ts"
_EMPTY_CS = frozenset({"", "None", "none"})


def unique_leftover_logic_ids() -> frozenset[str]:
    """Original unique-22 leftover IDs. Unique families minus combo YAML."""
    return RESEARCH_UNIQUE_LOGIC_IDS - CF_NEW_THESIS_IDS


@lru_cache(maxsize=1)
def unique22_occupancy_equal_lifted() -> frozenset[str]:
    """Leftover unique-22 whose YAML params.gates match comboEventGateOk occupancy."""
    from research.unique_logic.catalog import catalog_spec, spec_gates

    return frozenset(
        lid
        for lid in unique_leftover_logic_ids()
        if spec_gates(catalog_spec(lid))
    )


@lru_cache(maxsize=1)
def unique22_occupancy_park() -> frozenset[str]:
    """Leftover unique-22 whose occupancy is not combo-equal. Not a candidate.

    Re-audit 2026-08-22: no additional occupancy-equal lifts. Remaining 17 are
    dedicated CS books, sticky surprise-xs, trail-K, side-switch, or
    momentumAt(entryIdx) leftover. Do not silently unpark.
    """
    return unique_leftover_logic_ids() - unique22_occupancy_equal_lifted()


UNIQUE22_PARK_REASONS: dict[str, str] = {
    "event_pre_mom_agree_hold": "leftover momentumAt(entryIdx) vs combo pre_mom entryIdx-1",
    "surprise_xs_rank_hold": "dedicated surprise-xs rank book",
    "surprise_xs_rank_flip": "side-switch table, not combo gates",
    "surprise_xs_rank_adaptive": "trail-K adaptive, not combo gates",
    "event_funding_adaptive_side": "trail-K adaptive funding side",
    "event_funding_stress_ls": "fixed L/S table, not combo gates",
    "curve_steepen_impulse_cs": "dedicated CS overlay",
    "funding_impulse_cs_tilt": "dedicated CS overlay",
    "idio_mom_macro_impulse": "dedicated CS overlay",
    "disclosure_cluster_mom_gate": "dedicated event filter book",
    "large_surprise_event_hold": "dedicated event book",
    "month_end_cs_fade": "dedicated CS overlay",
    "overnight_easy_cs_follow": "dedicated CS overlay",
    "overnight_level_cs_tilt": "dedicated CS overlay",
    "repo_3m_level_cs": "dedicated CS overlay",
    "xs_low_vol_mom": "dedicated CS overlay",
    "xs_margin_delta_rank": "dedicated CS overlay",
}


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
    src = _WORKER_COMBO_GATES.read_text(encoding="utf-8")
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
    return frozenset(worker & set(RESEARCH_UNIQUE_LOGIC_IDS))


def _gates_of(spec: Mapping[str, Any]) -> list[str]:
    from research.unique_logic.catalog import spec_gates

    return spec_gates(spec)


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
    if spec.get("catalog") is not True and not (catalog_dir() / f"{lid}.yaml").is_file():
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



def usable_family_of(logic_id: str) -> str:
    """Family tag for usable inventory. Not a pass."""
    lid = str(logic_id or "")
    if lid.startswith("surprise_xs"):
        return "surprise_xs"
    if lid.startswith("cs_"):
        return "cs"
    if lid.startswith("event_"):
        return "event"
    return lid.split("_")[0] or "other"


def usable_inventory(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Countable material-band inventory. Excludes park / always-on / thin.

    Both-track occupancy required. Occupancy in (USABLE_OCCUPANCY_MIN,
    ALWAYS_ON_OCCUPANCY_WARN). Does not GO.
    """
    from collections import Counter

    countable = countable_thesis_ids()
    mid = dict(occupancy_by_track.get("mid_n_explore") or {})
    liq = dict(occupancy_by_track.get("liq_large") or {})
    usable: list[str] = []
    n_unclassified = 0
    n_recorded = 0
    for lid in sorted(countable):
        if lid in NEAR_EMPTY_PARK_IDS or lid in ALWAYS_ON_PARK_IDS:
            continue
        if lid in THIN_SLEEVE_EXCLUDE_IDS:
            continue
        a = mid.get(lid)
        b = liq.get(lid)
        band = classify_occupancy_pair(a, b)
        if band == "unclassified":
            n_unclassified += 1
            continue
        n_recorded += 1
        if band == "material":
            usable.append(lid)
    fam = Counter(usable_family_of(lid) for lid in usable)
    n = len(usable)
    return {
        "version": "usable-inventory/v1",
        "n_usable": n,
        "usable_ids": usable,
        "family": dict(fam),
        "family_share": {
            k: round(v / n, 4) if n else 0.0 for k, v in sorted(fam.items())
        },
        "n_countable": len(countable),
        "n_near_empty_park": len(NEAR_EMPTY_PARK_IDS),
        "n_thin_sleeve_exclude": len(THIN_SLEEVE_EXCLUDE_IDS),
        "n_always_on_park": len(ALWAYS_ON_PARK_IDS),
        "n_recorded_both_track": n_recorded,
        "n_unclassified": n_unclassified,
        "usable_occupancy_min": USABLE_OCCUPANCY_MIN,
        "always_on_occupancy_warn": ALWAYS_ON_OCCUPANCY_WARN,
        "go": False,
        "not_a_pass": True,
    }


def usable_inventory_read(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Family and primary-gate of usable inventory. Not a pass."""
    from collections import Counter

    from research.unique_logic.catalog import combo_thesis_records

    inv = usable_inventory(occupancy_by_track)
    usable = set(inv["usable_ids"])
    primary: Counter[str] = Counter()
    all_gates: Counter[str] = Counter()
    fam_primary: Counter[str] = Counter()
    n_ands: Counter[str] = Counter()
    pri_series: Counter[str] = Counter()
    n_pb = n_pb_primary = n_ac = n_ac_primary = 0
    for rec in combo_thesis_records():
        lid = str(rec.get("logic_id") or "")
        if lid not in usable:
            continue
        gates = [str(x) for x in (rec.get("gates") or []) if str(x).strip()]
        fam = usable_family_of(lid)
        pg = gates[0] if gates else ""
        fam_primary[f"{fam}|{pg}"] += 1
        n_ands[str(len(gates))] += 1
        gs = set(gates)
        if gs & PRI_VOL_GATES:
            pri_series["vol"] += 1
        elif gs & PRI_FLOW_GATES:
            pri_series["flow"] += 1
        elif gs & PRI_RATE_GATES:
            pri_series["rate"] += 1
        else:
            pri_series["other"] += 1
        if not gates:
            continue
        primary[pg] += 1
        for g in gates:
            all_gates[g] += 1
        if "cheap_pb" in gates:
            n_pb += 1
        if pg == "cheap_pb":
            n_pb_primary += 1
        if "afterclose" in gates:
            n_ac += 1
        if pg == "afterclose":
            n_ac_primary += 1
    n = int(inv["n_usable"])
    return {
        "version": "usable-read/v3",
        "n_usable": n,
        "family": inv["family"],
        "family_share": inv["family_share"],
        "primary_gate": dict(primary),
        "family_primary_gate": dict(fam_primary),
        "all_gates": dict(all_gates),
        "n_ands": dict(n_ands),
        "pri_series": dict(pri_series),
        "cheap_pb_in_gates": n_pb,
        "cheap_pb_primary": n_pb_primary,
        "cheap_pb_primary_share": round(n_pb_primary / n, 4) if n else 0.0,
        "afterclose_in_gates": n_ac,
        "afterclose_primary": n_ac_primary,
        "afterclose_primary_share": round(n_ac_primary / n, 4) if n else 0.0,
        "go": False,
        "not_a_pass": True,
    }


def usable_series_breakdown(
    occupancy_by_track: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Family / vol / flow / rate / fund tags of usable inventory. Not a pass."""
    from collections import Counter

    from research.unique_logic.catalog import combo_thesis_records

    inv = usable_inventory(occupancy_by_track)
    usable = set(inv["usable_ids"])
    tags: Counter[str] = Counter()
    combo: Counter[str] = Counter()
    n_ands: Counter[str] = Counter()
    n_event_xs_3 = 0
    for rec in combo_thesis_records():
        lid = str(rec.get("logic_id") or "")
        if lid not in usable:
            continue
        gates = [str(x) for x in (rec.get("gates") or []) if str(x).strip()]
        gs = set(gates)
        hit: list[str] = []
        if gs & PRI_VOL_GATES:
            hit.append("vol")
        if gs & PRI_FLOW_GATES:
            hit.append("flow")
        if gs & PRI_RATE_GATES:
            hit.append("rate")
        if gs & PRI_FUND_GATES:
            hit.append("fund")
        if not hit:
            hit.append("other")
        for t in hit:
            tags[t] += 1
        combo["+".join(hit)] += 1
        n_ands[str(len(gates))] += 1
        fam = usable_family_of(lid)
        if len(gates) == 3 and fam in {"event", "surprise_xs"}:
            n_event_xs_3 += 1
    n = int(inv["n_usable"])
    return {
        "version": "usable-series/v1",
        "n_usable": n,
        "family": inv["family"],
        "family_share": inv["family_share"],
        "tag_counts": dict(tags),
        "tag_combo": dict(combo),
        "n_ands": dict(n_ands),
        "n_event_or_surprise_xs_3and": n_event_xs_3,
        "pri_series_exclusive": usable_inventory_read(occupancy_by_track)["pri_series"],
        "go": False,
        "not_a_pass": True,
    }


def countable_inventory_bias() -> dict[str, Any]:
    """Family / primary-gate / dataset occupancy of countable theses. Not a pass."""
    from collections import Counter

    from research.unique_logic.catalog import catalog_spec

    ids = countable_thesis_ids()
    primary: Counter[str] = Counter()
    all_gates: Counter[str] = Counter()
    prefix: Counter[str] = Counter()
    n_pb = n_pb_primary = n_ac = n_ac_primary = 0
    for lid in ids:
        spec = catalog_spec(lid) or {}
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
    "CatalogAndPlusNStoppedError",
    "KnownThinRewriteError",
    "EventThreeAndBatchError",
    "NearEmptyBatchError",
    "AlwaysOnBatchError",
    "assert_catalog_and_plus_n_stopped",
    "assert_known_thin_unused_absent",
    "assert_new_batch_not_event_three_and",
    "assert_new_batch_cheap_pb_cap",
    "assert_new_batch_occupancy_not_near_empty",
    "assert_new_batch_occupancy_not_always_on",
    "assert_new_batch_occupancy_in_material_band",
    "assert_near_empty_park_covers",
    "recorded_near_empty_ids",
    "recorded_always_on_ids",
    "countable_inventory_bias",
    "usable_inventory",
    "usable_inventory_read",
    "usable_series_breakdown",
    "usable_family_of",
    "classify_occupancy_pair",
    "countable_thesis_ids",
    "cell_occupancy",
    "mean_occupancy_by_logic",
    "near_empty_occupancy_park",
    "always_on_occupancy_park",
    "primary_gate_of",
    "is_countable_spec",
    "unique_leftover_logic_ids",
    "UNIQUE22_PARK_REASONS",
    "worker_body_missing",
    "unique22_occupancy_equal_lifted",
    "unique22_occupancy_park",
    "worker_implemented_logic_ids",
]
