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
from .personal_draft import (
    PERSONAL_BAR_COVERAGE_EVIDENCE,
    UNMANAGED_DRAFT_BASIS,
    observed_market_bar_coverage,
    source_sync_evidence,
    universe_corporate_action_check,
)
from .personal_retrospective_session import (
    PersonalRetrospectiveSessionResult,
    am_session_view_contract,
    am_session_view_digest,
    get_personal_retrospective_am_signal_equity_bars_daily,
    get_personal_retrospective_pm_fill_equity_bars_daily,
)
from .personal_research_view import (
    ArtifactRef,
    OfflineFixture,
    OfflineFixtureDataView,
    PersonalResearchDataView,
    PersonalResearchViewError,
    SnapshotIdentity,
    refuse_offline_fixture_for_controlled,
)
from .errors import (
    AsOfRequired,
    DatabaseNotFound,
    InvalidAsOf,
    InvalidDataset,
    HistoryReadError,
    PitError,
    SnapshotNotReady,
    SnapshotObservationClockError,
)
from .governed_am_view import (
    GovernedAmSessionDataView,
    OfflineFixtureAmSessionDataView,
    VerifiedControlledSnapshotHandle,
)
from .models import PIT_API_VERSION, PitReadClock, PitResult

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
    "PersonalRetrospectiveSessionResult",
    "am_session_view_contract",
    "am_session_view_digest",
    "PERSONAL_BAR_COVERAGE_EVIDENCE",
    "UNMANAGED_DRAFT_BASIS",
    "observed_market_bar_coverage",
    "source_sync_evidence",
    "universe_corporate_action_check",
    "ArtifactRef",
    "OfflineFixture",
    "OfflineFixtureDataView",
    "PersonalResearchDataView",
    "PersonalResearchViewError",
    "SnapshotIdentity",
    "refuse_offline_fixture_for_controlled",
    # result / version
    "PitReadClock",
    "PitResult",
    "PIT_API_VERSION",
    "GovernedAmSessionDataView",
    "OfflineFixtureAmSessionDataView",
    "VerifiedControlledSnapshotHandle",
    # errors (catch the family with `except PitError`)
    "PitError",
    "HistoryReadError",
    "AsOfRequired",
    "InvalidAsOf",
    "InvalidDataset",
    "DatabaseNotFound",
    "SnapshotNotReady",
    "SnapshotObservationClockError",
]

__version__ = PIT_API_VERSION
