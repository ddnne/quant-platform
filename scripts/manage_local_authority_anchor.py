#!/usr/bin/env python3
"""Inspect or invoke the fixed external local-authority high-water anchor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_MANAGER_ROOT = Path(__file__).resolve().parents[1]
if str(_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(_MANAGER_ROOT))

from scripts.local_authority_anchor_protocol import (
    AnchorOperationalHold,
    AnchorProtocolError,
    anchor_plan,
    collect_anchor,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "collect"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = anchor_plan() if args.command == "plan" else collect_anchor()
    except AnchorOperationalHold:
        print("external local-authority anchor: operational HOLD", file=sys.stderr)
        return 1
    except (AnchorProtocolError, OSError):
        print("external local-authority anchor: fail-closed rejection", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
