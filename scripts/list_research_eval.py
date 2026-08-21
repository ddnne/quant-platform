#!/usr/bin/env python3
"""List research eval jobs from D1 (scores stay on R2/D1, not Git)."""
from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
from _bootstrap import ensure_repo_root

ensure_repo_root()

from research.eval_registry import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["--list"]))
