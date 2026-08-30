"""Point-in-time (PIT) Data API — the sole read path for structured facts.

Every public ``get_*`` requires an explicit ``as_of`` and returns only rows
whose ``available_at <= as_of`` (NULL ``available_at`` excluded). Reads open
the SQLite DB **read-only** (``mode=ro``); there are no writes and no external
HTTP calls. Research, feature and strategy code must read facts through this
package — **never** via direct SQLite. See ``docs/pit_api.md``.

Quick example::

    from pit import get_equity_bars_daily

    res = get_equity_bars_daily(
        as_of="2025-04-01T17:00:00+09:00",
        code="8697",
        from_event="2025-03-01",
        to_event="2025-03-31",
    )
    for row in res:               # iterate matching rows
        print(row["date"], row["close"])
    print(res.metadata)           # as_of / table / source / count / pit_api_version
"""

from __future__ import annotations

from .api import (
    first_invalid_adjusted_close,
    get_equity_bars_daily,
    get_equity_master,
    get_jsda_bond_trades,
    get_jsda_repo_rates,
    get_jquants_records,
    get_market_calendar,
)
from .personal_retrospective_session import (
    get_personal_retrospective_am_signal_equity_bars_daily,
    get_personal_retrospective_pm_fill_equity_bars_daily,
)
from .errors import (
    AsOfRequired,
    DatabaseNotFound,
    InvalidAsOf,
    InvalidDataset,
    PitError,
    SnapshotNotReady,
)
from .models import PIT_API_VERSION, PitResult

__all__ = [
    # public reads
    "get_equity_master",
    "get_equity_bars_daily",
    "first_invalid_adjusted_close",
    "get_market_calendar",
    "get_jquants_records",
    "get_jsda_bond_trades",
    "get_jsda_repo_rates",
    "get_personal_retrospective_am_signal_equity_bars_daily",
    "get_personal_retrospective_pm_fill_equity_bars_daily",
    # result / version
    "PitResult",
    "PIT_API_VERSION",
    # errors (catch the family with `except PitError`)
    "PitError",
    "AsOfRequired",
    "InvalidAsOf",
    "InvalidDataset",
    "DatabaseNotFound",
    "SnapshotNotReady",
]

__version__ = PIT_API_VERSION
