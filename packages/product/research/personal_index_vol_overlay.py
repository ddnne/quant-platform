"""Predeclared Nikkei-225 volatility overlays for one frozen stock sleeve.

This module is deliberately a small, pure-Python research core.  It consumes
daily observations that were prepared elsewhere and neither reads storage nor
selects a strategy after seeing results.  Listed-option volatility is only for
the Nikkei 225.  The stock sleeve may use price-based realised volatility, but
single-stock option IV is not part of this input surface.

Timing is fixed and causal: a signal observed at the close of D is rebalanced
at the close of D+1 and first earns the D+1-to-D+2 close return.  Missing
required observations make that candidate NOT_EVALUATED; values are never
forward-filled.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Final, Mapping, Sequence

from research.factor_cohorts import get_research_cohort
from research.options_225_smile_features import OPTIONS_225_SMILE_SURFACE_SCOPE
from research import options_225_smile_transport as _smile_transport_core
from research.options_225_smile_transport import (
    OPTIONS_225_SMILE_TRANSPORT_VERSION,
    STICKY_MONEYNESS,
    STICKY_STRIKE,
    TRUSTED_FORWARD_UNAVAILABLE,
)
from research.options_225_vol_series import DATASET_ID
from research.personal_metrics import summarize_performance
from strategies.spec import strategy_spec_digest


PERSONAL_INDEX_VOL_OVERLAY_SCHEMA: Final = "personal-index-vol-overlay/v1"
PREPARED_PANEL_MANIFEST_SCHEMA: Final = "prepared-index-vol-overlay-panel/v1"
BASE_SLEEVE_ID: Final = "personal_sector_balanced_four_factor_v1_ls"
BASE_UNIVERSE_ID: Final = "topix_all"
BASE_COHORT_ID: Final = "sector-relative-ls-v1"
TOPIX_PROXY_DATASET: Final = "indices_bars_daily_topix"
ONE_WAY_COST_RATE: Final = 0.001  # 10 bp on sleeve and proxy turnover.
BETA_LOOKBACK_RETURNS: Final = 126
BETA_MIN_RETURNS: Final = 63
MAX_ABS_TOPIX_HEDGE: Final = 1.5
BASE_RETURN_SEMANTICS: Final = (
    "NET_AFTER_STOCK_EXECUTION_COSTS_AND_SHORT_FINANCING"
)
BASE_NAV_SEMANTICS: Final = "CONTINUOUS_PRE_EXISTING_INVESTABLE_NAV"
SOURCE_SLICE_WRAPPER_COST_SEMANTICS: Final = (
    "EXCLUDES_NAV_WRAPPER_ENTRY_AND_LIQUIDATION"
)
PANEL_OBSERVATION_DIGEST_SCHEMA: Final = "index-vol-overlay-observations/v1"
TRADING_CALENDAR_DIGEST_SCHEMA: Final = "ordered-trading-session-dates/v1"
CONSERVATIVE_EXECUTION_CUTOFF_JST: Final = "15:00:00+09:00"
LIFECYCLE_STAGE: Final = "DRAFT_DIAGNOSTIC"
PERSONAL_INDEX_SMILE_TRANSPORT_SCHEMA: Final = (
    "personal-index-smile-transport/v1"
)
PREPARED_SMILE_TRANSPORT_PANEL_MANIFEST_SCHEMA: Final = (
    "prepared-index-smile-transport-panel/v1"
)
SMILE_TRANSPORT_PANEL_DIGEST_SCHEMA: Final = (
    "index-smile-transport-observations/v1"
)
SMILE_TRANSPORT_CORE_MODULE: Final = (
    "packages/product/research/options_225_smile_transport.py"
)
POTENTIAL_MINIMUM_MISMATCH_SCALE: Final = 0.10
COMMON_VALID_MIN_SIGNAL_DAYS: Final = 40
COMMON_VALID_MIN_CALENDAR_MONTHS: Final = 4
FEATURE_AVAILABLE_NO_EARLIER_THAN_JST: Final = "23:59:59+09:00"
DOWN_SIDE_SMILE_FAMILY: Final = "downside_smile_term_surprise"
POTENTIAL_MINIMUM_FAMILY: Final = "potential_minimum_transport"
SMILE_TRANSPORT_COORDINATE_DEFINITION: Final = "k=ln(strike/UnderPx_proxy)"
SMILE_TRANSPORT_SIGNAL_CUTOFF: Final = "D_close"
SMILE_TRANSPORT_EXECUTION_INTENT: Final = "D_plus_1_or_later"
SMILE_TRANSPORT_RESEARCH_STATUS: Final = "DRAFT_DIAGNOSTIC_ONLY"
SMILE_TRANSPORT_PAIRING_RULE: Final = (
    "adjacent_observation_dates_exact_same_expiry"
)
_SMILE_TRANSPORT_REQUIRED_FALSE: Final = (
    "single_stock_iv_used",
    "ffill_applied",
    "expiry_rank_substitution_applied",
    "extrapolation_applied",
    "trusted_forward_available",
    "under_px_is_trusted_forward",
)
_SMILE_TRANSPORT_REQUIRED_NULL: Final = (
    "forward_relative_minimum_log_moneyness",
    "forward_relative_minimum_strike_ratio_minus_one",
)
_SMILE_TRANSPORT_REQUIRED_EXACT: Final = {
    "version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
    "surface_scope": OPTIONS_225_SMILE_SURFACE_SCOPE,
    "source_dataset_id": DATASET_ID,
    "coordinate_definition": SMILE_TRANSPORT_COORDINATE_DEFINITION,
    "forward_relative_reason": TRUSTED_FORWARD_UNAVAILABLE,
    "signal_cutoff": SMILE_TRANSPORT_SIGNAL_CUTOFF,
    "execution_intent": SMILE_TRANSPORT_EXECUTION_INTENT,
    "research_status": SMILE_TRANSPORT_RESEARCH_STATUS,
    "pairing_rule": SMILE_TRANSPORT_PAIRING_RULE,
}


_BASE_COHORT_DEFINITION = get_research_cohort(BASE_COHORT_ID)
_BASE_STRATEGY_DEFINITION = next(
    (
        spec
        for spec in _BASE_COHORT_DEFINITION.strategy_specs
        if spec.strategy_id == BASE_SLEEVE_ID
    ),
    None,
)
if _BASE_STRATEGY_DEFINITION is None:  # pragma: no cover - import-time drift guard
    raise RuntimeError("frozen base strategy is absent from its declared cohort")
EXPECTED_BASE_STRATEGY_SPEC_DIGEST: Final = strategy_spec_digest(
    _BASE_STRATEGY_DEFINITION
)
EXPECTED_BASE_COHORT_DIGEST: Final = str(
    _BASE_COHORT_DEFINITION.to_dict()["cohort_digest"]
)


@dataclass(frozen=True, slots=True)
class IndexVolOverlayObservation:
    """One session of strictly index-level volatility and sleeve evidence.

    ``base_sleeve_return`` is the frozen stock sleeve's close-to-close return
    ending on ``date``.  IV fields are index-option observations.  No field can
    carry individual-stock option IV.
    """

    date: str
    # Timestamp at which every value in this prepared row was simultaneously
    # available.  It must be strictly earlier than the next session's
    # conservative 15:00 JST execution cutoff.
    available_at: str
    base_sleeve_return: float | None
    topix_cash_close: float | None
    n225_base_vol: float | None
    n225_atm_iv: float | None
    topix_realized_vol_20: float | None
    n225_front_atm_iv: float | None
    n225_next_atm_iv: float | None
    n225_front_downside_wing_iv: float | None
    n225_next_downside_wing_iv: float | None
    # SVI equivalents are retained for diagnostics only.  They never enter a
    # signal, candidate ordering, or result selection.
    svi_equivalent_atm_term_ratio: float | None = None
    # Same relative-smile definition as the observed candidate:
    # (front downside wing/front ATM)/(next downside wing/next ATM).
    svi_equivalent_downside_smile_term_ratio: float | None = None


def _canonical_sha256(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    payload = value[7:]
    return len(payload) == 64 and all(
        character in "0123456789abcdef" for character in payload
    )


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical_prepared_panel_digest(
    observations: Sequence[IndexVolOverlayObservation],
) -> str:
    """Hash every typed row field, including its availability timestamp."""

    return _canonical_digest(
        {
            "schema_version": PANEL_OBSERVATION_DIGEST_SCHEMA,
            "rows": [asdict(row) for row in observations],
        }
    )


def _canonical_authoritative_session_dates(
    session_dates: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(session_dates, (str, bytes)) or len(session_dates) < 3:
        raise ValueError("authoritative session dates must contain at least three rows")
    canonical: list[str] = []
    for raw in session_dates:
        try:
            parsed = date.fromisoformat(raw).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "authoritative session dates must be canonical ISO"
            ) from exc
        if parsed != raw:
            raise ValueError("authoritative session dates must be canonical ISO")
        if canonical and raw <= canonical[-1]:
            raise ValueError("authoritative session dates must be strictly increasing")
        canonical.append(raw)
    return tuple(canonical)


def canonical_trading_calendar_digest(session_dates: Sequence[str]) -> str:
    """Hash only the independently supplied authoritative session vector."""

    canonical = _canonical_authoritative_session_dates(session_dates)
    return _canonical_digest(
        {
            "schema_version": TRADING_CALENDAR_DIGEST_SCHEMA,
            "ordered_session_dates": list(canonical),
        }
    )


@dataclass(frozen=True, slots=True)
class PreparedIndexVolOverlayPanelManifest:
    """Typed provenance contract produced before overlay evaluation."""

    strategy_spec_digest: str
    cohort_digest: str
    snapshot_digest: str
    base_report_digest: str
    trading_calendar_digest: str
    prepared_panel_digest: str
    session_date_start: str
    session_date_end: str
    session_count: int
    base_strategy_id: str = BASE_SLEEVE_ID
    base_universe_id: str = BASE_UNIVERSE_ID
    base_cohort_id: str = BASE_COHORT_ID
    return_semantics: str = BASE_RETURN_SEMANTICS
    base_nav_semantics: str = BASE_NAV_SEMANTICS
    source_slice_wrapper_cost_semantics: str = (
        SOURCE_SLICE_WRAPPER_COST_SEMANTICS
    )
    lifecycle: str = LIFECYCLE_STAGE

    def __post_init__(self) -> None:
        if self.base_strategy_id != BASE_SLEEVE_ID:
            raise ValueError("prepared panel must bind the exact frozen base strategy")
        if self.base_universe_id != BASE_UNIVERSE_ID:
            raise ValueError("prepared panel must bind the exact topix_all universe")
        if self.base_cohort_id != BASE_COHORT_ID:
            raise ValueError(
                "prepared panel must bind the exact short-financing cohort"
            )
        if self.return_semantics != BASE_RETURN_SEMANTICS:
            raise ValueError(
                "base sleeve returns must be net of stock costs and financing"
            )
        if self.base_nav_semantics != BASE_NAV_SEMANTICS:
            raise ValueError("prepared panel base NAV semantics are invalid")
        if (
            self.source_slice_wrapper_cost_semantics
            != SOURCE_SLICE_WRAPPER_COST_SEMANTICS
        ):
            raise ValueError("prepared panel wrapper-cost semantics are invalid")
        if self.lifecycle != LIFECYCLE_STAGE:
            raise ValueError("prepared panel must remain DRAFT_DIAGNOSTIC")
        for name in (
            "strategy_spec_digest",
            "cohort_digest",
            "snapshot_digest",
            "base_report_digest",
            "trading_calendar_digest",
            "prepared_panel_digest",
        ):
            if not _canonical_sha256(getattr(self, name)):
                raise ValueError(f"{name} must be a canonical sha256 digest")
        if self.strategy_spec_digest != EXPECTED_BASE_STRATEGY_SPEC_DIGEST:
            raise ValueError("strategy_spec_digest does not match repo definition")
        if self.cohort_digest != EXPECTED_BASE_COHORT_DIGEST:
            raise ValueError("cohort_digest does not match repo definition")
        try:
            start = date.fromisoformat(self.session_date_start).isoformat()
            end = date.fromisoformat(self.session_date_end).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "manifest session dates must be canonical ISO dates"
            ) from exc
        if start != self.session_date_start or end != self.session_date_end:
            raise ValueError("manifest session dates must be canonical ISO dates")
        if end < start:
            raise ValueError("manifest session_date_end precedes session_date_start")
        if (
            not isinstance(self.session_count, int)
            or isinstance(self.session_count, bool)
            or self.session_count < 3
        ):
            raise ValueError("manifest session_count must be at least three")


@dataclass(frozen=True, slots=True)
class OverlayCandidate:
    candidate_id: str
    feature_kind: str
    mechanics: str
    thesis: str
    return_source: str


OVERLAY_CANDIDATES: Final[tuple[OverlayCandidate, ...]] = (
    OverlayCandidate(
        candidate_id="n225_basevol_10_over_60_defensive_v1",
        feature_kind="basevol_10_over_60",
        mechanics=(
            "x=mean(N225 BaseVol,10 sessions)/mean(N225 BaseVol,60 sessions); "
            "gross scale g=clip(1/x,0.5,1.0)"
        ),
        thesis="Reduce the frozen stock sleeve when short-run index volatility rises.",
        return_source="Lower drawdown and volatility drag during broad market stress.",
    ),
    OverlayCandidate(
        candidate_id="n225_atmiv_over_topix_rv20_normalized_126_v1",
        feature_kind="atmiv_topix_rv_normalized_126",
        mechanics=(
            "x=(N225 ATM IV/TOPIX RV20)/its inclusive trailing-126-session "
            "median; g=clip(1/x,0.5,1.0)"
        ),
        thesis="Treat unusually rich index IV versus TOPIX realised risk as caution.",
        return_source="Dynamic risk reduction when option-implied stress is elevated.",
    ),
    OverlayCandidate(
        candidate_id="n225_observed_front_over_next_atm_v1",
        feature_kind="observed_atm_term_ratio",
        mechanics="x=observed front ATM IV/next ATM IV; g=clip(1/x,0.5,1.0)",
        thesis="Front-month ATM inversion is a near-term stress signal.",
        return_source="Avoid part of short-horizon market drawdowns during inversion.",
    ),
    OverlayCandidate(
        candidate_id="n225_observed_downside_smile_front_over_next_v1",
        feature_kind="observed_downside_smile_term_ratio",
        mechanics=(
            "x=(observed front downside-wing IV/front ATM IV)/"
            "(observed next downside-wing IV/next ATM IV); "
            "g=clip(1/x,0.5,1.0)"
        ),
        thesis=(
            "Front downside-smile steepening, net of each maturity's ATM level, "
            "can warn before broad ATM volatility does."
        ),
        return_source=(
            "Reduce crash exposure when near-term downside protection is rich "
            "relative to its own ATM volatility."
        ),
    ),
)


SMILE_TRANSPORT_CANDIDATES: Final[tuple[OverlayCandidate, ...]] = (
    OverlayCandidate(
        candidate_id="n225_sticky_strike_downside_smile_term_surprise_v1",
        feature_kind="sticky_strike_downside_smile_term_surprise",
        mechanics=(
            "q=actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1; "
            "g=clip(1/(1+q),0.5,1.0)"
        ),
        thesis=(
            "Sticky-strike downside smile term surprise versus the prior exact "
            "expiry surface is a near-term caution signal."
        ),
        return_source=(
            "Reduce the frozen sleeve when the front/next downside smile term "
            "is richer than the sticky-strike prediction."
        ),
    ),
    OverlayCandidate(
        candidate_id="n225_sticky_moneyness_downside_smile_term_surprise_v1",
        feature_kind="sticky_moneyness_downside_smile_term_surprise",
        mechanics=(
            "q=actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1; "
            "g=clip(1/(1+q),0.5,1.0)"
        ),
        thesis=(
            "Sticky-moneyness downside smile term surprise versus the prior exact "
            "expiry surface is a separate, non-switched caution signal."
        ),
        return_source=(
            "Reduce the frozen sleeve when the front/next downside smile term "
            "is richer than the sticky-moneyness prediction."
        ),
    ),
    OverlayCandidate(
        candidate_id="n225_sticky_strike_potential_minimum_transport_v1",
        feature_kind="sticky_strike_potential_minimum_transport",
        mechanics=(
            "M=(abs(e_front)+abs(e_next))/2+abs(e_next-e_front); "
            "g=clip(1/(1+M/0.10),0.5,1.0)"
        ),
        thesis=(
            "A metaphor-only sticky-strike mismatch of the raw-SVI total-variance "
            "minimum location is a caution scale, not a causal claim."
        ),
        return_source=(
            "Reduce the frozen sleeve when the sticky-strike potential-minimum "
            "transport mismatch is large."
        ),
    ),
    OverlayCandidate(
        candidate_id="n225_sticky_moneyness_potential_minimum_transport_v1",
        feature_kind="sticky_moneyness_potential_minimum_transport",
        mechanics=(
            "M=(abs(e_front)+abs(e_next))/2+abs(e_next-e_front); "
            "g=clip(1/(1+M/0.10),0.5,1.0)"
        ),
        thesis=(
            "A metaphor-only sticky-moneyness mismatch of the raw-SVI "
            "total-variance minimum location is a caution scale, not a causal claim."
        ),
        return_source=(
            "Reduce the frozen sleeve when the sticky-moneyness potential-minimum "
            "transport mismatch is large."
        ),
    ),
)

SMILE_TRANSPORT_CANDIDATE_IDS: Final[tuple[str, ...]] = tuple(
    item.candidate_id for item in SMILE_TRANSPORT_CANDIDATES
)
_SMILE_TRANSPORT_IDENTITY: Final[dict[str, tuple[str, str]]] = {
    "n225_sticky_strike_downside_smile_term_surprise_v1": (
        STICKY_STRIKE,
        DOWN_SIDE_SMILE_FAMILY,
    ),
    "n225_sticky_moneyness_downside_smile_term_surprise_v1": (
        STICKY_MONEYNESS,
        DOWN_SIDE_SMILE_FAMILY,
    ),
    "n225_sticky_strike_potential_minimum_transport_v1": (
        STICKY_STRIKE,
        POTENTIAL_MINIMUM_FAMILY,
    ),
    "n225_sticky_moneyness_potential_minimum_transport_v1": (
        STICKY_MONEYNESS,
        POTENTIAL_MINIMUM_FAMILY,
    ),
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0.0 else None


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


_JST = timezone(timedelta(hours=9))
_EXECUTION_CUTOFF_TIME = time(hour=15, minute=0, second=0, tzinfo=_JST)


def _availability_timestamp(row: IndexVolOverlayObservation) -> datetime:
    try:
        parsed = datetime.fromisoformat(row.available_at)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"observation available_at must be canonical ISO: {row.available_at!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observation available_at must include a UTC offset")
    if (
        parsed.microsecond != 0
        or parsed.isoformat(timespec="seconds") != row.available_at
    ):
        raise ValueError("observation available_at must use canonical whole seconds")
    return parsed


def _next_session_execution_cutoff(next_session_date: str) -> datetime:
    return datetime.combine(
        date.fromisoformat(next_session_date),
        _EXECUTION_CUTOFF_TIME,
    )


def _validate_observations(
    observations: Sequence[IndexVolOverlayObservation],
) -> None:
    if len(observations) < 3:
        raise ValueError("at least three ordered sessions are required")
    previous: str | None = None
    availability: list[datetime] = []
    for row in observations:
        if not isinstance(row, IndexVolOverlayObservation):
            raise TypeError("observations must be IndexVolOverlayObservation values")
        try:
            parsed = date.fromisoformat(row.date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid observation date: {row.date!r}") from exc
        canonical = parsed.isoformat()
        if row.date != canonical:
            raise ValueError(f"observation date must be canonical ISO: {row.date!r}")
        if previous is not None and row.date <= previous:
            raise ValueError("observation dates must be unique and strictly increasing")
        availability.append(_availability_timestamp(row))
        previous = row.date
    for index, available_at in enumerate(availability[:-1]):
        cutoff = _next_session_execution_cutoff(observations[index + 1].date)
        if available_at >= cutoff:
            raise ValueError(
                "prepared row must be available strictly before its D+1 "
                "execution cutoff"
            )


def _validate_manifest(
    manifest: PreparedIndexVolOverlayPanelManifest,
    observations: Sequence[IndexVolOverlayObservation],
    authoritative_session_dates: Sequence[str],
) -> None:
    if not isinstance(manifest, PreparedIndexVolOverlayPanelManifest):
        raise TypeError("manifest must be PreparedIndexVolOverlayPanelManifest")
    authoritative = _canonical_authoritative_session_dates(
        authoritative_session_dates
    )
    observed_dates = tuple(row.date for row in observations)
    if observed_dates != authoritative:
        raise ValueError(
            "observation dates must exactly match authoritative session dates"
        )
    if manifest.session_count != len(authoritative):
        raise ValueError("prepared panel manifest session_count mismatch")
    if manifest.session_date_start != authoritative[0]:
        raise ValueError("prepared panel manifest session_date_start mismatch")
    if manifest.session_date_end != authoritative[-1]:
        raise ValueError("prepared panel manifest session_date_end mismatch")
    try:
        observed_panel_digest = canonical_prepared_panel_digest(observations)
    except (TypeError, ValueError) as exc:
        raise ValueError("prepared panel rows are not canonically hashable") from exc
    if manifest.prepared_panel_digest != observed_panel_digest:
        raise ValueError("prepared_panel_digest does not match observation rows")
    observed_calendar_digest = canonical_trading_calendar_digest(authoritative)
    if manifest.trading_calendar_digest != observed_calendar_digest:
        raise ValueError("trading_calendar_digest does not match ordered session dates")


def build_prepared_panel_manifest(
    observations: Sequence[IndexVolOverlayObservation],
    *,
    authoritative_session_dates: Sequence[str],
    snapshot_digest: str,
    base_report_digest: str,
) -> PreparedIndexVolOverlayPanelManifest:
    """Build the ergonomic manifest while deriving every repo/local digest."""

    _validate_observations(observations)
    authoritative = _canonical_authoritative_session_dates(
        authoritative_session_dates
    )
    if tuple(row.date for row in observations) != authoritative:
        raise ValueError(
            "observation dates must exactly match authoritative session dates"
        )
    return PreparedIndexVolOverlayPanelManifest(
        strategy_spec_digest=EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
        cohort_digest=EXPECTED_BASE_COHORT_DIGEST,
        snapshot_digest=snapshot_digest,
        base_report_digest=base_report_digest,
        trading_calendar_digest=canonical_trading_calendar_digest(authoritative),
        prepared_panel_digest=canonical_prepared_panel_digest(observations),
        session_date_start=authoritative[0],
        session_date_end=authoritative[-1],
        session_count=len(authoritative),
    )


def _ratio(numerator: Any, denominator: Any) -> float | None:
    left = _positive(numerator)
    right = _positive(denominator)
    if left is None or right is None:
        return None
    value = left / right
    return value if math.isfinite(value) and value > 0.0 else None


def _feature_value(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayObservation],
    index: int,
) -> tuple[float | None, str | None]:
    row = rows[index]
    if candidate.feature_kind == "basevol_10_over_60":
        if index < 59:
            return None, "basevol_60_session_history_unavailable"
        window = [
            _positive(item.n225_base_vol)
            for item in rows[index - 59 : index + 1]
        ]
        if any(value is None for value in window):
            return None, "basevol_required_history_has_missing_row"
        values = [float(value) for value in window if value is not None]
        return _ratio(mean(values[-10:]), mean(values)), None

    if candidate.feature_kind == "atmiv_topix_rv_normalized_126":
        if index < 125:
            return None, "atmiv_topix_rv_126_session_history_unavailable"
        window = [
            _ratio(item.n225_atm_iv, item.topix_realized_vol_20)
            for item in rows[index - 125 : index + 1]
        ]
        if any(value is None for value in window):
            return None, "atmiv_topix_rv_required_history_has_missing_row"
        values = [float(value) for value in window if value is not None]
        return _ratio(values[-1], median(values)), None

    if candidate.feature_kind == "observed_atm_term_ratio":
        value = _ratio(row.n225_front_atm_iv, row.n225_next_atm_iv)
        return value, None if value is not None else "observed_atm_term_row_missing"

    if candidate.feature_kind == "observed_downside_smile_term_ratio":
        front_smile = _ratio(
            row.n225_front_downside_wing_iv,
            row.n225_front_atm_iv,
        )
        next_smile = _ratio(
            row.n225_next_downside_wing_iv,
            row.n225_next_atm_iv,
        )
        value = _ratio(front_smile, next_smile)
        return (
            value,
            None
            if value is not None
            else "observed_downside_smile_term_row_missing",
        )
    raise AssertionError(f"unknown frozen candidate feature: {candidate.feature_kind}")


def _topix_return(
    rows: Sequence[IndexVolOverlayObservation],
    start_index: int,
    end_index: int,
) -> float | None:
    before = _positive(rows[start_index].topix_cash_close)
    after = _positive(rows[end_index].topix_cash_close)
    if before is None or after is None:
        return None
    return _finite(after / before - 1.0)


def _estimate_beta(
    rows: Sequence[IndexVolOverlayObservation],
    signal_index: int,
) -> tuple[tuple[float, int, str] | None, str | None]:
    if signal_index < 1:
        return None, "beta_current_signal_day_pair_unavailable"
    current_sleeve_return = _finite(rows[signal_index].base_sleeve_return)
    current_proxy_return = _topix_return(rows, signal_index - 1, signal_index)
    if current_sleeve_return is None or current_proxy_return is None:
        return None, "beta_current_signal_day_pair_unavailable"
    paired: list[tuple[str, float, float]] = []
    first_source_return = max(1, signal_index - BETA_LOOKBACK_RETURNS + 1)
    for index in range(first_source_return, signal_index + 1):
        sleeve_return = _finite(rows[index].base_sleeve_return)
        proxy_return = _topix_return(rows, index - 1, index)
        if sleeve_return is None or proxy_return is None:
            continue
        paired.append((rows[index].date, sleeve_return, proxy_return))
    if len(paired) < BETA_MIN_RETURNS:
        return None, "beta_min_63_pairs_unavailable_in_last_126_source_sessions"
    if paired[-1][0] != rows[signal_index].date:
        return None, "beta_current_signal_day_pair_unavailable"
    sleeve_values = [item[1] for item in paired]
    proxy_values = [item[2] for item in paired]
    sleeve_mean = mean(sleeve_values)
    proxy_mean = mean(proxy_values)
    covariance = sum(
        (sleeve - sleeve_mean) * (proxy - proxy_mean)
        for sleeve, proxy in zip(sleeve_values, proxy_values, strict=True)
    )
    variance = sum((proxy - proxy_mean) ** 2 for proxy in proxy_values)
    if variance <= 1.0e-18:
        return None, "beta_proxy_variance_unavailable"
    beta = _finite(covariance / variance)
    if beta is None:
        return None, "beta_non_finite"
    return (beta, len(paired), paired[-1][0]), None


def _missing(date_value: str, reason: str) -> dict[str, str]:
    return {"date": date_value, "reason": reason}


def _plans_for_candidate(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayObservation],
    signal_indices: Sequence[int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    plans: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for signal_index in signal_indices:
        signal_row = rows[signal_index]
        if signal_index + 2 >= len(rows):
            missing.append(_missing(signal_row.date, "d_plus_2_session_unavailable"))
            continue
        x_value, feature_error = _feature_value(candidate, rows, signal_index)
        if x_value is None:
            missing.append(
                _missing(signal_row.date, feature_error or "feature_value_unavailable")
            )
            continue
        beta, beta_error = _estimate_beta(rows, signal_index)
        if beta is None:
            missing.append(
                _missing(signal_row.date, beta_error or "beta_estimate_unavailable")
            )
            continue
        pnl_index = signal_index + 2
        sleeve_return = _finite(rows[pnl_index].base_sleeve_return)
        proxy_return = _topix_return(rows, signal_index + 1, pnl_index)
        if sleeve_return is None:
            missing.append(_missing(rows[pnl_index].date, "base_sleeve_return_missing"))
            continue
        if proxy_return is None:
            missing.append(_missing(rows[pnl_index].date, "topix_cash_return_missing"))
            continue
        gross_scale = _clip(1.0 / x_value, 0.5, 1.0)
        estimated_beta, beta_observations, beta_last_date = beta
        hedge_weight = _clip(
            -gross_scale * estimated_beta,
            -MAX_ABS_TOPIX_HEDGE,
            MAX_ABS_TOPIX_HEDGE,
        )
        plans.append(
            {
                "signal_date": signal_row.date,
                "rebalance_date": rows[signal_index + 1].date,
                "pnl_date": rows[pnl_index].date,
                "feature_ratio_x": x_value,
                "gross_scale": gross_scale,
                "estimated_beta": estimated_beta,
                "beta_observations": beta_observations,
                "beta_window_last_return_date": beta_last_date,
                "topix_hedge_weight": hedge_weight,
                "base_sleeve_return": sleeve_return,
                "topix_cash_return": proxy_return,
            }
        )
    return plans, missing


def _trade(
    *,
    side: str,
    signal_date: str,
    fill_date: str,
    pnl_date: str,
    signed_notional: float,
) -> dict[str, Any] | None:
    if signed_notional == 0.0:
        return None
    return {
        "side": side,
        "signal_date": signal_date,
        "fill_date": fill_date,
        "pnl_date": pnl_date,
        "notional": signed_notional,
        "cost": abs(signed_notional) * ONE_WAY_COST_RATE,
    }


def _evaluate_plans(
    plans: Sequence[dict[str, Any]],
    *,
    starting_capital: float,
    continuous_nav_wrapper: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    equity = starting_capital
    carried_sleeve_notional = 0.0
    carried_proxy_notional = 0.0
    curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for plan_index, plan in enumerate(plans):
        gross_scale = float(plan["gross_scale"])
        hedge_weight = float(plan["topix_hedge_weight"])
        opening_equity = equity
        if continuous_nav_wrapper and plan_index > 0:
            target_sleeve_notional = carried_sleeve_notional
            target_proxy_notional = carried_proxy_notional
        else:
            target_sleeve_notional = gross_scale * opening_equity
            target_proxy_notional = hedge_weight * opening_equity
        sleeve_trade_notional = target_sleeve_notional - carried_sleeve_notional
        proxy_trade_notional = target_proxy_notional - carried_proxy_notional
        sleeve_turnover_amount = abs(sleeve_trade_notional)
        proxy_turnover_amount = abs(proxy_trade_notional)
        for trade in (
            _trade(
                side="sleeve_rebalance",
                signal_date=str(plan["signal_date"]),
                fill_date=str(plan["rebalance_date"]),
                pnl_date=str(plan["pnl_date"]),
                signed_notional=sleeve_trade_notional,
            ),
            _trade(
                side="topix_cash_proxy_rebalance",
                signal_date=str(plan["signal_date"]),
                fill_date=str(plan["rebalance_date"]),
                pnl_date=str(plan["pnl_date"]),
                signed_notional=proxy_trade_notional,
            ),
        ):
            if trade is not None:
                trades.append(trade)
        opening_cost = ONE_WAY_COST_RATE * (
            sleeve_turnover_amount + proxy_turnover_amount
        )
        sleeve_return = float(plan["base_sleeve_return"])
        proxy_return = float(plan["topix_cash_return"])
        gross_pnl = (
            target_sleeve_notional * sleeve_return
            + target_proxy_notional * proxy_return
        )
        gross_return = gross_pnl / opening_equity
        equity = opening_equity + gross_pnl - opening_cost
        post_return_sleeve_notional = target_sleeve_notional * (
            1.0 + sleeve_return
        )
        post_return_proxy_notional = target_proxy_notional * (1.0 + proxy_return)
        terminal_turnover_amount = 0.0
        terminal_cost = 0.0
        terminal_close = plan_index == len(plans) - 1
        if terminal_close:
            sleeve_close_notional = -post_return_sleeve_notional
            proxy_close_notional = -post_return_proxy_notional
            terminal_turnover_amount = abs(sleeve_close_notional) + abs(
                proxy_close_notional
            )
            for trade in (
                _trade(
                    side="sleeve_terminal_close",
                    signal_date=str(plan["signal_date"]),
                    fill_date=str(plan["pnl_date"]),
                    pnl_date=str(plan["pnl_date"]),
                    signed_notional=sleeve_close_notional,
                ),
                _trade(
                    side="topix_cash_proxy_terminal_close",
                    signal_date=str(plan["signal_date"]),
                    fill_date=str(plan["pnl_date"]),
                    pnl_date=str(plan["pnl_date"]),
                    signed_notional=proxy_close_notional,
                ),
            ):
                if trade is not None:
                    trades.append(trade)
            terminal_cost = ONE_WAY_COST_RATE * terminal_turnover_amount
            equity -= terminal_cost
        if not math.isfinite(equity) or equity <= 0.0:
            raise ValueError("overlay path produced non-positive or non-finite equity")
        net_return = equity / opening_equity - 1.0
        curve.append(
            {
                **plan,
                "gross_return": gross_return,
                "pre_rebalance_sleeve_notional": carried_sleeve_notional,
                "pre_rebalance_topix_proxy_notional": carried_proxy_notional,
                "target_sleeve_notional": target_sleeve_notional,
                "target_topix_proxy_notional": target_proxy_notional,
                "sleeve_trade_notional": sleeve_trade_notional,
                "topix_proxy_trade_notional": proxy_trade_notional,
                "sleeve_turnover_one_way_amount": sleeve_turnover_amount,
                "topix_proxy_turnover_one_way_amount": proxy_turnover_amount,
                "sleeve_turnover_one_way": (
                    sleeve_turnover_amount / opening_equity
                ),
                "topix_proxy_turnover_one_way": (
                    proxy_turnover_amount / opening_equity
                ),
                "rebalance_cost_amount": opening_cost,
                "post_return_sleeve_notional": post_return_sleeve_notional,
                "post_return_topix_proxy_notional": post_return_proxy_notional,
                "terminal_close": terminal_close,
                "terminal_turnover_one_way_amount": terminal_turnover_amount,
                "terminal_turnover_one_way": (
                    0.0
                    if not terminal_close
                    else terminal_turnover_amount / (equity + terminal_cost)
                ),
                "terminal_close_cost_amount": terminal_cost,
                "net_return": net_return,
                "date": plan["pnl_date"],
                "equity": equity,
            }
        )
        carried_sleeve_notional = post_return_sleeve_notional
        carried_proxy_notional = post_return_proxy_notional
    performance = summarize_performance(
        equity_curve=curve,
        trades=trades,
        starting_capital=starting_capital,
    )
    performance.update(
        {
            "cost_turnover_fill_scope": "OVERLAY_INCREMENTAL_ONLY",
            "base_sleeve_return_semantics": BASE_RETURN_SEMANTICS,
            "base_nav_semantics": BASE_NAV_SEMANTICS,
            "source_slice_wrapper_cost_semantics": (
                SOURCE_SLICE_WRAPPER_COST_SEMANTICS
            ),
            "total_strategy_cost_turnover_fill_comparable": False,
        }
    )
    return curve, trades, performance


def _candidate_result(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayObservation],
    signal_indices: Sequence[int],
    *,
    starting_capital: float,
) -> dict[str, Any]:
    plans, missing = _plans_for_candidate(candidate, rows, signal_indices)
    declaration = asdict(candidate)
    if missing:
        return {
            **declaration,
            "status": "NOT_EVALUATED",
            "reason": "missing_required_row_no_forward_fill",
            "missing_required_rows": missing,
            "daily_path": [],
            "trades": [],
            "performance": None,
        }
    if not plans:
        return {
            **declaration,
            "status": "NOT_EVALUATED",
            "reason": "no_signal_sessions_in_requested_range",
            "missing_required_rows": [],
            "daily_path": [],
            "trades": [],
            "performance": None,
        }
    curve, trades, performance = _evaluate_plans(
        plans,
        starting_capital=starting_capital,
    )
    return {
        **declaration,
        "status": "EVALUATED",
        "reason": None,
        "missing_required_rows": [],
        "daily_path": curve,
        "trades": trades,
        "performance": performance,
    }


def _diagnostic_control_result(
    rows: Sequence[IndexVolOverlayObservation],
    signal_indices: Sequence[int],
    *,
    starting_capital: float,
) -> dict[str, Any]:
    """Evaluate the frozen base sleeve without adding a fifth candidate."""

    plans: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for signal_index in signal_indices:
        signal_row = rows[signal_index]
        if signal_index + 2 >= len(rows):
            missing.append(_missing(signal_row.date, "d_plus_2_session_unavailable"))
            continue
        pnl_index = signal_index + 2
        sleeve_return = _finite(rows[pnl_index].base_sleeve_return)
        if sleeve_return is None:
            missing.append(_missing(rows[pnl_index].date, "base_sleeve_return_missing"))
            continue
        plans.append(
            {
                "signal_date": signal_row.date,
                "rebalance_date": rows[signal_index + 1].date,
                "pnl_date": rows[pnl_index].date,
                "feature_ratio_x": 1.0,
                "gross_scale": 1.0,
                "estimated_beta": None,
                "beta_observations": None,
                "beta_window_last_return_date": None,
                "topix_hedge_weight": 0.0,
                "base_sleeve_return": sleeve_return,
                "topix_cash_return": 0.0,
            }
        )
    declaration = {
        "control_id": "base_g1_h0_control_v1",
        "role": "NAV_WRAPPER_CONTROL_WITH_10BP_ENTRY_EXIT",
        "ranking_role": "DIAGNOSTIC_CONTROL_NOT_RANKED",
        "mechanics": (
            "continuous pre-existing base NAV with g=1 and h=0, plus only "
            "the wrapper's 10bp entry and liquidation accounting"
        ),
        "source_slice_wrapper_cost_semantics": (
            SOURCE_SLICE_WRAPPER_COST_SEMANTICS
        ),
    }
    if missing or not plans:
        return {
            **declaration,
            "status": "NOT_EVALUATED",
            "reason": (
                "missing_required_row_no_forward_fill"
                if missing
                else "no_signal_sessions_in_requested_range"
            ),
            "missing_required_rows": missing,
            "daily_path": [],
            "trades": [],
            "performance": None,
        }
    curve, trades, performance = _evaluate_plans(
        plans,
        starting_capital=starting_capital,
        continuous_nav_wrapper=True,
    )
    return {
        **declaration,
        "status": "EVALUATED",
        "reason": None,
        "missing_required_rows": [],
        "daily_path": curve,
        "trades": trades,
        "performance": performance,
    }


def evaluate_index_vol_overlays(
    observations: Sequence[IndexVolOverlayObservation],
    *,
    manifest: PreparedIndexVolOverlayPanelManifest,
    authoritative_session_dates: Sequence[str],
    signal_start: str,
    signal_end: str | None = None,
    starting_capital: float = 1_000_000.0,
) -> dict[str, Any]:
    """Evaluate exactly four predeclared overlays without selecting a winner."""

    _validate_observations(observations)
    _validate_manifest(manifest, observations, authoritative_session_dates)
    try:
        start = date.fromisoformat(signal_start).isoformat()
        end = (
            date.fromisoformat(signal_end).isoformat()
            if signal_end
            else observations[-3].date
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("signal_start/signal_end must be canonical ISO dates") from exc
    if start != signal_start or (signal_end is not None and end != signal_end):
        raise ValueError("signal_start/signal_end must be canonical ISO dates")
    if end is not None and end < start:
        raise ValueError("signal_end must be on or after signal_start")
    capital = _positive(starting_capital)
    if capital is None:
        raise ValueError("starting_capital must be positive and finite")
    signal_indices = [
        index
        for index, row in enumerate(observations)
        if row.date >= start and (end is None or row.date <= end)
    ]
    if not signal_indices:
        raise ValueError("requested signal range has no observations")
    results = [
        _candidate_result(
            candidate,
            observations,
            signal_indices,
            starting_capital=capital,
        )
        for candidate in OVERLAY_CANDIDATES
    ]
    diagnostic_control = _diagnostic_control_result(
        observations,
        signal_indices,
        starting_capital=capital,
    )
    diagnostics = [
        {
            "date": observations[index].date,
            "svi_equivalent_atm_term_ratio": _positive(
                observations[index].svi_equivalent_atm_term_ratio
            ),
            "svi_equivalent_downside_smile_term_ratio": _positive(
                observations[index].svi_equivalent_downside_smile_term_ratio
            ),
        }
        for index in signal_indices
    ]
    evaluated_count = sum(result["status"] == "EVALUATED" for result in results)
    return {
        "schema_version": PERSONAL_INDEX_VOL_OVERLAY_SCHEMA,
        "status": "EVALUATED" if evaluated_count == len(results) else "NOT_EVALUATED",
        "lifecycle": {
            "stage": LIFECYCLE_STAGE,
            "role": "DIAGNOSTIC_RESEARCH_ONLY",
            "paper_execution": False,
            "automatic_promotion": False,
        },
        "prepared_panel_provenance": {
            "schema_version": PREPARED_PANEL_MANIFEST_SCHEMA,
            **asdict(manifest),
        },
        "base_sleeve": {
            "strategy_id": BASE_SLEEVE_ID,
            "universe_id": BASE_UNIVERSE_ID,
            "selection_timing": "PREDECLARED_BEFORE_OVERLAY_RESULTS",
            "single_stock_option_iv": "EXCLUDED_FROM_INPUT_SURFACE",
            "stock_price_realized_volatility": "ALLOWED_IN_FROZEN_BASE_SLEEVE",
            "return_semantics": BASE_RETURN_SEMANTICS,
            "nav_semantics": BASE_NAV_SEMANTICS,
            "source_slice_wrapper_cost_semantics": (
                SOURCE_SLICE_WRAPPER_COST_SEMANTICS
            ),
        },
        "timing": {
            "signal": "D_CLOSE",
            "rebalance": "D_PLUS_1_CLOSE",
            "first_pnl": "D_PLUS_1_CLOSE_TO_D_PLUS_2_CLOSE",
            "terminal_close": True,
            "authoritative_calendar_alignment": "EXACT_ORDERED_DATE_MATCH",
            "prepared_row_availability": (
                "STRICTLY_BEFORE_D_PLUS_1_CONSERVATIVE_15_00_JST_CUTOFF"
            ),
            "conservative_execution_cutoff_jst": CONSERVATIVE_EXECUTION_CUTOFF_JST,
        },
        "cost_model": {
            "one_way_basis_points": 10.0,
            "applies_to": ["base_sleeve_turnover", "topix_proxy_turnover"],
            "reported_cost_turnover_fill_scope": "OVERLAY_INCREMENTAL_ONLY",
            "not_total_strategy_cost_metrics": True,
            "base_nav_source_slice_excludes_wrapper_entry_liquidation": True,
        },
        "topix_proxy": {
            "dataset": TOPIX_PROXY_DATASET,
            "label": "TOPIX cash index close-to-close return",
            "role": "NON_EXECUTABLE_HEDGE_APPROXIMATION",
            "etf_fill_claim": False,
            "warning": (
                "This is not an ETF fill or tradable execution claim; later cloud "
                "work must bind an explicit executable proxy before paper execution."
            ),
        },
        "beta_policy": {
            "lookback_source_sessions": BETA_LOOKBACK_RETURNS,
            "minimum_paired_returns": BETA_MIN_RETURNS,
            "current_signal_day_pair_required": True,
            "hedge_formula": "h=clip(-g*beta,-1.5,1.5)",
        },
        "candidate_policy": {
            "declared_count": len(OVERLAY_CANDIDATES),
            "evaluated_count": evaluated_count,
            "post_result_selection": "NOT_PERFORMED",
            "ranking": None,
            "diagnostic_control_in_declared_count": False,
            "candidate_order": [item.candidate_id for item in OVERLAY_CANDIDATES],
        },
        "diagnostic_control": diagnostic_control,
        "svi_equivalent_diagnostics": {
            "role": "DIAGNOSTIC_ONLY_NOT_RANKED",
            "downside_smile_term_ratio_formula": (
                "(front_downside_wing_iv/front_atm_iv)/"
                "(next_downside_wing_iv/next_atm_iv)"
            ),
            "used_in_signals": False,
            "used_in_performance": False,
            "rows": diagnostics,
        },
        "candidates": results,
    }


def smile_transport_core_digest() -> str:
    """Content-address the reviewed transport core actually imported."""

    path = Path(_smile_transport_core.__file__ or "")
    if not path.is_file():
        raise RuntimeError("smile-transport core module path is unavailable")
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def downside_smile_term_gross_scale(q_value: float) -> float | None:
    """Map downside term surprise ``q`` onto the frozen overlay sleeve scale."""

    q_number = _finite(q_value)
    if q_number is None:
        return None
    denominator = 1.0 + q_number
    if denominator <= 0.0:
        return None
    return _clip(1.0 / denominator, 0.5, 1.0)


def potential_minimum_gross_scale(mismatch_severity: float) -> float | None:
    """Map nonnegative potential-minimum mismatch ``M`` onto the sleeve scale."""

    severity = _finite(mismatch_severity)
    if severity is None or severity < 0.0:
        return None
    return _clip(
        1.0 / (1.0 + severity / POTENTIAL_MINIMUM_MISMATCH_SCALE),
        0.5,
        1.0,
    )


def _smile_transport_availability_timestamp(
    row: IndexVolOverlayObservation,
) -> datetime:
    available_at = _availability_timestamp(row)
    floor = datetime.fromisoformat(f"{row.date}T{FEATURE_AVAILABLE_NO_EARLIER_THAN_JST}")
    if available_at < floor:
        raise ValueError(
            "smile-transport feature must not be available earlier than "
            "D 23:59:59 JST"
        )
    return available_at


def _validate_smile_transport_observations(
    observations: Sequence[IndexVolOverlayObservation],
) -> None:
    _validate_observations(observations)
    for row in observations:
        _smile_transport_availability_timestamp(row)


def _physical_potential_declaration(candidate: OverlayCandidate) -> dict[str, Any]:
    potential = candidate.feature_kind.endswith(POTENTIAL_MINIMUM_FAMILY)
    return {
        "metaphor_only": True,
        "causal_claim": False,
        "applies_to_physical_potential_language": potential,
    }


def _transport_gross_scale(
    candidate: OverlayCandidate,
    row: Mapping[str, Any] | None,
) -> tuple[float | None, float | None, str | None]:
    if row is None:
        return None, None, "transport_feature_row_missing"
    if row.get("candidate_success") is not True:
        return None, None, str(row.get("candidate_reason") or "candidate_unsuccessful")
    raw = _finite(row.get("candidate_value"))
    if raw is None:
        return None, None, "candidate_value_unavailable"
    if candidate.feature_kind.endswith(DOWN_SIDE_SMILE_FAMILY):
        scale = downside_smile_term_gross_scale(raw)
        if scale is None:
            return None, raw, "downside_q_not_mappable_to_g"
        return scale, raw, None
    if candidate.feature_kind.endswith(POTENTIAL_MINIMUM_FAMILY):
        scale = potential_minimum_gross_scale(raw)
        if scale is None:
            return None, raw, "potential_minimum_mismatch_not_mappable_to_g"
        return scale, raw, None
    raise AssertionError(f"unknown frozen transport feature: {candidate.feature_kind}")


def _canonical_iso_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value).isoformat()
    except ValueError:
        return None
    return parsed if parsed == value else None


def _reject_single_stock_transport_row(row: Mapping[str, Any]) -> None:
    if (
        row.get("single_stock_iv_used") is not False
        or row.get("surface_scope") != OPTIONS_225_SMILE_SURFACE_SCOPE
        or row.get("source_dataset_id") != DATASET_ID
    ):
        raise ValueError("single-stock option IV is forbidden")


def _group_transport_features(
    rows: Sequence[Mapping[str, Any]],
    session_dates: Sequence[str],
) -> dict[str, list[Mapping[str, Any]]]:
    allowed = set(session_dates)
    grouped: dict[str, list[Mapping[str, Any]]] = {day: [] for day in session_dates}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("transport feature rows must be mappings")
        _reject_single_stock_transport_row(row)
        day = str(row.get("date") or "")
        if day not in allowed:
            raise ValueError("transport feature date is outside the bound panel")
        grouped[day].append(row)
    return grouped


def _provenance_issues(row: Mapping[str, Any], *, prefix: str) -> list[str]:
    issues: list[str] = []
    for field, expected in _SMILE_TRANSPORT_REQUIRED_EXACT.items():
        if row.get(field) != expected:
            issues.append(f"{prefix}:{field}_not_canonical")
    for field in _SMILE_TRANSPORT_REQUIRED_FALSE:
        if row.get(field) is not False:
            issues.append(f"{prefix}:{field}_not_false")
    for field in _SMILE_TRANSPORT_REQUIRED_NULL:
        if field in row and row.get(field) is not None:
            issues.append(f"{prefix}:{field}_not_null")
        elif field not in row:
            issues.append(f"{prefix}:{field}_missing")
    return issues


def _expiry_pair_issues(
    row: Mapping[str, Any],
    *,
    signal_date: str,
    prefix: str,
) -> list[str]:
    front = _canonical_iso_date(row.get("front_expiry"))
    nxt = _canonical_iso_date(row.get("next_expiry"))
    if front is None or nxt is None:
        return [f"{prefix}:exact_expiry_pair_missing"]
    if not (signal_date < front < nxt):
        return [f"{prefix}:expiry_order_invalid"]
    return []


def _candidate_row_issues(
    candidate: OverlayCandidate,
    row: Mapping[str, Any] | None,
    *,
    signal_date: str,
    predecessor: str | None,
) -> list[str]:
    if row is None:
        return [f"{candidate.candidate_id}:missing"]
    issues: list[str] = []
    expected_model, expected_family = _SMILE_TRANSPORT_IDENTITY[candidate.candidate_id]
    derived_id = f"n225_{row.get('transport_model')}_{row.get('signal_family')}_v1"
    if str(row.get("candidate_id") or "") != candidate.candidate_id:
        issues.append(f"{candidate.candidate_id}:identity_mismatch")
    if derived_id != candidate.candidate_id:
        issues.append(f"{candidate.candidate_id}:model_family_mismatch")
    if row.get("transport_model") != expected_model:
        issues.append(f"{candidate.candidate_id}:sticky_model_mismatch")
    if row.get("signal_family") != expected_family:
        issues.append(f"{candidate.candidate_id}:signal_family_mismatch")
    issues.extend(_provenance_issues(row, prefix=candidate.candidate_id))
    issues.extend(
        _expiry_pair_issues(
            row,
            signal_date=signal_date,
            prefix=candidate.candidate_id,
        )
    )
    previous = str(row.get("previous_observation_date") or "")
    if predecessor is None:
        issues.append(f"{candidate.candidate_id}:official_predecessor_unavailable")
    elif previous != predecessor:
        issues.append(
            f"{candidate.candidate_id}:previous_observation_not_official_predecessor"
        )
    scale, _raw, scale_error = _transport_gross_scale(candidate, row)
    if scale is None:
        issues.append(
            f"{candidate.candidate_id}:{scale_error or 'gross_scale_unavailable'}"
        )
    return issues


def _common_validity_for_date(
    *,
    day: str,
    predecessor: str | None,
    day_rows: Sequence[Mapping[str, Any]],
    observations: Sequence[IndexVolOverlayObservation],
    signal_index: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    ids = [str(row.get("candidate_id") or "") for row in day_rows]
    unique_ids = set(ids)
    expected = set(SMILE_TRANSPORT_CANDIDATE_IDS)
    if len(ids) != len(unique_ids):
        reasons.append("candidate_ids_not_unique")
    if unique_ids != expected:
        reasons.append("candidate_identity_not_exact_four")
    by_id = {
        str(row.get("candidate_id") or ""): row
        for row in day_rows
        if str(row.get("candidate_id") or "")
    }
    for candidate in SMILE_TRANSPORT_CANDIDATES:
        reasons.extend(
            _candidate_row_issues(
                candidate,
                by_id.get(candidate.candidate_id),
                signal_date=day,
                predecessor=predecessor,
            )
        )
    if signal_index + 2 >= len(observations):
        reasons.append("d_plus_2_session_unavailable")
    beta, beta_error = _estimate_beta(observations, signal_index)
    if beta is None:
        reasons.append(beta_error or "beta_estimate_unavailable")
    # Preserve first-seen order while dropping exact duplicates from stacked checks.
    ordered: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)
    return {
        "date": day,
        "common_valid": not ordered,
        "reasons": ordered,
        "predecessor": predecessor,
    }


def _signal_outcome_issues(
    observations: Sequence[IndexVolOverlayObservation],
    signal_index: int,
) -> list[str]:
    if signal_index + 2 >= len(observations):
        return ["d_plus_2_session_unavailable"]
    issues: list[str] = []
    if _finite(observations[signal_index + 2].base_sleeve_return) is None:
        issues.append("base_sleeve_return_missing")
    if _topix_return(observations, signal_index + 1, signal_index + 2) is None:
        issues.append("topix_cash_return_missing")
    return issues


def _not_evaluated_smile_control(
    *,
    reason: str,
    missing: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "control_id": "base_g1_h0_control_v1",
        "role": "COMMON_VALID_CALENDAR_NAV_WRAPPER_CONTROL_WITH_10BP_COSTS",
        "ranking_role": "DIAGNOSTIC_CONTROL_NOT_RANKED",
        "status": "NOT_EVALUATED",
        "reason": reason,
        "missing_required_rows": list(missing),
        "daily_path": [],
        "trades": [],
        "performance": None,
    }


def _calendar_months(dates: Sequence[str]) -> tuple[str, ...]:
    months: list[str] = []
    seen: set[str] = set()
    for day in dates:
        month = day[:7]
        if month not in seen:
            seen.add(month)
            months.append(month)
    return tuple(months)


def _invested_control_plan(
    rows: Sequence[IndexVolOverlayObservation],
    signal_index: int,
) -> dict[str, Any]:
    pnl_index = signal_index + 2
    sleeve_return = _finite(rows[pnl_index].base_sleeve_return)
    return {
        "signal_date": rows[signal_index].date,
        "rebalance_date": rows[signal_index + 1].date,
        "pnl_date": rows[pnl_index].date,
        "feature_ratio_x": 1.0,
        "gross_scale": 1.0,
        "estimated_beta": None,
        "beta_observations": None,
        "beta_window_last_return_date": None,
        "topix_hedge_weight": 0.0,
        "base_sleeve_return": 0.0 if sleeve_return is None else sleeve_return,
        "topix_cash_return": 0.0,
        "flatten_applied": False,
        "common_valid": True,
    }


def _smile_transport_control_result(
    rows: Sequence[IndexVolOverlayObservation],
    signal_indices: Sequence[int],
    validity_by_date: Mapping[str, Mapping[str, Any]],
    *,
    starting_capital: float,
) -> dict[str, Any]:
    """Compare g=1,h=0 on the same flatten calendar as the four candidates."""

    plans = [
        (
            _invested_control_plan(rows, signal_index)
            if validity_by_date[rows[signal_index].date]["common_valid"]
            else _flatten_plan(rows, signal_index)
        )
        for signal_index in signal_indices
    ]
    declaration = {
        "control_id": "base_g1_h0_control_v1",
        "role": "COMMON_VALID_CALENDAR_NAV_WRAPPER_CONTROL_WITH_10BP_COSTS",
        "ranking_role": "DIAGNOSTIC_CONTROL_NOT_RANKED",
        "mechanics": (
            "g=1 and h=0 on the common-valid decision calendar; "
            "flatten g=0,h=0 at D+1 on common-invalid dates; "
            "same overlay 10bp turnover costs as the four candidates"
        ),
        "source_slice_wrapper_cost_semantics": (
            SOURCE_SLICE_WRAPPER_COST_SEMANTICS
        ),
    }
    curve, trades, performance = _evaluate_plans(
        plans,
        starting_capital=starting_capital,
    )
    return {
        **declaration,
        "status": "EVALUATED",
        "reason": None,
        "missing_required_rows": [],
        "daily_path": curve,
        "trades": trades,
        "performance": performance,
    }


def _flatten_plan(
    rows: Sequence[IndexVolOverlayObservation],
    signal_index: int,
) -> dict[str, Any]:
    pnl_index = signal_index + 2
    sleeve_return = _finite(rows[pnl_index].base_sleeve_return)
    proxy_return = _topix_return(rows, signal_index + 1, pnl_index)
    return {
        "signal_date": rows[signal_index].date,
        "rebalance_date": rows[signal_index + 1].date,
        "pnl_date": rows[pnl_index].date,
        "feature_ratio_x": None,
        "gross_scale": 0.0,
        "estimated_beta": None,
        "beta_observations": None,
        "beta_window_last_return_date": None,
        "topix_hedge_weight": 0.0,
        "base_sleeve_return": 0.0 if sleeve_return is None else sleeve_return,
        "topix_cash_return": 0.0 if proxy_return is None else proxy_return,
        "flatten_applied": True,
        "common_valid": False,
    }


def _valid_transport_plan(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayObservation],
    signal_index: int,
    feature_row: Mapping[str, Any],
) -> dict[str, Any] | None:
    gross_scale, raw_value, error = _transport_gross_scale(candidate, feature_row)
    if gross_scale is None:
        return None
    beta, beta_error = _estimate_beta(rows, signal_index)
    if beta is None:
        return None
    pnl_index = signal_index + 2
    sleeve_return = _finite(rows[pnl_index].base_sleeve_return)
    proxy_return = _topix_return(rows, signal_index + 1, pnl_index)
    if sleeve_return is None or proxy_return is None:
        return None
    estimated_beta, beta_observations, beta_last_date = beta
    hedge_weight = _clip(
        -gross_scale * estimated_beta,
        -MAX_ABS_TOPIX_HEDGE,
        MAX_ABS_TOPIX_HEDGE,
    )
    return {
        "signal_date": rows[signal_index].date,
        "rebalance_date": rows[signal_index + 1].date,
        "pnl_date": rows[pnl_index].date,
        "feature_ratio_x": raw_value,
        "gross_scale": gross_scale,
        "estimated_beta": estimated_beta,
        "beta_observations": beta_observations,
        "beta_window_last_return_date": beta_last_date,
        "topix_hedge_weight": hedge_weight,
        "base_sleeve_return": sleeve_return,
        "topix_cash_return": proxy_return,
        "flatten_applied": False,
        "common_valid": True,
        "feature_error": error,
    }


def _not_evaluated_transport_result(
    candidate: OverlayCandidate,
    *,
    reason: str,
    missing: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        **asdict(candidate),
        "physical_potential": _physical_potential_declaration(candidate),
        "status": "NOT_EVALUATED",
        "reason": reason,
        "missing_required_rows": list(missing or []),
        "daily_path": [],
        "trades": [],
        "performance": None,
    }


def canonical_smile_transport_panel_digest(
    observations: Sequence[IndexVolOverlayObservation],
    transport_features: Sequence[Mapping[str, Any]],
    common_validity: Sequence[Mapping[str, Any]],
) -> str:
    """Hash market rows, the four daily transport rows, and gate flags."""

    return _canonical_digest(
        {
            "schema_version": SMILE_TRANSPORT_PANEL_DIGEST_SCHEMA,
            "market_rows": [
                {
                    "date": row.date,
                    "available_at": row.available_at,
                    "base_sleeve_return": row.base_sleeve_return,
                    "topix_cash_close": row.topix_cash_close,
                }
                for row in observations
            ],
            "transport_rows": [dict(row) for row in transport_features],
            "common_validity": [dict(row) for row in common_validity],
        }
    )


def evaluate_index_smile_transport_overlays(
    observations: Sequence[IndexVolOverlayObservation],
    transport_features: Sequence[Mapping[str, Any]],
    *,
    manifest: PreparedIndexVolOverlayPanelManifest,
    authoritative_session_dates: Sequence[str],
    signal_start: str,
    signal_end: str | None = None,
    starting_capital: float = 1_000_000.0,
    core_digest: str | None = None,
) -> dict[str, Any]:
    """Evaluate the frozen four smile-transport overlays without selecting."""

    _validate_smile_transport_observations(observations)
    _validate_manifest(manifest, observations, authoritative_session_dates)
    try:
        start = date.fromisoformat(signal_start).isoformat()
        end = (
            date.fromisoformat(signal_end).isoformat()
            if signal_end
            else observations[-3].date
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("signal_start/signal_end must be canonical ISO dates") from exc
    if start != signal_start or (signal_end is not None and end != signal_end):
        raise ValueError("signal_start/signal_end must be canonical ISO dates")
    if end < start:
        raise ValueError("signal_end must be on or after signal_start")
    capital = _positive(starting_capital)
    if capital is None:
        raise ValueError("starting_capital must be positive and finite")
    if len(SMILE_TRANSPORT_CANDIDATES) != 4:
        raise RuntimeError("smile-transport candidate set must remain exact-four")
    if len(set(SMILE_TRANSPORT_CANDIDATE_IDS)) != 4:
        raise RuntimeError("smile-transport candidate ids must be unique")
    signal_indices = [
        index
        for index, row in enumerate(observations)
        if row.date >= start and row.date <= end
    ]
    if not signal_indices:
        raise ValueError("requested signal range has no observations")
    grouped = _group_transport_features(
        transport_features,
        tuple(row.date for row in observations),
    )
    validity_rows: list[dict[str, Any]] = []
    for signal_index in signal_indices:
        day = observations[signal_index].date
        predecessor = (
            observations[signal_index - 1].date if signal_index > 0 else None
        )
        validity_rows.append(
            _common_validity_for_date(
                day=day,
                predecessor=predecessor,
                day_rows=grouped.get(day, []),
                observations=observations,
                signal_index=signal_index,
            )
        )
    validity_by_date = {row["date"]: row for row in validity_rows}
    valid_dates = [row["date"] for row in validity_rows if row["common_valid"]]
    valid_months = _calendar_months(valid_dates)
    gate_passed = (
        len(valid_dates) >= COMMON_VALID_MIN_SIGNAL_DAYS
        and len(valid_months) >= COMMON_VALID_MIN_CALENDAR_MONTHS
    )
    gate = {
        "passed": gate_passed,
        "required_signal_days": COMMON_VALID_MIN_SIGNAL_DAYS,
        "required_distinct_calendar_months": COMMON_VALID_MIN_CALENDAR_MONTHS,
        "common_valid_signal_days": len(valid_dates),
        "common_valid_calendar_months": len(valid_months),
        "common_valid_month_ids": list(valid_months),
        "common_valid_dates": valid_dates,
        "excluded": [
            {"date": row["date"], "reasons": row["reasons"]}
            for row in validity_rows
            if not row["common_valid"]
        ],
        "common_invalid_policy": "flatten_g0_h0_at_d_plus_1_close_prior",
    }
    outcome_missing: list[dict[str, Any]] = []
    for signal_index in signal_indices:
        day = observations[signal_index].date
        if not validity_by_date[day]["common_valid"]:
            continue
        outcome_issues = _signal_outcome_issues(observations, signal_index)
        if outcome_issues:
            outcome_missing.append({"date": day, "reasons": outcome_issues})
    outcome_complete = not outcome_missing
    outcome_completeness = {
        "passed": outcome_complete,
        "policy": "signal_valid_dates_require_realized_d_plus_2_returns",
        "missing": outcome_missing,
        "reason": (
            None
            if outcome_complete
            else "signal_valid_d_plus_2_outcome_missing"
        ),
    }
    observed_core_digest = core_digest or smile_transport_core_digest()
    if not _canonical_sha256(observed_core_digest):
        raise ValueError("core_digest must be a canonical sha256 digest")
    if not gate_passed:
        results = [
            _not_evaluated_transport_result(
                candidate,
                reason="common_validity_gate_failed",
                missing=gate["excluded"],
            )
            for candidate in SMILE_TRANSPORT_CANDIDATES
        ]
        diagnostic_control = _not_evaluated_smile_control(
            reason="common_validity_gate_failed",
            missing=gate["excluded"],
        )
    elif not outcome_complete:
        results = [
            _not_evaluated_transport_result(
                candidate,
                reason="signal_valid_d_plus_2_outcome_missing",
                missing=outcome_missing,
            )
            for candidate in SMILE_TRANSPORT_CANDIDATES
        ]
        diagnostic_control = _not_evaluated_smile_control(
            reason="signal_valid_d_plus_2_outcome_missing",
            missing=outcome_missing,
        )
    else:
        results = []
        for candidate in SMILE_TRANSPORT_CANDIDATES:
            plans: list[dict[str, Any]] = []
            for signal_index in signal_indices:
                day = observations[signal_index].date
                if validity_by_date[day]["common_valid"]:
                    by_id = {
                        str(row.get("candidate_id") or ""): row
                        for row in grouped[day]
                    }
                    plan = _valid_transport_plan(
                        candidate,
                        observations,
                        signal_index,
                        by_id[candidate.candidate_id],
                    )
                    if plan is None:
                        raise RuntimeError(
                            "common-valid date lost a required transport plan"
                        )
                    plans.append(plan)
                else:
                    plans.append(_flatten_plan(observations, signal_index))
            curve, trades, performance = _evaluate_plans(
                plans,
                starting_capital=capital,
            )
            results.append(
                {
                    **asdict(candidate),
                    "physical_potential": _physical_potential_declaration(
                        candidate
                    ),
                    "status": "EVALUATED",
                    "reason": None,
                    "missing_required_rows": [],
                    "daily_path": curve,
                    "trades": trades,
                    "performance": performance,
                }
            )
        diagnostic_control = _smile_transport_control_result(
            observations,
            signal_indices,
            validity_by_date,
            starting_capital=capital,
        )
    evaluated_count = sum(result["status"] == "EVALUATED" for result in results)
    return {
        "schema_version": PERSONAL_INDEX_SMILE_TRANSPORT_SCHEMA,
        "status": "EVALUATED" if evaluated_count == len(results) else "NOT_EVALUATED",
        "lifecycle": {
            "stage": LIFECYCLE_STAGE,
            "role": "DIAGNOSTIC_RESEARCH_ONLY",
            "paper_execution": False,
            "automatic_promotion": False,
        },
        "prepared_panel_provenance": {
            "schema_version": PREPARED_SMILE_TRANSPORT_PANEL_MANIFEST_SCHEMA,
            **asdict(manifest),
            "transport_feature_digest": canonical_smile_transport_panel_digest(
                observations,
                transport_features,
                validity_rows,
            ),
            "core_version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
            "core_digest": observed_core_digest,
            "core_module": SMILE_TRANSPORT_CORE_MODULE,
        },
        "base_sleeve": {
            "strategy_id": BASE_SLEEVE_ID,
            "universe_id": BASE_UNIVERSE_ID,
            "selection_timing": "PREDECLARED_BEFORE_OVERLAY_RESULTS",
            "single_stock_option_iv": "EXCLUDED_FROM_INPUT_SURFACE",
            "stock_price_realized_volatility": "ALLOWED_IN_FROZEN_BASE_SLEEVE",
            "return_semantics": BASE_RETURN_SEMANTICS,
            "nav_semantics": BASE_NAV_SEMANTICS,
            "source_slice_wrapper_cost_semantics": (
                SOURCE_SLICE_WRAPPER_COST_SEMANTICS
            ),
        },
        "timing": {
            "signal": "D_CLOSE",
            "feature_available_no_earlier_than": "D_23_59_59_JST",
            "rebalance": "D_PLUS_1_CLOSE",
            "first_pnl": "D_PLUS_1_CLOSE_TO_D_PLUS_2_CLOSE",
            "terminal_close": True,
            "authoritative_calendar_alignment": "EXACT_ORDERED_DATE_MATCH",
            "official_predecessor_rule": (
                "D_MINUS_1_IS_IMMEDIATELY_PRECEDING_OFFICIAL_SESSION"
            ),
            "prepared_row_availability": (
                "NO_EARLIER_THAN_D_23_59_59_JST_AND_STRICTLY_BEFORE_"
                "D_PLUS_1_CONSERVATIVE_15_00_JST_CUTOFF"
            ),
            "conservative_execution_cutoff_jst": CONSERVATIVE_EXECUTION_CUTOFF_JST,
            "no_forward_fill": True,
            "no_expiry_rank_substitution": True,
            "no_extrapolation": True,
            "no_mutable_current_db": True,
        },
        "cost_model": {
            "one_way_basis_points": 10.0,
            "applies_to": ["base_sleeve_turnover", "topix_proxy_turnover"],
            "reported_cost_turnover_fill_scope": "OVERLAY_INCREMENTAL_ONLY",
            "not_total_strategy_cost_metrics": True,
            "base_nav_source_slice_excludes_wrapper_entry_liquidation": True,
        },
        "topix_proxy": {
            "dataset": TOPIX_PROXY_DATASET,
            "label": "TOPIX cash index close-to-close return",
            "role": "NON_EXECUTABLE_HEDGE_APPROXIMATION",
            "etf_fill_claim": False,
            "warning": (
                "This is not an ETF fill or tradable execution claim; later cloud "
                "work must bind an explicit executable proxy before paper execution."
            ),
        },
        "beta_policy": {
            "lookback_source_sessions": BETA_LOOKBACK_RETURNS,
            "minimum_paired_returns": BETA_MIN_RETURNS,
            "current_signal_day_pair_required": True,
            "hedge_formula": "h=clip(-g*beta,-1.5,1.5)",
        },
        "exposure_formulas": {
            "downside_q": (
                "actual_downside_smile_term_ratio/"
                "predicted_downside_smile_term_ratio-1"
            ),
            "downside_g": "clip(1/(1+q),0.5,1.0)",
            "potential_minimum_M": (
                "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)"
            ),
            "potential_minimum_g": "clip(1/(1+M/0.10),0.5,1.0)",
            "hedge_h": "clip(-g*beta_D,-1.5,1.5)",
        },
        "physical_potential": {
            "metaphor_only": True,
            "causal_claim": False,
        },
        "candidate_policy": {
            "declared_count": len(SMILE_TRANSPORT_CANDIDATES),
            "evaluated_count": evaluated_count,
            "post_result_selection": "NOT_PERFORMED",
            "selection": "NOT_PERFORMED",
            "ranking": None,
            "diagnostic_control_in_declared_count": False,
            "candidate_order": list(SMILE_TRANSPORT_CANDIDATE_IDS),
            "sticky_models": [STICKY_STRIKE, STICKY_MONEYNESS],
            "adaptive_model_switch": False,
        },
        "common_validity_gate": gate,
        "outcome_completeness": outcome_completeness,
        "diagnostic_control": diagnostic_control,
        "candidates": results,
        "under_px_policy": {
            "role": "DISCLOSED_COORDINATE_PROXY",
            "trusted_forward": False,
            "forward_relative_fields": "null_with_reason",
            "forward_relative_reason": "trusted_forward_unavailable",
        },
    }


# --- Causal AM/PM overlay and smile-transport families (separately versioned) ---

PERSONAL_INDEX_VOL_OVERLAY_AM_PM_SCHEMA: Final = (
    "personal-index-vol-overlay-am-pm/v1"
)
PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_SCHEMA: Final = (
    "personal-index-smile-transport-am-pm/v1"
)
PREPARED_AM_PM_PANEL_MANIFEST_SCHEMA: Final = (
    "prepared-index-vol-overlay-am-pm-panel/v1"
)
PREPARED_AM_PM_SMILE_TRANSPORT_PANEL_MANIFEST_SCHEMA: Final = (
    "prepared-index-smile-transport-am-pm-panel/v1"
)
AM_PM_PANEL_OBSERVATION_DIGEST_SCHEMA: Final = (
    "index-vol-overlay-am-pm-observations/v1"
)
AM_PM_SMILE_TRANSPORT_PANEL_DIGEST_SCHEMA: Final = (
    "index-smile-transport-am-pm-observations/v1"
)
AM_PM_TEMPORAL_CONTRACT_DIGEST_SCHEMA: Final = (
    "index-vol-overlay-am-pm-temporal-contract/v1"
)
AM_PM_BASE_COHORT_ID: Final = "sector-relative-ls-am-pm-v1"
AM_PM_BASE_SLEEVE_ID: Final = "personal_sector_balanced_four_factor_v1_ls_am_pm"
AM_PM_BASE_SLEEVE_SCHEMA: Final = "personal-base-sleeve-source-am-pm/v1"
AM_PM_EXECUTION_MODE: Final = "am_pm"
AM_PM_NON_PRICE_CUTOFF_JST: Final = "11:30:00+09:00"
AM_PM_EQUITY_USABLE_BY_JST: Final = "12:30:00+09:00"
AM_PM_FILL_CUTOFF_JST: Final = "15:00:00+09:00"
TOPIX_ETF_CODE: Final = "13060"
N225_ETF_CODE: Final = "13210"
AM_PM_CONTROL_ID: Final = "base_g1_h0_control_am_pm_v1"

AM_PM_TEMPORAL_CONTRACT: Final[dict[str, Any]] = {
    "non_price_cutoff_jst": AM_PM_NON_PRICE_CUTOFF_JST,
    "equity_am_usable_by_jst": AM_PM_EQUITY_USABLE_BY_JST,
    "order_sizing": "d_am_price",
    "signal_state_equity": "d_madjc",
    "fill_timing": "d_pm_aadjc",
    "first_pnl_interval": "d_pm_to_d_plus_1_pm",
    "option_signal_as_of": "through_d_minus_1",
    "smile_transport_pair": "d_minus_2_to_d_minus_1",
    "d_option_surface_in_d_signal": False,
    "d_full_close_in_d_signal": False,
    "d_aadjc_in_d_signal": False,
    "no_forward_fill": True,
    "no_expiry_rank_substitution": True,
    "no_extrapolation": True,
    "no_full_close_fallback": True,
    "no_recovery_promotion": True,
    "no_interpolation_beyond_fit_band": True,
    "single_stock_iv": False,
}

_AM_PM_EQUITY_USABLE_BY_TIME = time(hour=12, minute=30, second=0, tzinfo=_JST)
_AM_PM_FILL_CUTOFF_TIME = time(hour=15, minute=0, second=0, tzinfo=_JST)


def _am_pm_candidate(candidate: OverlayCandidate) -> OverlayCandidate:
    if candidate.candidate_id.endswith("_am_pm_v1"):
        return candidate
    if not candidate.candidate_id.endswith("_v1"):
        raise RuntimeError("frozen candidate id is not version-suffixed")
    return OverlayCandidate(
        candidate_id=candidate.candidate_id[:-3] + "_am_pm_v1",
        feature_kind=candidate.feature_kind,
        mechanics=candidate.mechanics,
        thesis=candidate.thesis,
        return_source=candidate.return_source,
    )


OVERLAY_AM_PM_CANDIDATES: Final[tuple[OverlayCandidate, ...]] = tuple(
    _am_pm_candidate(item) for item in OVERLAY_CANDIDATES
)
OVERLAY_AM_PM_CANDIDATE_IDS: Final[tuple[str, ...]] = tuple(
    item.candidate_id for item in OVERLAY_AM_PM_CANDIDATES
)
SMILE_TRANSPORT_AM_PM_CANDIDATES: Final[tuple[OverlayCandidate, ...]] = tuple(
    _am_pm_candidate(item) for item in SMILE_TRANSPORT_CANDIDATES
)
SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS: Final[tuple[str, ...]] = tuple(
    item.candidate_id for item in SMILE_TRANSPORT_AM_PM_CANDIDATES
)
_AM_PM_SMILE_TRANSPORT_IDENTITY: Final[dict[str, tuple[str, str]]] = {
    candidate_id.replace("_v1", "_am_pm_v1"): identity
    for candidate_id, identity in _SMILE_TRANSPORT_IDENTITY.items()
}


def am_pm_temporal_contract_digest() -> str:
    return _canonical_digest(
        {
            "schema_version": AM_PM_TEMPORAL_CONTRACT_DIGEST_SCHEMA,
            **AM_PM_TEMPORAL_CONTRACT,
        }
    )


def am_pm_proxy_mapping() -> dict[str, Any]:
    return {
        "executable_hedge": {
            "code": TOPIX_ETF_CODE,
            "label": "TOPIX ETF 13060 morning/afternoon adjustment close",
            "role": "EXECUTABLE_HEDGE_PROXY",
            "etf_fill_claim": True,
            "tracking_basis_risk": True,
            "requires_exact_m_a_observations": True,
        },
        "n225_etf_if_required": {
            "code": N225_ETF_CODE,
            "role": "NOT_USED_IN_THIS_FAMILY",
            "etf_fill_claim": False,
        },
        "cash_index": {
            "topix_dataset": TOPIX_PROXY_DATASET,
            "role": "DIAGNOSTIC_BETA_CONTEXT_ONLY",
            "executable_fill_claim": False,
        },
    }


def am_pm_proxy_mapping_digest() -> str:
    return _canonical_digest(
        {
            "schema_version": "index-vol-overlay-am-pm-proxy-mapping/v1",
            **am_pm_proxy_mapping(),
        }
    )


def _am_pm_repo_bindings() -> tuple[str | None, str | None]:
    try:
        cohort = get_research_cohort(AM_PM_BASE_COHORT_ID)
    except KeyError:
        return None, None
    spec = next(
        (
            item
            for item in cohort.strategy_specs
            if item.strategy_id in {AM_PM_BASE_SLEEVE_ID, BASE_SLEEVE_ID}
        ),
        None,
    )
    spec_digest = strategy_spec_digest(spec) if spec is not None else None
    return spec_digest, str(cohort.to_dict()["cohort_digest"])


@dataclass(frozen=True, slots=True)
class IndexVolOverlayAmPmObservation:
    """One official session of causal AM/PM overlay evidence.

    Signal/sizing/beta may use ``base_sleeve_am_nav`` and ETF ``MAdjC``.
    Fill and first PnL use afternoon ``AAdjC`` / PM NAV and must not enter
    the D signal.  Option/SVI fields are the observations *on this date* and
    are consumed only by a later session's signal.
    """

    date: str
    available_at: str
    base_sleeve_am_nav: float | None
    base_sleeve_pm_nav: float | None
    topix_etf_13060_madjc: float | None
    topix_etf_13060_aadjc: float | None
    topix_cash_close: float | None
    n225_cash_close: float | None
    n225_base_vol: float | None
    n225_atm_iv: float | None
    topix_realized_vol_20: float | None
    n225_front_atm_iv: float | None
    n225_next_atm_iv: float | None
    n225_front_downside_wing_iv: float | None
    n225_next_downside_wing_iv: float | None
    svi_equivalent_atm_term_ratio: float | None = None
    svi_equivalent_downside_smile_term_ratio: float | None = None


def canonical_prepared_am_pm_panel_digest(
    observations: Sequence[IndexVolOverlayAmPmObservation],
) -> str:
    return _canonical_digest(
        {
            "schema_version": AM_PM_PANEL_OBSERVATION_DIGEST_SCHEMA,
            "rows": [asdict(row) for row in observations],
        }
    )


@dataclass(frozen=True, slots=True)
class PreparedIndexVolOverlayAmPmPanelManifest:
    """Typed AM/PM provenance; rejects the next-close overlay panel."""

    strategy_spec_digest: str
    cohort_digest: str
    snapshot_digest: str
    base_report_digest: str
    trading_calendar_digest: str
    prepared_panel_digest: str
    temporal_contract_digest: str
    proxy_mapping_digest: str
    session_date_start: str
    session_date_end: str
    session_count: int
    base_strategy_id: str = AM_PM_BASE_SLEEVE_ID
    base_universe_id: str = BASE_UNIVERSE_ID
    base_cohort_id: str = AM_PM_BASE_COHORT_ID
    return_semantics: str = BASE_RETURN_SEMANTICS
    base_nav_semantics: str = BASE_NAV_SEMANTICS
    source_slice_wrapper_cost_semantics: str = (
        SOURCE_SLICE_WRAPPER_COST_SEMANTICS
    )
    lifecycle: str = LIFECYCLE_STAGE
    execution_mode: str = AM_PM_EXECUTION_MODE

    def __post_init__(self) -> None:
        if self.base_cohort_id != AM_PM_BASE_COHORT_ID:
            raise ValueError("AM/PM prepared panel must bind sector-relative-ls-am-pm-v1")
        if self.base_cohort_id == BASE_COHORT_ID:
            raise ValueError("old sector-relative-ls-v1 base is invalid for AM/PM")
        if self.base_strategy_id == BASE_SLEEVE_ID:
            raise ValueError("old next-close base sleeve is invalid for AM/PM")
        if self.base_strategy_id != AM_PM_BASE_SLEEVE_ID:
            raise ValueError("prepared panel must bind the AM/PM frozen base strategy")
        if self.base_universe_id != BASE_UNIVERSE_ID:
            raise ValueError("prepared panel must bind the exact topix_all universe")
        if self.execution_mode != AM_PM_EXECUTION_MODE:
            raise ValueError("AM/PM prepared panel must use am_pm execution")
        if self.return_semantics != BASE_RETURN_SEMANTICS:
            raise ValueError(
                "base sleeve returns must be net of stock costs and financing"
            )
        if self.base_nav_semantics != BASE_NAV_SEMANTICS:
            raise ValueError("prepared panel base NAV semantics are invalid")
        if (
            self.source_slice_wrapper_cost_semantics
            != SOURCE_SLICE_WRAPPER_COST_SEMANTICS
        ):
            raise ValueError("prepared panel wrapper-cost semantics are invalid")
        if self.lifecycle != LIFECYCLE_STAGE:
            raise ValueError("prepared panel must remain DRAFT_DIAGNOSTIC")
        for name in (
            "strategy_spec_digest",
            "cohort_digest",
            "snapshot_digest",
            "base_report_digest",
            "trading_calendar_digest",
            "prepared_panel_digest",
            "temporal_contract_digest",
            "proxy_mapping_digest",
        ):
            if not _canonical_sha256(getattr(self, name)):
                raise ValueError(f"{name} must be a canonical sha256 digest")
        if self.strategy_spec_digest == EXPECTED_BASE_STRATEGY_SPEC_DIGEST:
            raise ValueError("old next-close strategy_spec_digest is invalid for AM/PM")
        if self.cohort_digest == EXPECTED_BASE_COHORT_DIGEST:
            raise ValueError("old sector-relative-ls-v1 cohort_digest is invalid for AM/PM")
        repo_spec, repo_cohort = _am_pm_repo_bindings()
        if repo_spec is not None and self.strategy_spec_digest != repo_spec:
            raise ValueError("strategy_spec_digest does not match AM/PM repo definition")
        if repo_cohort is not None and self.cohort_digest != repo_cohort:
            raise ValueError("cohort_digest does not match AM/PM repo definition")
        if self.temporal_contract_digest != am_pm_temporal_contract_digest():
            raise ValueError("temporal_contract_digest does not match frozen AM/PM contract")
        if self.proxy_mapping_digest != am_pm_proxy_mapping_digest():
            raise ValueError("proxy_mapping_digest does not match frozen AM/PM proxy map")
        try:
            start = date.fromisoformat(self.session_date_start).isoformat()
            end = date.fromisoformat(self.session_date_end).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "manifest session dates must be canonical ISO dates"
            ) from exc
        if start != self.session_date_start or end != self.session_date_end:
            raise ValueError("manifest session dates must be canonical ISO dates")
        if end < start:
            raise ValueError("manifest session_date_end precedes session_date_start")
        if (
            not isinstance(self.session_count, int)
            or isinstance(self.session_count, bool)
            or self.session_count < 3
        ):
            raise ValueError("manifest session_count must be at least three")


def _am_pm_availability_timestamp(row: IndexVolOverlayAmPmObservation) -> datetime:
    try:
        parsed = datetime.fromisoformat(row.available_at)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"observation available_at must be canonical ISO: {row.available_at!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observation available_at must include a UTC offset")
    if (
        parsed.microsecond != 0
        or parsed.isoformat(timespec="seconds") != row.available_at
    ):
        raise ValueError("observation available_at must use canonical whole seconds")
    usable_by = datetime.combine(
        date.fromisoformat(row.date),
        _AM_PM_EQUITY_USABLE_BY_TIME,
    )
    fill_cutoff = datetime.combine(
        date.fromisoformat(row.date),
        _AM_PM_FILL_CUTOFF_TIME,
    )
    if parsed > usable_by:
        raise ValueError(
            "AM/PM signal row must be available no later than D 12:30 JST"
        )
    if parsed >= fill_cutoff:
        raise ValueError(
            "AM/PM signal row must be available strictly before the D PM fill"
        )
    return parsed


def _validate_am_pm_observations(
    observations: Sequence[IndexVolOverlayAmPmObservation],
) -> None:
    if len(observations) < 3:
        raise ValueError("at least three ordered sessions are required")
    previous: str | None = None
    for row in observations:
        if not isinstance(row, IndexVolOverlayAmPmObservation):
            raise TypeError(
                "AM/PM observations must be IndexVolOverlayAmPmObservation values"
            )
        try:
            parsed = date.fromisoformat(row.date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid observation date: {row.date!r}") from exc
        if row.date != parsed.isoformat():
            raise ValueError(f"observation date must be canonical ISO: {row.date!r}")
        if previous is not None and row.date <= previous:
            raise ValueError("observation dates must be unique and strictly increasing")
        _am_pm_availability_timestamp(row)
        previous = row.date


def _validate_am_pm_manifest(
    manifest: PreparedIndexVolOverlayAmPmPanelManifest,
    observations: Sequence[IndexVolOverlayAmPmObservation],
    authoritative_session_dates: Sequence[str],
) -> None:
    if not isinstance(manifest, PreparedIndexVolOverlayAmPmPanelManifest):
        raise TypeError(
            "AM/PM job must not accept an old next-close prepared panel"
        )
    if isinstance(manifest, PreparedIndexVolOverlayPanelManifest):
        raise TypeError(
            "AM/PM job must not accept an old next-close prepared panel"
        )
    authoritative = _canonical_authoritative_session_dates(
        authoritative_session_dates
    )
    observed_dates = tuple(row.date for row in observations)
    if observed_dates != authoritative:
        raise ValueError(
            "observation dates must exactly match authoritative session dates"
        )
    if manifest.session_count != len(authoritative):
        raise ValueError("prepared panel manifest session_count mismatch")
    if manifest.session_date_start != authoritative[0]:
        raise ValueError("prepared panel manifest session_date_start mismatch")
    if manifest.session_date_end != authoritative[-1]:
        raise ValueError("prepared panel manifest session_date_end mismatch")
    try:
        observed_panel_digest = canonical_prepared_am_pm_panel_digest(observations)
    except (TypeError, ValueError) as exc:
        raise ValueError("prepared panel rows are not canonically hashable") from exc
    if manifest.prepared_panel_digest != observed_panel_digest:
        raise ValueError("prepared_panel_digest does not match observation rows")
    observed_calendar_digest = canonical_trading_calendar_digest(authoritative)
    if manifest.trading_calendar_digest != observed_calendar_digest:
        raise ValueError("trading_calendar_digest does not match ordered session dates")


def build_prepared_am_pm_panel_manifest(
    observations: Sequence[IndexVolOverlayAmPmObservation],
    *,
    authoritative_session_dates: Sequence[str],
    snapshot_digest: str,
    base_report_digest: str,
    strategy_spec_digest: str,
    cohort_digest: str,
) -> PreparedIndexVolOverlayAmPmPanelManifest:
    """Build the AM/PM manifest; never bind the next-close overlay panel."""

    _validate_am_pm_observations(observations)
    authoritative = _canonical_authoritative_session_dates(
        authoritative_session_dates
    )
    if tuple(row.date for row in observations) != authoritative:
        raise ValueError(
            "observation dates must exactly match authoritative session dates"
        )
    return PreparedIndexVolOverlayAmPmPanelManifest(
        strategy_spec_digest=strategy_spec_digest,
        cohort_digest=cohort_digest,
        snapshot_digest=snapshot_digest,
        base_report_digest=base_report_digest,
        trading_calendar_digest=canonical_trading_calendar_digest(authoritative),
        prepared_panel_digest=canonical_prepared_am_pm_panel_digest(observations),
        temporal_contract_digest=am_pm_temporal_contract_digest(),
        proxy_mapping_digest=am_pm_proxy_mapping_digest(),
        session_date_start=authoritative[0],
        session_date_end=authoritative[-1],
        session_count=len(authoritative),
    )


def _nav_return(
    before: Any,
    after: Any,
) -> float | None:
    start = _positive(before)
    end = _positive(after)
    if start is None or end is None:
        return None
    return _finite(end / start - 1.0)


def _am_sleeve_return(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    start_index: int,
    end_index: int,
) -> float | None:
    return _nav_return(
        rows[start_index].base_sleeve_am_nav,
        rows[end_index].base_sleeve_am_nav,
    )


def _pm_sleeve_return(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    start_index: int,
    end_index: int,
) -> float | None:
    return _nav_return(
        rows[start_index].base_sleeve_pm_nav,
        rows[end_index].base_sleeve_pm_nav,
    )


def _etf_am_return(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    start_index: int,
    end_index: int,
) -> float | None:
    return _nav_return(
        rows[start_index].topix_etf_13060_madjc,
        rows[end_index].topix_etf_13060_madjc,
    )


def _etf_pm_return(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    start_index: int,
    end_index: int,
) -> float | None:
    return _nav_return(
        rows[start_index].topix_etf_13060_aadjc,
        rows[end_index].topix_etf_13060_aadjc,
    )


def _am_pm_estimate_beta(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
) -> tuple[tuple[float, int, str] | None, str | None]:
    if signal_index < 1:
        return None, "beta_current_signal_day_pair_unavailable"
    current_sleeve_return = _am_sleeve_return(rows, signal_index - 1, signal_index)
    current_proxy_return = _etf_am_return(rows, signal_index - 1, signal_index)
    if current_sleeve_return is None or current_proxy_return is None:
        return None, "beta_current_signal_day_pair_unavailable"
    paired: list[tuple[str, float, float]] = []
    first_source_return = max(1, signal_index - BETA_LOOKBACK_RETURNS + 1)
    for index in range(first_source_return, signal_index + 1):
        sleeve_return = _am_sleeve_return(rows, index - 1, index)
        proxy_return = _etf_am_return(rows, index - 1, index)
        if sleeve_return is None or proxy_return is None:
            continue
        paired.append((rows[index].date, sleeve_return, proxy_return))
    if len(paired) < BETA_MIN_RETURNS:
        return None, "beta_min_63_pairs_unavailable_in_last_126_source_sessions"
    if paired[-1][0] != rows[signal_index].date:
        return None, "beta_current_signal_day_pair_unavailable"
    sleeve_values = [item[1] for item in paired]
    proxy_values = [item[2] for item in paired]
    sleeve_mean = mean(sleeve_values)
    proxy_mean = mean(proxy_values)
    covariance = sum(
        (sleeve - sleeve_mean) * (proxy - proxy_mean)
        for sleeve, proxy in zip(sleeve_values, proxy_values, strict=True)
    )
    variance = sum((proxy - proxy_mean) ** 2 for proxy in proxy_values)
    if variance <= 1.0e-18:
        return None, "beta_proxy_variance_unavailable"
    beta = _finite(covariance / variance)
    if beta is None:
        return None, "beta_non_finite"
    return (beta, len(paired), paired[-1][0]), None


def _am_pm_structural_issues(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
    *,
    require_pnl: bool,
) -> list[str]:
    issues: list[str] = []
    if signal_index < 1:
        issues.append("exact_prior_official_session_missing")
        return issues
    signal = rows[signal_index]
    prior = rows[signal_index - 1]
    if _positive(signal.base_sleeve_am_nav) is None:
        issues.append("d_morning_field_missing")
    if _positive(signal.base_sleeve_pm_nav) is None:
        issues.append("d_afternoon_field_missing")
    if _positive(signal.topix_etf_13060_madjc) is None:
        issues.append("d_etf_13060_madjc_missing")
    if _positive(signal.topix_etf_13060_aadjc) is None:
        issues.append("d_etf_13060_aadjc_missing")
    if _positive(prior.base_sleeve_am_nav) is None:
        issues.append("prior_session_morning_field_missing")
    if _positive(prior.topix_etf_13060_madjc) is None:
        issues.append("prior_session_etf_13060_madjc_missing")
    if require_pnl:
        if signal_index + 1 >= len(rows):
            issues.append("d_plus_1_session_unavailable")
        else:
            nxt = rows[signal_index + 1]
            if _positive(nxt.base_sleeve_pm_nav) is None:
                issues.append("d_plus_1_afternoon_field_missing")
            if _positive(nxt.topix_etf_13060_aadjc) is None:
                issues.append("d_plus_1_etf_13060_aadjc_missing")
    return issues


def _am_pm_option_feature_value(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
) -> tuple[float | None, str | None]:
    option_index = signal_index - 1
    if option_index < 0:
        return None, "option_observations_through_d_minus_1_unavailable"
    # Reconstruct a next-close-shaped row so the frozen formulas stay identical
    # while reading only the D-1 option/SVI observation.
    class _OptionView:
        __slots__ = (
            "n225_base_vol",
            "n225_atm_iv",
            "topix_realized_vol_20",
            "n225_front_atm_iv",
            "n225_next_atm_iv",
            "n225_front_downside_wing_iv",
            "n225_next_downside_wing_iv",
        )

        def __init__(self, source: IndexVolOverlayAmPmObservation) -> None:
            self.n225_base_vol = source.n225_base_vol
            self.n225_atm_iv = source.n225_atm_iv
            self.topix_realized_vol_20 = source.topix_realized_vol_20
            self.n225_front_atm_iv = source.n225_front_atm_iv
            self.n225_next_atm_iv = source.n225_next_atm_iv
            self.n225_front_downside_wing_iv = source.n225_front_downside_wing_iv
            self.n225_next_downside_wing_iv = source.n225_next_downside_wing_iv

    viewed = [_OptionView(row) for row in rows]
    return _feature_value(candidate, viewed, option_index)  # type: ignore[arg-type]


def _am_pm_signal_range(
    observations: Sequence[IndexVolOverlayAmPmObservation],
    signal_start: str,
    signal_end: str | None,
) -> tuple[str, str, list[int]]:
    try:
        start = date.fromisoformat(signal_start).isoformat()
        end = (
            date.fromisoformat(signal_end).isoformat()
            if signal_end
            else observations[-2].date
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("signal_start/signal_end must be canonical ISO dates") from exc
    if start != signal_start or (signal_end is not None and end != signal_end):
        raise ValueError("signal_start/signal_end must be canonical ISO dates")
    if end < start:
        raise ValueError("signal_end must be on or after signal_start")
    signal_indices = [
        index
        for index, row in enumerate(observations)
        if row.date >= start and row.date <= end
    ]
    if not signal_indices:
        raise ValueError("requested signal range has no observations")
    return start, end, signal_indices


def _am_pm_not_evaluated_candidate(
    candidate: OverlayCandidate,
    *,
    reason: str,
    missing: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        **asdict(candidate),
        "status": "NOT_EVALUATED",
        "reason": reason,
        "missing_required_rows": list(missing),
        "daily_path": [],
        "trades": [],
        "performance": None,
    }
    if candidate.candidate_id in SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS:
        payload["physical_potential"] = _physical_potential_declaration(candidate)
    return payload


def _am_pm_not_evaluated_control(
    *,
    reason: str,
    missing: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "control_id": AM_PM_CONTROL_ID,
        "role": "NAV_WRAPPER_CONTROL_WITH_10BP_ENTRY_EXIT",
        "ranking_role": "DIAGNOSTIC_CONTROL_NOT_RANKED",
        "status": "NOT_EVALUATED",
        "reason": reason,
        "missing_required_rows": list(missing),
        "daily_path": [],
        "trades": [],
        "performance": None,
    }


def _am_pm_candidate_plans(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_indices: Sequence[int],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    plans: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for signal_index in signal_indices:
        signal_row = rows[signal_index]
        structural = _am_pm_structural_issues(rows, signal_index, require_pnl=True)
        if structural:
            missing.append(_missing(signal_row.date, structural[0]))
            continue
        x_value, feature_error = _am_pm_option_feature_value(
            candidate, rows, signal_index
        )
        if x_value is None:
            missing.append(
                _missing(signal_row.date, feature_error or "feature_value_unavailable")
            )
            continue
        beta, beta_error = _am_pm_estimate_beta(rows, signal_index)
        if beta is None:
            missing.append(
                _missing(signal_row.date, beta_error or "beta_estimate_unavailable")
            )
            continue
        pnl_index = signal_index + 1
        sleeve_return = _pm_sleeve_return(rows, signal_index, pnl_index)
        proxy_return = _etf_pm_return(rows, signal_index, pnl_index)
        if sleeve_return is None:
            missing.append(_missing(rows[pnl_index].date, "base_sleeve_pm_return_missing"))
            continue
        if proxy_return is None:
            missing.append(_missing(rows[pnl_index].date, "topix_etf_13060_pm_return_missing"))
            continue
        gross_scale = _clip(1.0 / x_value, 0.5, 1.0)
        estimated_beta, beta_observations, beta_last_date = beta
        hedge_weight = _clip(
            -gross_scale * estimated_beta,
            -MAX_ABS_TOPIX_HEDGE,
            MAX_ABS_TOPIX_HEDGE,
        )
        plans.append(
            {
                "signal_date": signal_row.date,
                "rebalance_date": signal_row.date,
                "pnl_date": rows[pnl_index].date,
                "feature_ratio_x": x_value,
                "gross_scale": gross_scale,
                "estimated_beta": estimated_beta,
                "beta_observations": beta_observations,
                "beta_window_last_return_date": beta_last_date,
                "topix_hedge_weight": hedge_weight,
                "base_sleeve_return": sleeve_return,
                "topix_cash_return": proxy_return,
            }
        )
    return plans, missing


def _am_pm_overlay_candidate_result(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_indices: Sequence[int],
    *,
    starting_capital: float,
) -> dict[str, Any]:
    plans, missing = _am_pm_candidate_plans(candidate, rows, signal_indices)
    if missing:
        return _am_pm_not_evaluated_candidate(
            candidate,
            reason="missing_required_row_no_forward_fill",
            missing=missing,
        )
    if not plans:
        return _am_pm_not_evaluated_candidate(
            candidate,
            reason="no_signal_sessions_in_requested_range",
            missing=[],
        )
    curve, trades, performance = _evaluate_plans(
        plans,
        starting_capital=starting_capital,
    )
    return {
        **asdict(candidate),
        "status": "EVALUATED",
        "reason": None,
        "missing_required_rows": [],
        "daily_path": curve,
        "trades": trades,
        "performance": performance,
    }


def _am_pm_overlay_control_result(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_indices: Sequence[int],
    *,
    starting_capital: float,
) -> dict[str, Any]:
    plans: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for signal_index in signal_indices:
        signal_row = rows[signal_index]
        structural = _am_pm_structural_issues(rows, signal_index, require_pnl=True)
        if structural:
            missing.append(_missing(signal_row.date, structural[0]))
            continue
        pnl_index = signal_index + 1
        sleeve_return = _pm_sleeve_return(rows, signal_index, pnl_index)
        if sleeve_return is None:
            missing.append(_missing(rows[pnl_index].date, "base_sleeve_pm_return_missing"))
            continue
        plans.append(
            {
                "signal_date": signal_row.date,
                "rebalance_date": signal_row.date,
                "pnl_date": rows[pnl_index].date,
                "feature_ratio_x": 1.0,
                "gross_scale": 1.0,
                "estimated_beta": None,
                "beta_observations": None,
                "beta_window_last_return_date": None,
                "topix_hedge_weight": 0.0,
                "base_sleeve_return": sleeve_return,
                "topix_cash_return": 0.0,
            }
        )
    declaration = {
        "control_id": AM_PM_CONTROL_ID,
        "role": "NAV_WRAPPER_CONTROL_WITH_10BP_ENTRY_EXIT",
        "ranking_role": "DIAGNOSTIC_CONTROL_NOT_RANKED",
        "mechanics": (
            "continuous pre-existing AM/PM base NAV with g=1 and h=0, plus only "
            "the wrapper's 10bp entry and liquidation accounting"
        ),
        "source_slice_wrapper_cost_semantics": SOURCE_SLICE_WRAPPER_COST_SEMANTICS,
    }
    if missing or not plans:
        return {
            **declaration,
            **_am_pm_not_evaluated_control(
                reason=(
                    "missing_required_row_no_forward_fill"
                    if missing
                    else "no_signal_sessions_in_requested_range"
                ),
                missing=missing,
            ),
        }
    curve, trades, performance = _evaluate_plans(
        plans,
        starting_capital=starting_capital,
        continuous_nav_wrapper=True,
    )
    return {
        **declaration,
        "status": "EVALUATED",
        "reason": None,
        "missing_required_rows": [],
        "daily_path": curve,
        "trades": trades,
        "performance": performance,
    }


def _am_pm_report_framing(
    *,
    schema_version: str,
    manifest: PreparedIndexVolOverlayAmPmPanelManifest,
    extra_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provenance = {
        "schema_version": (
            PREPARED_AM_PM_SMILE_TRANSPORT_PANEL_MANIFEST_SCHEMA
            if schema_version == PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_SCHEMA
            else PREPARED_AM_PM_PANEL_MANIFEST_SCHEMA
        ),
        **asdict(manifest),
        "execution_contract_digest": am_pm_temporal_contract_digest(),
        "proxy_mapping": am_pm_proxy_mapping(),
    }
    if extra_provenance:
        provenance.update(dict(extra_provenance))
    return {
        "schema_version": schema_version,
        "lifecycle": {
            "stage": LIFECYCLE_STAGE,
            "role": "DIAGNOSTIC_RESEARCH_ONLY",
            "paper_execution": False,
            "automatic_promotion": False,
        },
        "prepared_panel_provenance": provenance,
        "base_sleeve": {
            "strategy_id": AM_PM_BASE_SLEEVE_ID,
            "universe_id": BASE_UNIVERSE_ID,
            "cohort_id": AM_PM_BASE_COHORT_ID,
            "selection_timing": "PREDECLARED_BEFORE_OVERLAY_RESULTS",
            "single_stock_option_iv": "EXCLUDED_FROM_INPUT_SURFACE",
            "stock_price_realized_volatility": "ALLOWED_IN_FROZEN_BASE_SLEEVE",
            "return_semantics": BASE_RETURN_SEMANTICS,
            "nav_semantics": BASE_NAV_SEMANTICS,
            "source_slice_wrapper_cost_semantics": (
                SOURCE_SLICE_WRAPPER_COST_SEMANTICS
            ),
            "execution_mode": AM_PM_EXECUTION_MODE,
        },
        "timing": {
            "signal": "D_AM",
            "non_price_cutoff_jst": AM_PM_NON_PRICE_CUTOFF_JST,
            "equity_am_usable_by_jst": AM_PM_EQUITY_USABLE_BY_JST,
            "order_sizing": "D_AM_PRICE",
            "rebalance": "D_PM_AADJC",
            "first_pnl": "D_PM_TO_D_PLUS_1_PM",
            "option_observations": "THROUGH_D_MINUS_1",
            "smile_transport_pair": "D_MINUS_2_TO_D_MINUS_1",
            "terminal_close": True,
            "authoritative_calendar_alignment": "EXACT_ORDERED_DATE_MATCH",
            "prepared_row_availability": (
                "NO_LATER_THAN_D_12_30_JST_AND_STRICTLY_BEFORE_D_PM_FILL"
            ),
            "conservative_execution_cutoff_jst": AM_PM_FILL_CUTOFF_JST,
            "no_forward_fill": True,
            "no_expiry_rank_substitution": True,
            "no_extrapolation": True,
            "no_full_close_fallback": True,
            "no_recovery_promotion": True,
        },
        "cost_model": {
            "one_way_basis_points": 10.0,
            "applies_to": ["base_sleeve_turnover", "topix_etf_13060_turnover"],
            "reported_cost_turnover_fill_scope": "OVERLAY_INCREMENTAL_ONLY",
            "not_total_strategy_cost_metrics": True,
            "base_nav_source_slice_excludes_wrapper_entry_liquidation": True,
        },
        "hedge_proxy": am_pm_proxy_mapping()["executable_hedge"],
        "cash_index": am_pm_proxy_mapping()["cash_index"],
        "beta_policy": {
            "lookback_source_sessions": BETA_LOOKBACK_RETURNS,
            "minimum_paired_returns": BETA_MIN_RETURNS,
            "current_signal_day_pair_required": True,
            "return_basis": "am_to_am_madjc",
            "hedge_instrument": TOPIX_ETF_CODE,
            "hedge_formula": "h=clip(-g*beta,-1.5,1.5)",
        },
    }


def evaluate_index_vol_overlays_am_pm(
    observations: Sequence[IndexVolOverlayAmPmObservation],
    *,
    manifest: PreparedIndexVolOverlayAmPmPanelManifest,
    authoritative_session_dates: Sequence[str],
    signal_start: str,
    signal_end: str | None = None,
    starting_capital: float = 1_000_000.0,
) -> dict[str, Any]:
    """Evaluate the four ordinary overlay ideas under the AM/PM causal identity."""

    if any(isinstance(row, IndexVolOverlayObservation) for row in observations):
        raise TypeError("AM/PM job must not accept an old next-close prepared panel")
    _validate_am_pm_observations(observations)
    _validate_am_pm_manifest(manifest, observations, authoritative_session_dates)
    capital = _positive(starting_capital)
    if capital is None:
        raise ValueError("starting_capital must be positive and finite")
    if len(OVERLAY_AM_PM_CANDIDATES) != 4:
        raise RuntimeError("AM/PM overlay candidate set must remain exact-four")
    _start, _end, signal_indices = _am_pm_signal_range(
        observations, signal_start, signal_end
    )
    structural_missing = [
        _missing(
            observations[signal_index].date,
            _am_pm_structural_issues(
                observations, signal_index, require_pnl=True
            )[0],
        )
        for signal_index in signal_indices
        if _am_pm_structural_issues(observations, signal_index, require_pnl=True)
    ]
    if structural_missing:
        results = [
            _am_pm_not_evaluated_candidate(
                candidate,
                reason="missing_required_row_no_forward_fill",
                missing=structural_missing,
            )
            for candidate in OVERLAY_AM_PM_CANDIDATES
        ]
        diagnostic_control = _am_pm_not_evaluated_control(
            reason="missing_required_row_no_forward_fill",
            missing=structural_missing,
        )
    else:
        results = [
            _am_pm_overlay_candidate_result(
                candidate,
                observations,
                signal_indices,
                starting_capital=capital,
            )
            for candidate in OVERLAY_AM_PM_CANDIDATES
        ]
        diagnostic_control = _am_pm_overlay_control_result(
            observations,
            signal_indices,
            starting_capital=capital,
        )
    diagnostics = [
        {
            "date": observations[index].date,
            "option_as_of_date": observations[index - 1].date if index else None,
            "svi_equivalent_atm_term_ratio": (
                _positive(observations[index - 1].svi_equivalent_atm_term_ratio)
                if index
                else None
            ),
            "svi_equivalent_downside_smile_term_ratio": (
                _positive(
                    observations[index - 1].svi_equivalent_downside_smile_term_ratio
                )
                if index
                else None
            ),
        }
        for index in signal_indices
    ]
    evaluated_count = sum(result["status"] == "EVALUATED" for result in results)
    report = _am_pm_report_framing(
        schema_version=PERSONAL_INDEX_VOL_OVERLAY_AM_PM_SCHEMA,
        manifest=manifest,
    )
    report.update(
        {
            "status": (
                "EVALUATED" if evaluated_count == len(results) else "NOT_EVALUATED"
            ),
            "candidate_policy": {
                "declared_count": len(OVERLAY_AM_PM_CANDIDATES),
                "evaluated_count": evaluated_count,
                "post_result_selection": "NOT_PERFORMED",
                "selection": "NOT_PERFORMED",
                "ranking": None,
                "diagnostic_control_in_declared_count": False,
                "candidate_order": list(OVERLAY_AM_PM_CANDIDATE_IDS),
            },
            "diagnostic_control": diagnostic_control,
            "svi_equivalent_diagnostics": {
                "role": "DIAGNOSTIC_ONLY_NOT_RANKED",
                "downside_smile_term_ratio_formula": (
                    "(front_downside_wing_iv/front_atm_iv)/"
                    "(next_downside_wing_iv/next_atm_iv)"
                ),
                "used_in_signals": False,
                "used_in_performance": False,
                "option_as_of": "through_d_minus_1",
                "rows": diagnostics,
            },
            "candidates": results,
        }
    )
    return report


def _am_pm_transport_row(
    candidate: OverlayCandidate,
    day_rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    expected_model, expected_family = _AM_PM_SMILE_TRANSPORT_IDENTITY[
        candidate.candidate_id
    ]
    matches = [
        row
        for row in day_rows
        if row.get("transport_model") == expected_model
        and row.get("signal_family") == expected_family
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _am_pm_transport_row_issues(
    candidate: OverlayCandidate,
    row: Mapping[str, Any] | None,
    *,
    pair_end: str,
    pair_start: str | None,
) -> list[str]:
    if row is None:
        return [f"{candidate.candidate_id}:missing_d_minus_2_to_d_minus_1_pair"]
    issues: list[str] = []
    expected_model, expected_family = _AM_PM_SMILE_TRANSPORT_IDENTITY[
        candidate.candidate_id
    ]
    raw_id = str(row.get("candidate_id") or "")
    allowed_ids = {
        candidate.candidate_id,
        candidate.candidate_id.replace("_am_pm_v1", "_v1"),
    }
    if raw_id and raw_id not in allowed_ids:
        issues.append(f"{candidate.candidate_id}:identity_mismatch")
    if row.get("transport_model") != expected_model:
        issues.append(f"{candidate.candidate_id}:sticky_model_mismatch")
    if row.get("signal_family") != expected_family:
        issues.append(f"{candidate.candidate_id}:signal_family_mismatch")
    issues.extend(_provenance_issues(row, prefix=candidate.candidate_id))
    issues.extend(
        _expiry_pair_issues(
            row,
            signal_date=pair_end,
            prefix=candidate.candidate_id,
        )
    )
    previous = str(row.get("previous_observation_date") or "")
    if pair_start is None:
        issues.append(f"{candidate.candidate_id}:official_predecessor_unavailable")
    elif previous != pair_start:
        issues.append(
            f"{candidate.candidate_id}:previous_observation_not_official_d_minus_2"
        )
    if str(row.get("date") or "") != pair_end:
        issues.append(f"{candidate.candidate_id}:pair_end_not_d_minus_1")
    scale, _raw, scale_error = _transport_gross_scale(candidate, row)
    if scale is None:
        issues.append(
            f"{candidate.candidate_id}:{scale_error or 'gross_scale_unavailable'}"
        )
    return issues


def _am_pm_common_validity_for_date(
    *,
    day: str,
    pair_end: str | None,
    pair_start: str | None,
    day_rows: Sequence[Mapping[str, Any]],
    observations: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    structural = _am_pm_structural_issues(
        observations, signal_index, require_pnl=False
    )
    reasons.extend(structural)
    if pair_end is None or pair_start is None:
        reasons.append("d_minus_2_to_d_minus_1_pair_unavailable")
    ids = [str(row.get("candidate_id") or "") for row in day_rows]
    if len(ids) != len(set(ids)):
        reasons.append("candidate_ids_not_unique")
    by_identity = {
        (str(row.get("transport_model") or ""), str(row.get("signal_family") or "")): row
        for row in day_rows
    }
    if len(by_identity) != len(day_rows):
        reasons.append("candidate_identity_not_exact_four")
    for candidate in SMILE_TRANSPORT_AM_PM_CANDIDATES:
        reasons.extend(
            _am_pm_transport_row_issues(
                candidate,
                _am_pm_transport_row(candidate, day_rows),
                pair_end=pair_end or "",
                pair_start=pair_start,
            )
        )
    if signal_index + 1 >= len(observations):
        reasons.append("d_plus_1_session_unavailable")
    beta, beta_error = _am_pm_estimate_beta(observations, signal_index)
    if beta is None:
        reasons.append(beta_error or "beta_estimate_unavailable")
    ordered: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)
    return {
        "date": day,
        "common_valid": not ordered,
        "reasons": ordered,
        "pair_start": pair_start,
        "pair_end": pair_end,
        "predecessor": pair_end,
    }


def _am_pm_signal_outcome_issues(
    observations: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
) -> list[str]:
    return _am_pm_structural_issues(observations, signal_index, require_pnl=True)


def _am_pm_flatten_plan(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
) -> dict[str, Any]:
    pnl_index = min(signal_index + 1, len(rows) - 1)
    sleeve_return = _pm_sleeve_return(rows, signal_index, pnl_index)
    proxy_return = _etf_pm_return(rows, signal_index, pnl_index)
    return {
        "signal_date": rows[signal_index].date,
        "rebalance_date": rows[signal_index].date,
        "pnl_date": rows[pnl_index].date,
        "feature_ratio_x": None,
        "gross_scale": 0.0,
        "estimated_beta": None,
        "beta_observations": None,
        "beta_window_last_return_date": None,
        "topix_hedge_weight": 0.0,
        "base_sleeve_return": 0.0 if sleeve_return is None else sleeve_return,
        "topix_cash_return": 0.0 if proxy_return is None else proxy_return,
        "flatten_applied": True,
        "common_valid": False,
    }


def _am_pm_valid_transport_plan(
    candidate: OverlayCandidate,
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
    feature_row: Mapping[str, Any],
) -> dict[str, Any] | None:
    gross_scale, raw_value, error = _transport_gross_scale(candidate, feature_row)
    if gross_scale is None:
        return None
    beta, _beta_error = _am_pm_estimate_beta(rows, signal_index)
    if beta is None:
        return None
    pnl_index = signal_index + 1
    sleeve_return = _pm_sleeve_return(rows, signal_index, pnl_index)
    proxy_return = _etf_pm_return(rows, signal_index, pnl_index)
    if sleeve_return is None or proxy_return is None:
        return None
    estimated_beta, beta_observations, beta_last_date = beta
    hedge_weight = _clip(
        -gross_scale * estimated_beta,
        -MAX_ABS_TOPIX_HEDGE,
        MAX_ABS_TOPIX_HEDGE,
    )
    return {
        "signal_date": rows[signal_index].date,
        "rebalance_date": rows[signal_index].date,
        "pnl_date": rows[pnl_index].date,
        "feature_ratio_x": raw_value,
        "gross_scale": gross_scale,
        "estimated_beta": estimated_beta,
        "beta_observations": beta_observations,
        "beta_window_last_return_date": beta_last_date,
        "topix_hedge_weight": hedge_weight,
        "base_sleeve_return": sleeve_return,
        "topix_cash_return": proxy_return,
        "flatten_applied": False,
        "common_valid": True,
        "feature_error": error,
    }


def _am_pm_invested_control_plan(
    rows: Sequence[IndexVolOverlayAmPmObservation],
    signal_index: int,
) -> dict[str, Any]:
    pnl_index = signal_index + 1
    sleeve_return = _pm_sleeve_return(rows, signal_index, pnl_index)
    return {
        "signal_date": rows[signal_index].date,
        "rebalance_date": rows[signal_index].date,
        "pnl_date": rows[pnl_index].date,
        "feature_ratio_x": 1.0,
        "gross_scale": 1.0,
        "estimated_beta": None,
        "beta_observations": None,
        "beta_window_last_return_date": None,
        "topix_hedge_weight": 0.0,
        "base_sleeve_return": 0.0 if sleeve_return is None else sleeve_return,
        "topix_cash_return": 0.0,
        "flatten_applied": False,
        "common_valid": True,
    }


def canonical_smile_transport_am_pm_panel_digest(
    observations: Sequence[IndexVolOverlayAmPmObservation],
    transport_features: Sequence[Mapping[str, Any]],
    common_validity: Sequence[Mapping[str, Any]],
) -> str:
    return _canonical_digest(
        {
            "schema_version": AM_PM_SMILE_TRANSPORT_PANEL_DIGEST_SCHEMA,
            "market_rows": [
                {
                    "date": row.date,
                    "available_at": row.available_at,
                    "base_sleeve_am_nav": row.base_sleeve_am_nav,
                    "base_sleeve_pm_nav": row.base_sleeve_pm_nav,
                    "topix_etf_13060_madjc": row.topix_etf_13060_madjc,
                    "topix_etf_13060_aadjc": row.topix_etf_13060_aadjc,
                }
                for row in observations
            ],
            "transport_rows": [dict(row) for row in transport_features],
            "common_validity": [dict(row) for row in common_validity],
        }
    )


def evaluate_index_smile_transport_overlays_am_pm(
    observations: Sequence[IndexVolOverlayAmPmObservation],
    transport_features: Sequence[Mapping[str, Any]],
    *,
    manifest: PreparedIndexVolOverlayAmPmPanelManifest,
    authoritative_session_dates: Sequence[str],
    signal_start: str,
    signal_end: str | None = None,
    starting_capital: float = 1_000_000.0,
    core_digest: str | None = None,
) -> dict[str, Any]:
    """Evaluate the four smile-transport ideas on D-2->D-1 under AM/PM timing."""

    if any(isinstance(row, IndexVolOverlayObservation) for row in observations):
        raise TypeError("AM/PM job must not accept an old next-close prepared panel")
    _validate_am_pm_observations(observations)
    _validate_am_pm_manifest(manifest, observations, authoritative_session_dates)
    capital = _positive(starting_capital)
    if capital is None:
        raise ValueError("starting_capital must be positive and finite")
    if len(SMILE_TRANSPORT_AM_PM_CANDIDATES) != 4:
        raise RuntimeError("AM/PM smile-transport candidate set must remain exact-four")
    if len(set(SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS)) != 4:
        raise RuntimeError("AM/PM smile-transport candidate ids must be unique")
    _start, _end, signal_indices = _am_pm_signal_range(
        observations, signal_start, signal_end
    )
    grouped = _group_transport_features(
        transport_features,
        tuple(row.date for row in observations),
    )
    validity_rows: list[dict[str, Any]] = []
    for signal_index in signal_indices:
        day = observations[signal_index].date
        pair_end = observations[signal_index - 1].date if signal_index > 0 else None
        pair_start = (
            observations[signal_index - 2].date if signal_index > 1 else None
        )
        validity_rows.append(
            _am_pm_common_validity_for_date(
                day=day,
                pair_end=pair_end,
                pair_start=pair_start,
                day_rows=grouped.get(pair_end, []) if pair_end else [],
                observations=observations,
                signal_index=signal_index,
            )
        )
    validity_by_date = {row["date"]: row for row in validity_rows}
    valid_dates = [row["date"] for row in validity_rows if row["common_valid"]]
    valid_months = _calendar_months(valid_dates)
    gate_passed = (
        len(valid_dates) >= COMMON_VALID_MIN_SIGNAL_DAYS
        and len(valid_months) >= COMMON_VALID_MIN_CALENDAR_MONTHS
    )
    gate = {
        "passed": gate_passed,
        "required_signal_days": COMMON_VALID_MIN_SIGNAL_DAYS,
        "required_distinct_calendar_months": COMMON_VALID_MIN_CALENDAR_MONTHS,
        "common_valid_signal_days": len(valid_dates),
        "common_valid_calendar_months": len(valid_months),
        "common_valid_month_ids": list(valid_months),
        "common_valid_dates": valid_dates,
        "excluded": [
            {"date": row["date"], "reasons": row["reasons"]}
            for row in validity_rows
            if not row["common_valid"]
        ],
        "common_invalid_policy": "flatten_g0_h0_at_d_pm",
        "transport_pair": "d_minus_2_to_d_minus_1",
    }
    outcome_missing: list[dict[str, Any]] = []
    for signal_index in signal_indices:
        day = observations[signal_index].date
        if not validity_by_date[day]["common_valid"]:
            continue
        outcome_issues = _am_pm_signal_outcome_issues(observations, signal_index)
        if outcome_issues:
            outcome_missing.append({"date": day, "reasons": outcome_issues})
    outcome_complete = not outcome_missing
    outcome_completeness = {
        "passed": outcome_complete,
        "policy": "signal_valid_dates_require_realized_d_plus_1_pm_returns",
        "missing": outcome_missing,
        "reason": (
            None if outcome_complete else "signal_valid_d_plus_1_pm_outcome_missing"
        ),
    }
    observed_core_digest = core_digest or smile_transport_core_digest()
    if not _canonical_sha256(observed_core_digest):
        raise ValueError("core_digest must be a canonical sha256 digest")
    if not gate_passed:
        results = [
            _am_pm_not_evaluated_candidate(
                candidate,
                reason="common_validity_gate_failed",
                missing=gate["excluded"],
            )
            for candidate in SMILE_TRANSPORT_AM_PM_CANDIDATES
        ]
        diagnostic_control = _am_pm_not_evaluated_control(
            reason="common_validity_gate_failed",
            missing=gate["excluded"],
        )
        diagnostic_control["role"] = (
            "COMMON_VALID_CALENDAR_NAV_WRAPPER_CONTROL_WITH_10BP_COSTS"
        )
    elif not outcome_complete:
        results = [
            _am_pm_not_evaluated_candidate(
                candidate,
                reason="signal_valid_d_plus_1_pm_outcome_missing",
                missing=outcome_missing,
            )
            for candidate in SMILE_TRANSPORT_AM_PM_CANDIDATES
        ]
        diagnostic_control = _am_pm_not_evaluated_control(
            reason="signal_valid_d_plus_1_pm_outcome_missing",
            missing=outcome_missing,
        )
        diagnostic_control["role"] = (
            "COMMON_VALID_CALENDAR_NAV_WRAPPER_CONTROL_WITH_10BP_COSTS"
        )
    else:
        results = []
        for candidate in SMILE_TRANSPORT_AM_PM_CANDIDATES:
            plans: list[dict[str, Any]] = []
            for signal_index in signal_indices:
                day = observations[signal_index].date
                if validity_by_date[day]["common_valid"]:
                    pair_end = observations[signal_index - 1].date
                    feature_row = _am_pm_transport_row(
                        candidate, grouped.get(pair_end, [])
                    )
                    if feature_row is None:
                        raise RuntimeError(
                            "common-valid date lost a required transport plan"
                        )
                    plan = _am_pm_valid_transport_plan(
                        candidate,
                        observations,
                        signal_index,
                        feature_row,
                    )
                    if plan is None:
                        raise RuntimeError(
                            "common-valid date lost a required transport plan"
                        )
                    plans.append(plan)
                else:
                    plans.append(_am_pm_flatten_plan(observations, signal_index))
            curve, trades, performance = _evaluate_plans(
                plans,
                starting_capital=capital,
            )
            results.append(
                {
                    **asdict(candidate),
                    "physical_potential": _physical_potential_declaration(candidate),
                    "status": "EVALUATED",
                    "reason": None,
                    "missing_required_rows": [],
                    "daily_path": curve,
                    "trades": trades,
                    "performance": performance,
                }
            )
        control_plans = [
            (
                _am_pm_invested_control_plan(observations, signal_index)
                if validity_by_date[observations[signal_index].date]["common_valid"]
                else _am_pm_flatten_plan(observations, signal_index)
            )
            for signal_index in signal_indices
        ]
        curve, trades, performance = _evaluate_plans(
            control_plans,
            starting_capital=capital,
        )
        diagnostic_control = {
            "control_id": AM_PM_CONTROL_ID,
            "role": "COMMON_VALID_CALENDAR_NAV_WRAPPER_CONTROL_WITH_10BP_COSTS",
            "ranking_role": "DIAGNOSTIC_CONTROL_NOT_RANKED",
            "mechanics": (
                "g=1 and h=0 on the common-valid AM/PM decision calendar; "
                "flatten g=0,h=0 at D PM on common-invalid dates; "
                "same overlay 10bp turnover costs as the four candidates"
            ),
            "source_slice_wrapper_cost_semantics": (
                SOURCE_SLICE_WRAPPER_COST_SEMANTICS
            ),
            "status": "EVALUATED",
            "reason": None,
            "missing_required_rows": [],
            "daily_path": curve,
            "trades": trades,
            "performance": performance,
        }
    evaluated_count = sum(result["status"] == "EVALUATED" for result in results)
    report = _am_pm_report_framing(
        schema_version=PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_SCHEMA,
        manifest=manifest,
        extra_provenance={
            "transport_feature_digest": canonical_smile_transport_am_pm_panel_digest(
                observations,
                transport_features,
                validity_rows,
            ),
            "core_version": OPTIONS_225_SMILE_TRANSPORT_VERSION,
            "core_digest": observed_core_digest,
            "core_module": SMILE_TRANSPORT_CORE_MODULE,
        },
    )
    report.update(
        {
            "status": (
                "EVALUATED" if evaluated_count == len(results) else "NOT_EVALUATED"
            ),
            "exposure_formulas": {
                "downside_q": (
                    "actual_downside_smile_term_ratio/"
                    "predicted_downside_smile_term_ratio-1"
                ),
                "downside_g": "clip(1/(1+q),0.5,1.0)",
                "potential_minimum_M": (
                    "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)"
                ),
                "potential_minimum_g": "clip(1/(1+M/0.10),0.5,1.0)",
                "hedge_h": "clip(-g*beta_D,-1.5,1.5)",
            },
            "physical_potential": {
                "metaphor_only": True,
                "causal_claim": False,
            },
            "candidate_policy": {
                "declared_count": len(SMILE_TRANSPORT_AM_PM_CANDIDATES),
                "evaluated_count": evaluated_count,
                "post_result_selection": "NOT_PERFORMED",
                "selection": "NOT_PERFORMED",
                "ranking": None,
                "diagnostic_control_in_declared_count": False,
                "candidate_order": list(SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS),
                "sticky_models": [STICKY_STRIKE, STICKY_MONEYNESS],
                "adaptive_model_switch": False,
            },
            "common_validity_gate": gate,
            "outcome_completeness": outcome_completeness,
            "diagnostic_control": diagnostic_control,
            "candidates": results,
            "under_px_policy": {
                "role": "DISCLOSED_COORDINATE_PROXY",
                "trusted_forward": False,
                "forward_relative_fields": "null_with_reason",
                "forward_relative_reason": "trusted_forward_unavailable",
            },
        }
    )
    return report


__all__ = [
    "AM_PM_BASE_COHORT_ID",
    "AM_PM_BASE_SLEEVE_ID",
    "AM_PM_BASE_SLEEVE_SCHEMA",
    "AM_PM_CONTROL_ID",
    "AM_PM_EXECUTION_MODE",
    "BASE_COHORT_ID",
    "BASE_NAV_SEMANTICS",
    "BASE_RETURN_SEMANTICS",
    "BASE_SLEEVE_ID",
    "BASE_UNIVERSE_ID",
    "BETA_LOOKBACK_RETURNS",
    "BETA_MIN_RETURNS",
    "EXPECTED_BASE_COHORT_DIGEST",
    "EXPECTED_BASE_STRATEGY_SPEC_DIGEST",
    "IndexVolOverlayAmPmObservation",
    "IndexVolOverlayObservation",
    "MAX_ABS_TOPIX_HEDGE",
    "N225_ETF_CODE",
    "ONE_WAY_COST_RATE",
    "OVERLAY_AM_PM_CANDIDATES",
    "OVERLAY_AM_PM_CANDIDATE_IDS",
    "OVERLAY_CANDIDATES",
    "PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_SCHEMA",
    "PERSONAL_INDEX_SMILE_TRANSPORT_SCHEMA",
    "PERSONAL_INDEX_VOL_OVERLAY_AM_PM_SCHEMA",
    "PERSONAL_INDEX_VOL_OVERLAY_SCHEMA",
    "POTENTIAL_MINIMUM_MISMATCH_SCALE",
    "PREPARED_AM_PM_PANEL_MANIFEST_SCHEMA",
    "PREPARED_PANEL_MANIFEST_SCHEMA",
    "PREPARED_SMILE_TRANSPORT_PANEL_MANIFEST_SCHEMA",
    "PreparedIndexVolOverlayAmPmPanelManifest",
    "PreparedIndexVolOverlayPanelManifest",
    "SMILE_TRANSPORT_AM_PM_CANDIDATES",
    "SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS",
    "SMILE_TRANSPORT_CANDIDATES",
    "SMILE_TRANSPORT_CANDIDATE_IDS",
    "SMILE_TRANSPORT_CORE_MODULE",
    "SOURCE_SLICE_WRAPPER_COST_SEMANTICS",
    "TOPIX_ETF_CODE",
    "TOPIX_PROXY_DATASET",
    "am_pm_proxy_mapping",
    "am_pm_proxy_mapping_digest",
    "am_pm_temporal_contract_digest",
    "build_prepared_am_pm_panel_manifest",
    "build_prepared_panel_manifest",
    "canonical_prepared_am_pm_panel_digest",
    "canonical_prepared_panel_digest",
    "canonical_smile_transport_am_pm_panel_digest",
    "canonical_smile_transport_panel_digest",
    "canonical_trading_calendar_digest",
    "downside_smile_term_gross_scale",
    "evaluate_index_smile_transport_overlays",
    "evaluate_index_smile_transport_overlays_am_pm",
    "evaluate_index_vol_overlays",
    "evaluate_index_vol_overlays_am_pm",
    "potential_minimum_gross_scale",
    "smile_transport_core_digest",
]
