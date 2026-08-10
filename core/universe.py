"""As-of tradable universe, built only from the PIT equity master.

This is the first anti-survivorship step: at each decision instant we ask PIT
"which equities existed and were listed as of now?" and trade only those. We
do **not** consult any delisting table or look forward — a name that lists or
delists between two decision days simply appears in / disappears from the
universe on the day its master snapshot becomes visible (or stops being the
latest known).

The master can carry multiple snapshots per code (keyed by ``snapshot_date``);
we take the **latest-known-as-of** snapshot per code and treat the code as
tradable if it has any snapshot visible by ``as_of``. Richer filters (sector,
scale, explicit listing-status flags in the raw payload, liquidity screens)
are deliberately out of scope for the minimal engine.
"""

from __future__ import annotations

from typing import Any

import pit

from .strategy_protocol import EquityMaster


def load_master(as_of: Any, *, db_path: Any = None) -> dict[str, EquityMaster]:
    """Latest-known-as-of equity master per code, read through PIT.

    Returns a ``{code: EquityMaster}`` mapping. PIT already returns rows in
    ``(code, snapshot_date)`` order and gates them on ``available_at <= as_of``;
    we keep the last row per code, which is the most recent snapshot visible
    as of ``as_of``.
    """
    result = pit.get_equity_master(as_of=as_of, db_path=db_path)
    latest: dict[str, EquityMaster] = {}
    for row in result.rows:
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

    Every code with a master snapshot visible by ``as_of`` is included. This
    is the structural anti-survivorship guarantee: a name that did not exist
    yet as of ``as_of`` cannot be traded.
    """
    return tuple(sorted(load_master(as_of=as_of, db_path=db_path).keys()))
