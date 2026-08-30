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
from statistics import mean, median
from typing import Any, Final, Sequence

from research.factor_cohorts import get_research_cohort
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


def canonical_trading_calendar_digest(
    observations: Sequence[IndexVolOverlayObservation],
) -> str:
    """Hash the complete ordered session-date vector independently."""

    return _canonical_digest(
        {
            "schema_version": TRADING_CALENDAR_DIGEST_SCHEMA,
            "ordered_session_dates": [row.date for row in observations],
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
) -> None:
    if not isinstance(manifest, PreparedIndexVolOverlayPanelManifest):
        raise TypeError("manifest must be PreparedIndexVolOverlayPanelManifest")
    if manifest.session_count != len(observations):
        raise ValueError("prepared panel manifest session_count mismatch")
    if manifest.session_date_start != observations[0].date:
        raise ValueError("prepared panel manifest session_date_start mismatch")
    if manifest.session_date_end != observations[-1].date:
        raise ValueError("prepared panel manifest session_date_end mismatch")
    try:
        observed_panel_digest = canonical_prepared_panel_digest(observations)
    except (TypeError, ValueError) as exc:
        raise ValueError("prepared panel rows are not canonically hashable") from exc
    if manifest.prepared_panel_digest != observed_panel_digest:
        raise ValueError("prepared_panel_digest does not match observation rows")
    observed_calendar_digest = canonical_trading_calendar_digest(observations)
    if manifest.trading_calendar_digest != observed_calendar_digest:
        raise ValueError("trading_calendar_digest does not match ordered session dates")


def build_prepared_panel_manifest(
    observations: Sequence[IndexVolOverlayObservation],
    *,
    snapshot_digest: str,
    base_report_digest: str,
) -> PreparedIndexVolOverlayPanelManifest:
    """Build the ergonomic manifest while deriving every repo/local digest."""

    _validate_observations(observations)
    return PreparedIndexVolOverlayPanelManifest(
        strategy_spec_digest=EXPECTED_BASE_STRATEGY_SPEC_DIGEST,
        cohort_digest=EXPECTED_BASE_COHORT_DIGEST,
        snapshot_digest=snapshot_digest,
        base_report_digest=base_report_digest,
        trading_calendar_digest=canonical_trading_calendar_digest(observations),
        prepared_panel_digest=canonical_prepared_panel_digest(observations),
        session_date_start=observations[0].date,
        session_date_end=observations[-1].date,
        session_count=len(observations),
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
    signal_start: str,
    signal_end: str | None = None,
    starting_capital: float = 1_000_000.0,
) -> dict[str, Any]:
    """Evaluate exactly four predeclared overlays without selecting a winner."""

    _validate_observations(observations)
    _validate_manifest(manifest, observations)
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


__all__ = [
    "BASE_COHORT_ID",
    "BASE_NAV_SEMANTICS",
    "BASE_RETURN_SEMANTICS",
    "BASE_SLEEVE_ID",
    "BASE_UNIVERSE_ID",
    "BETA_LOOKBACK_RETURNS",
    "BETA_MIN_RETURNS",
    "EXPECTED_BASE_COHORT_DIGEST",
    "EXPECTED_BASE_STRATEGY_SPEC_DIGEST",
    "IndexVolOverlayObservation",
    "MAX_ABS_TOPIX_HEDGE",
    "ONE_WAY_COST_RATE",
    "OVERLAY_CANDIDATES",
    "PERSONAL_INDEX_VOL_OVERLAY_SCHEMA",
    "PREPARED_PANEL_MANIFEST_SCHEMA",
    "PreparedIndexVolOverlayPanelManifest",
    "SOURCE_SLICE_WRAPPER_COST_SEMANTICS",
    "TOPIX_PROXY_DATASET",
    "build_prepared_panel_manifest",
    "canonical_prepared_panel_digest",
    "canonical_trading_calendar_digest",
    "evaluate_index_vol_overlays",
]
