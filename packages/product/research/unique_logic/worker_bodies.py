"""Worker-body thesis counting. YAML-only clones do not count. Does not GO."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Mapping

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
    """Leftover unique-22 whose occupancy is not combo-equal. Not a candidate."""
    return unique_leftover_logic_ids() - unique22_occupancy_equal_lifted()


@lru_cache(maxsize=1)
def _daily_path_src() -> str:
    return _WORKER_DAILY_PATH.read_text(encoding="utf-8")


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


def worker_body_missing(logic_id: str) -> bool:
    """True for unique catalog lids that must not enter the candidate pool."""
    lid = str(logic_id or "").strip()
    if not lid or lid not in RESEARCH_UNIQUE_LOGIC_IDS:
        return False
    if lid in unique22_occupancy_park():
        return False
    return lid not in countable_thesis_ids()


__all__ = [
    "combo_cs_gates_implemented",
    "combo_worker_gates_ok",
    "countable_thesis_ids",
    "is_countable_spec",
    "unique_leftover_logic_ids",
    "worker_body_missing",
    "unique22_occupancy_equal_lifted",
    "unique22_occupancy_park",
    "worker_implemented_logic_ids",
]
