#!/usr/bin/env python3
"""Fail-closed release-evidence publication boundary.

Caller-supplied JSON is not remote observation. Authenticated collection and
publication implementation is missing on this path (not merely unprovisioned
keys). Public entrypoints refuse before reading evidence or writing output.
A6 remains OPEN until a content-addressed artifact from authentic observation
is independently accepted.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping, NoReturn

try:
    from scripts.finding_ledger_gate import require_pinned_finding_ledger_gate
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from finding_ledger_gate import require_pinned_finding_ledger_gate  # type: ignore[no-redef]


class ReleaseObservationAuthorityUnavailable(RuntimeError):
    """Trusted remote observations cannot yet be minted or published."""


def _refuse_publication() -> NoReturn:
    raise ReleaseObservationAuthorityUnavailable(
        "release evidence publication is PENDING: authenticated "
        "collection/publication implementation is missing; caller-supplied "
        "JSON is untrusted"
    )


def build_envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    del payload
    _refuse_publication()


def write_envelope(payload: Mapping[str, Any], output_dir: Path) -> NoReturn:
    del payload, output_dir
    _refuse_publication()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input",
        type=Path,
        help="normalized non-secret release observations JSON",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    del args
    require_pinned_finding_ledger_gate()
    _refuse_publication()


if __name__ == "__main__":
    raise SystemExit(main())
