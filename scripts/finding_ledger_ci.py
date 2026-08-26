#!/usr/bin/env python3
"""Validate the pinned finding ledger for source integration.

This command deliberately does not authorize a production release.  It lets
reviewed, fail-closed implementation work merge while an operational finding
still needs an administrator or human-present ceremony.  Production deploy,
release evidence, READY publication, and Controlled Pilot entrypoints continue
to call ``finding_ledger_gate.py`` and require every P0 finding to be FIXED.
"""

from __future__ import annotations

import sys

try:
    from scripts.finding_ledger_gate import FindingLedgerError, load_pinned_finding_ledger
except ImportError:  # pragma: no cover - direct script execution
    from finding_ledger_gate import FindingLedgerError, load_pinned_finding_ledger


def main() -> int:
    if len(sys.argv) != 1:
        print("finding ledger CI validation accepts no arguments", file=sys.stderr)
        return 2
    try:
        snapshot = load_pinned_finding_ledger()
    except FindingLedgerError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        "finding ledger CI validation: ok "
        f"({snapshot.digest}; release_allowed={str(snapshot.release_allowed).lower()}; "
        f"open_p0_ids={list(snapshot.open_p0_ids)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
