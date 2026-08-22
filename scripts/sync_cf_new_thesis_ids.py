#!/usr/bin/env python3
"""Rewrite Worker CF_NEW_* ID arrays from Python frozensets.

Python ``research.unique_logic.constants`` is SoT. Does not evaluate,
promote, or GO. Run from repo root:

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


def main() -> int:
    root = ensure_repo_root()
    sys.path.insert(0, str(root / "packages" / "product"))
    from research.unique_logic.constants import (
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
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
    event_ids = sorted(CF_NEW_EVENT_THESIS_IDS)
    cs_ids = sorted(CF_NEW_CS_THESIS_IDS)
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
    if n1 != 1 or n2 != 1:
        raise SystemExit(f"rewrite failed n_event={n1} n_cs={n2}")
    if src2 != src:
        path.write_text(src2, encoding="utf-8")
        print("rewrote", path)
    else:
        print("already in sync", path)
    print("n_event", len(event_ids), "n_cs", len(cs_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
