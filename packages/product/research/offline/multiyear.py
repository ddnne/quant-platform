"""Offline W78–W86 multi-year window stitch (not CF SoT; no GO).

``run_class_hyp_multi_year_eval`` is the public entry.
Reporting lives in ``research.offline.multiyear_report``.
Periods SoT is ``research.eval_windows``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from features.class_signals import (
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
    EVENT_POST_ENTRY_MODE,
    SIGNAL_ID_CROSS_SECTION,
    SIGNAL_ID_EVENT_POST,
    SIGNAL_ID_FLOW_DEMAND,
    SIGNAL_ID_FUNDAMENTALS_PRICE,
    SIGNAL_ID_MACRO_CONDITIONED,
    SIGNAL_ID_MULTI_DAY_HOLD,
    SUPPORTED_HOLD_DAYS,
)
from research.cost_models import (
    DEFAULT_ONE_WAY_COST,
    REPO_DATASET_ID,
    apply_liquidity_to_one_way_cost,
    compute_liquidity_proxy_from_bars,
    liquidity_bucket_from_proxy,
    liquidity_cost_multipliers,
    load_repo_rate_series_from_rows,
)
from pit.personal_research_view import PersonalResearchDataView
from research.eval_loaders import (
    bars_rich_to_close_panel,
    collect_liquidity_bar_rows,
    load_bars_from_sqlite_rich,
    load_fins_earnings_date_from_sqlite,
    load_fins_events_from_sqlite,
    load_margin_from_sqlite,
    load_repo_rows_from_sqlite,
    load_short_ratio_series_from_sqlite,
    merge_event_calendars,
)
from research.eval_tracks import EVAL_TRACK_LIQ_LARGE, EVAL_TRACKS
from research.eval_universe import (
    select_eval_universe,
)
from research.eval_windows import DEFAULT_PERIODS
from research.offline.bar_eval import (
    evaluate_cross_section_on_bars,
    evaluate_event_post_on_bars,
    evaluate_flow_demand_on_bars,
    evaluate_fundamentals_price_on_bars,
    evaluate_macro_conditioned_on_bars,
    evaluate_multi_day_hold_on_bars,
)
from research.offline.multiyear_report import assemble_class_hyp_multi_year_report

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
    view: Any | None = None,
    mirror_dir: str | Path | None = None,
    sqlite_path: str | Path | None = None,
    include_cross_section: bool = True,
    include_cross_section_hold_10: bool = True,
    include_cross_section_hold_10_mom3: bool = True,
    include_event_post: bool = True,
    include_flow_demand: bool = True,
    include_fundamentals_price: bool = True,
    include_fundamentals_hold_10: bool = True,
    include_multi_day_hold_10: bool = True,
    cross_section_hold_days: int = 5,
    cross_section_momentum_n: int | None = None,
    cross_section_hold10_momentum_n: int = 5,
    cross_section_hold10_mom3_momentum_n: int = 3,
    cross_section_long_frac: float = 0.3,
    cross_section_short_frac: float = 0.3,
    event_hold_days: int = DEFAULT_EVENT_POST_HOLD_DAYS,
    flow_hold_days: int = DEFAULT_FLOW_HOLD_DAYS,
    flow_require_short_confirm: bool = False,
    flow_short_confirm_mode: str | None = None,  # off|hard|soft
    apply_short_cost_remeasure: bool = True,
    short_borrow_sensitivity: str = "mid",
    short_fraction_ls: float = 0.5,
    fund_hold_days: int = DEFAULT_FUND_HOLD_DAYS,
    fund_momentum_n: int = DEFAULT_FUND_MOMENTUM_N,
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
    """Offline class-hyp window stitch. Candidate needs gate + floors + stats bar.

    Local bars/SQLite only. Not READY / Mass / GO. event_post is PIT entry.
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

    if mirror_dir is not None or sqlite_path is not None:
        raise TypeError(
            "offline multiyear cannot take raw mirror/sqlite market paths; "
            "pass PersonalResearchDataView"
        )
    if not isinstance(view, PersonalResearchDataView):
        raise TypeError("eval sqlite loaders require PersonalResearchDataView")
    as_of_s = max(

        (
            str(p.get("period_end") or p.get("end") or "")[:10]
            for p in period_list
        ),
        default="",
    )
    if not as_of_s:
        raise ValueError("as_of is required (PIT has no latest default)")
    repo_rows = load_repo_rows_from_sqlite(view, as_of=as_of_s)
    repo_series = (
        load_repo_rate_series_from_rows(repo_rows) if repo_rows else None
    )
    repo_load_note = {
        "source": "local_sqlite_jsda_repo_rates",
        "view_kind": getattr(view, "kind", None),
        "n_rows": len(repo_rows),
        "as_of": as_of_s,
        "series_n_dates": (
            len((repo_series or {}).get("rates_by_date") or {})
            if repo_series
            else 0
        ),
        "pit_disclosure": (
            "available_at IS NOT NULL AND available_at <= as_of. "
            "as_of_date range is additive. No invent fill."
        ),
        "dataset": REPO_DATASET_ID,
    }

    # Fins lookback buffer for prior EPS / as-of PIT
    fins_global_start = "2014-01-01"
    fins_global_end = "2026-12-31"
    fins_summary_events = (
        load_fins_events_from_sqlite(
            view,
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
            view,
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
        "view_kind": getattr(view, "kind", None),
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
            "fins_summary DiscDate+DiscTime PIT entry; earnings_date thickens "
            "calendar only. Surprise needs fins_summary EPS/FEPS. No invent."
        ),
        "entry_mode": EVENT_POST_ENTRY_MODE,
        "dataset": event_source,
    }

    short_series_full = (
        load_short_ratio_series_from_sqlite(
            view, section="0050", start="2014-01-01", end="2026-12-31"
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
    result_sinks: list[tuple[bool, list[dict[str, Any]]]] = [
        (True, results_md),
        (True, results_macro),
        (include_cross_section, results_xs),
        (include_cross_section_hold_10, results_xs10),
        (include_cross_section_hold_10_mom3, results_xs10_mom3),
        (include_event_post, results_event),
        (include_flow_demand, results_flow),
        (include_fundamentals_price, results_fund),
        (include_fundamentals_hold_10, results_fund10),
        (include_multi_day_hold_10, results_md10),
    ]

    def _push_status(row: Mapping[str, Any]) -> None:
        payload = dict(row)
        for include, dest in result_sinks:
            if include:
                dest.append(dict(payload))

    for raw in period_list:
        p = dict(raw)
        pid = str(p.get("period_id") or p.get("year") or "period")
        year = p.get("year")
        p_start = str(p.get("period_start") or "")[:10] or None
        p_end = str(p.get("period_end") or "")[:10] or None
        if not p_start or not p_end:
            _push_status(
                {
                    "period_id": pid,
                    "year": year,
                    "status": "skipped",
                    "skip_reason": f"bars period missing for {pid}",
                }
            )
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

            rich = load_bars_from_sqlite_rich(
                view,
                codes=selected,
                period_start=p_start,
                period_end=p_end,
                max_days=period_max_days,
                decision_date=p_end,
            )
            bars = bars_rich_to_close_panel(rich)
            if not bars:
                raise RuntimeError("no bars after code filter")

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
                    "n_codes": eval_out.get("n_codes"),
                    "gross_signed_mean_active": eval_out.get(
                        "gross_signed_mean_active"
                    ),
                    "net_one_way_mean_active": eval_out.get(
                        "net_one_way_mean_active"
                    ),
                    "n_active_positions": eval_out.get("n_active_positions"),
                    "non_null": eval_out.get("n_active_positions"),
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
                margin = load_margin_from_sqlite(
                    view,
                    codes=selected,
                    start=p_start or (f"{year}-01-01" if year else None),
                    end=p_end or (f"{year}-12-31" if year else None),
                )
                margin_src = "personal_research_data_view"
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
            _push_status(
                {
                    "period_id": pid,
                    "year": year,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return assemble_class_hyp_multi_year_report(
        period_list=period_list,
        selected=selected,
        h=h,
        macro_mode=macro_mode,
        one_way_cost=one_way_cost,
        prefer_liquidity_linked=prefer_liquidity_linked,
        apply_short_cost_remeasure=apply_short_cost_remeasure,
        short_fraction_ls=short_fraction_ls,
        short_borrow_sensitivity=short_borrow_sensitivity,
        apply_robustness_gate=apply_robustness_gate,
        min_periods_gate=min_periods_gate,
        min_active_per_period=min_active_per_period,
        min_economic_net=min_economic_net,
        min_activation_rate_multiday=min_activation_rate_multiday,
        min_events_per_code_year=min_events_per_code_year,
        min_events_per_trading_day=min_events_per_trading_day,
        min_years_research_candidate=min_years_research_candidate,
        max_year_pos_net_share=max_year_pos_net_share,
        min_abs_t_stat=min_abs_t_stat,
        min_sharpe_period=min_sharpe_period,
        min_period_win_rate=min_period_win_rate,
        min_positive_periods=min_positive_periods,
        require_stats_bar=require_stats_bar,
        checklist_complete=checklist_complete,
        include_cross_section=include_cross_section,
        include_cross_section_hold_10=include_cross_section_hold_10,
        include_cross_section_hold_10_mom3=include_cross_section_hold_10_mom3,
        include_event_post=include_event_post,
        include_flow_demand=include_flow_demand,
        include_fundamentals_price=include_fundamentals_price,
        include_fundamentals_hold_10=include_fundamentals_hold_10,
        include_multi_day_hold_10=include_multi_day_hold_10,
        cross_section_hold_days=cross_section_hold_days,
        event_hold_days=event_hold_days,
        flow_hold_days=flow_hold_days,
        fund_hold_days=fund_hold_days,
        xs_mom_n=xs_mom_n,
        xs10_mom_n=xs10_mom_n,
        xs10_mom3_n=xs10_mom3_n,
        xs_long_frac=xs_long_frac,
        xs_short_frac=xs_short_frac,
        fund_mom_n=fund_mom_n,
        fund10_mom_n=fund10_mom_n,
        fund_mode_s=fund_mode_s,
        flow_short_confirm=flow_short_confirm,
        results_md=results_md,
        results_md10=results_md10,
        results_macro=results_macro,
        results_xs=results_xs,
        results_xs10=results_xs10,
        results_xs10_mom3=results_xs10_mom3,
        results_event=results_event,
        results_flow=results_flow,
        results_fund=results_fund,
        results_fund10=results_fund10,
        repo_series=repo_series,
        repo_load_note=repo_load_note,
        fins_load_note=fins_load_note,
        short_load_note=short_load_note,
    )


__all__ = [
    "CLASS_HYP_EVAL_VERSION",
    "CLASS_HYP_EVAL_WAVE",
    "run_class_hyp_multi_year_eval",
]
