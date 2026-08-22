#!/usr/bin/env python3
"""Rewrite Worker unique-logic ID/gate arrays from Python frozensets.

Python ``research.unique_logic.constants`` is SoT. Does not evaluate,
promote, or GO. Does not copy PYTHON_ONLY_EVENT_GATES onto the Worker
(those have no Worker gate bodies). Run from repo root:

  PYTHONPATH=packages/product:. python scripts/sync_cf_new_thesis_ids.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
from _bootstrap import ensure_repo_root


def _ts_array(name: str, ids: list[str]) -> str:
    inner = ",\n".join(f'  "{lid}"' for lid in ids)
    return f"export const {name} = [\n{inner},\n] as const;"


def _ts_array_spread(name: str, ids: list[str], spread: str) -> str:
    inner = ",\n".join(f'  "{lid}"' for lid in ids)
    return f"export const {name} = [\n{inner},\n  ...{spread},\n] as const;"


def _ts_set(name: str, ids: list[str]) -> str:
    inner = ",\n".join(f'  "{lid}"' for lid in ids)
    return f"const {name} = new Set([\n{inner},\n]);"


def _quoted_ids(block: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', block))


def main() -> int:
    root = ensure_repo_root()
    sys.path.insert(0, str(root / "packages" / "product"))
    from research.unique_logic.constants import (
        ADAPTIVE_LOGIC_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        COMBO_EVENT_GATES,
        CS_LOGIC_IDS,
        EVENT_FILTER_LOGIC_IDS,
        EVENT_LOGIC_IDS,
        EVENT_SIDES_LOGIC_IDS,
        PROPOSE_ALLOWED_GATES,
        PYTHON_ONLY_EVENT_GATES,
    )
    from research.cf_propose_thesis import PROPOSE_ALLOWED_DATASETS

    py_only = set(PYTHON_ONLY_EVENT_GATES) & set(COMBO_EVENT_GATES)
    if py_only:
        raise SystemExit(
            f"COMBO_EVENT_GATES must not include PYTHON_ONLY_EVENT_GATES: "
            f"{sorted(py_only)}"
        )
    overlap = set(CS_LOGIC_IDS) & set(CF_NEW_CS_THESIS_IDS)
    if overlap:
        raise SystemExit(
            f"CS_LOGIC_IDS must stay off CF_NEW_CS_THESIS_IDS: {sorted(overlap)}"
        )
    event_prefix = (
        EVENT_LOGIC_IDS
        | EVENT_FILTER_LOGIC_IDS
        | EVENT_SIDES_LOGIC_IDS
        | ADAPTIVE_LOGIC_IDS
    )
    event_overlap = event_prefix & set(CF_NEW_EVENT_THESIS_IDS)
    if event_overlap:
        raise SystemExit(
            "event-family prefix must stay off CF_NEW_EVENT_THESIS_IDS: "
            f"{sorted(event_overlap)}"
        )

    path = (
        root
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "daily_path.ts"
    )
    src = path.read_text(encoding="utf-8")
    unique_m = re.search(
        r"export const CF_UNIQUE_CS_LOGIC_IDS = \[(.*?)] as const;",
        src,
        flags=re.S,
    )
    if unique_m is None:
        raise SystemExit("CF_UNIQUE_CS_LOGIC_IDS not found")
    dropped = _quoted_ids(unique_m.group(1)) - set(CS_LOGIC_IDS)
    uncovered = dropped - set(CF_NEW_CS_THESIS_IDS)
    if uncovered:
        raise SystemExit(
            "refusing to shrink CF_UNIQUE_CS_LOGIC_IDS; dispatch would drop "
            f"{sorted(uncovered)} (not on CF_NEW_CS_THESIS_IDS)"
        )

    event_ids = sorted(CF_NEW_EVENT_THESIS_IDS)
    event_prefix_ids = sorted(event_prefix)
    cs_ids = sorted(CF_NEW_CS_THESIS_IDS)
    unique_cs_ids = sorted(CS_LOGIC_IDS)
    gate_ids = sorted(COMBO_EVENT_GATES)
    src2, n1 = re.subn(
        r"export const CF_NEW_EVENT_THESIS_IDS = \[.*?\] as const;",
        _ts_array("CF_NEW_EVENT_THESIS_IDS", event_ids),
        src,
        count=1,
        flags=re.S,
    )
    src2, n2 = re.subn(
        r"export const CF_NEW_CS_THESIS_IDS = \[.*?\] as const;",
        _ts_array("CF_NEW_CS_THESIS_IDS", cs_ids),
        src2,
        count=1,
        flags=re.S,
    )
    src2, n3 = re.subn(
        r"export const CF_UNIQUE_CS_LOGIC_IDS = \[.*?\] as const;",
        _ts_array("CF_UNIQUE_CS_LOGIC_IDS", unique_cs_ids),
        src2,
        count=1,
        flags=re.S,
    )
    src2, n4 = re.subn(
        r"const COMBO_EVENT_GATES = new Set\(\[.*?\]\);",
        _ts_set("COMBO_EVENT_GATES", gate_ids),
        src2,
        count=1,
        flags=re.S,
    )
    src2, n5 = re.subn(
        r"export const CF_EVENT_LOGIC_IDS = \[.*?\] as const;",
        _ts_array_spread(
            "CF_EVENT_LOGIC_IDS", event_prefix_ids, "CF_NEW_EVENT_THESIS_IDS"
        ),
        src2,
        count=1,
        flags=re.S,
    )
    if n1 != 1 or n2 != 1 or n3 != 1 or n4 != 1 or n5 != 1:
        raise SystemExit(
            f"rewrite failed n_event={n1} n_cs={n2} n_unique_cs={n3} "
            f"n_gates={n4} n_event_logic={n5}"
        )
    if "(CF_NEW_CS_THESIS_IDS as readonly string[]).includes(lid)" not in src2:
        raise SystemExit("dispatch/usesCrossSection must still OR CF_NEW_CS_THESIS_IDS")
    if "...CF_NEW_EVENT_THESIS_IDS" not in src2:
        raise SystemExit("CF_EVENT_LOGIC_IDS must spread CF_NEW_EVENT_THESIS_IDS")
    if src2 != src:
        path.write_text(src2, encoding="utf-8")
        print("rewrote", path)
    else:
        print("already in sync", path)
    propose_path = (
        root
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "propose_thesis.ts"
    )
    psrc = propose_path.read_text(encoding="utf-8")
    p2, pn1 = re.subn(
        r"const PROPOSE_ALLOWED_DATASETS = \[.*?\] as const;",
        _ts_array("PROPOSE_ALLOWED_DATASETS", sorted(PROPOSE_ALLOWED_DATASETS)).replace(
            "export const ", "const "
        ),
        psrc,
        count=1,
        flags=re.S,
    )
    p2, pn2 = re.subn(
        r"const PROPOSE_ALLOWED_GATES = \[.*?\] as const;",
        _ts_array("PROPOSE_ALLOWED_GATES", sorted(PROPOSE_ALLOWED_GATES)).replace(
            "export const ", "const "
        ),
        p2,
        count=1,
        flags=re.S,
    )
    if pn1 != 1 or pn2 != 1:
        raise SystemExit(f"propose rewrite failed n_ds={pn1} n_gates={pn2}")
    if p2 != psrc:
        propose_path.write_text(p2, encoding="utf-8")
        print("rewrote", propose_path)
    else:
        print("already in sync", propose_path)

    print(
        "n_event",
        len(event_ids),
        "n_event_prefix",
        len(event_prefix_ids),
        "n_cs",
        len(cs_ids),
        "n_unique_cs",
        len(unique_cs_ids),
        "n_gates",
        len(gate_ids),
        "n_propose_gates",
        len(PROPOSE_ALLOWED_GATES),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
