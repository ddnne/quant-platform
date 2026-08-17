"""Transaction-cost and short-financing models for the core engine.

A :class:`CostModel` charges a fixed basis-points rate on the **one-way
notional** of every fill (buys and sells both pay). Two named factories cover
the handoff requirement:

* :func:`standard_cost` — the baseline realistic cost (default 5 bps one-way).
* :func:`stress_cost` — a multiple of standard, for robustness / sensitivity.

W85 / w0816t adds :class:`ShortFinancingModel` for paper L-S short legs:

* daily financing on short market value = f(repo_rate[t] + fixed spread bp)
* low / mid / high spread sensitivity (25 / 50 / 150 bp; default mid)
* repo gaps → no invent charge (0 that day + gap disclosed); optional fixed
  fallback only when no series is supplied (disclosed ``fixed_bp_placeholder``)

Both are required to be deterministic so two runs with the same model produce
identical results. The model is recorded verbatim in the result metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


# Short-borrow spread over repo (research / paper sensitivity bands).
# Mirrors research.cost_models.SHORT_BORROW_SPREAD_* (kept local so core
# does not import product research).
SHORT_BORROW_SPREAD_LOW_BP: float = 25.0
SHORT_BORROW_SPREAD_MID_BP: float = 50.0
SHORT_BORROW_SPREAD_HIGH_BP: float = 150.0
DEFAULT_SHORT_BORROW_SPREAD_BP: float = SHORT_BORROW_SPREAD_MID_BP
SHORT_BORROW_SPREAD_SENSITIVITY: dict[str, float] = {
    "low": SHORT_BORROW_SPREAD_LOW_BP,
    "mid": SHORT_BORROW_SPREAD_MID_BP,
    "high": SHORT_BORROW_SPREAD_HIGH_BP,
}
DEFAULT_TRADING_DAYS_PER_YEAR: int = 245


@dataclass(frozen=True)
class CostModel:
    """Fixed bps one-way transaction cost.

    ``one_way_cost(notional)`` returns the cash charged for a fill of the
    given signed notional (sign ignored — buyers and sellers pay symmetrically).
    """

    bps_one_way: float
    name: str = "standard"
    # Informational: how this model was derived (e.g. stress = 5x standard).
    stress_multiple: float | None = None

    def one_way_cost(self, notional: float) -> float:
        """Cash cost for a fill of ``notional`` (signed; charged on |notional|)."""
        return abs(notional) * self.bps_one_way / 1e4

    def describe(self) -> dict:
        """Stable, JSON-serializable description for reproducibility metadata."""
        return {
            "name": self.name,
            "bps_one_way": self.bps_one_way,
            "stress_multiple": self.stress_multiple,
        }


@dataclass(frozen=True)
class ShortFinancingModel:
    """Daily financing on short market value = f(repo[t] + fixed spread).

    Formula (approved approximation, W85)::

        short_annual_bp[t] = repo_pct[t] * 100 + spread_bp
        daily_cost = |short_notional| * (short_annual_bp / 10000) / trading_days

    ``repo_rates_by_date`` maps ``YYYY-MM-DD`` → JSDA rate **percent**.
    Missing dates are **gaps** — charge 0 that day (no invent / no ffill)
    and count toward ``n_gap_days`` in engine metadata.

    When no series is supplied, uses ``fallback_repo_annual_bp`` (default 0)
    + spread as a disclosed fixed placeholder (matches research mid band
    when repo ≈ 0 → ~50bp annual).
    """

    spread_bp: float = DEFAULT_SHORT_BORROW_SPREAD_BP
    sensitivity: str | None = "mid"
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR
    # date -> repo rate in percent (JSDA schema units)
    repo_rates_by_date: Mapping[str, float] | None = None
    # Used only when series is absent (not for per-date gap invent fill).
    fallback_repo_annual_bp: float = 0.0
    name: str = "repo_plus_borrow_spread"
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.sensitivity is not None:
            key = str(self.sensitivity).strip().lower()
            if key not in SHORT_BORROW_SPREAD_SENSITIVITY:
                raise ValueError(
                    f"sensitivity must be one of "
                    f"{list(SHORT_BORROW_SPREAD_SENSITIVITY)}, got "
                    f"{self.sensitivity!r}"
                )
            object.__setattr__(
                self, "spread_bp", float(SHORT_BORROW_SPREAD_SENSITIVITY[key])
            )
            object.__setattr__(self, "sensitivity", key)
        if float(self.spread_bp) < 0:
            raise ValueError("spread_bp must be >= 0")
        if int(self.trading_days_per_year) < 1:
            raise ValueError("trading_days_per_year must be >= 1")

    @property
    def has_repo_series(self) -> bool:
        return bool(self.repo_rates_by_date)

    def rate_source(self) -> str:
        if self.repo_rates_by_date:
            return "repo_plus_borrow_spread"
        return "fixed_bp_placeholder"

    def daily_rate_fraction(self, date: str | None = None) -> tuple[float | None, bool]:
        """Return ``(daily_fraction, is_gap)``.

        Gap → ``(None, True)`` — caller must not invent a charge.
        """
        if not self.enabled:
            return 0.0, False
        days = float(self.trading_days_per_year)
        spread = float(self.spread_bp)
        if self.repo_rates_by_date is not None:
            if date is None:
                return None, True
            d = str(date)[:10]
            if d not in self.repo_rates_by_date:
                return None, True
            try:
                repo_pct = float(self.repo_rates_by_date[d])
            except (TypeError, ValueError):
                return None, True
            # percent → annual bp = pct * 100; annual fraction = pct/100
            annual_frac = (repo_pct / 100.0) + (spread / 10_000.0)
            return annual_frac / days, False
        # Fixed fallback: repo annual bp + spread
        annual_frac = (
            float(self.fallback_repo_annual_bp) / 10_000.0
            + spread / 10_000.0
        )
        return annual_frac / days, False

    def daily_cost(self, short_notional: float, date: str | None = None) -> tuple[float, bool]:
        """Cash financing for ``|short_notional|`` on ``date``.

        Returns ``(cost, is_gap)``. Gap days charge **0** (no invent).
        """
        if not self.enabled or short_notional == 0:
            return 0.0, False
        rate, is_gap = self.daily_rate_fraction(date)
        if is_gap or rate is None:
            return 0.0, True
        return abs(float(short_notional)) * float(rate), False

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": bool(self.enabled),
            "spread_bp": float(self.spread_bp),
            "sensitivity": self.sensitivity,
            "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
            "trading_days_per_year": int(self.trading_days_per_year),
            "rate_source": self.rate_source(),
            "has_repo_series": self.has_repo_series,
            "n_repo_dates": (
                len(self.repo_rates_by_date) if self.repo_rates_by_date else 0
            ),
            "fallback_repo_annual_bp": float(self.fallback_repo_annual_bp),
            "formula": (
                "daily_cost = |short_notional| * "
                "(repo_pct/100 + spread_bp/10000) / trading_days"
            ),
            "gap_policy": "disclose_only_no_ffill_no_invent",
        }


def standard_cost(bps: float = 5.0) -> CostModel:
    """Baseline cost model: ``bps`` basis points one-way (default 5 bps)."""
    return CostModel(bps_one_way=float(bps), name="standard")


def stress_cost(multiple: float = 5.0, base_bps: float = 5.0) -> CostModel:
    """Stress cost: ``multiple`` x the standard ``base_bps`` one-way."""
    return CostModel(
        bps_one_way=float(base_bps) * float(multiple),
        name="stress",
        stress_multiple=float(multiple),
    )


def short_financing(
    *,
    sensitivity: str = "mid",
    spread_bp: float | None = None,
    repo_rates_by_date: Mapping[str, float] | None = None,
    fallback_repo_annual_bp: float = 0.0,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    enabled: bool = True,
) -> ShortFinancingModel:
    """Factory for paper short-leg financing (repo + fixed spread)."""
    return ShortFinancingModel(
        spread_bp=(
            float(spread_bp)
            if spread_bp is not None
            else float(DEFAULT_SHORT_BORROW_SPREAD_BP)
        ),
        sensitivity=sensitivity if spread_bp is None else None,
        repo_rates_by_date=repo_rates_by_date,
        fallback_repo_annual_bp=float(fallback_repo_annual_bp),
        trading_days_per_year=int(trading_days_per_year),
        enabled=bool(enabled),
    )
