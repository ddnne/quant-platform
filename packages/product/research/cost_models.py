"""Research cost models: transaction + short borrow + leverage financing (W77 / w0816k).

Purpose
-------
Document **explicit research cost assumptions** beyond the base 10bp one-way
transaction cost. Used by checklist v2 so leverage/short costs are never
implicit.

Hard constraints
----------------
* Research-only · 仮定に依存 · 運用GOではない
* Does **not** mint READY / arm Mass / open Phase7 / authorize orders
* Does **not** claim edge / significance
* Pure helpers preferred (unit-testable without R2 / D1)

Models
------
1. **Transaction (base)** — one-way default 10bp (matches robustness_gate).
2. **Short borrow / stock-lending fee** — annualized rate applied to short
   notional when the hyp shorts (documented default rates).
3. **Leverage / financing (repo)** — annualized financing cost when gross
   exposure > 1× equity; long-only unlevered hyps must still **state** the
   unlevered assumption.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Identity / freeze (must never arm)
# ---------------------------------------------------------------------------

COST_MODELS_VERSION: str = "research-cost-models/v1"
COST_MODELS_LABEL: str = (
    "研究用コストモデル・未宣言 "
    "(取引コスト + 空売り借入 + レバ調達 / READY未接続 / Mass NO-GO)"
)

MASS_RESEARCH: str = "NO-GO"
PHASE7: str = "OFF"
READY_DECLARED: bool = False
OPERATIONAL_GO: bool = False
SIGNIFICANCE_CLAIMED: bool = False
EDGE_CLAIMED: bool = False
CONNECTED_TO_READY: bool = False
CONNECTED_TO_MASS: bool = False

# Base transaction (matches robustness_gate / holding_metrics).
DEFAULT_ONE_WAY_COST_BP: float = 10.0
DEFAULT_ONE_WAY_COST: float = DEFAULT_ONE_WAY_COST_BP / 10_000.0  # 0.001
DEFAULT_ROUND_TRIP_COST: float = DEFAULT_ONE_WAY_COST * 2.0

# Short borrow / stock-lending (research defaults; 仮定に依存).
# ~50bp annualized is a conservative liquid-name research placeholder for
# TSE large-cap hard-to-borrow is higher; document when overriding.
DEFAULT_SHORT_BORROW_ANNUAL_BP: float = 50.0
DEFAULT_SHORT_BORROW_ANNUAL: float = DEFAULT_SHORT_BORROW_ANNUAL_BP / 10_000.0
# Trading days per year for daily amortization illustration.
DEFAULT_TRADING_DAYS_PER_YEAR: int = 245

# Leverage / financing (repo-like research default).
# ~25bp annualized over risk-free is a light research placeholder when
# leverage is used; long-only unlevered must state financing_not_applicable.
DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP: float = 25.0
DEFAULT_LEVERAGE_FINANCING_ANNUAL: float = (
    DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP / 10_000.0
)

# Position style tags accepted by checklist v2.
POSITION_STYLE_LONG_ONLY_UNLEVERED: str = "long_only_unlevered"
POSITION_STYLE_LONG_SHORT: str = "long_short"
POSITION_STYLE_LEVERED_LONG: str = "levered_long"
POSITION_STYLE_LEVERED_LONG_SHORT: str = "levered_long_short"
KNOWN_POSITION_STYLES: tuple[str, ...] = (
    POSITION_STYLE_LONG_ONLY_UNLEVERED,
    POSITION_STYLE_LONG_SHORT,
    POSITION_STYLE_LEVERED_LONG,
    POSITION_STYLE_LEVERED_LONG_SHORT,
)


def _freeze_fields() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "edge_claimed": EDGE_CLAIMED,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "label": COST_MODELS_LABEL,
    }


def cost_models_document() -> dict[str, Any]:
    """Public document for research cost-model surface (checklist v2)."""
    doc: dict[str, Any] = {
        "version": COST_MODELS_VERSION,
        "label": COST_MODELS_LABEL,
        "transaction": {
            "one_way_cost_bp": DEFAULT_ONE_WAY_COST_BP,
            "one_way_cost": DEFAULT_ONE_WAY_COST,
            "round_trip_cost_bp": DEFAULT_ONE_WAY_COST_BP * 2.0,
            "round_trip_cost": DEFAULT_ROUND_TRIP_COST,
            "formula_one_way": "net_one_way = gross_signed_mean_active - one_way_cost",
            "change_requires": "cost_change_reason",
            "label": "仮定に依存・研究用・運用GOではない",
        },
        "short_borrow": {
            "default_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
            "default_annual": DEFAULT_SHORT_BORROW_ANNUAL,
            "trading_days_per_year": DEFAULT_TRADING_DAYS_PER_YEAR,
            "formula_daily": (
                "short_borrow_daily ≈ short_borrow_annual / trading_days_per_year"
            ),
            "applies_when": "position_style uses short side (long_short / levered_long_short)",
            "note": (
                "Research stock-lending fee model only. Not a broker borrow quote. "
                "Hard-to-borrow names need higher explicit rates."
            ),
        },
        "leverage_financing": {
            "default_annual_bp": DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP,
            "default_annual": DEFAULT_LEVERAGE_FINANCING_ANNUAL,
            "trading_days_per_year": DEFAULT_TRADING_DAYS_PER_YEAR,
            "formula_daily": (
                "financing_daily ≈ leverage_financing_annual "
                "* max(gross_leverage - 1, 0) / trading_days_per_year"
            ),
            "applies_when": "gross_leverage > 1 (levered styles)",
            "long_only_unlevered_rule": (
                "Must state position_style=long_only_unlevered and "
                "financing_not_applicable=True (or gross_leverage<=1)"
            ),
            "note": "Research repo/financing illustration only. Not operational GO.",
        },
        "known_position_styles": list(KNOWN_POSITION_STYLES),
        "note": (
            "Research cost models for checklist v2. Explicit short/leverage "
            "assumptions required. Pass does not mint READY, arm Mass, or claim edge."
        ),
    }
    doc.update(_freeze_fields())
    return doc


def short_borrow_daily_cost(
    *,
    short_borrow_annual: float = DEFAULT_SHORT_BORROW_ANNUAL,
    short_borrow_annual_bp: float | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    short_fraction: float = 1.0,
) -> float:
    """Daily short-borrow cost fraction of short notional (research).

    Parameters
    ----------
    short_borrow_annual:
        Annualized borrow rate as fraction (default 50bp = 0.005).
    short_borrow_annual_bp:
        If set, overrides annual rate via bp / 10_000.
    trading_days_per_year:
        Days used to amortize annual rate (default 245).
    short_fraction:
        Fraction of gross that is short (0..1+); multiplies daily cost.
    """
    if short_borrow_annual_bp is not None:
        annual = float(short_borrow_annual_bp) / 10_000.0
    else:
        annual = float(short_borrow_annual)
    days = int(trading_days_per_year)
    if days <= 0:
        raise ValueError(f"trading_days_per_year must be positive, got {days}")
    frac = max(0.0, float(short_fraction))
    return (annual / float(days)) * frac


def leverage_financing_daily_cost(
    *,
    gross_leverage: float = 1.0,
    financing_annual: float = DEFAULT_LEVERAGE_FINANCING_ANNUAL,
    financing_annual_bp: float | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> float:
    """Daily financing cost on excess leverage above 1× (research).

    ``gross_leverage <= 1`` → 0 (unlevered long or dollar-neutral L/S with
    no borrowed cash illustration).
    """
    if financing_annual_bp is not None:
        annual = float(financing_annual_bp) / 10_000.0
    else:
        annual = float(financing_annual)
    days = int(trading_days_per_year)
    if days <= 0:
        raise ValueError(f"trading_days_per_year must be positive, got {days}")
    lev = float(gross_leverage)
    excess = max(lev - 1.0, 0.0)
    return (annual * excess) / float(days)


def research_net_with_extended_costs(
    gross_signed_mean: float | None,
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    short_borrow_daily: float = 0.0,
    financing_daily: float = 0.0,
) -> float | None:
    """Research net = gross − one_way − short_borrow_daily − financing_daily.

    All costs are fractional per active unit (same units as gross_signed_mean).
    """
    if gross_signed_mean is None:
        return None
    try:
        g = float(gross_signed_mean)
    except (TypeError, ValueError):
        return None
    return (
        g
        - float(one_way_cost)
        - float(short_borrow_daily)
        - float(financing_daily)
    )


def build_leverage_short_cost_assumption(
    *,
    position_style: str = POSITION_STYLE_LONG_ONLY_UNLEVERED,
    gross_leverage: float = 1.0,
    short_fraction: float = 0.0,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    one_way_cost_bp: float | None = None,
    short_borrow_annual_bp: float | None = None,
    financing_annual_bp: float | None = None,
    trading_days_per_year: int = DEFAULT_TRADING_DAYS_PER_YEAR,
    cost_change_reason: str | None = None,
    short_borrow_change_reason: str | None = None,
    financing_change_reason: str | None = None,
    uses_short: bool | None = None,
    uses_leverage: bool | None = None,
) -> dict[str, Any]:
    """Build explicit leverage/short cost assumption block for checklist v2.

    Long-only unlevered hyps **must** still produce this block with
    ``financing_not_applicable=True`` and ``short_borrow_not_applicable=True``.

    Returns a freeze-wrapped dict. Does not mint READY/Mass.
    """
    style = str(position_style or "").strip().lower() or POSITION_STYLE_LONG_ONLY_UNLEVERED
    if style not in KNOWN_POSITION_STYLES:
        # Accept unknown styles but mark disclosed; still require explicit flags.
        style_known = False
    else:
        style_known = True

    if one_way_cost_bp is not None:
        tx = float(one_way_cost_bp) / 10_000.0
        tx_bp = float(one_way_cost_bp)
    else:
        tx = float(one_way_cost)
        tx_bp = tx * 10_000.0

    # Infer uses_short / uses_leverage from style when not provided.
    if uses_short is None:
        uses_short = style in (
            POSITION_STYLE_LONG_SHORT,
            POSITION_STYLE_LEVERED_LONG_SHORT,
        ) or float(short_fraction) > 0.0
    else:
        uses_short = bool(uses_short)
    if uses_leverage is None:
        uses_leverage = style in (
            POSITION_STYLE_LEVERED_LONG,
            POSITION_STYLE_LEVERED_LONG_SHORT,
        ) or float(gross_leverage) > 1.0 + 1e-12
    else:
        uses_leverage = bool(uses_leverage)

    borrow_bp = (
        float(short_borrow_annual_bp)
        if short_borrow_annual_bp is not None
        else DEFAULT_SHORT_BORROW_ANNUAL_BP
    )
    fin_bp = (
        float(financing_annual_bp)
        if financing_annual_bp is not None
        else DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP
    )

    short_daily = 0.0
    short_not_applicable = not uses_short
    if uses_short:
        sf = float(short_fraction) if float(short_fraction) > 0 else 0.5
        short_daily = short_borrow_daily_cost(
            short_borrow_annual_bp=borrow_bp,
            trading_days_per_year=trading_days_per_year,
            short_fraction=sf,
        )

    fin_daily = 0.0
    financing_not_applicable = not uses_leverage
    lev = float(gross_leverage)
    if uses_leverage:
        if lev <= 1.0:
            lev = 1.0  # caller said uses leverage but leverage<=1 → no excess
            financing_not_applicable = True
            fin_daily = 0.0
        else:
            fin_daily = leverage_financing_daily_cost(
                gross_leverage=lev,
                financing_annual_bp=fin_bp,
                trading_days_per_year=trading_days_per_year,
            )

    # Long-only unlevered: force N/A disclosure.
    if style == POSITION_STYLE_LONG_ONLY_UNLEVERED and not uses_short and not uses_leverage:
        short_not_applicable = True
        financing_not_applicable = True
        short_daily = 0.0
        fin_daily = 0.0
        lev = min(lev, 1.0)

    default_tx = float(DEFAULT_ONE_WAY_COST)
    tx_changed = abs(tx - default_tx) > 1e-15
    borrow_changed = abs(borrow_bp - DEFAULT_SHORT_BORROW_ANNUAL_BP) > 1e-12
    fin_changed = abs(fin_bp - DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP) > 1e-12

    # Completeness: style disclosed + short/leverage assumptions explicit.
    disclosed = True
    missing: list[str] = []
    if not style:
        disclosed = False
        missing.append("position_style")
    if uses_short and short_borrow_annual_bp is None and not short_not_applicable:
        # default rate is OK if uses_short — defaults count as disclosed
        pass
    if uses_short and float(short_fraction) <= 0 and style in (
        POSITION_STYLE_LONG_SHORT,
        POSITION_STYLE_LEVERED_LONG_SHORT,
    ):
        # short_fraction defaulted to 0.5 above when uses_short; mark explicit
        pass
    if tx_changed and not (cost_change_reason and str(cost_change_reason).strip()):
        disclosed = False
        missing.append("cost_change_reason")
    if (
        uses_short
        and borrow_changed
        and not (short_borrow_change_reason and str(short_borrow_change_reason).strip())
    ):
        disclosed = False
        missing.append("short_borrow_change_reason")
    if (
        uses_leverage
        and fin_changed
        and not (financing_change_reason and str(financing_change_reason).strip())
    ):
        disclosed = False
        missing.append("financing_change_reason")

    assumptions_complete = disclosed and (
        short_not_applicable or uses_short
    ) and (
        financing_not_applicable or uses_leverage or lev <= 1.0
    )

    out: dict[str, Any] = {
        "version": COST_MODELS_VERSION,
        "kind": "leverage_short_cost_assumption",
        "position_style": style,
        "position_style_known": style_known,
        "gross_leverage": lev,
        "short_fraction": (
            float(short_fraction)
            if uses_short
            else 0.0
        ),
        "uses_short": uses_short,
        "uses_leverage": uses_leverage,
        "transaction": {
            "one_way_cost": tx,
            "one_way_cost_bp": tx_bp,
            "round_trip_cost": tx * 2.0,
            "round_trip_cost_bp": tx_bp * 2.0,
            "default_one_way_cost": default_tx,
            "changed_from_default": tx_changed,
            "change_reason": (
                str(cost_change_reason).strip() if cost_change_reason else None
            ),
            "formula": "net_one_way = gross_signed_mean_active - one_way_cost",
        },
        "short_borrow": {
            "not_applicable": short_not_applicable,
            "annual_bp": borrow_bp if uses_short else None,
            "annual": (borrow_bp / 10_000.0) if uses_short else None,
            "daily_cost": short_daily,
            "daily_cost_bp": short_daily * 10_000.0,
            "trading_days_per_year": int(trading_days_per_year),
            "default_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
            "changed_from_default": borrow_changed if uses_short else False,
            "change_reason": (
                str(short_borrow_change_reason).strip()
                if short_borrow_change_reason
                else None
            ),
            "formula": (
                "short_borrow_daily ≈ (annual_bp/10000) / trading_days "
                "* short_fraction"
            ),
            "note": (
                "Research stock-lending fee model. "
                if uses_short
                else "Short side not used; borrow fee N/A (explicit)."
            ),
        },
        "leverage_financing": {
            "not_applicable": financing_not_applicable,
            "annual_bp": fin_bp if uses_leverage and not financing_not_applicable else None,
            "annual": (
                (fin_bp / 10_000.0)
                if uses_leverage and not financing_not_applicable
                else None
            ),
            "daily_cost": fin_daily,
            "daily_cost_bp": fin_daily * 10_000.0,
            "gross_leverage": lev,
            "trading_days_per_year": int(trading_days_per_year),
            "default_annual_bp": DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP,
            "changed_from_default": fin_changed if uses_leverage else False,
            "change_reason": (
                str(financing_change_reason).strip()
                if financing_change_reason
                else None
            ),
            "formula": (
                "financing_daily ≈ (annual_bp/10000) * max(gross_leverage-1,0) "
                "/ trading_days"
            ),
            "note": (
                "Research financing/repo illustration. "
                if uses_leverage and not financing_not_applicable
                else "Unlevered or financing N/A (explicit)."
            ),
        },
        "combined_daily_extra_cost": short_daily + fin_daily,
        "combined_daily_extra_cost_bp": (short_daily + fin_daily) * 10_000.0,
        "net_formula_extended": (
            "net = gross - one_way_cost - short_borrow_daily - financing_daily"
        ),
        "assumptions_disclosed": disclosed,
        "assumptions_complete": bool(assumptions_complete),
        "missing_disclosure": missing,
        "label": "仮定に依存・研究用・運用GOではない",
        "note": (
            "Explicit leverage/short cost assumptions for checklist v2. "
            "Long-only unlevered must still state N/A. Not READY / not Mass."
        ),
    }
    out.update(_freeze_fields())
    return out


def default_long_only_unlevered_cost_assumption(
    *,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    cost_change_reason: str | None = None,
) -> dict[str, Any]:
    """Convenience: long-only unlevered with base 10bp + explicit N/A shorts/lev."""
    return build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_ONLY_UNLEVERED,
        gross_leverage=1.0,
        short_fraction=0.0,
        one_way_cost=one_way_cost,
        cost_change_reason=cost_change_reason,
        uses_short=False,
        uses_leverage=False,
    )


def annotate_period_rows_with_extended_costs(
    period_rows: Sequence[Mapping[str, Any]],
    *,
    cost_assumption: Mapping[str, Any] | None = None,
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
) -> list[dict[str, Any]]:
    """Copy period rows adding extended net fields (research illustration)."""
    ca = dict(cost_assumption) if cost_assumption is not None else {}
    tx = float(ca.get("transaction", {}).get("one_way_cost", one_way_cost))
    short_d = float(ca.get("short_borrow", {}).get("daily_cost") or 0.0)
    fin_d = float(ca.get("leverage_financing", {}).get("daily_cost") or 0.0)
    out: list[dict[str, Any]] = []
    for raw in period_rows:
        row = dict(raw)
        gross = row.get("gross_signed_mean_active")
        if gross is None:
            gross = row.get("gross_signed_mean")
        try:
            g = float(gross) if gross is not None else None
        except (TypeError, ValueError):
            g = None
        net_ext = research_net_with_extended_costs(
            g,
            one_way_cost=tx,
            short_borrow_daily=short_d,
            financing_daily=fin_d,
        )
        row["gross_signed_mean_active"] = g
        row["net_one_way_mean_active"] = (
            (g - tx) if g is not None else None
        )
        row["net_extended_mean_active"] = net_ext
        row["one_way_cost"] = tx
        row["short_borrow_daily"] = short_d
        row["financing_daily"] = fin_d
        row["extended_cost_formula"] = (
            "net_extended = gross - one_way - short_borrow_daily - financing_daily"
        )
        out.append(row)
    return out


__all__ = [
    "CONNECTED_TO_MASS",
    "CONNECTED_TO_READY",
    "COST_MODELS_LABEL",
    "COST_MODELS_VERSION",
    "DEFAULT_LEVERAGE_FINANCING_ANNUAL",
    "DEFAULT_LEVERAGE_FINANCING_ANNUAL_BP",
    "DEFAULT_ONE_WAY_COST",
    "DEFAULT_ONE_WAY_COST_BP",
    "DEFAULT_ROUND_TRIP_COST",
    "DEFAULT_SHORT_BORROW_ANNUAL",
    "DEFAULT_SHORT_BORROW_ANNUAL_BP",
    "DEFAULT_TRADING_DAYS_PER_YEAR",
    "EDGE_CLAIMED",
    "KNOWN_POSITION_STYLES",
    "MASS_RESEARCH",
    "OPERATIONAL_GO",
    "PHASE7",
    "POSITION_STYLE_LEVERED_LONG",
    "POSITION_STYLE_LEVERED_LONG_SHORT",
    "POSITION_STYLE_LONG_ONLY_UNLEVERED",
    "POSITION_STYLE_LONG_SHORT",
    "READY_DECLARED",
    "SIGNIFICANCE_CLAIMED",
    "annotate_period_rows_with_extended_costs",
    "build_leverage_short_cost_assumption",
    "cost_models_document",
    "default_long_only_unlevered_cost_assumption",
    "leverage_financing_daily_cost",
    "research_net_with_extended_costs",
    "short_borrow_daily_cost",
]
