"""Offline W78–W86 multi-year orchestration surface (not CF SoT; no GO).

``run_class_hyp_multi_year_eval`` body. Local bar mirrors + SQLite only;
not Mass / READY / Phase7 / operational GO.
"""

from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from features.class_signals import (
    CLASS_EVENT_POST,
    CLASS_FLOW_DEMAND,
    CLASS_FUNDAMENTALS_PRICE,
    CLASS_MACRO_CONDITIONED,
    CLASS_MULTI_DAY_HOLD,
    DEFAULT_EVENT_POST_HOLD_DAYS,
    DEFAULT_FLOW_HOLD_DAYS,
    DEFAULT_FUND_HOLD_DAYS,
    DEFAULT_FUND_MOMENTUM_N,
    DEFAULT_HOLD_DAYS,
    DEFAULT_MAX_YEAR_POS_NET_SHARE,
    DEFAULT_MIN_ABS_T_STAT,
    DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
    DEFAULT_MIN_ECONOMIC_NET,
    DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
    DEFAULT_MIN_PERIOD_WIN_RATE,
    DEFAULT_MIN_POSITIVE_PERIODS,
    DEFAULT_MIN_SHARPE_PERIOD,
    DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE,
    DEFAULT_TRADING_DAYS_PER_YEAR,
    EVENT_POST_ENTRY_MODE,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MULTI_DAY_HOLD,
    SUPPORTED_HOLD_DAYS,
    class_signal_definitions,
    class_signals_document,
    economic_net_meaningful,
    multi_year_skew_check,
    occurrence_rate_event_post,
    occurrence_rate_multiday,
    production_candidate_bar,
)
from research.cost_models import (
    DEFAULT_ONE_WAY_COST,
    REPO_DATASET_ID,
    SHORT_BORROW_SPREAD_SENSITIVITY,
    apply_liquidity_to_one_way_cost,
    build_leverage_short_cost_assumption,
    compute_liquidity_proxy_from_bars,
    default_long_only_unlevered_cost_assumption,
    liquidity_bucket_from_proxy,
    liquidity_cost_multipliers,
    load_repo_rate_series_from_rows,
    mean_repo_rate_pct,
    remeasure_period_rows_with_short_cost,
)
from research.eval_loaders import (
    DEFAULT_BARS_MIRROR_DIR,
    bars_rich_to_close_panel,
    collect_liquidity_bar_rows,
    load_bars_ndjson_rich,
    load_fins_earnings_date_from_sqlite,
    load_margin_from_sqlite,
    load_margin_ndjson,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
    merge_event_calendars,
    resolve_bars_path,
    resolve_margin_path,
)
from research.eval_tracks import EVAL_TRACK_LIQ_LARGE, EVAL_TRACKS
from research.eval_universe import (
    DEFAULT_SQLITE,
    load_fins_events_from_sqlite,
    select_eval_universe,
)
from research.eval_windows import DEFAULT_PERIODS
from research.freezes import MASS_RESEARCH, PHASE7
from research.holding_metrics import (
    cost_amortization_report,
    holding_metrics_report,
)
from research.offline.bar_eval import (
    _freeze,
    evaluate_cross_section_on_bars,
    evaluate_event_post_on_bars,
    evaluate_flow_demand_on_bars,
    evaluate_fundamentals_price_on_bars,
    evaluate_macro_conditioned_on_bars,
    evaluate_multi_day_hold_on_bars,
)
from research.risk_scenarios import (
    SCENARIO_CRASH,
    SCENARIO_HIGH_VOL,
    SCENARIO_LIQUIDITY_STRESS,
    SCENARIO_RATE_DOWN,
    SCENARIO_RATE_UP,
    evaluate_risk_scenarios,
    scenario_row,
)
from research.robustness_gate import evaluate_research_robustness_gate
from research.sign_selection import (
    SIGN_INVERTED,
    SIGN_ORIGINAL,
    SIGN_SELECTION_VERSION,
    SIGN_SELECTION_WAVE,
    sign_selection_document,
    sign_selection_from_period_rows,
)
from research.stats_metrics import (
    period_stats_report,
    stats_bar_check,
    stats_metrics_document,
)

# Floors SoT is this module (CLASS_HYP_EVAL_VERSION).
CLASS_HYP_EVAL_VERSION: str = "class-hyp-eval/v7"
CLASS_HYP_EVAL_WAVE: str = "W86 / w0816u"
MIN_ECONOMIC_NET: float = DEFAULT_MIN_ECONOMIC_NET
MIN_ACTIVATION_RATE_MULTIDAY: float = DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY
MIN_EVENTS_PER_CODE_YEAR: float = DEFAULT_MIN_EVENTS_PER_CODE_YEAR
MIN_EVENTS_PER_TRADING_DAY: float = DEFAULT_MIN_EVENTS_PER_TRADING_DAY
MIN_YEARS_RESEARCH_CANDIDATE: int = DEFAULT_MIN_YEARS_RESEARCH_CANDIDATE
MAX_YEAR_POS_NET_SHARE: float = DEFAULT_MAX_YEAR_POS_NET_SHARE
MIN_ABS_T_STAT: float = DEFAULT_MIN_ABS_T_STAT
MIN_SHARPE_PERIOD: float = DEFAULT_MIN_SHARPE_PERIOD
MIN_PERIOD_WIN_RATE: float = DEFAULT_MIN_PERIOD_WIN_RATE
MIN_POSITIVE_PERIODS: int = DEFAULT_MIN_POSITIVE_PERIODS


def run_class_hyp_multi_year_eval(
    periods: Sequence[Mapping[str, Any]] | None = None,
    *,
    codes: Sequence[str] | None = None,
    hold_days: int = DEFAULT_HOLD_DAYS,
    macro_mode: str = "rate_change",
    one_way_cost: float = DEFAULT_ONE_WAY_COST,
    mirror_dir: str | Path = DEFAULT_BARS_MIRROR_DIR,
    sqlite_path: str | Path = DEFAULT_SQLITE,
    include_cross_section: bool = True,
    include_cross_section_hold_10: bool = True,
    # W85: promote explore xs hold=10 mom=3 after multi-window paper align.
    include_cross_section_hold_10_mom3: bool = True,
    include_event_post: bool = True,
    include_flow_demand: bool = True,
    include_fundamentals_price: bool = True,
    include_fundamentals_hold_10: bool = True,
    include_multi_day_hold_10: bool = True,
    cross_section_hold_days: int = 5,
    cross_section_momentum_n: int | None = None,
    # Sticky hold=10 uses short mom lookback (W82 pin). Content-matched
    # mom=10 collapses residual (W83 explore) — do not "align" blindly.
    cross_section_hold10_momentum_n: int = 5,
    # W85 promoted: sticky hold=10 with mom=3 (research standout + multi-window paper).
    cross_section_hold10_mom3_momentum_n: int = 3,
    cross_section_long_frac: float = 0.3,
    cross_section_short_frac: float = 0.3,
    event_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    flow_hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    flow_require_short_confirm: bool = False,
    flow_short_confirm_mode: str | None = None,  # off|hard|soft (W85)
    # W85: apply short = f(repo[t]+spread) remeasure on L-S classes (default on).
    apply_short_cost_remeasure: bool = True,
    short_borrow_sensitivity: str = "mid",
    short_fraction_ls: float = 0.5,
    fund_hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    fund_momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
    # W83 candidate: hold=10 mom=10 value×momentum agree (separate block).
    fund_hold10_momentum_n: int = 10,
    fund_mode: str = "value_momentum_agree",
    max_days: int | None = None,
    min_periods_gate: int = 2,
    min_active_per_period: int = 20,
    min_economic_net: float = MIN_ECONOMIC_NET,
    min_activation_rate_multiday: float = MIN_ACTIVATION_RATE_MULTIDAY,
    min_events_per_code_year: float = MIN_EVENTS_PER_CODE_YEAR,
    min_events_per_trading_day: float = MIN_EVENTS_PER_TRADING_DAY,
    min_years_research_candidate: int = MIN_YEARS_RESEARCH_CANDIDATE,
    max_year_pos_net_share: float = MAX_YEAR_POS_NET_SHARE,
    min_abs_t_stat: float = MIN_ABS_T_STAT,
    min_sharpe_period: float = MIN_SHARPE_PERIOD,
    min_period_win_rate: float = MIN_PERIOD_WIN_RATE,
    min_positive_periods: int = MIN_POSITIVE_PERIODS,
    require_stats_bar: bool = True,
    apply_robustness_gate: bool = True,
    prefer_liquidity_linked: bool = True,
    thicken_event_with_earnings_date: bool = True,
    checklist_complete: bool = True,
) -> dict[str, Any]:
    """Multi-year offline eval for all enabled class hyps (W81–W83).

    Uses local W63 Q4 + W64 full bar/margin mirrors and local SQLite
    (jsda_repo_rates, fins_summary, fins_earnings_date, short_ratio).

    Production ``research_candidate=True`` only when gate + economic net +
    occurrence rate + multi-year skew + risk + **statistical bar**
    (|t|, Sharpe, period win-rate) all pass (still not READY/Mass).
    No mean-bp-only promotion. event_post uses W82 PIT entry only.

    W83: default path always includes sticky cross_section hold=10 as a
    separate block when ``include_cross_section_hold_10`` (parallel to
    multi_day_hold_10). Primary ``cross_section_hold_days`` default remains 5.
    """
    period_list = [dict(p) for p in (periods or DEFAULT_PERIODS)]
    selected = (
        [str(c).strip() for c in codes if str(c).strip()]
        if codes is not None
        else select_eval_universe(
            max_codes=int(EVAL_TRACKS[EVAL_TRACK_LIQ_LARGE]["max_codes"])
        )
    )
    h = int(hold_days)
    if h not in SUPPORTED_HOLD_DAYS:
        if h < 1:
            raise ValueError(f"hold_days must be >= 1, got {hold_days!r}")

    # Load full repo series once (research offline; as_of_date keyed).
    repo_rows = load_repo_rows_from_sqlite(sqlite_path)
    repo_series = (
        load_repo_rate_series_from_rows(repo_rows) if repo_rows else None
    )
    repo_load_note = {
        "source": "local_sqlite_jsda_repo_rates",
        "path": str(sqlite_path),
        "n_rows": len(repo_rows),
        "series_n_dates": (
            len((repo_series or {}).get("rates_by_date") or {})
            if repo_series
            else 0
        ),
        "pit_disclosure": (
            "Local jsda_repo_rates rows carry bulk-ingest available_at "
            "(2026). Offline multi-year research keys regime by as_of_date "
            "(event date), not bulk available_at. Disclosed; no invent fill."
        ),
        "dataset": REPO_DATASET_ID,
    }

    # Fins lookback buffer for prior EPS / as-of PIT
    fins_global_start = "2014-01-01"
    fins_global_end = "2026-12-31"
    fins_summary_events = (
        load_fins_events_from_sqlite(
            sqlite_path,
            codes=selected,
            start=fins_global_start,
            end=fins_global_end,
        )
        if (include_event_post or include_fundamentals_price)
        else {}
    )
    earn_date_events: dict[str, list[dict[str, Any]]] = {}
    if thicken_event_with_earnings_date and (
        include_event_post or include_fundamentals_price
    ):
        earn_date_events = load_fins_earnings_date_from_sqlite(
            sqlite_path,
            codes=selected,
            start=fins_global_start,
            end=fins_global_end,
        )
    if thicken_event_with_earnings_date and earn_date_events:
        fins_events = merge_event_calendars(fins_summary_events, earn_date_events)
        event_source = "fins_summary+fins_earnings_date"
    else:
        fins_events = fins_summary_events
        event_source = "fins_summary"
    fins_load_note = {
        "source": "local_sqlite_jquants_records_" + event_source.replace("+", "_"),
        "path": str(sqlite_path),
        "n_codes": len(fins_events),
        "n_events": sum(len(v) for v in fins_events.values()),
        "n_events_fins_summary": sum(len(v) for v in fins_summary_events.values()),
        "n_events_fins_earnings_date": sum(
            len(v) for v in earn_date_events.values()
        ),
        "thickened_with_earnings_date": bool(
            thicken_event_with_earnings_date and earn_date_events
        ),
        "event_source": event_source,
        "pit_disclosure": (
            "fins_summary SoT: DiscDate + DiscTime (aliases DisclosedDate/"
            "DisclosedTime); envelope event_time/available_at when present. "
            "W82 entry = first session close not looking ahead of availability "
            "(after-close or missing DiscTime → next trading bar; no invent "
            "timestamps). fins_earnings_date thickens calendar via PubDate|"
            "SchDate when available; surprise still requires fins_summary "
            "EPS/FEPS (no invent). Disclosed."
        ),
        "entry_mode": EVENT_POST_ENTRY_MODE,
        "dataset": event_source,
    }

    short_series_full = (
        load_short_ratio_series_from_sqlite(
            sqlite_path, section="0050", start="2014-01-01", end="2026-12-31"
        )
        if include_flow_demand
        else []
    )
    short_load_note = {
        "source": "local_sqlite_markets_short_ratio",
        "section": "0050",
        "n_dates": len(short_series_full),
        "dataset": "markets_short_ratio",
        "note": "Market-level S33=0050 ratio for optional flow confirm.",
    }

    results_md: list[dict[str, Any]] = []
    results_md10: list[dict[str, Any]] = []
    results_macro: list[dict[str, Any]] = []
    results_xs: list[dict[str, Any]] = []
    results_xs10: list[dict[str, Any]] = []
    results_xs10_mom3: list[dict[str, Any]] = []
    results_event: list[dict[str, Any]] = []
    results_flow: list[dict[str, Any]] = []
    results_fund: list[dict[str, Any]] = []
    results_fund10: list[dict[str, Any]] = []
    xs_mom_n = (
        int(cross_section_momentum_n)
        if cross_section_momentum_n is not None
        else int(cross_section_hold_days)
    )
    xs10_mom_n = int(cross_section_hold10_momentum_n)
    xs10_mom3_n = int(cross_section_hold10_mom3_momentum_n)
    xs_long_frac = float(cross_section_long_frac)
    xs_short_frac = float(cross_section_short_frac)
    fund_mom_n = int(fund_momentum_n)
    fund10_mom_n = int(fund_hold10_momentum_n)
    fund_mode_s = str(fund_mode or "value_momentum_agree")
    flow_short_confirm = bool(flow_require_short_confirm)

    for raw in period_list:
        p = dict(raw)
        pid = str(p.get("period_id") or p.get("year") or "period")
        year = p.get("year")
        p_start = str(p.get("period_start") or "")[:10] or None
        p_end = str(p.get("period_end") or "")[:10] or None
        bars_path = p.get("bars_path") or resolve_bars_path(
            pid, mirror_dir=mirror_dir
        )
        if bars_path is None or not Path(bars_path).exists():
            skip = {
                "period_id": pid,
                "year": year,
                "status": "skipped",
                "skip_reason": f"bars mirror missing for {pid}",
            }
            results_md.append(skip)
            results_macro.append(dict(skip))
            if include_cross_section:
                results_xs.append(dict(skip))
            if include_cross_section_hold_10:
                results_xs10.append(dict(skip))
            if include_cross_section_hold_10_mom3:
                results_xs10_mom3.append(dict(skip))
            if include_event_post:
                results_event.append(dict(skip))
            if include_flow_demand:
                results_flow.append(dict(skip))
            if include_fundamentals_price:
                results_fund.append(dict(skip))
            if include_fundamentals_hold_10:
                results_fund10.append(dict(skip))
            if include_multi_day_hold_10:
                results_md10.append(dict(skip))
            continue

        try:
            # Full-year windows need more than 80 days; Q4 can stay capped.
            window_kind = str(p.get("window_kind") or "")
            if max_days is not None:
                period_max_days = int(max_days)
            elif "full" in str(pid).lower() or window_kind.startswith("full"):
                period_max_days = 260
            else:
                period_max_days = 80

            rich = load_bars_ndjson_rich(
                bars_path,
                codes=selected,
                max_days=period_max_days,
                period_start=p_start,
                period_end=p_end,
            )
            bars = bars_rich_to_close_panel(rich)
            if not bars:
                raise RuntimeError("no bars after code filter")

            # Liquidity-linked one-way cost (prefer when ADV available)
            liq_rows = collect_liquidity_bar_rows(rich)
            liq_proxy = compute_liquidity_proxy_from_bars(
                liq_rows, source_label=f"bars:{pid}"
            )
            liq_bucket = liquidity_bucket_from_proxy(liq_proxy)
            liq_mults = liquidity_cost_multipliers(
                str(liq_bucket.get("bucket") or "missing")
            )
            tx_mult = (
                float(liq_mults.get("tx_mult") or 1.0)
                if prefer_liquidity_linked
                else 1.0
            )
            if not prefer_liquidity_linked:
                tx_mult = 1.0
            # missing bucket → mult 1.0 unmodulated (no invent)
            if liq_bucket.get("is_gap") or str(liq_bucket.get("bucket")) == "missing":
                if prefer_liquidity_linked:
                    tx_mult = float(liq_mults.get("tx_mult") or 1.0)
            one_way_eff = apply_liquidity_to_one_way_cost(
                one_way_cost, tx_mult=tx_mult
            )
            liq_extra = {
                "liquidity_bucket": liq_bucket.get("bucket"),
                "liquidity_adv_jpy": liq_proxy.get("adv_jpy"),
                "liquidity_tx_mult": tx_mult,
                "one_way_cost_base": float(one_way_cost),
                "one_way_cost_eff": float(one_way_eff),
                "prefer_liquidity_linked": bool(prefer_liquidity_linked),
                "liquidity_is_gap": bool(liq_bucket.get("is_gap")),
            }

            def _period_row(
                eval_out: Mapping[str, Any],
                *,
                signal_id: str,
                extra: Mapping[str, Any] | None = None,
            ) -> dict[str, Any]:
                row = {
                    "period_id": pid,
                    "year": year,
                    "status": "ok",
                    "period_start": p_start,
                    "period_end": p_end,
                    "bars_path": str(bars_path),
                    "window_kind": window_kind or None,
                    "n_codes": eval_out.get("n_codes"),
                    "gross_signed_mean_active": eval_out.get(
                        "gross_signed_mean_active"
                    ),
                    "net_one_way_mean_active": eval_out.get(
                        "net_one_way_mean_active"
                    ),
                    "n_active_positions": eval_out.get("n_active_positions"),
                    "non_null": eval_out.get("non_null")
                    or eval_out.get("n_active_positions"),
                    "non_null_rate": eval_out.get("non_null_rate"),
                    "n_trading_days": eval_out.get("n_trading_days"),
                    "n_code_days": eval_out.get("n_code_days"),
                    "occurrence": eval_out.get("occurrence"),
                    "trade_stats": eval_out.get("trade_stats"),
                    "signal_id": signal_id,
                    "holding_records": eval_out.get("holding_records"),
                    **liq_extra,
                }
                if extra:
                    row.update(dict(extra))
                return row

            md = evaluate_multi_day_hold_on_bars(
                bars, hold_days=h, one_way_cost=one_way_eff
            )
            results_md.append(
                _period_row(
                    md,
                    signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
                    extra={
                        "amortized_one_way_cost": md.get(
                            "amortized_one_way_cost"
                        ),
                        "hold_days": h,
                    },
                )
            )

            if include_multi_day_hold_10 and h != 10:
                md10 = evaluate_multi_day_hold_on_bars(
                    bars, hold_days=10, one_way_cost=one_way_eff
                )
                results_md10.append(
                    _period_row(
                        md10,
                        signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
                        extra={
                            "amortized_one_way_cost": md10.get(
                                "amortized_one_way_cost"
                            ),
                            "hold_days": 10,
                            "variant": "hold_10",
                        },
                    )
                )

            macro = evaluate_macro_conditioned_on_bars(
                bars,
                repo_series,
                momentum_n=h,
                hold_days=h,
                mode=macro_mode,
                one_way_cost=one_way_eff,
            )
            results_macro.append(
                _period_row(
                    macro,
                    signal_id=SIGNAL_ID_MACRO_CONDITIONED,
                    extra={
                        "n_regime_gap": macro.get("n_regime_gap"),
                        "regime_counts": macro.get("regime_counts"),
                        "mode": macro_mode,
                    },
                )
            )

            if include_cross_section:
                xs = evaluate_cross_section_on_bars(
                    bars,
                    momentum_n=xs_mom_n,
                    one_way_cost=one_way_eff,
                    hold_days=int(cross_section_hold_days),
                    long_frac=xs_long_frac,
                    short_frac=xs_short_frac,
                )
                results_xs.append(
                    _period_row(
                        xs,
                        signal_id=SIGNAL_ID_CROSS_SECTION,
                        extra={
                            "hold_days": int(cross_section_hold_days),
                            "momentum_n": xs_mom_n,
                            "long_frac": xs_long_frac,
                            "short_frac": xs_short_frac,
                            "amortized_one_way_cost": xs.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_cross_section_hold_10 and int(cross_section_hold_days) != 10:
                # W83 default path: sticky hold=10 with W82-pin mom lookback
                # (mom=5). Content-matched mom=10 fails multi-year residual.
                xs10 = evaluate_cross_section_on_bars(
                    bars,
                    momentum_n=xs10_mom_n,
                    one_way_cost=one_way_eff,
                    hold_days=10,
                    long_frac=xs_long_frac,
                    short_frac=xs_short_frac,
                )
                results_xs10.append(
                    _period_row(
                        xs10,
                        signal_id=SIGNAL_ID_CROSS_SECTION,
                        extra={
                            "hold_days": 10,
                            "momentum_n": xs10_mom_n,
                            "variant": "hold_10",
                            "long_frac": xs_long_frac,
                            "short_frac": xs_short_frac,
                            "amortized_one_way_cost": xs10.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_cross_section_hold_10_mom3 and not (
                include_cross_section_hold_10 and int(xs10_mom_n) == int(xs10_mom3_n)
            ):
                # W85 promote_default: sticky hold=10 mom=3 (research standout
                # t≈3.0 + multi-window paper majority positive). Parallel to
                # mom=5 pin — does not replace W82 pin block.
                xs10m3 = evaluate_cross_section_on_bars(
                    bars,
                    momentum_n=xs10_mom3_n,
                    one_way_cost=one_way_eff,
                    hold_days=10,
                    long_frac=xs_long_frac,
                    short_frac=xs_short_frac,
                )
                results_xs10_mom3.append(
                    _period_row(
                        xs10m3,
                        signal_id=SIGNAL_ID_CROSS_SECTION,
                        extra={
                            "hold_days": 10,
                            "momentum_n": xs10_mom3_n,
                            "variant": "hold_10_mom3",
                            "long_frac": xs_long_frac,
                            "short_frac": xs_short_frac,
                            "amortized_one_way_cost": xs10m3.get(
                                "amortized_one_way_cost"
                            ),
                            "promoted_wave": "W85 / w0816t",
                        },
                    )
                )

            if include_event_post:
                ep = evaluate_event_post_on_bars(
                    bars,
                    fins_events,
                    post_hold_days=int(event_hold_days),
                    one_way_cost=one_way_eff,
                    period_start=p_start,
                    period_end=p_end,
                )
                results_event.append(
                    _period_row(
                        ep,
                        signal_id=SIGNAL_ID_EVENT_POST,
                        extra={
                            "post_hold_days": int(event_hold_days),
                            "n_events": ep.get("n_events"),
                            "n_no_surprise": ep.get("n_no_surprise"),
                            "n_no_bar_match": ep.get("n_no_bar_match"),
                            "n_same_day_entry": ep.get("n_same_day_entry"),
                            "n_next_session_entry": ep.get(
                                "n_next_session_entry"
                            ),
                            "entry_mode": ep.get("entry_mode"),
                            "amortized_one_way_cost": ep.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_flow_demand:
                margin_path = resolve_margin_path(pid, mirror_dir=mirror_dir)
                if margin_path is not None and Path(margin_path).exists():
                    margin = load_margin_ndjson(margin_path, codes=selected)
                    margin_src = f"ndjson:{margin_path}"
                else:
                    margin = load_margin_from_sqlite(
                        sqlite_path,
                        codes=selected,
                        start=p_start or (f"{year}-01-01" if year else None),
                        end=p_end or (f"{year}-12-31" if year else None),
                    )
                    margin_src = "sqlite:markets_margin_interest"
                # short slice for period
                short_slice = [
                    (d, r)
                    for d, r in short_series_full
                    if (not p_start or d >= p_start)
                    and (not p_end or d <= p_end)
                ]
                flow = evaluate_flow_demand_on_bars(
                    bars,
                    margin,
                    short_slice,
                    hold_days=int(flow_hold_days),
                    one_way_cost=one_way_eff,
                    require_short_confirm=flow_short_confirm,
                    short_confirm_mode=flow_short_confirm_mode,
                )
                results_flow.append(
                    _period_row(
                        flow,
                        signal_id=SIGNAL_ID_FLOW_DEMAND,
                        extra={
                            "hold_days": int(flow_hold_days),
                            "require_short_confirm": bool(
                                flow.get("require_short_confirm")
                            ),
                            "short_confirm_mode": flow.get(
                                "short_confirm_mode"
                            ),
                            "margin_source": margin_src,
                            "n_margin_obs": flow.get("n_margin_obs"),
                            "n_codes_with_margin": flow.get(
                                "n_codes_with_margin"
                            ),
                            "amortized_one_way_cost": flow.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_fundamentals_price:
                fund = evaluate_fundamentals_price_on_bars(
                    bars,
                    fins_events,
                    hold_days=int(fund_hold_days),
                    momentum_n=fund_mom_n,
                    one_way_cost=one_way_eff,
                    mode=fund_mode_s,
                )
                results_fund.append(
                    _period_row(
                        fund,
                        signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
                        extra={
                            "hold_days": int(fund_hold_days),
                            "momentum_n": fund_mom_n,
                            "mode": fund_mode_s,
                            "n_missing_fins_days": fund.get(
                                "n_missing_fins_days"
                            ),
                            "value_benchmark_median": fund.get(
                                "value_benchmark_median"
                            ),
                            "amortized_one_way_cost": fund.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )

            if include_fundamentals_hold_10 and (
                int(fund_hold_days) != 10 or int(fund_mom_n) != int(fund10_mom_n)
            ):
                # W83: fund hold=10 mom=10 on default path (candidate in explore).
                fund10 = evaluate_fundamentals_price_on_bars(
                    bars,
                    fins_events,
                    hold_days=10,
                    momentum_n=fund10_mom_n,
                    one_way_cost=one_way_eff,
                    mode=fund_mode_s,
                )
                results_fund10.append(
                    _period_row(
                        fund10,
                        signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
                        extra={
                            "hold_days": 10,
                            "momentum_n": fund10_mom_n,
                            "mode": fund_mode_s,
                            "variant": "hold_10_mom_matched",
                            "n_missing_fins_days": fund10.get(
                                "n_missing_fins_days"
                            ),
                            "value_benchmark_median": fund10.get(
                                "value_benchmark_median"
                            ),
                            "amortized_one_way_cost": fund10.get(
                                "amortized_one_way_cost"
                            ),
                        },
                    )
                )
        except Exception as exc:  # noqa: BLE001 — year isolation
            err = {
                "period_id": pid,
                "year": year,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            results_md.append(err)
            results_macro.append(dict(err))
            if include_cross_section:
                results_xs.append(dict(err))
            if include_cross_section_hold_10:
                results_xs10.append(dict(err))
            if include_cross_section_hold_10_mom3:
                results_xs10_mom3.append(dict(err))
            if include_event_post:
                results_event.append(dict(err))
            if include_flow_demand:
                results_flow.append(dict(err))
            if include_fundamentals_price:
                results_fund.append(dict(err))
            if include_fundamentals_hold_10:
                results_fund10.append(dict(err))
            if include_multi_day_hold_10:
                results_md10.append(dict(err))

    # ------------------------------------------------------------------
    # W85: short cost remeasure on L-S classes
    # short = f(repo[t] + fixed spread bp); low/mid/high sensitivity
    # Primary (default mid) overwrites net_one_way_mean_active for gates/stats.
    # ------------------------------------------------------------------
    short_cost_remeasure_blocks: dict[str, Any] = {}
    short_frac_ls = float(short_fraction_ls)
    short_sens = str(short_borrow_sensitivity or "mid").strip().lower()
    if short_sens not in SHORT_BORROW_SPREAD_SENSITIVITY:
        short_sens = "mid"

    def _apply_short_remeasure(
        rows: list[dict[str, Any]],
        *,
        hold_days: int,
        block_key: str,
    ) -> list[dict[str, Any]]:
        if not apply_short_cost_remeasure or not rows:
            return rows
        # Per-row liquidity short_spread_mult when present (else 1.0)
        # Remeasure uses date-matched repo; no invent on gaps.
        pack = remeasure_period_rows_with_short_cost(
            rows,
            repo_rate_series=repo_series,
            short_fraction=short_frac_ls,
            hold_days=int(hold_days),
            default_sensitivity=short_sens,
            sensitivities=("low", "mid", "high"),
            apply_primary_net=True,
            fallback_mean_repo_when_date_gap=False,
        )
        short_cost_remeasure_blocks[block_key] = {
            "summary_by_sensitivity": pack.get("summary_by_sensitivity"),
            "n_short_cost_obs": pack.get("n_short_cost_obs"),
            "n_repo_gaps": pack.get("n_repo_gaps"),
            "default_sensitivity": pack.get("default_sensitivity"),
            "short_fraction": pack.get("short_fraction"),
            "formula": pack.get("formula"),
            "assumptions": pack.get("assumptions"),
            "mean_repo": pack.get("mean_repo"),
        }
        return list(pack.get("period_rows") or rows)

    if apply_short_cost_remeasure:
        results_macro = _apply_short_remeasure(
            results_macro, hold_days=h, block_key="macro_conditioned"
        )
        if include_cross_section:
            results_xs = _apply_short_remeasure(
                results_xs,
                hold_days=int(cross_section_hold_days),
                block_key="cross_section_relative",
            )
        if include_cross_section_hold_10 and results_xs10:
            results_xs10 = _apply_short_remeasure(
                results_xs10,
                hold_days=10,
                block_key="cross_section_hold_10",
            )
        if include_cross_section_hold_10_mom3 and results_xs10_mom3:
            results_xs10_mom3 = _apply_short_remeasure(
                results_xs10_mom3,
                hold_days=10,
                block_key="cross_section_hold_10_mom3",
            )
        if include_fundamentals_price:
            results_fund = _apply_short_remeasure(
                results_fund,
                hold_days=int(fund_hold_days),
                block_key="fundamentals_price",
            )
        if include_fundamentals_hold_10 and results_fund10:
            results_fund10 = _apply_short_remeasure(
                results_fund10,
                hold_days=10,
                block_key="fundamentals_hold_10",
            )

    def _gate(rows: list[dict[str, Any]], signal_id: str) -> dict[str, Any] | None:
        if not apply_robustness_gate:
            return None
        period_rows = [
            {
                "period_id": r["period_id"],
                "status": "ok",
                "gross_signed_mean_active": r.get("gross_signed_mean_active"),
                "net_one_way_mean_active": r.get("net_one_way_mean_active"),
                "n_active_positions": r.get("n_active_positions")
                or r.get("non_null"),
                "non_null": r.get("non_null"),
                "non_null_rate": r.get("non_null_rate"),
            }
            for r in rows
            if r.get("status") == "ok"
            and r.get("gross_signed_mean_active") is not None
        ]
        if not period_rows:
            return {
                "passed": False,
                "signal_id": signal_id,
                "reason": "no_ok_periods_with_gross",
                "research_candidate": False,
            }
        # For sparse event_post, relax min_active (events are rare)
        min_active = min_active_per_period
        if signal_id == SIGNAL_ID_EVENT_POST:
            min_active = min(5, min_active_per_period)
        return evaluate_research_robustness_gate(
            period_rows,
            signal_id=signal_id,
            min_periods=min_periods_gate,
            min_active_per_period=min_active,
            one_way_cost=one_way_cost,
            require_net_sign_majority=True,
        )

    gate_md = _gate(results_md, SIGNAL_ID_MULTI_DAY_HOLD)
    gate_md10 = (
        _gate(results_md10, SIGNAL_ID_MULTI_DAY_HOLD + "_hold10")
        if include_multi_day_hold_10
        else None
    )
    gate_macro = _gate(results_macro, SIGNAL_ID_MACRO_CONDITIONED)
    gate_xs = (
        _gate(results_xs, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section
        else None
    )
    gate_xs10 = (
        _gate(results_xs10, SIGNAL_ID_CROSS_SECTION + "_hold10")
        if include_cross_section_hold_10 and results_xs10
        else None
    )
    gate_xs10_mom3 = (
        _gate(results_xs10_mom3, SIGNAL_ID_CROSS_SECTION + "_hold10_mom3")
        if include_cross_section_hold_10_mom3 and results_xs10_mom3
        else None
    )
    gate_event = (
        _gate(results_event, SIGNAL_ID_EVENT_POST)
        if include_event_post
        else None
    )
    gate_flow = (
        _gate(results_flow, SIGNAL_ID_FLOW_DEMAND)
        if include_flow_demand
        else None
    )
    gate_fund = (
        _gate(results_fund, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_price
        else None
    )
    gate_fund10 = (
        _gate(results_fund10, SIGNAL_ID_FUNDAMENTALS_PRICE + "_hold10")
        if include_fundamentals_hold_10 and results_fund10
        else None
    )

    cost_md = default_long_only_unlevered_cost_assumption(
        one_way_cost=one_way_cost
    )
    cost_md["prefer_liquidity_linked"] = bool(prefer_liquidity_linked)
    cost_md["liquidity_note"] = (
        "Per-period one_way_eff = one_way_base * tx_mult[bucket] from "
        "equities_bars ADV. Missing ADV → mult=1.0 gap disclosed (no invent)."
    )
    cost_macro = build_leverage_short_cost_assumption(
        position_style="long_short",
        gross_leverage=1.0,
        short_fraction=short_frac_ls,
        one_way_cost=one_way_cost,
        uses_short=True,
        uses_leverage=False,
        repo_rate_series=repo_series,
        prefer_repo_linked=True,
        short_borrow_sensitivity=short_sens,
    )
    cost_ls = build_leverage_short_cost_assumption(
        position_style="long_short",
        gross_leverage=1.0,
        short_fraction=short_frac_ls,
        one_way_cost=one_way_cost,
        uses_short=True,
        uses_leverage=False,
        repo_rate_series=repo_series,
        prefer_repo_linked=True,
        short_borrow_sensitivity=short_sens,
    )
    cost_ls["short_cost_remeasure"] = {
        "applied": bool(apply_short_cost_remeasure),
        "default_sensitivity": short_sens,
        "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "formula": (
            "net = gross - amortized_one_way - "
            "short_borrow_daily(repo[t]+spread)*hold_days"
        ),
        "blocks": short_cost_remeasure_blocks,
        "proof": "docs/proof/w0816t_w85_short_cost_repo_spread_20260817.md",
    }
    cost_macro["short_cost_remeasure"] = dict(cost_ls["short_cost_remeasure"])
    if repo_series is not None:
        mean_repo = mean_repo_rate_pct(repo_series)
        cost_macro["repo_linked"] = {
            "preferred": True,
            "dataset": REPO_DATASET_ID,
            "mean_rate_pct": mean_repo.get("mean_rate_pct"),
            "mean_annual_bp": mean_repo.get("mean_annual_bp"),
            "n_obs": mean_repo.get("n_obs"),
            "note": (
                "W85: date-matched repo[t]+spread applied to L-S period nets; "
                "mean disclosed for summary. Gaps never invent-filled."
            ),
        }
        cost_ls["repo_linked"] = dict(cost_macro["repo_linked"])
    else:
        cost_macro["repo_linked"] = {
            "preferred": True,
            "available": False,
            "fallback": "fixed_bp_placeholder",
        }
        cost_ls["repo_linked"] = dict(cost_macro["repo_linked"])

    holding_md = None
    md_hold_recs: list[dict[str, Any]] = []
    for r in results_md:
        if r.get("status") == "ok" and r.get("holding_records"):
            md_hold_recs.extend(list(r["holding_records"]))
    if md_hold_recs:
        holding_md = holding_metrics_report(
            md_hold_recs, one_way_cost=one_way_cost
        )

    def _scen_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ok = [
            r
            for r in rows
            if r.get("status") == "ok"
            and r.get("gross_signed_mean_active") is not None
        ]
        if not ok:
            return [
                scenario_row(
                    SCENARIO_CRASH,
                    not_applicable=True,
                    na_reason="no ok periods",
                ),
                scenario_row(
                    SCENARIO_HIGH_VOL,
                    not_applicable=True,
                    na_reason="no ok periods",
                ),
                scenario_row(
                    SCENARIO_RATE_UP,
                    not_applicable=True,
                    na_reason="insufficient",
                ),
                scenario_row(
                    SCENARIO_RATE_DOWN,
                    not_applicable=True,
                    na_reason="insufficient",
                ),
                scenario_row(
                    SCENARIO_LIQUIDITY_STRESS,
                    not_applicable=True,
                    na_reason="no liq data",
                ),
            ]
        grosses = [float(r["gross_signed_mean_active"]) for r in ok]
        nets = [
            float(r["net_one_way_mean_active"])
            if r.get("net_one_way_mean_active") is not None
            else float(r["gross_signed_mean_active"]) - float(one_way_cost)
            for r in ok
        ]
        worst_i = min(range(len(grosses)), key=lambda i: grosses[i])
        vol_i = max(range(len(grosses)), key=lambda i: abs(grosses[i]))
        return [
            scenario_row(
                SCENARIO_CRASH,
                gross_signed_mean=grosses[worst_i],
                net_one_way_mean=nets[worst_i],
            ),
            scenario_row(
                SCENARIO_HIGH_VOL,
                gross_signed_mean=grosses[vol_i],
                net_one_way_mean=nets[vol_i],
            ),
            scenario_row(
                SCENARIO_RATE_UP,
                gross_signed_mean=mean(grosses),
                net_one_way_mean=mean(nets),
                notes="proxy: overall mean (rate_up slice not fully segmented)",
            ),
            scenario_row(
                SCENARIO_RATE_DOWN,
                gross_signed_mean=mean(grosses),
                net_one_way_mean=mean(nets),
                notes="proxy: overall mean (rate_down slice not fully segmented)",
            ),
            scenario_row(
                SCENARIO_LIQUIDITY_STRESS,
                not_applicable=True,
                na_reason="no liquidity stress dataset in this offline path",
            ),
        ]

    def _risk(rows: list[dict[str, Any]], signal_id: str) -> dict[str, Any]:
        return evaluate_risk_scenarios(
            _scen_from_rows(rows),
            rate_data_usable=True,
            liquidity_data_available=False,
            prefer_fail_on_sign_break=True,
            signal_id=signal_id,
        )

    risk_md = _risk(results_md, SIGNAL_ID_MULTI_DAY_HOLD)
    risk_macro = _risk(results_macro, SIGNAL_ID_MACRO_CONDITIONED)
    risk_xs = _risk(results_xs, SIGNAL_ID_CROSS_SECTION) if include_cross_section else None
    risk_xs10 = (
        _risk(results_xs10, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section_hold_10 and results_xs10
        else None
    )
    risk_xs10_mom3 = (
        _risk(results_xs10_mom3, SIGNAL_ID_CROSS_SECTION)
        if include_cross_section_hold_10_mom3 and results_xs10_mom3
        else None
    )
    risk_event = _risk(results_event, SIGNAL_ID_EVENT_POST) if include_event_post else None
    risk_flow = _risk(results_flow, SIGNAL_ID_FLOW_DEMAND) if include_flow_demand else None
    risk_fund = (
        _risk(results_fund, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_price
        else None
    )
    risk_fund10 = (
        _risk(results_fund10, SIGNAL_ID_FUNDAMENTALS_PRICE)
        if include_fundamentals_hold_10 and results_fund10
        else None
    )

    def _econ_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
        nets = [
            r.get("net_one_way_mean_active")
            for r in rows
            if r.get("status") == "ok"
            and r.get("net_one_way_mean_active") is not None
        ]
        return economic_net_meaningful(
            nets,
            min_mean_net=float(min_economic_net),
            require_positive_majority=True,
        )

    def _aggregate_occurrence_multiday(
        rows: list[dict[str, Any]], *, hold_days: int
    ) -> dict[str, Any]:
        ok = [r for r in rows if r.get("status") == "ok"]
        n_active = sum(int(r.get("n_active_positions") or 0) for r in ok)
        n_cd = sum(int(r.get("n_code_days") or 0) for r in ok)
        n_td = sum(int(r.get("n_trading_days") or 0) for r in ok)
        n_codes = 0
        for r in ok:
            n_codes = max(n_codes, int(r.get("n_codes") or 0))
        occ = occurrence_rate_multiday(
            n_active=n_active,
            n_code_days=n_cd,
            n_trading_days=n_td,
            n_codes=n_codes,
            hold_days=hold_days,
            min_activation_rate=float(min_activation_rate_multiday),
        )
        occ["per_period"] = [
            {
                "period_id": r.get("period_id"),
                "occurrence": r.get("occurrence"),
                "n_active": r.get("n_active_positions"),
                "n_code_days": r.get("n_code_days"),
                "n_trading_days": r.get("n_trading_days"),
            }
            for r in ok
        ]
        return occ

    def _aggregate_occurrence_event(
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ok = [r for r in rows if r.get("status") == "ok"]
        n_events = sum(int(r.get("n_events") or 0) for r in ok)
        n_scored = sum(int(r.get("n_active_positions") or 0) for r in ok)
        n_td = sum(int(r.get("n_trading_days") or 0) for r in ok)
        n_cd = sum(int(r.get("n_code_days") or 0) for r in ok)
        n_codes = 0
        for r in ok:
            n_codes = max(n_codes, int(r.get("n_codes") or 0))
        occ = occurrence_rate_event_post(
            n_events=n_events,
            n_scored=n_scored,
            n_trading_days=n_td,
            n_codes=n_codes,
            n_code_days=n_cd,
            trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
            min_events_per_code_year=float(min_events_per_code_year),
            min_events_per_trading_day=float(min_events_per_trading_day),
        )
        occ["per_period"] = [
            {
                "period_id": r.get("period_id"),
                "occurrence": r.get("occurrence"),
                "n_events": r.get("n_events"),
                "n_scored": r.get("n_active_positions"),
                "n_trading_days": r.get("n_trading_days"),
            }
            for r in ok
        ]
        return occ

    def _skew_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
        nets: dict[str, float | None] = {}
        for r in rows:
            if r.get("status") != "ok":
                continue
            pid_r = str(r.get("period_id") or r.get("year") or "p")
            nets[pid_r] = r.get("net_one_way_mean_active")
        return multi_year_skew_check(
            nets, max_pos_share=float(max_year_pos_net_share)
        )

    def _stats_from_rows(
        rows: list[dict[str, Any]],
        *,
        hold_days: int | None = None,
    ) -> dict[str, Any]:
        """Period-net statistical pack + W81 stats bar check."""
        ok_rows = [
            r
            for r in rows
            if r.get("status") == "ok"
            and r.get("net_one_way_mean_active") is not None
        ]
        nets = [float(r["net_one_way_mean_active"]) for r in ok_rows]
        pids = [str(r.get("period_id") or r.get("year") or "p") for r in ok_rows]
        stats = period_stats_report(
            nets, period_ids=pids, hold_days=hold_days
        )
        # Attach per-period trade_stats summaries when present (no raw trades).
        trade_rows = []
        for r in ok_rows:
            ts = r.get("trade_stats")
            if isinstance(ts, Mapping):
                trade_rows.append(
                    {
                        "period_id": r.get("period_id"),
                        "n_trades": ts.get("n_trades"),
                        "mean_net": ts.get("mean_net"),
                        "t_stat": ts.get("t_stat"),
                        "sharpe_ann": ts.get("sharpe_ann"),
                        "win_rate": ts.get("win_rate"),
                        "payoff": ts.get("payoff"),
                        "max_dd": ts.get("max_dd"),
                    }
                )
        if trade_rows:
            stats["per_period_trade_stats"] = trade_rows
        bar = stats_bar_check(
            stats,
            min_abs_t=float(min_abs_t_stat),
            min_sharpe=float(min_sharpe_period),
            min_win_rate=float(min_period_win_rate),
            min_positive_periods=int(min_positive_periods),
        )
        return {"stats": stats, "stats_bar": bar}

    def _candidate_verdict(
        gate: dict[str, Any] | None,
        risk: dict[str, Any] | None,
        rows: list[dict[str, Any]],
        *,
        n_ok: int,
        occurrence: Mapping[str, Any] | None = None,
        hyp_kind: str = "generic",
        hold_days_for_occ: int = 5,
    ) -> dict[str, Any]:
        """W81 production bar: gate + risk + econ + occurrence + skew + stats.

        Weak consistent-negative → not_candidate even if gate passes.
        Noisy low t/Sharpe / unstable yearly signs → demote discussion_only.
        research_candidate=True only when all production criteria pass
        (still not READY / Mass / operational GO).
        """
        gate_pass = bool(gate and gate.get("passed"))
        risk_ok = bool(risk and risk.get("research_candidate_allowed"))
        econ = _econ_from_rows(rows)
        econ_ok = bool(econ.get("meaningful"))
        if occurrence is None:
            if hyp_kind == "event_post":
                occurrence = _aggregate_occurrence_event(rows)
            elif hyp_kind in {"multi_day_hold", "multi_day_hold_10"}:
                occurrence = _aggregate_occurrence_multiday(
                    rows, hold_days=hold_days_for_occ
                )
            else:
                # generic: treat n_active/code_days if present
                occurrence = _aggregate_occurrence_multiday(
                    rows, hold_days=hold_days_for_occ
                )
        occ_ok = bool((occurrence or {}).get("sufficient"))
        skew = _skew_from_rows(rows)
        skew_ok = bool(skew.get("ok"))
        multi_year_ok = bool(n_ok >= int(min_years_research_candidate))
        stats_pack = _stats_from_rows(rows, hold_days=hold_days_for_occ)
        stats = stats_pack["stats"]
        sbar = stats_pack["stats_bar"]
        stats_ok = bool(sbar.get("stats_ok"))

        bar = production_candidate_bar(
            checklist_complete=bool(checklist_complete),
            gate_passed=gate_pass,
            risk_ok=risk_ok,
            economic_net_ok=econ_ok,
            occurrence_ok=occ_ok,
            multi_year_ok=multi_year_ok,
            skew_ok=skew_ok,
            n_ok_periods=n_ok,
            min_years=int(min_years_research_candidate),
            economic_net=econ,
            occurrence=occurrence,
            skew=skew,
            stats_ok=stats_ok,
            stats=stats,
            stats_bar=sbar,
            require_stats=bool(require_stats_bar),
        )
        return {
            "research_candidate": bool(bar.get("research_candidate")),
            "research_candidate_allowed": bool(
                bar.get("research_candidate_allowed")
            ),
            "candidate_yes_no": bar.get("candidate_yes_no"),
            "gate_passed": gate_pass,
            "risk_scenarios_ok": risk_ok,
            "economic_net": econ,
            "economic_net_ok": econ_ok,
            "occurrence": dict(occurrence or {}),
            "occurrence_ok": occ_ok,
            "skew": skew,
            "skew_ok": skew_ok,
            "stats": stats,
            "stats_bar": sbar,
            "stats_ok": stats_ok,
            "production_criteria": bar.get("production_criteria"),
            "n_ok_periods": n_ok,
            "verdict": bar.get("verdict"),
            "ready_declared": False,
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "operational_go": False,
            "connected_to_ready": False,
            "connected_to_mass": False,
            "min_economic_net": float(min_economic_net),
            "min_years_research_candidate": int(min_years_research_candidate),
            "min_abs_t_stat": float(min_abs_t_stat),
            "min_sharpe_period": float(min_sharpe_period),
            "min_period_win_rate": float(min_period_win_rate),
            "min_positive_periods": int(min_positive_periods),
            "note": bar.get("note"),
        }

    def _n_ok(rows: list[dict[str, Any]]) -> int:
        return sum(1 for r in rows if r.get("status") == "ok")

    n_ok_md = _n_ok(results_md)
    n_ok_macro = _n_ok(results_macro)
    n_ok_xs = _n_ok(results_xs)
    n_ok_xs10 = _n_ok(results_xs10)
    n_ok_xs10_mom3 = _n_ok(results_xs10_mom3)
    n_ok_event = _n_ok(results_event)
    n_ok_flow = _n_ok(results_flow)
    n_ok_fund = _n_ok(results_fund)
    n_ok_fund10 = _n_ok(results_fund10)
    n_ok_md10 = _n_ok(results_md10)

    def _compact(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            c = {k: v for k, v in r.items() if k != "holding_records"}
            out.append(c)
        return out

    def _class_block(
        *,
        signal_id: str,
        hyp_class: str,
        rows: list[dict[str, Any]],
        gate: dict[str, Any] | None,
        risk: dict[str, Any] | None,
        cost: dict[str, Any] | None = None,
        holding: dict[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
        hyp_kind: str = "generic",
        hold_days_for_occ: int = 5,
    ) -> dict[str, Any]:
        n_ok = _n_ok(rows)
        cand = _candidate_verdict(
            gate,
            risk,
            rows,
            n_ok=n_ok,
            hyp_kind=hyp_kind,
            hold_days_for_occ=hold_days_for_occ,
        )
        block: dict[str, Any] = {
            "signal_id": signal_id,
            "hypothesis_class": hyp_class,
            "years": _compact(rows),
            "cross_year_table": _compact(
                [r for r in rows if r.get("status") == "ok"]
            ),
            "robustness_gate": gate,
            "cost_assumption": cost,
            "risk_scenarios": risk,
            "candidate": cand,
            "occurrence": cand.get("occurrence"),
        }
        if holding is not None:
            block["holding"] = holding
        if extra:
            block.update(dict(extra))
        return block

    out: dict[str, Any] = {
        "version": CLASS_HYP_EVAL_VERSION,
        "wave": CLASS_HYP_EVAL_WAVE,
        "class_signals": class_signals_document(),
        "definitions": class_signal_definitions(
            hold_days=h,
            macro_mode=macro_mode,
            event_hold_days=int(event_hold_days),
            flow_hold_days=int(flow_hold_days),
            fund_hold_days=int(fund_hold_days),
        ),
        "hold_days": h,
        "macro_mode": macro_mode,
        "codes": selected,
        "one_way_cost": float(one_way_cost),
        "one_way_cost_bp": float(one_way_cost) * 10_000.0,
        "prefer_liquidity_linked": bool(prefer_liquidity_linked),
        "apply_short_cost_remeasure": bool(apply_short_cost_remeasure),
        "short_borrow_sensitivity": short_sens,
        "short_fraction_ls": short_frac_ls,
        "short_cost_sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
        "short_cost_remeasure": short_cost_remeasure_blocks,
        "min_economic_net": float(min_economic_net),
        "min_activation_rate_multiday": float(min_activation_rate_multiday),
        "min_events_per_code_year": float(min_events_per_code_year),
        "min_events_per_trading_day": float(min_events_per_trading_day),
        "min_years_research_candidate": int(min_years_research_candidate),
        "max_year_pos_net_share": float(max_year_pos_net_share),
        "min_abs_t_stat": float(min_abs_t_stat),
        "min_sharpe_period": float(min_sharpe_period),
        "min_period_win_rate": float(min_period_win_rate),
        "min_positive_periods": int(min_positive_periods),
        "require_stats_bar": bool(require_stats_bar),
        "stats_metrics": stats_metrics_document(),
        "repo_load": repo_load_note,
        "fins_load": fins_load_note,
        "short_load": short_load_note,
        "multi_day_hold": _class_block(
            signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
            hyp_class=CLASS_MULTI_DAY_HOLD,
            rows=results_md,
            gate=gate_md,
            risk=risk_md,
            cost=cost_md,
            holding=holding_md,
            hyp_kind="multi_day_hold",
            hold_days_for_occ=h,
            extra={
                "cost_amortization": cost_amortization_report(
                    one_way_cost=one_way_cost
                ),
            },
        ),
        "macro_conditioned": _class_block(
            signal_id=SIGNAL_ID_MACRO_CONDITIONED,
            hyp_class=CLASS_MACRO_CONDITIONED,
            rows=results_macro,
            gate=gate_macro,
            risk=risk_macro,
            cost=cost_macro,
            hyp_kind="generic",
            hold_days_for_occ=h,
        ),
        "n_years_requested": len(period_list),
        "n_years_ok_multi_day_hold": n_ok_md,
        "n_years_ok_macro_conditioned": n_ok_macro,
        "history_source": (
            "local_r2_mirror_ndjson (W63 q4 + W64 full) + local_sqlite "
            "(jsda_repo_rates · fins_summary · fins_earnings_date · "
            "margin · short_ratio)"
        ),
        "label": "研究用・複数年クラス仮説評価・W81統計バー再判定・未宣言",
        **_freeze(),
        "note": (
            "W85 class hyp multi-year offline eval with occurrence rates + "
            "liquidity-linked costs + short=repo[t]+spread (L/M/H) remeasure "
            "on CS L-S / fund L-S / macro + extended full-year windows + "
            "statistical bar (|t|≥1.5, Sharpe≥0.5, period win-rate≥0.6, "
            "≥4 positive periods). No mean-bp-only promotion. "
            "Default path includes sticky cross_section hold=10 (mom=5 pin), "
            "W85-promoted hold=10 mom=3, and fundamentals hold=10 mom=10. "
            "event_post uses W82 PIT DiscDate+DiscTime entry only. "
            "research_candidate=True only if checklist v2 + gate + risk + "
            "economic net meaningful + occurrence rate sufficient + "
            "multi-year (≥min_years) without extreme skew + stats bar. "
            "Weak consistent-negative → not_candidate. "
            "Noisy low t/Sharpe / unstable yearly signs → demote. "
            "READY/Mass/operational GO never auto-connect. "
            "Not READY / Mass NO-GO / Phase7 OFF."
        ),
    }

    if include_multi_day_hold_10:
        out["multi_day_hold_10"] = _class_block(
            signal_id=SIGNAL_ID_MULTI_DAY_HOLD,
            hyp_class=CLASS_MULTI_DAY_HOLD,
            rows=results_md10,
            gate=gate_md10,
            risk=_risk(results_md10, SIGNAL_ID_MULTI_DAY_HOLD)
            if results_md10
            else None,
            cost=cost_md,
            hyp_kind="multi_day_hold_10",
            hold_days_for_occ=10,
            extra={"variant": "hold_10", "n_ok": n_ok_md10},
        )
    if include_cross_section:
        out["cross_section_relative"] = _class_block(
            signal_id=SIGNAL_ID_CROSS_SECTION,
            hyp_class="cross_section_relative",
            rows=results_xs,
            gate=gate_xs,
            risk=risk_xs,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=int(cross_section_hold_days),
            extra={
                "hold_days": int(cross_section_hold_days),
                "momentum_n": xs_mom_n,
                "long_frac": xs_long_frac,
                "short_frac": xs_short_frac,
            },
        )
    if include_cross_section_hold_10 and results_xs10:
        out["cross_section_hold_10"] = _class_block(
            signal_id=SIGNAL_ID_CROSS_SECTION,
            hyp_class="cross_section_relative",
            rows=results_xs10,
            gate=gate_xs10,
            risk=risk_xs10,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=10,
            extra={
                "hold_days": 10,
                "momentum_n": xs10_mom_n,
                "variant": "hold_10",
                "long_frac": xs_long_frac,
                "short_frac": xs_short_frac,
                "n_ok": n_ok_xs10,
                "note": (
                    f"W83 default-path sticky hold=10 with momentum_n="
                    f"{xs10_mom_n} (W82 pin; mom=10 collapses). "
                    "W86 sign-selection applies both sides after cost. "
                    "Not Mass/READY."
                ),
            },
        )
    if include_cross_section_hold_10_mom3 and results_xs10_mom3:
        out["cross_section_hold_10_mom3"] = _class_block(
            signal_id=SIGNAL_ID_CROSS_SECTION,
            hyp_class="cross_section_relative",
            rows=results_xs10_mom3,
            gate=gate_xs10_mom3,
            risk=risk_xs10_mom3,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=10,
            extra={
                "hold_days": 10,
                "momentum_n": xs10_mom3_n,
                "variant": "hold_10_mom3",
                "long_frac": xs_long_frac,
                "short_frac": xs_short_frac,
                "n_ok": n_ok_xs10_mom3,
                "promoted_wave": "W85 / w0816t",
                "note": (
                    f"W85 promote_default: sticky hold=10 momentum_n="
                    f"{xs10_mom3_n}. Research hard RC (t≈3.0) + multi-window "
                    "paper majority positive. Parallel to mom=5 pin — does not "
                    "replace W82 pin. W86 sign-selection both sides. "
                    "Not Mass/READY/live."
                ),
            },
        )
    if include_event_post:
        out["event_post"] = _class_block(
            signal_id=SIGNAL_ID_EVENT_POST,
            hyp_class=CLASS_EVENT_POST,
            rows=results_event,
            gate=gate_event,
            risk=risk_event,
            cost=cost_md,
            hyp_kind="event_post",
            hold_days_for_occ=int(event_hold_days),
            extra={
                "post_hold_days": int(event_hold_days),
                "n_ok": n_ok_event,
                "entry_mode": EVENT_POST_ENTRY_MODE,
                "pit_definition": "W82 DiscDate+DiscTime first non-look-ahead close",
            },
        )
    if include_flow_demand:
        out["flow_demand"] = _class_block(
            signal_id=SIGNAL_ID_FLOW_DEMAND,
            hyp_class=CLASS_FLOW_DEMAND,
            rows=results_flow,
            gate=gate_flow,
            risk=risk_flow,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=int(flow_hold_days),
            extra={
                "hold_days": int(flow_hold_days),
                "require_short_confirm": flow_short_confirm,
                "n_ok": n_ok_flow,
            },
        )
    if include_fundamentals_price:
        out["fundamentals_price"] = _class_block(
            signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
            hyp_class=CLASS_FUNDAMENTALS_PRICE,
            rows=results_fund,
            gate=gate_fund,
            risk=risk_fund,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=int(fund_hold_days),
            extra={
                "hold_days": int(fund_hold_days),
                "momentum_n": fund_mom_n,
                "mode": fund_mode_s,
                "n_ok": n_ok_fund,
            },
        )
    if include_fundamentals_hold_10 and results_fund10:
        out["fundamentals_hold_10"] = _class_block(
            signal_id=SIGNAL_ID_FUNDAMENTALS_PRICE,
            hyp_class=CLASS_FUNDAMENTALS_PRICE,
            rows=results_fund10,
            gate=gate_fund10,
            risk=risk_fund10,
            cost=cost_ls,
            hyp_kind="generic",
            hold_days_for_occ=10,
            extra={
                "hold_days": 10,
                "momentum_n": fund10_mom_n,
                "mode": fund_mode_s,
                "variant": "hold_10_mom_matched",
                "n_ok": n_ok_fund10,
                "note": (
                    "W83 default-path fund hold=10 mom-matched. "
                    "W86 sign-selection applies both sides after cost "
                    "(paper-negative → flip-first). Not Mass/READY."
                ),
            },
        )

    # ------------------------------------------------------------------
    # W86 / w0816u: sign flip both-sides after cost for default/main
    # explore representatives. Record chosen_sign for reproducibility.
    # ------------------------------------------------------------------
    # paper_mean_negative flags from W85 multi-window paper honesty:
    # xs mom5 −0.49% · fund mom10 −1.77% · mom3 +0.66% (not paper-neg).
    _SIGN_FLIP_TARGETS: tuple[tuple[str, bool, int | None], ...] = (
        # key, paper_mean_negative, hold_days override
        ("cross_section_hold_10", True, 10),
        ("cross_section_hold_10_mom3", False, 10),
        ("fundamentals_hold_10", True, 10),
    )
    sign_selection_blocks: dict[str, Any] = {}
    for skey, paper_neg, hold_ov in _SIGN_FLIP_TARGETS:
        block = out.get(skey)
        if not isinstance(block, Mapping):
            continue
        rows_ss = list(block.get("years") or block.get("cross_year_table") or [])
        hold_ss = hold_ov
        if hold_ss is None:
            hold_ss = int(block.get("hold_days") or 10)
        sel = sign_selection_from_period_rows(
            rows_ss,
            hold_days=int(hold_ss),
            min_mean_net=float(min_economic_net),
            paper_mean_negative=bool(paper_neg),
        )
        # Attach to block (mutable dicts produced by _class_block)
        if isinstance(block, dict):
            block["sign_selection"] = sel
            block["chosen_sign"] = sel.get("chosen_sign")
            block["chosen_sign_label"] = sel.get("chosen_label")
            block["sign_selection_decision"] = sel.get("decision")
            # Effective metrics after selection (chosen side)
            if sel.get("chosen_sign") == SIGN_INVERTED:
                inv = sel.get("inverted") or {}
                block["metrics_after_sign"] = {
                    "sign": SIGN_INVERTED,
                    "mean_net": inv.get("mean_net"),
                    "mean_net_bp": inv.get("mean_net_bp"),
                    "t_stat": inv.get("t_stat"),
                    "sharpe": inv.get("sharpe"),
                    "win_rate": inv.get("win_rate"),
                    "n_pos": inv.get("n_pos"),
                    "n_neg": inv.get("n_neg"),
                }
            elif sel.get("chosen_sign") == SIGN_ORIGINAL:
                orig = sel.get("original") or {}
                block["metrics_after_sign"] = {
                    "sign": SIGN_ORIGINAL,
                    "mean_net": orig.get("mean_net"),
                    "mean_net_bp": orig.get("mean_net_bp"),
                    "t_stat": orig.get("t_stat"),
                    "sharpe": orig.get("sharpe"),
                    "win_rate": orig.get("win_rate"),
                    "n_pos": orig.get("n_pos"),
                    "n_neg": orig.get("n_neg"),
                }
            else:
                block["metrics_after_sign"] = {
                    "sign": None,
                    "mean_net": None,
                    "reason": sel.get("decision"),
                }
            # Demote research_candidate when both sides fail non-zero
            cand_b = block.get("candidate")
            if isinstance(cand_b, dict) and sel.get("chosen_sign") is None:
                cand_b["sign_selection_demote"] = True
                cand_b["research_candidate"] = False
                cand_b["research_candidate_allowed"] = False
                cand_b["candidate_yes_no"] = "no"
                cand_b["verdict"] = "not_candidate_sign_both_sides_fail"
                cand_b["note_sign"] = (
                    "W86 both sides fail non-zero / non-positive after cost "
                    "→ demote (not Mass/READY path)."
                )
            elif isinstance(cand_b, dict):
                cand_b["chosen_sign"] = sel.get("chosen_sign")
                cand_b["chosen_sign_label"] = sel.get("chosen_label")
                cand_b["sign_selection_decision"] = sel.get("decision")
                # If flipped, expose chosen-side stats for transparency
                if sel.get("chosen_sign") == SIGN_INVERTED:
                    inv = sel.get("inverted") or {}
                    cand_b["stats_original_side"] = cand_b.get("stats")
                    cand_b["stats_chosen_side"] = {
                        "mean_net": inv.get("mean_net"),
                        "t_stat": inv.get("t_stat"),
                        "sharpe": inv.get("sharpe"),
                        "win_rate": inv.get("win_rate"),
                        "n_pos": inv.get("n_pos"),
                        "n_neg": inv.get("n_neg"),
                        "sign": SIGN_INVERTED,
                    }
        sign_selection_blocks[skey] = {
            "chosen_sign": sel.get("chosen_sign"),
            "chosen_label": sel.get("chosen_label"),
            "decision": sel.get("decision"),
            "verdict": sel.get("verdict"),
            "chosen_mean_net_bp": sel.get("chosen_mean_net_bp"),
            "chosen_t_stat": sel.get("chosen_t_stat"),
            "chosen_sharpe": sel.get("chosen_sharpe"),
            "original_mean_net_bp": (sel.get("original") or {}).get("mean_net_bp"),
            "original_t_stat": (sel.get("original") or {}).get("t_stat"),
            "original_sharpe": (sel.get("original") or {}).get("sharpe"),
            "inverted_mean_net_bp": (sel.get("inverted") or {}).get("mean_net_bp"),
            "inverted_t_stat": (sel.get("inverted") or {}).get("t_stat"),
            "inverted_sharpe": (sel.get("inverted") or {}).get("sharpe"),
            "paper_mean_negative": bool(paper_neg),
            "reasons": sel.get("reasons"),
        }

    out["sign_selection"] = {
        "version": SIGN_SELECTION_VERSION,
        "wave": SIGN_SELECTION_WAVE,
        "document": sign_selection_document(),
        "blocks": sign_selection_blocks,
        "note": (
            "W86 evaluate both original and inverted after costs; "
            "prefer positive mean net with non-zero evidence (t guideline). "
            "Both fail → reject/explore demote. Not Mass/READY/live."
        ),
    }

    # Default-path representatives after sign selection.
    # Policy: do not over-invest mom3 vs mom5 — keep both if both survive,
    # else keep the surviving primary. Primary = mom5 pin if survives,
    # else mom3; fund separate.
    survivors: list[dict[str, Any]] = []
    for skey, _pn, _h in _SIGN_FLIP_TARGETS:
        ss = sign_selection_blocks.get(skey) or {}
        block = out.get(skey)
        if not isinstance(block, Mapping):
            continue
        cand = block.get("candidate") or {}
        chosen = ss.get("chosen_sign")
        if chosen is None:
            continue
        rc = bool(cand.get("research_candidate"))
        survivors.append(
            {
                "block_key": skey,
                "chosen_sign": chosen,
                "chosen_label": ss.get("chosen_label"),
                "momentum_n": block.get("momentum_n"),
                "hold_days": block.get("hold_days"),
                "research_candidate": rc,
                "mean_net_bp_chosen": ss.get("chosen_mean_net_bp"),
                "t_stat_chosen": ss.get("chosen_t_stat"),
                "sharpe_chosen": ss.get("chosen_sharpe"),
                "decision": ss.get("decision"),
            }
        )

    xs_surv = [s for s in survivors if s["block_key"].startswith("cross_section")]
    fund_surv = [s for s in survivors if s["block_key"].startswith("fundamentals")]
    # mom3 vs mom5 compression rule
    mom_compress_note: str
    xs_default: list[dict[str, Any]]
    if len(xs_surv) >= 2:
        # both survive → keep both as parallel defaults (W85 already promoted mom3)
        xs_default = list(xs_surv)
        mom_compress_note = (
            "both xs mom5 and mom3 survive sign selection → keep both "
            "as parallel default representatives (no over-invest; not merge)"
        )
    elif len(xs_surv) == 1:
        xs_default = list(xs_surv)
        mom_compress_note = (
            f"single xs survivor after sign selection: {xs_surv[0]['block_key']}"
        )
    else:
        xs_default = []
        mom_compress_note = "no xs survivor after sign selection → demote both"

    default_reps = {
        "wave": SIGN_SELECTION_WAVE,
        "xs_representatives": xs_default,
        "fund_representatives": fund_surv,
        "all_survivors": survivors,
        "mom3_vs_mom5": mom_compress_note,
        "n_default_wired_candidates": len(xs_default) + len(fund_surv),
        "mass_research": MASS_RESEARCH,
        "ready_declared": False,
        "operational_go": False,
        "phase7": PHASE7,
        "note": (
            "Default representatives after W86 sign selection. "
            "research_candidate on block still requires full production bar; "
            "chosen_sign is recorded for StrategySpec signal_sign wiring. "
            "Not Mass / READY / ops GO / live."
        ),
    }
    out["default_path_representatives"] = default_reps

    # Summary yes/no per class (honest; may be yes if research_candidate)
    summary: dict[str, Any] = {}
    any_research_candidate = False
    for key in (
        "multi_day_hold",
        "multi_day_hold_10",
        "event_post",
        "macro_conditioned",
        "cross_section_relative",
        "cross_section_hold_10",
        "cross_section_hold_10_mom3",
        "flow_demand",
        "fundamentals_price",
        "fundamentals_hold_10",
    ):
        block = out.get(key)
        if not isinstance(block, Mapping):
            continue
        cand = block.get("candidate") or {}
        rc = bool(cand.get("research_candidate"))
        if rc:
            any_research_candidate = True
        stats = cand.get("stats") or {}
        ss_sum = sign_selection_blocks.get(key) or {}
        summary[key] = {
            "signal_id": block.get("signal_id"),
            "gate_passed": cand.get("gate_passed"),
            "economic_net_ok": cand.get("economic_net_ok"),
            "occurrence_ok": cand.get("occurrence_ok"),
            "skew_ok": cand.get("skew_ok"),
            "stats_ok": cand.get("stats_ok"),
            "research_candidate_allowed": cand.get(
                "research_candidate_allowed"
            ),
            "research_candidate": rc,
            "verdict": cand.get("verdict"),
            "candidate_yes_no": cand.get("candidate_yes_no") or "no",
            "mean_net": (cand.get("economic_net") or {}).get("mean_net"),
            "t_stat": stats.get("t_stat"),
            "sharpe": stats.get("sharpe"),
            "win_rate": stats.get("win_rate"),
            "payoff": stats.get("payoff"),
            "max_dd": stats.get("max_dd"),
            "calmar": stats.get("calmar"),
            "n_ok_periods": cand.get("n_ok_periods"),
            "chosen_sign": ss_sum.get("chosen_sign", block.get("chosen_sign")),
            "chosen_sign_label": ss_sum.get(
                "chosen_label", block.get("chosen_sign_label")
            ),
            "sign_selection_decision": ss_sum.get("decision"),
            "mean_net_bp_original": ss_sum.get("original_mean_net_bp"),
            "mean_net_bp_inverted": ss_sum.get("inverted_mean_net_bp"),
            "t_stat_original": ss_sum.get("original_t_stat"),
            "t_stat_inverted": ss_sum.get("inverted_t_stat"),
            "decision": (
                "keep"
                if rc
                else (
                    "demote"
                    if (
                        (cand.get("production_criteria") or {}).get("w80_core_ok")
                        and not cand.get("stats_ok")
                    )
                    or cand.get("sign_selection_demote")
                    else "not_candidate"
                )
            ),
        }
    out["candidate_summary"] = summary
    out["any_research_candidate"] = any_research_candidate
    out["ready_declared"] = False
    out["mass_research"] = MASS_RESEARCH
    out["phase7"] = PHASE7
    out["operational_go"] = False
    return out



__all__ = [
    "CLASS_HYP_EVAL_VERSION",
    "CLASS_HYP_EVAL_WAVE",
    "DEFAULT_SQLITE",
    "MAX_YEAR_POS_NET_SHARE",
    "MIN_ABS_T_STAT",
    "MIN_ACTIVATION_RATE_MULTIDAY",
    "MIN_ECONOMIC_NET",
    "MIN_EVENTS_PER_CODE_YEAR",
    "MIN_EVENTS_PER_TRADING_DAY",
    "MIN_PERIOD_WIN_RATE",
    "MIN_POSITIVE_PERIODS",
    "MIN_SHARPE_PERIOD",
    "MIN_YEARS_RESEARCH_CANDIDATE",
    "load_repo_rows_from_sqlite",
    "run_class_hyp_multi_year_eval",
]
