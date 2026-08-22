"""CF bar-native logic specs.

SoT for the 30 CF-evaluable bar-native logics (period-net). Factory templates
consume this module for the overlapping ids (six factory-only ids stay offline).
``cf_mass_eval_job`` / ``cf_daily_path_job`` load this instead of the factory.

Not the W65 rejected S1–S5 baseline catalog (``research.baseline_catalog``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

_BARS: tuple[str, ...] = ("equities_bars_daily", "markets_calendar")
_BARS_IDX: tuple[str, ...] = _BARS + ("indices_bars_daily_topix",)
_BARS_IDX_FUT: tuple[str, ...] = _BARS_IDX + (
    "indices_bars_daily",
    "derivatives_bars_daily_futures",
)
_BARS_OPT: tuple[str, ...] = _BARS + ("derivatives_bars_daily_options_225",)
_BARS_REPO: tuple[str, ...] = _BARS_IDX + ("jsda_tokyo_repo_rates",)
_BARS_FINS: tuple[str, ...] = ("fins_summary",) + _BARS
_BARS_MARGIN: tuple[str, ...] = ("markets_margin_interest",) + _BARS
_BARS_MARGIN_SHORT: tuple[str, ...] = (
    "markets_margin_interest",
    "markets_short_ratio",
) + _BARS
_BARS_FINS_REPO: tuple[str, ...] = ("fins_summary", "jsda_tokyo_repo_rates") + _BARS

_FAMILY_MDH: str = "multi_day_hold"
_FAMILY_XS: str = "cross_section_relative"
_FAMILY_MACRO: str = "macro_conditioned"
_FAMILY_FUND: str = "fundamentals_price"
_FAMILY_FLOW: str = "flow_demand"
_FAMILY_VOL: str = "vol_risk_adjusted"
_FAMILY_MF: str = "multi_factor"
_FAMILY_NKY: str = "index_vol_regime"
_FAMILY_OPT: str = "options_vol_regime"


def _fingerprint(
    *,
    logic_id: str,
    family_id: str,
    signal_definition: str,
    position_rule: str,
    datasets_used: Sequence[str],
    params: Mapping[str, Any],
    structural_keys: Sequence[str],
) -> str:
    payload = {
        "logic_id": logic_id,
        "family_id": family_id,
        "signal_definition": signal_definition,
        "position_rule": position_rule,
        "datasets": list(datasets_used),
        "structural": {
            k: params.get(k) for k in structural_keys if k in params
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _spec(
    logic_id: str,
    *,
    family_id: str,
    params: Mapping[str, Any],
    thesis: str,
    signal_definition: str,
    position_rule: str,
    datasets_used: Sequence[str],
    structural_keys: Sequence[str] = (),
) -> dict[str, Any]:
    p = dict(params)
    sk = tuple(structural_keys)
    return {
        "logic_id": logic_id,
        "family_id": family_id,
        "params": p,
        "thesis": thesis,
        "signal_definition": signal_definition,
        "position_rule": position_rule,
        "datasets_used": list(datasets_used),
        "structural_keys": list(sk),
        "logic_fingerprint": _fingerprint(
            logic_id=logic_id,
            family_id=family_id,
            signal_definition=signal_definition,
            position_rule=position_rule,
            datasets_used=datasets_used,
            params=p,
            structural_keys=sk,
        ),
    }


# Insertion order is CF_BAR_NATIVE_LOGIC_IDS.
BAR_NATIVE_SPECS: dict[str, dict[str, Any]] = {
    "mdh_sticky_momentum": _spec(
        "mdh_sticky_momentum",
        family_id=_FAMILY_MDH,
        params={
            "hold_days": 10,
            "momentum_n": 10,
            "rebalance_mode": "fixed_horizon",
            "signal_polarity": 1,
        },
        thesis="Short-horizon winners continue over multi-day sticky holds",
        signal_definition="sign(momentum_n) with n=hold; no daily flip",
        position_rule="fixed_horizon sticky hold; equal-weight active longs/shorts",
        datasets_used=_BARS_IDX,
        structural_keys=("rebalance_mode", "signal_polarity"),
    ),
    "mdh_mean_reversion": _spec(
        "mdh_mean_reversion",
        family_id=_FAMILY_MDH,
        params={
            "hold_days": 10,
            "momentum_n": 10,
            "rebalance_mode": "fixed_horizon",
            "signal_polarity": -1,
        },
        thesis="Short-horizon moves reverse over multi-day holds (opposite entry)",
        signal_definition="−sign(momentum_n); reversion entry (not eval-time sign flip)",
        position_rule="fixed_horizon sticky hold of reversion signs",
        datasets_used=_BARS_IDX,
        structural_keys=("rebalance_mode", "signal_polarity"),
    ),
    "xs_rank_ls_sticky": _spec(
        "xs_rank_ls_sticky",
        family_id=_FAMILY_XS,
        params={
            "hold_days": 10,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "book_mode": "balanced_ls",
        },
        thesis="Relative strength: long top rank mom, short bottom, multi-day sticky",
        signal_definition="same-day cross-section momentum ranks → L/S signs",
        position_rule="sticky fixed_horizon hold of daily rank signs; balanced L/S book",
        datasets_used=_BARS_IDX,
        structural_keys=("book_mode",),
    ),
    "xs_rank_ls_daily": _spec(
        "xs_rank_ls_daily",
        family_id=_FAMILY_XS,
        params={
            "hold_days": 1,
            "momentum_n": 5,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "book_mode": "balanced_ls_daily",
        },
        thesis="Relative strength harvested via daily rebalance (higher turnover)",
        signal_definition="same-day rank L/S on momentum",
        position_rule="hold_days=1 daily rebalance; balanced L/S",
        datasets_used=_BARS_IDX,
        structural_keys=("book_mode",),
    ),
    "vol_risk_adjusted_mom": _spec(
        "vol_risk_adjusted_mom",
        family_id=_FAMILY_VOL,
        params={
            "hold_days": 10,
            "momentum_n": 10,
            "vol_n": 10,
            "vol_threshold": 1.0,
            "gate_mode": "mom_over_vol",
        },
        thesis="Momentum only when conviction |mom|/vol exceeds a risk floor",
        signal_definition="sign(mom) only if |mom|/realized_vol ≥ threshold else flat",
        position_rule="fixed_horizon sticky hold of risk-gated signs",
        datasets_used=_BARS,
        structural_keys=("gate_mode",),
    ),
    "vol_breakout_expand": _spec(
        "vol_breakout_expand",
        family_id=_FAMILY_VOL,
        params={
            "hold_days": 10,
            "momentum_n": 10,
            "vol_n": 10,
            "vol_threshold": 1.0,
            "gate_mode": "vol_expand",
        },
        thesis="Trend entries only when realized vol is expanding (breakout regime)",
        signal_definition="sign(mom) only if recent_vol / prior_vol ≥ expand_ratio",
        position_rule="fixed_horizon sticky hold of expansion-gated signs",
        datasets_used=_BARS,
        structural_keys=("gate_mode",),
    ),
    "nky_vol_abs_level": _spec(
        "nky_vol_abs_level",
        family_id=_FAMILY_NKY,
        params={
            "mode": "nky_vol_abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 0.20,
            "low_threshold": 0.10,
        },
        thesis=(
            "Absolute Nikkei (NK225F) / TOPIX realized-vol level is a risk "
            "regime: low index RV → risk-on keep CS relative strength; "
            "high index RV → risk-off reverse CS; mid → flat"
        ),
        signal_definition=(
            "CS rank(mom) L-S risk-adjusted by absolute index RV "
            "(short-window annualized); not per-name |mom|/vol gate"
        ),
        position_rule="sticky fixed_horizon balanced L/S after abs-vol book transform",
        datasets_used=_BARS_IDX_FUT,
        structural_keys=("mode",),
    ),
    "nky_vol_term_levels": _spec(
        "nky_vol_term_levels",
        family_id=_FAMILY_NKY,
        params={
            "mode": "nky_vol_term_levels",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 0.20,
            "low_threshold": 0.10,
        },
        thesis=(
            "Joint short- and long-window index RV levels: both calm → "
            "risk-on CS; both stressed → risk-off reverse; disagreement → flat"
        ),
        signal_definition=(
            "CS rank mom L-S; regime requires short RV and long RV to agree "
            "on high or low absolute levels (not ratio-only)"
        ),
        position_rule="sticky fixed_horizon balanced L/S after dual-level vol transform",
        datasets_used=_BARS_IDX_FUT,
        structural_keys=("mode", "vol_short_n", "vol_long_n"),
    ),
    "nky_vol_term_ratio": _spec(
        "nky_vol_term_ratio",
        family_id=_FAMILY_NKY,
        params={
            "mode": "nky_vol_term_ratio",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "expand_ratio": 1.20,
            "compress_ratio": 0.80,
        },
        thesis=(
            "Index RV term structure (short/long): compressing → risk-on keep "
            "CS; expanding → risk-off reverse; mid → no trade"
        ),
        signal_definition=(
            "ratio = RV_short/RV_long on Nikkei proxy; CS L-S risk-adjusted "
            "by expand/compress regime (index-level, not per-name expand)"
        ),
        position_rule="sticky fixed_horizon balanced L/S after vol-term-ratio transform",
        datasets_used=_BARS_IDX_FUT,
        structural_keys=("mode", "vol_short_n", "vol_long_n"),
    ),
    "opt225_basevol_abs_level": _spec(
        "opt225_basevol_abs_level",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_basevol_abs_level",
            "series_kind": "basevol",
            "transform": "abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 24.0,
            "low_threshold": 12.0,
        },
        thesis=(
            "Absolute Nikkei 225 options BaseVol level (exchange ATM base, "
            "percent vol points) is a risk regime: low → risk-on keep CS; "
            "high → risk-off reverse; mid → flat"
        ),
        signal_definition=(
            "CS rank(mom) L-S risk-adjusted by abs BaseVol level; "
            "dataset=derivatives_bars_daily_options_225 (COMPLETE SoT)"
        ),
        position_rule="sticky fixed_horizon balanced L/S after abs-BaseVol transform",
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind"),
    ),
    "opt225_basevol_term_levels": _spec(
        "opt225_basevol_term_levels",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_basevol_term_levels",
            "series_kind": "basevol",
            "transform": "term_levels",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 24.0,
            "low_threshold": 12.0,
        },
        thesis=(
            "Joint short/long rolling BaseVol levels: both calm → risk-on; "
            "both stressed → risk-off; disagreement → flat"
        ),
        signal_definition=(
            "CS rank mom L-S; short+long BaseVol rolling means must agree"
        ),
        position_rule=(
            "sticky fixed_horizon balanced L/S after dual-level BaseVol transform"
        ),
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind", "vol_short_n", "vol_long_n"),
    ),
    "opt225_basevol_term_ratio": _spec(
        "opt225_basevol_term_ratio",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_basevol_term_ratio",
            "series_kind": "basevol",
            "transform": "term_ratio",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "expand_ratio": 1.20,
            "compress_ratio": 0.80,
        },
        thesis=(
            "BaseVol term structure (short/long rolling means): compressing → "
            "risk-on; expanding → risk-off; mid → no trade"
        ),
        signal_definition="ratio=BaseVol_short/BaseVol_long; expand/compress thresholds",
        position_rule=(
            "sticky fixed_horizon balanced L/S after BaseVol term-ratio transform"
        ),
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind", "vol_short_n", "vol_long_n"),
    ),
    "opt225_atm_iv_abs_level": _spec(
        "opt225_atm_iv_abs_level",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_atm_iv_abs_level",
            "series_kind": "atm_iv",
            "transform": "abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 25.0,
            "low_threshold": 12.0,
            "compare_only": True,
        },
        thesis=(
            "Reconstructed front-CM ATM IV (call+put mid) — compare-only vs "
            "canonical BaseVol level (W94)"
        ),
        signal_definition=(
            "CS rank mom L-S × abs ATM IV; front CM min_dte>=6; "
            "strike≈UnderPx; avg put/call IV"
        ),
        position_rule="sticky fixed_horizon balanced L/S after abs-ATM-IV transform",
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind"),
    ),
    "opt225_atm_iv_term_levels": _spec(
        "opt225_atm_iv_term_levels",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_atm_iv_term_levels",
            "series_kind": "atm_iv",
            "transform": "term_levels",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 25.0,
            "low_threshold": 12.0,
            "compare_only": True,
        },
        thesis=(
            "Joint short/long ATM IV levels (compare-only vs BaseVol dual levels)"
        ),
        signal_definition="CS rank mom L-S; short+long ATM IV rolling means agree",
        position_rule=(
            "sticky fixed_horizon balanced L/S after dual-level ATM IV transform"
        ),
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind", "vol_short_n", "vol_long_n"),
    ),
    "opt225_atm_iv_term_ratio": _spec(
        "opt225_atm_iv_term_ratio",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_atm_iv_term_ratio",
            "series_kind": "atm_iv",
            "transform": "term_ratio",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "expand_ratio": 1.20,
            "compress_ratio": 0.80,
            "compare_only": True,
        },
        thesis="ATM IV short/long ratio (compare-only vs BaseVol term ratio)",
        signal_definition="ratio=ATM_IV_short/ATM_IV_long; expand/compress thresholds",
        position_rule=(
            "sticky fixed_horizon balanced L/S after ATM IV term-ratio transform"
        ),
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind", "vol_short_n", "vol_long_n"),
    ),
    "opt225_iv_base_spread_abs": _spec(
        "opt225_iv_base_spread_abs",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_iv_base_spread_abs",
            "series_kind": "spread",
            "transform": "abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 1.0,
            "low_threshold": -0.5,
            "compare_only": True,
        },
        thesis=(
            "Spread = ATM IV − BaseVol — compare-only residual (W93: "
            "non-informative at frozen thresholds post min_dte=6)"
        ),
        signal_definition=(
            "CS rank mom L-S × abs(atm_iv - base_vol); convention documented "
            "as ATM−BaseVol (not reversed)"
        ),
        position_rule="sticky fixed_horizon balanced L/S after spread-level transform",
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind"),
    ),
    "opt225_iv_base_spread_change": _spec(
        "opt225_iv_base_spread_change",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_iv_base_spread_change",
            "series_kind": "spread_change",
            "transform": "abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 0.5,
            "low_threshold": -0.5,
            "compare_only": True,
        },
        thesis="Day-over-day change in (ATM IV − BaseVol) — compare-only residual",
        signal_definition=(
            "CS rank mom L-S × Δ(atm_iv - base_vol); gaps → no trade "
            "(no invent/ffill)"
        ),
        position_rule=(
            "sticky fixed_horizon balanced L/S after spread-change transform"
        ),
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind"),
    ),
    "opt225_skew_abs_level": _spec(
        "opt225_skew_abs_level",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_skew_abs_level",
            "series_kind": "skew",
            "transform": "abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 3.0,
            "low_threshold": 0.5,
        },
        thesis=(
            "Put skew = IV(listed strike≈0.95*UnderPx) − ATM mid IV: elevated "
            "crash-premium / risk-off → reverse CS; calm skew → risk-on keep"
        ),
        signal_definition=(
            "CS rank mom L-S × abs skew; front CM min_dte>=6; listed put "
            "nearest 0.95*UnderPx (never invent/interpolate strikes)"
        ),
        position_rule="sticky fixed_horizon balanced L/S after abs-skew transform",
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind"),
    ),
    "opt225_cm_term_abs_level": _spec(
        "opt225_cm_term_abs_level",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_cm_term_abs_level",
            "series_kind": "cm_term",
            "transform": "abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 2.0,
            "low_threshold": -1.0,
        },
        thesis=(
            "Calendar-month IV term (near ATM − next ATM): steep/inverted "
            "term structure is a risk regime for CS books"
        ),
        signal_definition=(
            "CS rank mom L-S × abs(near_atm_iv − next_atm_iv); both CMs "
            "min_dte>=6; listed ATM strikes only"
        ),
        position_rule="sticky fixed_horizon balanced L/S after abs CM-term transform",
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind"),
    ),
    "opt225_basevol_delta_abs": _spec(
        "opt225_basevol_delta_abs",
        family_id=_FAMILY_OPT,
        params={
            "mode": "opt225_basevol_delta_abs",
            "series_kind": "basevol_delta",
            "transform": "abs_level",
            "momentum_n": 5,
            "hold_days": 10,
            "long_frac": 0.3,
            "short_frac": 0.3,
            "vol_short_n": 10,
            "vol_long_n": 60,
            "high_threshold": 1.0,
            "low_threshold": -1.0,
        },
        thesis=(
            "Day-over-day BaseVol change (canonical level): rising → risk-off "
            "reverse CS; falling → risk-on keep; mid → flat"
        ),
        signal_definition=(
            "CS rank mom L-S × abs(BaseVol[t]−BaseVol[t-1]); first day omitted; "
            "no invent/ffill"
        ),
        position_rule="sticky fixed_horizon balanced L/S after abs-ΔBaseVol transform",
        datasets_used=_BARS_OPT,
        structural_keys=("mode", "series_kind"),
    ),
    "macro_repo_rate_change": _spec(
        "macro_repo_rate_change",
        family_id=_FAMILY_MACRO,
        params={
            "mode": "rate_change",
            "momentum_n": 10,
            "hold_days": 10,
            "high_threshold": 0.05,
            "low_threshold": 0.0,
        },
        thesis="Equity mom works differently under repo tightening vs easing",
        signal_definition="momentum gated/conditioned by Tokyo repo rate_change regime",
        position_rule="sticky multi-day hold under regime filter",
        datasets_used=_BARS_REPO,
        structural_keys=("mode",),
    ),
    "macro_repo_rate_level": _spec(
        "macro_repo_rate_level",
        family_id=_FAMILY_MACRO,
        params={
            "mode": "rate_level",
            "momentum_n": 10,
            "hold_days": 10,
            "high_threshold": 0.05,
            "low_threshold": 0.0,
        },
        thesis="Equity mom differs in high vs low absolute funding-rate regimes",
        signal_definition="momentum conditioned on Tokyo repo rate_level regime",
        position_rule="sticky multi-day hold under level regime filter",
        datasets_used=_BARS_REPO,
        structural_keys=("mode",),
    ),
    "flow_margin_pressure": _spec(
        "flow_margin_pressure",
        family_id=_FAMILY_FLOW,
        params={
            "hold_days": 10,
            "short_confirm_mode": "off",
            "require_short_confirm": False,
        },
        thesis="Rising margin interest proxies demand that persists multi-day",
        signal_definition="multi-day margin flow pressure (not S4 daily)",
        position_rule="min_hold sticky; no short-sale confirm",
        datasets_used=_BARS_MARGIN,
        structural_keys=("short_confirm_mode",),
    ),
    "flow_margin_short_hard": _spec(
        "flow_margin_short_hard",
        family_id=_FAMILY_FLOW,
        params={
            "hold_days": 10,
            "short_confirm_mode": "hard",
            "require_short_confirm": True,
        },
        thesis="Margin demand only when short-interest confirms directional pressure",
        signal_definition="margin flow AND hard short-ratio confirm filter",
        position_rule="min_hold sticky; hard short confirm required",
        datasets_used=_BARS_MARGIN_SHORT,
        structural_keys=("short_confirm_mode",),
    ),
    "flow_margin_short_soft": _spec(
        "flow_margin_short_soft",
        family_id=_FAMILY_FLOW,
        params={
            "hold_days": 10,
            "short_confirm_mode": "soft",
            "require_short_confirm": False,
        },
        thesis="Margin demand with soft short-interest tilt (not hard veto)",
        signal_definition="margin flow with soft short-ratio modulation",
        position_rule="min_hold sticky; soft short confirm",
        datasets_used=_BARS_MARGIN_SHORT,
        structural_keys=("short_confirm_mode",),
    ),
    "fund_value_only": _spec(
        "fund_value_only",
        family_id=_FAMILY_FUND,
        params={
            "hold_days": 10,
            "momentum_n": 10,
            "mode": "value_only",
        },
        thesis="Cheap (PIT value) names earn a multi-day premium vs expensive",
        signal_definition="PIT fundamental_value_score sign only (no mom confirm)",
        position_rule="sticky fixed_horizon hold of value signs",
        datasets_used=_BARS_FINS,
        structural_keys=("mode",),
    ),
    "fund_value_mom_agree": _spec(
        "fund_value_mom_agree",
        family_id=_FAMILY_FUND,
        params={
            "hold_days": 10,
            "momentum_n": 10,
            "mode": "value_momentum_agree",
        },
        thesis="Value and price momentum agreement improves multi-day edge",
        signal_definition="enter only when value score and mom agree in sign",
        position_rule="sticky fixed_horizon hold of agree-filtered signs",
        datasets_used=_BARS_FINS,
        structural_keys=("mode",),
    ),
    "fund_value_mom_agree_slow": _spec(
        "fund_value_mom_agree_slow",
        family_id=_FAMILY_FUND,
        params={
            "hold_days": 10,
            "momentum_n": 20,
            "mode": "value_momentum_agree",
            "mom_structure": "slow_20",
        },
        thesis="Value confirmed by slower price mom (20d) is a different agreement filter",
        signal_definition="value × slow mom agree",
        position_rule="sticky hold; slow mom confirm pin",
        datasets_used=_BARS_FINS,
        structural_keys=("mode", "mom_structure"),
    ),
    "mf_value_mom_rate": _spec(
        "mf_value_mom_rate",
        family_id=_FAMILY_MF,
        params={
            "mode": "value_mom_rate",
            "hold_days": 10,
            "momentum_n": 10,
            "high_threshold": 0.05,
            "low_threshold": 0.0,
        },
        thesis=(
            "Cheap winners under easy/mid funding and expensive losers under "
            "tight/mid funding earn a multi-day premium (three-factor agreement)"
        ),
        signal_definition=(
            "value_mom_agree AND funding alignment "
            "(long only if rate not high; short only if rate not low)"
        ),
        position_rule="sticky fixed_horizon hold of triple-agree signs",
        datasets_used=_BARS_FINS_REPO,
        structural_keys=("mode",),
    ),
    "mf_flow_price": _spec(
        "mf_flow_price",
        family_id=_FAMILY_MF,
        params={
            "mode": "flow_price",
            "hold_days": 10,
            "momentum_n": 10,
            "confirm": "price_mom",
        },
        thesis=(
            "Margin demand pressure earns multi-day only when price momentum "
            "confirms the flow direction (flow×price co-movement)"
        ),
        signal_definition="enter only when sign(margin_change)==sign(price_mom)",
        position_rule="min_hold sticky; price confirm (not short-ratio confirm)",
        datasets_used=_BARS_MARGIN,
        structural_keys=("mode", "confirm"),
    ),
}

BAR_NATIVE_LOGIC_IDS: tuple[str, ...] = tuple(BAR_NATIVE_SPECS)

if len(BAR_NATIVE_SPECS) < 30:
    raise RuntimeError(
        f"BAR_NATIVE_SPECS must have ≥30 ids, got {len(BAR_NATIVE_SPECS)}"
    )
