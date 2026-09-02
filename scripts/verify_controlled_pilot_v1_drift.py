#!/usr/bin/env python3
"""Fail closed unless the checked-in controlled_pilot_v1 artifacts match the compiler."""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from generate_controlled_pilot_v1_contract import write_artifacts


if __name__ == "__main__":
    raise SystemExit(write_artifacts(check=True))
