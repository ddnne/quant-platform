"""Opt-in gate for host-local market data regeneration CLIs.

Normal operation is Cloudflare: R2 persistent authority, D1 metadata,
Container SQLite ephemeral. Host-local files are developer/recovery only.

Call from ``if __name__ == "__main__"`` only — not from importable ``main()``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

LOCAL_MARKET_DATA_ENV = "QP_ALLOW_LOCAL_MARKET_DATA"
LOCAL_MARKET_DATA_DISABLED = (
    "local market data is disabled; host-local SQLite and raw files are not "
    "the operator path. Use Cloudflare R2 (persistent authority) and D1 "
    "metadata; Container SQLite is ephemeral. Set "
    f"{LOCAL_MARKET_DATA_ENV}=1 only for developer/recovery compatibility."
)


def local_market_data_allowed() -> bool:
    """True only when ``QP_ALLOW_LOCAL_MARKET_DATA=1`` (exact)."""
    return os.environ.get(LOCAL_MARKET_DATA_ENV) == "1"


def require_local_market_data_opt_in(
    argv: Sequence[str] | None = None,
) -> None:
    """Exit 2 unless the exact opt-in is set.

    ``-h`` / ``--help`` is allowed so usage can be read without creating files.
    """
    args = sys.argv[1:] if argv is None else argv
    if "-h" in args or "--help" in args:
        return
    if local_market_data_allowed():
        return
    print(LOCAL_MARKET_DATA_DISABLED, file=sys.stderr)
    raise SystemExit(2)
