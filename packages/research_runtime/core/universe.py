"""As-of tradable universe, built only from the PIT equity master.

This is the first anti-survivorship step: at each decision instant we ask PIT
"which equities existed and were listed as of now?" and trade only those. We
do **not** consult any delisting table or look forward — membership is taken
from the latest complete master snapshot visible at the decision instant.

The master can carry multiple full-market snapshots (keyed by
``snapshot_date``).  We select the latest applicable snapshot first and only
then build its code mapping, so a code absent after delisting does not survive
forever through an older per-code row. Richer filters (sector, scale, explicit
listing-status flags in the raw payload, liquidity screens) are deliberately
out of scope for the minimal engine.
"""

from __future__ import annotations

from typing import Any

import pit

from .strategy_protocol import EquityMaster


def load_master(as_of: Any, *, db_path: Any = None) -> dict[str, EquityMaster]:
    """Latest-known-as-of equity master per code, read through PIT.

    Returns a ``{code: EquityMaster}`` mapping for the newest complete master
    snapshot whose rows are visible at ``as_of``.  Selecting one snapshot date
    prevents missing (delisted) codes from leaking in via older snapshots.
    """
    result = pit.get_equity_master(as_of=as_of, db_path=db_path)
    latest_snapshot = max(
        (row.get("snapshot_date") or "" for row in result.rows), default=""
    )
    latest: dict[str, EquityMaster] = {}
    for row in result.rows:
        if (row.get("snapshot_date") or "") != latest_snapshot:
            continue
        code = row.get("code")
        if not code:
            continue
        latest[code] = EquityMaster(
            code=code,
            snapshot_date=row.get("snapshot_date") or "",
            company_name=row.get("company_name"),
            sector_17_code=row.get("sector_17_code"),
            sector_33_code=row.get("sector_33_code"),
            market_code=row.get("market_code"),
            scale_category=row.get("scale_category"),
        )
    return latest


def build_universe(as_of: Any, *, db_path: Any = None) -> tuple[str, ...]:
    """As-of tradable codes from the PIT equity master, sorted ascending.

    Every code in the latest full master snapshot visible by ``as_of`` is
    included. This excludes both not-yet-listed names and names omitted after
    delisting without consulting future snapshots.
    """
    return tuple(sorted(load_master(as_of=as_of, db_path=db_path).keys()))
