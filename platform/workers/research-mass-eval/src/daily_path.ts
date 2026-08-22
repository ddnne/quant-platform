/**
 * Candidate-grade daily MTM path on staged panels (not period-net screen).
 *
 * One Worker isolate evaluates one (or few) logics. The Python driver
 * fans out concurrent POSTs so batch wall-clock ≈ longest isolate.
 * n_survivors from /v1/mass-eval is not a pass.
 */
import { barNativeHeldBook } from "./eval";
import { sharpePeriod, tStatVsZero } from "./metrics";
import { isPathBroken } from "./path_broken";
import type { BarsByCode, LogicSpec, PeriodPanel } from "./types";

export { isPathBroken } from "./path_broken";

const DEFAULT_ONE_WAY = 0.001;

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function amortizedOneWayCost(oneWay: number, holdDays: number): number {
  const h = Math.max(1, Math.floor(holdDays));
  return (2 * oneWay) / h;
}

function unionDates(bars: BarsByCode): string[] {
  const s = new Set<string>();
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__")) continue;
    for (const [d] of pairs || []) s.add(String(d).slice(0, 10));
  }
  return Array.from(s).sort();
}

function closeByMap(bars: BarsByCode): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__")) continue;
    const m: Record<string, number> = {};
    for (const [d, c] of pairs || []) {
      if (finite(c)) m[String(d).slice(0, 10)] = c;
    }
    out[code] = m;
  }
  return out;
}

function momentumAt(
  pairs: Array<[string, number]>,
  n: number,
  i: number,
): number | null {
  if (i < n) return null;
  const base = pairs[i - n][1];
  const last = pairs[i][1];
  if (!finite(base) || !finite(last) || base === 0) return null;
  return (last - base) / base;
}

function signNum(v: number | null | undefined): number | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  if (v > 0) return 1;
  if (v < 0) return -1;
  return 0;
}

function stickyHold(
  daily: Array<number | null>,
  holdDays: number,
): Array<number | null> {
  const h = Math.max(1, Math.floor(holdDays));
  const out: Array<number | null> = new Array(daily.length).fill(null);
  let held: number | null = null;
  let since = 0;
  for (let i = 0; i < daily.length; i++) {
    const entry = signNum(daily[i]);
    if (i === 0 || since >= h) {
      if (entry !== null && entry !== 0) held = entry;
      else if (entry === 0) held = 0;
      since = 1;
    } else {
      since += 1;
    }
    out[i] = held;
  }
  return out;
}

function csRank(
  scores: Record<string, number | null>,
  longFrac: number,
  shortFrac: number,
): Record<string, number> {
  const items = Object.entries(scores)
    .filter(([, v]) => v !== null && Number.isFinite(v as number))
    .map(([c, v]) => [c, v as number] as [string, number])
    .sort((a, b) => b[1] - a[1]);
  const out: Record<string, number> = {};
  for (const c of Object.keys(scores)) out[c] = 0;
  const n = items.length;
  if (!n) return out;
  const nLong = Math.max(1, Math.floor(n * longFrac));
  const nShort = Math.max(1, Math.floor(n * shortFrac));
  for (let i = 0; i < n; i++) {
    const code = items[i][0];
    if (i < nLong) out[code] = 1;
    else if (i >= n - nShort) out[code] = -1;
    else out[code] = 0;
  }
  return out;
}

function mdhHeld(
  bars: BarsByCode,
  holdDays: number,
  polarity: number,
): Record<string, Record<string, number>> {
  const h = Math.max(1, Math.floor(holdDays));
  const pol = polarity < 0 ? -1 : 1;
  const held: Record<string, Record<string, number>> = {};
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__") || !pairs || pairs.length < h + 2) continue;
    const entries = pairs.map((_, i) => {
      const m = momentumAt(pairs, h, i);
      const s = signNum(m);
      return s === null ? null : s * pol;
    });
    const sticky = stickyHold(entries, h);
    held[code] = {};
    for (let i = 0; i < pairs.length; i++) {
      const pos = sticky[i];
      if (pos !== null) held[code][pairs[i][0]] = pos;
    }
  }
  return held;
}

function csHeld(
  bars: BarsByCode,
  momentumN: number,
  holdDays: number,
  longFrac: number,
  shortFrac: number,
  invert: boolean,
): Record<string, Record<string, number>> {
  const n = Math.max(1, Math.floor(momentumN));
  const h = Math.max(1, Math.floor(holdDays));
  const byDate: Record<string, Record<string, number | null>> = {};
  const datesByCode: Record<string, string[]> = {};
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__") || !pairs) continue;
    datesByCode[code] = pairs.map(([d]) => d);
    for (let i = 0; i < pairs.length; i++) {
      const d = pairs[i][0];
      if (!byDate[d]) byDate[d] = {};
      byDate[d][code] = momentumAt(pairs, n, i);
    }
  }
  const dates = Object.keys(byDate).sort();
  const dailyRank: Record<string, Record<string, number | null>> = {};
  for (const d of dates) {
    const ranks = csRank(byDate[d], longFrac, shortFrac);
    for (const [code, sign] of Object.entries(ranks)) {
      if (!dailyRank[code]) dailyRank[code] = {};
      dailyRank[code][d] = invert ? -sign : sign;
    }
  }
  const held: Record<string, Record<string, number>> = {};
  for (const code of Object.keys(datesByCode)) {
    const dlist = datesByCode[code];
    const entries = dlist.map((d) => dailyRank[code]?.[d] ?? null);
    const sticky = stickyHold(entries, h);
    held[code] = {};
    for (let i = 0; i < dlist.length; i++) {
      const pos = sticky[i];
      if (pos !== null) held[code][dlist[i]] = pos;
    }
  }
  return held;
}

export function equityPathDrawdown(
  equities: number[],
  dates: string[],
): {
  max_dd: number | null;
  abs_max_dd: number | null;
  dd_duration_days: number | null;
  recovery_days: number | null;
  recovered: boolean | null;
  total_return: number | null;
  n: number;
  method: string;
} {
  if (!equities.length) {
    return {
      max_dd: null,
      abs_max_dd: null,
      dd_duration_days: null,
      recovery_days: null,
      recovered: null,
      total_return: null,
      n: 0,
      method: "daily_equity_level_peak_to_trough",
    };
  }
  let peak = equities[0];
  let peakI = 0;
  let maxDd = 0;
  let troughI = 0;
  let peakAtDd = 0;
  for (let i = 0; i < equities.length; i++) {
    const v = equities[i];
    if (v > peak) {
      peak = v;
      peakI = i;
    }
    if (peak > 0) {
      const dd = v / peak - 1;
      if (dd < maxDd) {
        maxDd = dd;
        troughI = i;
        peakAtDd = peakI;
      }
    }
  }
  const ddDuration = maxDd < 0 ? troughI - peakAtDd : 0;
  let recoveryDays: number | null = null;
  let recovered = maxDd >= 0;
  if (maxDd < 0) {
    recovered = false;
    const peakLevel = equities[peakAtDd];
    for (let i = troughI + 1; i < equities.length; i++) {
      if (equities[i] >= peakLevel - 1e-15) {
        recoveryDays = i - troughI;
        recovered = true;
        break;
      }
    }
  }
  const totalRet =
    equities[0] !== 0 ? equities[equities.length - 1] / equities[0] - 1 : null;
  return {
    max_dd: maxDd,
    abs_max_dd: Math.abs(maxDd),
    dd_duration_days: ddDuration,
    recovery_days: recoveryDays,
    recovered,
    total_return: totalRet,
    n: equities.length,
    method: "daily_equity_level_peak_to_trough",
  };
}

function heldBookDailyMtm(
  held: Record<string, Record<string, number>>,
  closeBy: Record<string, Record<string, number>>,
  dates: string[],
  holdDays: number,
  oneWay: number,
  repoByDate?: Record<string, number>,
  advByCode?: Record<string, number>,
): {
  dates: string[];
  net_daily: number[];
  occupancy: number | null;
  n_gate_on: number;
} {
  const h = Math.max(1, Math.floor(holdDays));
  const dailyCost = amortizedOneWayCost(oneWay, h) / h;
  const netDaily: number[] = [];
  let nOn = 0;
  if (dates.length < 2) {
    return { dates: [], net_daily: [], occupancy: null, n_gate_on: 0 };
  }
  netDaily.push(0);
  for (let i = 1; i < dates.length; i++) {
    const prev = dates[i - 1];
    const d = dates[i];
    const contribs: number[] = [];
    let nShort = 0;
    const liqMults: number[] = [];
    for (const [code, cmap] of Object.entries(held)) {
      const pos = cmap[prev];
      if (!pos) continue;
      const c0 = closeBy[code]?.[prev];
      const c1 = closeBy[code]?.[d];
      if (!finite(c0) || !finite(c1) || c0 === 0) continue;
      contribs.push(pos * (c1 / c0 - 1));
      if (pos < 0) nShort += 1;
      const adv = advByCode?.[code];
      if (finite(adv)) {
        if (adv >= 1e9) liqMults.push(1.0);
        else if (adv >= 1e8) liqMults.push(1.5);
        else liqMults.push(2.5);
      }
    }
    let net = 0;
    if (contribs.length) {
      const g = contribs.reduce((a, b) => a + b, 0) / contribs.length;
      const liq =
        liqMults.length > 0
          ? liqMults.reduce((a, b) => a + b, 0) / liqMults.length
          : 1.0;
      let shortDrag = 0;
      const repo = repoByDate?.[prev];
      if (nShort && finite(repo)) {
        shortDrag =
          (nShort / contribs.length) * ((repo as number) / 100 / 252) * liq;
      }
      net = g - dailyCost * liq - shortDrag;
      nOn += 1;
    }
    netDaily.push(net);
  }
  const occ = dates.length > 1 ? nOn / (dates.length - 1) : null;
  return { dates, net_daily: netDaily, occupancy: occ, n_gate_on: nOn };
}

export const CF_UNIQUE_CS_LOGIC_IDS = [
  "funding_impulse_cs_tilt",
  "curve_steepen_impulse_cs",
  "xs_margin_delta_rank",
  "idio_mom_macro_impulse",
  "overnight_level_cs_tilt",
  "overnight_easy_cs_follow",
  "month_end_cs_fade",
  "xs_low_vol_mom",
  "repo_3m_level_cs",
  "overnight_tight_cs_fade",
  "curve_invert_cs_fade",
  "xs_high_vol_fade",
  "month_start_cs_follow",
  "rate_change_cs_confirm",
  "flow_price_margin_triple",
  "opt225_skew_cs_gate",
  "nky_vol_term_cs_gate",
  "opt225_spread_cs_tilt",
  "repo_3m_change_cs",
  "flow_margin_price_agree",
  "cs_mom_easy_funding",
  "fy_end_cs_fade",
  "fy_start_cs_follow",
  "curve_steep_cs_follow",
  "overnight_p90_cs_flip",
  "flow_price_disagree_fade",
  "nky_vol_compress_cs",
  "opt225_skew_and_term_cs",
  "basevol_up_day_fade",
  "iv_below_basevol_cs",
  "cs_skip_monday",
  "cs_tue_thu_follow",
  "overnight_down_cs_follow",
  "overnight_up_cs_fade",
  "cs_midmonth_follow",
  "cs_friday_fade",
  "cs_not_month_end",
  "cs_easing_midmonth",
  "cs_tue_thu_down",
  "overnight_down_skip_monday_cs",
  "cs_friday_tight_fade",
  "flow_disagree_midmonth",
  "curve_steep_midmonth_cs",
  "rate_up_tue_thu_cs",
  "cs_steep_skip_monday",
  "cs_midmonth_tight_fade",
  "flow_disagree_tue_thu",
  "iv_below_midmonth_cs",
  "overnight_down_first_half_cs",
  "rate_up_midmonth_cs",
  "cs_month_start_easing",
  "nky_vol_compress_midmonth_cs",
  "cs_friday_down",
  "cs_tue_thu_steep",
  "overnight_up_skip_monday_cs",
  "flow_disagree_skip_monday",
  "cs_easy_tue_thu",
  "cs_easy_skip_monday",
  "cs_not_friday_down",
  "cs_midmonth_easy",
  "cs_steep_friday",
  "cs_skip_tuesday",
  "cs_skip_wednesday",
  "cs_not_last_week",
  "cs_month_start7",
  "cs_not_first_week",
  "cs_easy_skip_friday",
  "flow_disagree_skip_friday",
  "overnight_down_skip_tuesday_cs",
  "cs_margin_up_chase",
  "cs_margin_down_follow",
  "cs_short_ratio_up_fade",
  "cs_on_impulse",
  "cs_overnight_p10",
  "cs_repo3m_down",
  "cs_curve_flatten",
  "cs_nky_vol_high_fade",
  "cs_cheap_pb",
  "cs_expensive_pb_fade",
  "cs_earnings_yield_high",
  "cs_roe_high",
  "cs_div_positive",
  "cs_np_positive",
] as const;

function usesCrossSection(logic: LogicSpec): boolean {
  const lid = String(logic.logic_id || "");
  const fam = String(logic.family_id || "");
  return (
    (CF_UNIQUE_CS_LOGIC_IDS as readonly string[]).includes(lid) ||
    (CF_NEW_CS_THESIS_IDS as readonly string[]).includes(lid) ||
    lid.startsWith("xs_") ||
    lid.includes("cross_section") ||
    fam.includes("cross_section") ||
    lid.startsWith("nky_vol_") ||
    lid.startsWith("opt225_") ||
    lid.startsWith("fund_") ||
    lid.startsWith("mf_") ||
    lid.startsWith("overnight_") ||
    lid.startsWith("funding_impulse") ||
    lid.startsWith("curve_steepen") ||
    lid.startsWith("month_end") ||
    lid.startsWith("repo_3m") ||
    lid.startsWith("idio_mom") ||
    lid.startsWith("xs_margin")
  );
}

/** Filled vs intended-lite gaps vs Python unique_logic. Keep in sync with
 * research.unique_logic.constants.CF_EVENT_FIDELITY. */
export const CF_EVENT_FIDELITY = {
  surprise: "aligned: feps-eps else eps-prior_eps (no invent)",
  adaptive_trail_k: "aligned: last K completed holds orig vs flip; min K",
  margin_pit: "aligned: last print < entry, stale<=14d, level < PIT median",
  surprise_xs: "aligned: rank surprise among in-window names (not price mom)",
  intended_lite_windows: "Worker period shards vs Python HONEST_3Y stitch",
  intended_lite_entry: "disc_time hour>=15 vs full event_post_entry_bar_index",
} as const;

export const CF_NEW_EVENT_THESIS_IDS = [
  "event_funding_tight_fade",
  "event_curve_invert_fade",
  "event_afterclose_easy_funding",
  "event_large_surprise_easy_funding",
  "event_pre_mom_easy_funding",
  "event_margin_or_funding_skip",
  "event_large_surprise_steep_curve",
  "event_afterclose_steep_curve",
  "event_tight_and_crowded_fade",
  "event_cluster_easy_pead",
  "surprise_xs_rank_easy_funding",
  "surprise_xs_rank_steep_curve",
  "event_pre_mom_steep_curve",
  "event_large_surprise_afterclose",
  "event_margin_uncrowded_steep",
  "event_easy_funding_curve_steep",
  "event_skip_announce_day",
  "event_late_hold_only",
  "month_end_event_skip",
  "event_first_half_month",
  "overnight_easing_event",
  "overnight_tightening_fade_event",
  "event_cluster_fade",
  "margin_crowd_fade_event",
  "surprise_xs_month_start",
  "surprise_xs_fy_end",
  "event_afterclose_delay2",
  "event_skip_monday",
  "event_tue_thu_only",
  "event_friday_skip",
  "fy_end_event_fade",
  "fy_start_event_follow",
  "event_midmonth_only",
  "surprise_xs_afterclose",
  "event_easing_uncrowded",
  "surprise_xs_tue_thu",
  "event_afterclose_midmonth",
  "event_easing_midmonth",
  "event_friday_easing",
  "event_uncrowded_midmonth",
  "event_may_results_follow",
  "event_tue_thu_easing",
  "surprise_xs_midmonth",
  "surprise_xs_easing_change",
  "surprise_xs_afterclose_easing",
  "event_tue_thu_uncrowded",
  "event_afterclose_easing",
  "event_may_easing",
  "event_skip_monday_uncrowded",
  "event_first_half_easing",
  "surprise_xs_skip_monday",
  "surprise_xs_friday_skip",
  "surprise_xs_uncrowded",
  "event_friday_uncrowded",
  "event_skip_monday_easing",
  "event_afterclose_skip_monday",
  "event_easing_skip_friday",
  "event_first_half_uncrowded",
  "event_tue_thu_steep",
  "event_midmonth_steep",
  "surprise_xs_first_half",
  "surprise_xs_afterclose_skip_monday",
  "surprise_xs_steep_skip_monday",
  "surprise_xs_uncrowded_skip_monday",
  "event_skip_tuesday",
  "event_skip_wednesday",
  "event_not_last_week",
  "event_month_start7",
  "event_not_first_week",
  "event_afterclose_skip_friday",
  "event_easing_skip_tuesday",
  "event_uncrowded_skip_friday",
  "event_tight_skip_monday",
  "event_cluster_skip_monday",
  "event_easy_skip_tuesday",
  "event_afterclose_not_last_week",
  "surprise_xs_skip_tuesday",
  "surprise_xs_not_last_week",
  "surprise_xs_month_start7",
  "surprise_xs_not_first_week",
  "surprise_xs_easing_skip_friday",
  "surprise_xs_afterclose_skip_friday",
  "surprise_xs_tight_fade",
  "surprise_xs_on_impulse",
  "surprise_xs_invert_fade",
  "event_on_impulse_pead",
  "event_margin_delta_fade",
  "event_cheap_iv_pead",
  "event_rich_iv_fade",
  "surprise_xs_cheap_iv",
  "event_positive_eps_pead",
  "event_cheap_pb_pead",
  "surprise_xs_eps_up",
  "event_div_payer_pead",
  "event_eqar_high_pead",
  "event_eqar_low_fade",
  "event_ta_up_pead",
  "surprise_xs_eqar_high",
  "event_cheap_pb_easy_funding",
  "surprise_xs_margin_up_fade",
  "event_margin_down_follow",
  "event_crowd_on_impulse",
  "surprise_xs_margin_up",
  "event_overnight_p10_pead",
  "event_curve_flatten_pead",
  "event_repo3m_down_pead",
  "surprise_xs_repo3m_down",
  "event_cheap_iv_cheap_pb",
  "surprise_xs_rich_iv_fade",
  "event_nky_high_skip",
  "surprise_xs_div_payer",
  "event_eqar_high_easy",
  "event_eqar_high_on_impulse",
  "event_eqar_low_tight_fade",
  "event_ta_up_easy_funding",
  "surprise_xs_eqar_high_easy",
  "event_eqar_high_repo3m_down",
  "event_ta_up_curve_flatten",
  "surprise_xs_ta_up",
  "event_eqar_low_on_impulse_fade",
  "event_eqar_high_overnight_p10",
  "surprise_xs_margin_down",
  "event_margin_up_tight_fade",
  "event_margin_down_easy",
  "surprise_xs_margin_up_on_impulse",
  "event_repo3m_down_uncrowded",
  "surprise_xs_overnight_p10",
  "event_curve_flatten_uncrowded",
  "event_on_impulse_uncrowded",
  "event_eqar_high_cheap_iv",
  "surprise_xs_eqar_high_cheap_iv",
  "event_ta_up_cheap_iv",
  "event_rich_iv_eqar_low_fade",
  "event_div_payer_easy",
  "surprise_xs_eqar_low_fade",
  "event_positive_eps_easy",
  "event_cheap_pb_on_impulse",
  "event_ta_up_on_impulse",
  "event_eqar_high_uncrowded",
  "event_ta_up_uncrowded",
  "surprise_xs_ta_up_easy",
  "event_eqar_low_repo3m_down_fade",
  "event_eqar_high_steep",
  "surprise_xs_eqar_high_repo3m_down",
  "event_ta_up_overnight_p10",
  "event_eqar_high_afterclose",
  "event_margin_down_on_impulse",
  "event_margin_up_easy",
  "surprise_xs_eqar_high_on_impulse",
  "event_eqar_low_cheap_iv_fade",
  "surprise_xs_div_payer_easy",
  "event_div_payer_cheap_iv",
  "event_positive_eps_on_impulse",
  "event_cheap_pb_repo3m_down",
  "event_overnight_p10_eqar_low_fade",
  "surprise_xs_curve_flatten",
  "event_ta_up_afterclose",
  "event_eps_up_easy",
  "surprise_xs_ta_up_on_impulse",
  "event_eqar_high_margin_down",
  "event_ta_up_margin_down",
  "event_cheap_pb_uncrowded",
  "surprise_xs_positive_eps_easy",
  "event_repo3m_down_afterclose",
  "surprise_xs_margin_down_on_impulse",
  "event_eqar_high_cluster",
  "event_ta_up_cluster",
  "event_cheap_pb_cluster",
  "event_eqar_high_large_surprise",
  "event_ta_up_large_surprise",
  "event_cheap_pb_large_surprise",
  "event_eqar_high_margin_up_fade",
  "event_ta_up_margin_up_fade",
  "event_cheap_pb_margin_up_fade",
  "event_eqar_high_liq_high",
  "event_ta_up_liq_high",
  "event_cheap_pb_liq_high",
  "event_eqar_high_price_down",
  "event_ta_up_price_down",
  "event_cheap_pb_price_down",
  "event_margin_up_price_down_fade",
  "event_margin_down_price_down",
  "event_eqar_high_eps_up",
  "event_ta_up_eps_up",
  "event_positive_eps_margin_down",
  "event_div_payer_margin_down",
  "event_eqar_low_margin_up_fade",
  "event_liq_high_large_surprise",
  "surprise_xs_eqar_high_liq_high",
  "surprise_xs_margin_up_price_down",
  "surprise_xs_eqar_high_price_down",
] as const;

export const CF_NEW_CS_THESIS_IDS = [
  "overnight_tight_cs_fade",
  "curve_invert_cs_fade",
  "xs_high_vol_fade",
  "month_start_cs_follow",
  "rate_change_cs_confirm",
  "flow_price_margin_triple",
  "opt225_skew_cs_gate",
  "nky_vol_term_cs_gate",
  "opt225_spread_cs_tilt",
  "repo_3m_change_cs",
  "flow_margin_price_agree",
  "cs_mom_easy_funding",
  "fy_end_cs_fade",
  "fy_start_cs_follow",
  "curve_steep_cs_follow",
  "overnight_p90_cs_flip",
  "flow_price_disagree_fade",
  "nky_vol_compress_cs",
  "opt225_skew_and_term_cs",
  "basevol_up_day_fade",
  "iv_below_basevol_cs",
  "cs_skip_monday",
  "cs_tue_thu_follow",
  "overnight_down_cs_follow",
  "overnight_up_cs_fade",
  "cs_midmonth_follow",
  "cs_friday_fade",
  "cs_not_month_end",
  "cs_easing_midmonth",
  "cs_tue_thu_down",
  "overnight_down_skip_monday_cs",
  "cs_friday_tight_fade",
  "flow_disagree_midmonth",
  "curve_steep_midmonth_cs",
  "rate_up_tue_thu_cs",
  "cs_steep_skip_monday",
  "cs_midmonth_tight_fade",
  "flow_disagree_tue_thu",
  "iv_below_midmonth_cs",
  "overnight_down_first_half_cs",
  "rate_up_midmonth_cs",
  "cs_month_start_easing",
  "nky_vol_compress_midmonth_cs",
  "cs_friday_down",
  "cs_tue_thu_steep",
  "overnight_up_skip_monday_cs",
  "flow_disagree_skip_monday",
  "cs_easy_tue_thu",
  "cs_easy_skip_monday",
  "cs_not_friday_down",
  "cs_midmonth_easy",
  "cs_steep_friday",
  "cs_skip_tuesday",
  "cs_skip_wednesday",
  "cs_not_last_week",
  "cs_month_start7",
  "cs_not_first_week",
  "cs_easy_skip_friday",
  "flow_disagree_skip_friday",
  "overnight_down_skip_tuesday_cs",
  "cs_margin_up_chase",
  "cs_margin_down_follow",
  "cs_short_ratio_up_fade",
  "cs_on_impulse",
  "cs_overnight_p10",
  "cs_repo3m_down",
  "cs_curve_flatten",
  "cs_nky_vol_high_fade",
  "cs_cheap_pb",
  "cs_expensive_pb_fade",
  "cs_earnings_yield_high",
  "cs_roe_high",
  "cs_div_positive",
  "cs_np_positive",
  "cs_eqar_high",
  "cs_eqar_low_fade",
  "cs_ta_up",
  "cs_eqar_high_easy",
  "cs_eqar_high_cheap_iv",
  "cs_margin_up_tight_fade",
  "cs_short_ratio_down_follow",
  "cs_eqar_high_repo3m_down",
  "cs_margin_down_easy",
  "cs_overnight_p10_steep",
  "cs_repo3m_down_easy",
  "cs_cheap_pb_cheap_iv",
  "cs_eqar_high_flatten",
  "cs_eqar_high_overnight_p10",
  "cs_ta_up_easy",
  "cs_margin_up_easy",
  "cs_curve_flatten_easy",
  "cs_eqar_low_tight",
  "cs_eqar_high_margin_down",
  "cs_ta_up_margin_down",
  "cs_cheap_pb_easy",
  "cs_eqar_high_on_impulse",
] as const;

export const CF_EVENT_LOGIC_IDS = [
  "event_funding_stress_skip",
  "curve_steep_event_confirm",
  "disclosure_cluster_mom_gate",
  "surprise_xs_rank_hold",
  "large_surprise_event_hold",
  "afterclose_only_event_hold",
  "event_pre_mom_agree_hold",
  "event_margin_crowding_skip",
  "event_funding_easy_short",
  "event_funding_stress_ls",
  "surprise_xs_rank_flip",
  "event_funding_adaptive_side",
  "surprise_xs_rank_adaptive",
  ...CF_NEW_EVENT_THESIS_IDS,
] as const;

function isEventLogic(lid: string): boolean {
  return (CF_EVENT_LOGIC_IDS as readonly string[]).includes(lid);
}

function surpriseProxy(ev: {
  eps?: number | null;
  feps?: number | null;
  prior_eps?: number | null;
}): number | null {
  const e = ev.eps;
  const f = ev.feps;
  const p = ev.prior_eps;
  if (finite(e) && finite(f)) return (f as number) - (e as number);
  if (finite(e) && finite(p)) return (e as number) - (p as number);
  return null;
}

function afterClose(discTime: string | null | undefined): boolean {
  const t = String(discTime || "").trim();
  if (t.length < 4) return false;
  const hh = Number(t.slice(0, 2));
  return Number.isFinite(hh) && hh >= 15;
}

const COMBO_EVENT_GATES = new Set([
  "skip_monday",
  "skip_tuesday",
  "skip_wednesday",
  "friday_skip",
  "friday_only",
  "tue_thu",
  "not_last_week",
  "month_start7",
  "not_first_week",
  "first_half_month",
  "midmonth",
  "afterclose",
  "overnight_easing",
  "easy_funding",
  "tight_funding",
  "steep_curve",
  "uncrowded_margin",
  "cluster",
  "invert_curve",
  "on_impulse",
  "cheap_iv",
  "rich_iv",
  "cheap_pb",
  "positive_eps",
  "eps_up",
  "div_positive",
  "margin_up",
  "margin_down",
  "eq_ar_high",
  "eq_ar_low",
  "ta_up",
  "overnight_p10",
  "curve_flatten",
  "repo_3m_down",
  "nky_vol_high_skip",
  "large_surprise",
  "liq_high",
  "price_down",
]);

function comboGatesOf(params: Record<string, unknown>): string[] {
  const g = params.gates;
  if (Array.isArray(g)) return g.map((x) => String(x)).filter(Boolean);
  return [];
}

function comboGatesImplemented(gates: string[]): boolean {
  return gates.length > 0 && gates.every((g) => COMBO_EVENT_GATES.has(g));
}

function overnightEased(
  overnight: Record<string, number>,
  d: string,
): boolean {
  const prevs = Object.keys(overnight)
    .filter((x) => x < d)
    .sort();
  const on = overnight[d];
  if (!prevs.length || on === undefined) return false;
  return on < overnight[prevs[prevs.length - 1]];
}

export function comboEventGateOk(
  gate: string,
  ev: {
    code: string;
    disc: string;
    entryDate: string;
    entryIdx: number;
    sign: number;
    abs: number;
    after: boolean;
    eps?: number | null;
    prior_eps?: number | null;
    bps?: number | null;
    div_ann?: number | null;
    np?: number | null;
    roe?: number | null;
    ta?: number | null;
    eq_ar?: number | null;
    prior_ta?: number | null;
  },
  overnight: Record<string, number>,
  spread: Record<string, number>,
  minHist: number,
  panel: PeriodPanel,
): boolean {
  const d = ev.entryDate;
  const wd = weekdayMon0(d);
  const dd = d.slice(8, 10);
  if (gate === "skip_monday") return wd !== 0;
  if (gate === "skip_tuesday") return wd !== 1;
  if (gate === "skip_wednesday") return wd !== 2;
  if (gate === "friday_skip") return wd !== 4;
  if (gate === "friday_only") return wd === 4;
  if (gate === "tue_thu") return [1, 2, 3].includes(wd);
  if (gate === "not_last_week") return dd < "24";
  if (gate === "month_start7") return dd <= "07";
  if (gate === "not_first_week") return dd > "07";
  if (gate === "first_half_month") return dd <= "15";
  if (gate === "midmonth") return dd >= "10" && dd <= "20";
  if (gate === "afterclose") return ev.after;
  if (gate === "overnight_easing") return overnightEased(overnight, d);
  if (gate === "easy_funding") {
    const on = overnight[d];
    const med = pitMedian(overnight, d, minHist);
    return on !== undefined && med !== null && on < med;
  }
  if (gate === "tight_funding") {
    const on = overnight[d];
    const med = pitMedian(overnight, d, minHist);
    return on !== undefined && med !== null && on >= med;
  }
  if (gate === "steep_curve") {
    const sp = spread[d];
    return sp !== undefined && sp > 0;
  }
  if (gate === "uncrowded_margin") {
    const levels = panel.flow_regime?.margin_level_by_code?.[ev.code] || {};
    const prior = Object.keys(levels)
      .filter((x) => x < d)
      .sort();
    if (!prior.length) return false;
    const lastD = prior[prior.length - 1];
    const age =
      (Date.parse(d + "T00:00:00Z") - Date.parse(lastD + "T00:00:00Z")) /
      86400000;
    const med = pitMedian(levels, d, minHist);
    if (!Number.isFinite(age) || age > 14 || med === null) return false;
    return (levels[lastD] as number) < med;
  }
  if (gate === "cluster") {
    const events = panel.fund_regime?.events_by_code || {};
    const discs: string[] = [];
    for (const rows of Object.values(events)) {
      for (const row of rows || []) {
        const x = String(row.disc_date || "").slice(0, 10);
        if (x) discs.push(x);
      }
    }
    const nDisc = discs.filter(
      (x) => x < ev.disc && x >= addDays(ev.disc, -5),
    ).length;
    const hist: Record<string, number> = {};
    for (const dd0 of discs) {
      if (dd0 >= ev.disc) continue;
      hist[dd0] = discs.filter(
        (x) => x < dd0 && x >= addDays(dd0, -5),
      ).length;
    }
    const med = pitMedian(hist, ev.disc, 10);
    return med !== null && nDisc >= med;
  }
  if (gate === "invert_curve") {
    const sp = spread[d];
    return sp !== undefined && sp <= 0;
  }
  if (gate === "on_impulse") {
    const prevs = Object.keys(overnight)
      .filter((x) => x < d)
      .sort();
    const on = overnight[d];
    if (!prevs.length || on === undefined) return false;
    const absCh = Math.abs(on - overnight[prevs[prevs.length - 1]]);
    const hist: Record<string, number> = {};
    for (let i = 1; i < prevs.length; i++) {
      hist[prevs[i]] = Math.abs(overnight[prevs[i]] - overnight[prevs[i - 1]]);
    }
    const med = pitMedian(hist, d, minHist);
    return med !== null && absCh >= med;
  }
  if (gate === "cheap_iv") {
    const iv = panel.atm_iv_series?.[d];
    const bv = panel.base_vol_series?.[d];
    return finite(iv) && finite(bv) && (iv as number) < (bv as number);
  }
  if (gate === "rich_iv") {
    const iv = panel.atm_iv_series?.[d];
    const bv = panel.base_vol_series?.[d];
    return finite(iv) && finite(bv) && (iv as number) > (bv as number);
  }
  if (gate === "positive_eps") {
    return ev.eps != null && finite(ev.eps) && (ev.eps as number) > 0;
  }
  if (gate === "eps_up") {
    return (
      ev.eps != null &&
      ev.prior_eps != null &&
      finite(ev.eps) &&
      finite(ev.prior_eps) &&
      (ev.eps as number) > (ev.prior_eps as number)
    );
  }
  if (gate === "div_positive") {
    return ev.div_ann != null && finite(ev.div_ann) && (ev.div_ann as number) > 0;
  }
  if (gate === "margin_up") {
    const chg = panel.flow_regime?.margin_change_by_code?.[ev.code]?.[d];
    return finite(chg) && (chg as number) > 0;
  }
  if (gate === "cheap_pb") {
    const close = panel.bars?.[ev.code]?.find(([x]) => x === d)?.[1];
    if (!finite(close) || ev.bps == null || !finite(ev.bps) || ev.bps === 0)
      return false;
    const pb = (close as number) / (ev.bps as number);
    const hist: Record<string, number> = {};
    const fins = panel.fund_regime?.events_by_code?.[ev.code] || [];
    const pairs = panel.bars?.[ev.code] || [];
    for (const [dd, px] of pairs) {
      if (dd >= d) break;
      const fin = [...fins].reverse().find((e) => String(e.disc_date || "") <= dd);
      const bps = fin?.bps;
      if (finite(px) && finite(bps) && (bps as number) !== 0) {
        hist[dd] = (px as number) / (bps as number);
      }
    }
    const med = pitMedian(hist, d, minHist);
    return med !== null && pb < med;
  }
  if (gate === "margin_down") {
    const chg = panel.flow_regime?.margin_change_by_code?.[ev.code]?.[d];
    return finite(chg) && (chg as number) < 0;
  }
  if (gate === "eq_ar_high" || gate === "eq_ar_low") {
    if (ev.eq_ar == null || !finite(ev.eq_ar)) return false;
    const hist: Record<string, number> = {};
    for (const row of panel.fund_regime?.events_by_code?.[ev.code] || []) {
      const dd = String(row.disc_date || "").slice(0, 10);
      if (dd && dd < d && finite(row.eq_ar)) hist[dd] = row.eq_ar as number;
    }
    const med = pitMedian(hist, d, 8);
    if (med === null) return false;
    return gate === "eq_ar_high"
      ? (ev.eq_ar as number) >= med
      : (ev.eq_ar as number) < med;
  }
  if (gate === "ta_up") {
    return (
      ev.ta != null &&
      ev.prior_ta != null &&
      finite(ev.ta) &&
      finite(ev.prior_ta) &&
      (ev.ta as number) > (ev.prior_ta as number)
    );
  }
  if (gate === "overnight_p10") {
    const hist = Object.keys(overnight)
      .filter((x) => x < d)
      .map((x) => overnight[x])
      .filter((v) => finite(v))
      .sort((a, b) => a - b);
    const on = overnight[d];
    if (hist.length < 20 || on === undefined) return false;
    const p10 = hist[Math.max(0, Math.floor(0.1 * (hist.length - 1)))];
    return on <= p10;
  }
  if (gate === "curve_flatten") {
    const prevs = Object.keys(spread)
      .filter((x) => x < d)
      .sort();
    const sp = spread[d];
    if (!prevs.length || !finite(sp)) return false;
    const psp = spread[prevs[prevs.length - 1]];
    return finite(psp) && (sp as number) < (psp as number);
  }
  if (gate === "repo_3m_down") {
    const prevs = Object.keys(overnight)
      .filter((x) => x < d)
      .sort();
    const on = overnight[d];
    const sp = spread[d];
    if (!prevs.length || on === undefined || !finite(sp)) return false;
    const prev = prevs[prevs.length - 1];
    const psp = spread[prev];
    return (
      finite(overnight[prev]) &&
      finite(psp) &&
      on + (sp as number) < overnight[prev] + (psp as number)
    );
  }
  if (gate === "nky_vol_high_skip") {
    const nky = panel.nky_vol_series?.rv_abs_by_date || {};
    const med = pitMedian(nky, d, 20);
    if (med === null || !finite(nky[d])) return false;
    return nky[d] < med;
  }
  if (gate === "large_surprise") {
    const events = panel.fund_regime?.events_by_code || {};
    const abs: number[] = [];
    for (const rows of Object.values(events)) {
      for (const row of rows || []) {
        const dd = String(row.disc_date || "").slice(0, 10);
        if (!dd || dd >= ev.disc) continue;
        const s = surpriseProxy(row);
        if (s !== null) abs.push(Math.abs(s));
      }
    }
    if (abs.length < minHist) return false;
    abs.sort((a, b) => a - b);
    const mid = Math.floor(abs.length / 2);
    const med = abs.length % 2 ? abs[mid] : (abs[mid - 1] + abs[mid]) / 2;
    return finite(ev.abs) && ev.abs >= med;
  }
  if (gate === "liq_high") {
    const advMap = panel.adv_by_code || {};
    const adv = advMap[ev.code];
    const vals = Object.values(advMap).filter((v) => finite(v)) as number[];
    if (!finite(adv) || vals.length < 4) return false;
    const srt = vals.slice().sort((a, b) => a - b);
    const med = srt[Math.floor(srt.length / 2)];
    return (adv as number) >= med;
  }
  if (gate === "price_down") {
    const pairs = panel.bars?.[ev.code] || [];
    const i = ev.entryIdx;
    if (i < 5 || !pairs[i] || !pairs[i - 5]) return false;
    const c0 = pairs[i - 5][1];
    const c1 = pairs[i][1];
    if (!finite(c0) || !finite(c1) || (c0 as number) === 0) return false;
    return (c1 as number) / (c0 as number) - 1 < 0;
  }
  // Unknown gate fails closed (do not silently always-on).
  return false;
}

export function comboCsGateOk(
  gate: string,
  d: string,
  overnight: Record<string, number>,
  spread: Record<string, number>,
  prev: string | null,
  medOn: number | null,
  marginChg: number | null,
  extras?: {
    shortUp?: boolean;
    nkyHigh?: boolean;
    cheapPb?: boolean;
    expensivePb?: boolean;
    eyHigh?: boolean;
    roeHigh?: boolean;
    divPositive?: boolean;
    npPositive?: boolean;
    eqArHigh?: boolean;
    eqArLow?: boolean;
    taUp?: boolean;
    cheapIv?: boolean;
    tightOn?: boolean;
    shortDown?: boolean;
  },
): { keep: boolean; invert: boolean } {
  const wd = weekdayMon0(d);
  const dd = d.slice(8, 10);
  const on = overnight[d];
  let invert = gate.includes("invert");
  let keep = false;
  if (gate === "skip_tuesday") keep = wd !== 1;
  else if (gate === "skip_wednesday") keep = wd !== 2;
  else if (gate === "not_last_week") keep = dd < "24";
  else if (gate === "month_start7") keep = dd <= "07";
  else if (gate === "not_first_week") keep = dd > "07";
  else if (gate === "overnight_easy_skip_friday") {
    keep = wd !== 4 && on !== undefined && medOn !== null && on < medOn;
  } else if (gate === "margin_crowd_skip_friday_invert") {
    keep = wd !== 4 && marginChg !== null && marginChg > 0;
    invert = true;
  } else if (gate === "overnight_down_skip_tuesday") {
    keep =
      wd !== 1 &&
      prev !== null &&
      finite(overnight[prev]) &&
      on !== undefined &&
      on < overnight[prev];
  } else if (gate === "margin_up") {
    keep = marginChg !== null && marginChg > 0;
  } else if (gate === "margin_down") {
    keep = marginChg !== null && marginChg < 0;
  } else if (gate === "on_impulse") {
    if (prev === null || on === undefined || !finite(overnight[prev])) keep = false;
    else {
      const absCh = Math.abs(on - overnight[prev]);
      const hist: Record<string, number> = {};
      const keys = Object.keys(overnight).sort();
      for (let i = 1; i < keys.length; i++) {
        if (keys[i] >= d) break;
        hist[keys[i]] = Math.abs(overnight[keys[i]] - overnight[keys[i - 1]]);
      }
      const med = pitMedian(hist, d, 20);
      keep = med !== null && absCh >= med;
    }
  } else if (gate === "overnight_p10") {
    const hist = Object.keys(overnight)
      .filter((x) => x < d)
      .map((x) => overnight[x])
      .filter((v) => finite(v))
      .sort((a, b) => a - b);
    if (hist.length < 20 || on === undefined) keep = false;
    else {
      const p10 = hist[Math.max(0, Math.floor(0.1 * (hist.length - 1)))];
      keep = on <= p10;
    }
  } else if (gate === "repo_3m_down") {
    if (prev === null || on === undefined) keep = false;
    else {
      const sp = spread[d];
      const psp = spread[prev];
      keep =
        finite(sp) &&
        finite(psp) &&
        finite(overnight[prev]) &&
        on + (sp as number) < overnight[prev] + (psp as number);
    }
  } else if (gate === "curve_flatten") {
    if (prev === null) keep = false;
    else {
      const sp = spread[d];
      const psp = spread[prev];
      keep = finite(sp) && finite(psp) && (sp as number) < (psp as number);
    }
  } else if (gate === "short_ratio_up_invert") {
    keep = extras?.shortUp === true;
    invert = true;
  } else if (gate === "nky_vol_high_invert") {
    keep = extras?.nkyHigh === true;
    invert = true;
  } else if (gate === "cheap_pb") {
    keep = extras?.cheapPb === true;
  } else if (gate === "expensive_pb_invert") {
    keep = extras?.expensivePb === true;
    invert = true;
  } else if (gate === "earnings_yield_high") {
    keep = extras?.eyHigh === true;
  } else if (gate === "roe_high") {
    keep = extras?.roeHigh === true;
  } else if (gate === "div_positive") {
    keep = extras?.divPositive === true;
  } else if (gate === "np_positive") {
    keep = extras?.npPositive === true;
  } else if (gate === "eq_ar_high") {
    keep = extras?.eqArHigh === true;
  } else if (gate === "eq_ar_low_invert") {
    keep = extras?.eqArLow === true;
    invert = true;
  } else if (gate === "ta_up") {
    keep = extras?.taUp === true;
  } else if (gate === "eq_ar_high_easy") {
    keep =
      extras?.eqArHigh === true &&
      on !== undefined &&
      medOn !== null &&
      on < medOn;
  } else if (gate === "eq_ar_high_cheap_iv") {
    keep = extras?.eqArHigh === true && extras?.cheapIv === true;
  } else if (gate === "margin_up_tight_invert") {
    keep = marginChg !== null && marginChg > 0 && extras?.tightOn === true;
    invert = true;
  } else if (gate === "short_ratio_down") {
    keep = extras?.shortDown === true;
  } else if (gate === "eq_ar_high_repo3m_down") {
    let repoDown = false;
    if (prev !== null && on !== undefined) {
      const sp = spread[d];
      const psp = spread[prev];
      repoDown =
        finite(sp) &&
        finite(psp) &&
        finite(overnight[prev]) &&
        on + (sp as number) < overnight[prev] + (psp as number);
    }
    keep = extras?.eqArHigh === true && repoDown;
  } else if (gate === "eq_ar_high_flatten") {
    let flat = false;
    if (prev !== null) {
      const sp = spread[d];
      const psp = spread[prev];
      flat = finite(sp) && finite(psp) && (sp as number) < (psp as number);
    }
    keep = extras?.eqArHigh === true && flat;
  } else if (gate === "margin_down_easy") {
    keep =
      marginChg !== null &&
      marginChg < 0 &&
      on !== undefined &&
      medOn !== null &&
      on < medOn;
  } else if (gate === "overnight_p10_steep") {
    const hist = Object.keys(overnight)
      .filter((x) => x < d)
      .map((x) => overnight[x])
      .filter((v) => finite(v))
      .sort((a, b) => a - b);
    let p10ok = false;
    if (hist.length >= 20 && on !== undefined) {
      const p10 = hist[Math.max(0, Math.floor(0.1 * (hist.length - 1)))];
      p10ok = on <= p10;
    }
    keep = p10ok && spread[d] !== undefined && spread[d] > 0;
  } else if (gate === "repo3m_down_easy") {
    let repoDown = false;
    if (prev !== null && on !== undefined) {
      const sp = spread[d];
      const psp = spread[prev];
      repoDown =
        finite(sp) &&
        finite(psp) &&
        finite(overnight[prev]) &&
        on + (sp as number) < overnight[prev] + (psp as number);
    }
    keep =
      repoDown && on !== undefined && medOn !== null && on < medOn;
  } else if (gate === "cheap_pb_cheap_iv") {
    keep = extras?.cheapPb === true && extras?.cheapIv === true;
  } else if (gate === "eq_ar_high_overnight_p10") {
    const hist = Object.keys(overnight)
      .filter((x) => x < d)
      .map((x) => overnight[x])
      .filter((v) => finite(v))
      .sort((a, b) => a - b);
    let p10ok = false;
    if (hist.length >= 20 && on !== undefined) {
      const p10 = hist[Math.max(0, Math.floor(0.1 * (hist.length - 1)))];
      p10ok = on <= p10;
    }
    keep = extras?.eqArHigh === true && p10ok;
  } else if (gate === "ta_up_easy") {
    keep =
      extras?.taUp === true &&
      on !== undefined &&
      medOn !== null &&
      on < medOn;
  } else if (gate === "margin_up_easy") {
    keep =
      marginChg !== null &&
      marginChg > 0 &&
      on !== undefined &&
      medOn !== null &&
      on < medOn;
  } else if (gate === "curve_flatten_easy") {
    let flat = false;
    if (prev !== null) {
      const sp = spread[d];
      const psp = spread[prev];
      flat = finite(sp) && finite(psp) && (sp as number) < (psp as number);
    }
    keep = flat && on !== undefined && medOn !== null && on < medOn;
  } else if (gate === "eq_ar_low_tight_invert") {
    keep =
      extras?.eqArLow === true && extras?.tightOn === true;
    invert = true;
  } else if (gate === "eq_ar_high_margin_down") {
    keep =
      extras?.eqArHigh === true &&
      marginChg !== null &&
      marginChg < 0;
  } else if (gate === "ta_up_margin_down") {
    keep =
      extras?.taUp === true &&
      marginChg !== null &&
      marginChg < 0;
  } else if (gate === "cheap_pb_easy") {
    keep =
      extras?.cheapPb === true &&
      on !== undefined &&
      medOn !== null &&
      on < medOn;
  } else if (gate === "eq_ar_high_on_impulse") {
    let impulse = false;
    if (prev !== null && on !== undefined && finite(overnight[prev])) {
      const absCh = Math.abs(on - overnight[prev]);
      const hist: Record<string, number> = {};
      const keys = Object.keys(overnight).sort();
      for (let i = 1; i < keys.length; i++) {
        if (keys[i] >= d) break;
        hist[keys[i]] = Math.abs(overnight[keys[i]] - overnight[keys[i - 1]]);
      }
      const med = pitMedian(hist, d, 20);
      impulse = med !== null && absCh >= med;
    }
    keep = extras?.eqArHigh === true && impulse;
  } else {
    return { keep: false, invert: false };
  }
  return { keep, invert };
}

/** Monday=0 … Sunday=6 (Python datetime.weekday). */
function weekdayMon0(iso: string): number {
  const t = Date.parse(String(iso).slice(0, 10) + "T00:00:00Z");
  if (!Number.isFinite(t)) return -1;
  return (new Date(t).getUTCDay() + 6) % 7;
}

function pitMedian(
  series: Record<string, number>,
  query: string,
  minHist: number,
): number | null {
  const hist = Object.keys(series)
    .filter((d) => d < query)
    .sort()
    .map((d) => series[d])
    .filter((v) => finite(v));
  if (hist.length < minHist) return null;
  const s = hist.slice().sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function eventHeld(
  logic: LogicSpec,
  panel: PeriodPanel,
): Record<string, Record<string, number>> | null {
  const lid = String(logic.logic_id || "");
  const params = logic.params || {};
  const holdDays = Math.max(
    1,
    Math.floor(
      finite(params.post_hold_days as number)
        ? (params.post_hold_days as number)
        : finite(params.hold_days as number)
          ? (params.hold_days as number)
          : 5,
    ),
  );
  const minHist = Math.max(
    5,
    Math.floor(finite(params.min_hist as number) ? (params.min_hist as number) : 20),
  );
  const events = panel.fund_regime?.events_by_code || {};
  const overnight =
    panel.repo_rate_regime?.rates_by_date ||
    panel.repo_rate_regime?.rate_by_date ||
    panel.repo_rate_by_date ||
    {};
  const spread = panel.repo_rate_regime?.spread_by_date || {};
  const bars = panel.bars || {};
  const closeMap = closeByMap(bars);
  const absSurprises: Array<{ d: string; abs: number }> = [];
  type Entry = {
    code: string;
    disc: string;
    entryDate: string;
    entryIdx: number;
    sign: number;
    abs: number;
    surprise: number;
    after: boolean;
    eps?: number | null;
    prior_eps?: number | null;
    bps?: number | null;
    div_ann?: number | null;
    np?: number | null;
    roe?: number | null;
    ta?: number | null;
    eq_ar?: number | null;
    prior_ta?: number | null;
  };
  const perCode: Record<string, { dlist: string[]; entries: Entry[] }> = {};

  for (const [code, pairs] of Object.entries(bars)) {
    if (code.startsWith("__") || !pairs || pairs.length < holdDays + 1) continue;
    const dlist = pairs.map(([d]) => String(d).slice(0, 10));
    const idx: Record<string, number> = {};
    dlist.forEach((d, i) => {
      idx[d] = i;
    });
    const entries: Entry[] = [];
    for (const ev of events[code] || []) {
      const disc = String(ev.disc_date || "").slice(0, 10);
      if (!disc) continue;
      const sur = surpriseProxy(ev);
      const sgn = signNum(sur);
      if (sgn === null || sgn === 0 || sur === null) continue;
      let i = idx[disc];
      const after = afterClose(ev.disc_time);
      if (i === undefined) {
        const later = dlist.find((d) => d > disc);
        if (later === undefined) continue;
        i = idx[later];
      } else if (after && i + 1 < dlist.length) {
        i = i + 1;
      }
      entries.push({
        code,
        disc,
        entryDate: dlist[i],
        entryIdx: i,
        sign: sgn,
        abs: Math.abs(sur),
        surprise: sur,
        after,
        eps: ev.eps,
        prior_eps: ev.prior_eps,
        bps: ev.bps,
        div_ann: ev.div_ann,
        np: ev.np,
        roe: ev.roe,
        ta: ev.ta,
        eq_ar: ev.eq_ar,
        prior_ta: ev.prior_ta,
      });
      absSurprises.push({ d: disc, abs: Math.abs(sur) });
    }
    perCode[code] = { dlist, entries };
  }

  const clusterLookback = 5;
  const discDates = absSurprises.map((x) => x.d).sort();

  const held: Record<string, Record<string, number>> = {};
  let nOn = 0;
  for (const [code, pack] of Object.entries(perCode)) {
    const pos: Record<string, number> = {};
    const arr: Array<number | null> = pack.dlist.map(() => null);
    for (const ev of pack.entries) {
      let ok = true;
      let sgn = ev.sign;
      if (lid === "afterclose_only_event_hold" && !ev.after) ok = false;
      if (lid === "event_funding_stress_skip" || lid === "event_funding_adaptive_side") {
        const on = overnight[ev.entryDate];
        const med = pitMedian(overnight, ev.entryDate, minHist);
        if (on === undefined || med === null || on >= med) ok = false;
      }
      if (lid === "event_funding_easy_short") {
        const on = overnight[ev.entryDate];
        const med = pitMedian(overnight, ev.entryDate, minHist);
        if (on === undefined || med === null || on >= med) ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "event_funding_stress_ls") {
        const on = overnight[ev.entryDate];
        const med = pitMedian(overnight, ev.entryDate, minHist);
        if (on === undefined || med === null) ok = false;
        else sgn = on >= med ? -ev.sign : ev.sign;
      }
      if (lid === "curve_steep_event_confirm") {
        const sp = spread[ev.entryDate];
        if (sp === undefined || sp <= 0) ok = false;
      }
      if (lid === "large_surprise_event_hold") {
        const prior = absSurprises.filter((x) => x.d < ev.disc).map((x) => x.abs);
        if (prior.length < minHist) ok = false;
        else {
          const s = prior.slice().sort((a, b) => a - b);
          const mid = Math.floor(s.length / 2);
          const med = s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
          if (ev.abs < med) ok = false;
        }
      }
      if (lid === "event_pre_mom_agree_hold") {
        const pairs = bars[code];
        const i = ev.entryIdx;
        if (!pairs || i < 5) ok = false;
        else {
          const m = momentumAt(pairs, 5, i);
          const ms = signNum(m);
          if (ms === null || ms === 0 || ms !== ev.sign) ok = false;
        }
      }
      const marginGate = (wantCrowded: boolean): boolean => {
        const levels =
          panel.flow_regime?.margin_level_by_code?.[code] || {};
        const prior = Object.keys(levels)
          .filter((d) => d < ev.entryDate)
          .sort();
        if (!prior.length) return false;
        const lastD = prior[prior.length - 1];
        const ageDays =
          (Date.parse(ev.entryDate + "T00:00:00Z") -
            Date.parse(lastD + "T00:00:00Z")) /
          86400000;
        const med = pitMedian(levels, ev.entryDate, minHist);
        if (!Number.isFinite(ageDays) || ageDays > 14 || med === null) return false;
        const crowded = (levels[lastD] as number) >= med;
        return wantCrowded ? crowded : !crowded;
      };
      const easyOn = (): boolean => {
        const on = overnight[ev.entryDate];
        const med = pitMedian(overnight, ev.entryDate, minHist);
        return on !== undefined && med !== null && on < med;
      };
      const tightOn = (): boolean => {
        const on = overnight[ev.entryDate];
        const med = pitMedian(overnight, ev.entryDate, minHist);
        return on !== undefined && med !== null && on >= med;
      };
      const steepOn = (): boolean => {
        const sp = spread[ev.entryDate];
        return sp !== undefined && sp > 0;
      };
      const invertOn = (): boolean => {
        const sp = spread[ev.entryDate];
        return sp !== undefined && sp <= 0;
      };
      if (lid === "event_margin_crowding_skip") {
        if (!marginGate(false)) ok = false;
      }
      if (lid === "event_funding_tight_fade") {
        if (!tightOn()) ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "event_curve_invert_fade") {
        if (!invertOn()) ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "event_afterclose_easy_funding") {
        if (!ev.after || !easyOn()) ok = false;
      }
      if (lid === "event_large_surprise_easy_funding") {
        if (!easyOn()) ok = false;
        const prior = absSurprises.filter((x) => x.d < ev.disc).map((x) => x.abs);
        if (prior.length < minHist) ok = false;
        else {
          const s = prior.slice().sort((a, b) => a - b);
          const mid = Math.floor(s.length / 2);
          const med = s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
          if (ev.abs < med) ok = false;
        }
      }
      if (lid === "event_pre_mom_easy_funding") {
        if (!easyOn()) ok = false;
        const pairs = bars[code];
        const i = ev.entryIdx;
        if (!pairs || i < 5) ok = false;
        else {
          const m = momentumAt(pairs, 5, i);
          const ms = signNum(m);
          if (ms === null || ms === 0 || ms !== ev.sign) ok = false;
        }
      }
      if (lid === "event_margin_or_funding_skip") {
        if (!marginGate(false) || !easyOn()) ok = false;
      }
      if (lid === "event_large_surprise_steep_curve") {
        if (!steepOn()) ok = false;
        const prior = absSurprises.filter((x) => x.d < ev.disc).map((x) => x.abs);
        if (prior.length < minHist) ok = false;
        else {
          const s = prior.slice().sort((a, b) => a - b);
          const mid = Math.floor(s.length / 2);
          const med = s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
          if (ev.abs < med) ok = false;
        }
      }
      if (lid === "event_afterclose_steep_curve") {
        if (!ev.after || !steepOn()) ok = false;
      }
      if (lid === "event_tight_and_crowded_fade") {
        if (!tightOn() || !marginGate(true)) ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "event_cluster_easy_pead") {
        if (!easyOn()) ok = false;
        const nDisc = discDates.filter(
          (x) => x < ev.entryDate && x >= addDays(ev.entryDate, -clusterLookback),
        ).length;
        const medC = pitMedian(
          Object.fromEntries(
            unionDates(bars).map((dd) => [
              dd,
              discDates.filter((x) => x < dd && x >= addDays(dd, -clusterLookback)).length,
            ]),
          ),
          ev.entryDate,
          10,
        );
        if (medC === null || nDisc < medC) ok = false;
      }
      if (lid === "event_pre_mom_steep_curve") {
        if (!steepOn()) ok = false;
        const pairs = bars[code];
        const i = ev.entryIdx;
        if (!pairs || i < 5) ok = false;
        else {
          const m = momentumAt(pairs, 5, i);
          const ms = signNum(m);
          if (ms === null || ms === 0 || ms !== ev.sign) ok = false;
        }
      }
      if (lid === "event_large_surprise_afterclose") {
        if (!ev.after) ok = false;
        const prior = absSurprises.filter((x) => x.d < ev.disc).map((x) => x.abs);
        if (prior.length < minHist) ok = false;
        else {
          const s = prior.slice().sort((a, b) => a - b);
          const mid = Math.floor(s.length / 2);
          const med = s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
          if (ev.abs < med) ok = false;
        }
      }
      if (lid === "event_margin_uncrowded_steep") {
        if (!marginGate(false) || !steepOn()) ok = false;
      }
      if (lid === "event_easy_funding_curve_steep") {
        if (!easyOn() || !steepOn()) ok = false;
      }
      if (lid === "month_end_event_skip") {
        if (ev.entryDate.slice(8, 10) >= "28") ok = false;
      }
      if (lid === "event_first_half_month") {
        if (ev.entryDate.slice(8, 10) > "15") ok = false;
      }
      if (lid === "overnight_easing_event") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (!prevs.length || on === undefined || on >= overnight[prevs[prevs.length - 1]])
          ok = false;
      }
      if (lid === "overnight_tightening_fade_event") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (!prevs.length || on === undefined || on <= overnight[prevs[prevs.length - 1]])
          ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "event_cluster_fade") {
        const nDisc = discDates.filter(
          (x) => x < ev.entryDate && x >= addDays(ev.entryDate, -clusterLookback),
        ).length;
        const medC = pitMedian(
          Object.fromEntries(
            unionDates(bars).map((dd) => [
              dd,
              discDates.filter((x) => x < dd && x >= addDays(dd, -clusterLookback)).length,
            ]),
          ),
          ev.entryDate,
          10,
        );
        if (medC === null || nDisc < medC) ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "margin_crowd_fade_event") {
        if (!marginGate(true)) ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "event_afterclose_delay2" && !ev.after) ok = false;
      if (lid === "event_skip_monday" && weekdayMon0(ev.entryDate) === 0) ok = false;
      if (
        lid === "event_tue_thu_only" &&
        ![1, 2, 3].includes(weekdayMon0(ev.entryDate))
      )
        ok = false;
      if (lid === "event_friday_skip" && weekdayMon0(ev.entryDate) === 4) ok = false;
      if (lid === "fy_end_event_fade") {
        if (ev.entryDate.slice(5, 7) !== "05") ok = false;
        else sgn = -ev.sign;
      }
      if (lid === "event_may_results_follow" && ev.entryDate.slice(5, 7) !== "05")
        ok = false;
      if (lid === "fy_start_event_follow" && ev.entryDate.slice(5, 7) !== "04")
        ok = false;
      if (lid === "event_midmonth_only") {
        const dd = ev.entryDate.slice(8, 10);
        if (dd < "10" || dd > "20") ok = false;
      }
      if (lid === "event_easing_uncrowded") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
        else if (!marginGate(false)) ok = false;
      }
      if (lid === "event_afterclose_midmonth") {
        const dd = ev.entryDate.slice(8, 10);
        if (!ev.after || dd < "10" || dd > "20") ok = false;
      }
      if (lid === "event_easing_midmonth") {
        const dd = ev.entryDate.slice(8, 10);
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (dd < "10" || dd > "20") ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_friday_easing") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (weekdayMon0(ev.entryDate) !== 4) ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_uncrowded_midmonth") {
        const dd = ev.entryDate.slice(8, 10);
        if (dd < "10" || dd > "20") ok = false;
        else if (!marginGate(false)) ok = false;
      }
      if (lid === "event_tue_thu_easing") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (![1, 2, 3].includes(weekdayMon0(ev.entryDate))) ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_tue_thu_uncrowded") {
        if (![1, 2, 3].includes(weekdayMon0(ev.entryDate))) ok = false;
        else if (!marginGate(false)) ok = false;
      }
      if (lid === "event_afterclose_easing") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (!ev.after) ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_may_easing") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (ev.entryDate.slice(5, 7) !== "05") ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_skip_monday_uncrowded") {
        if (weekdayMon0(ev.entryDate) === 0) ok = false;
        else if (!marginGate(false)) ok = false;
      }
      if (lid === "event_first_half_easing") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (ev.entryDate.slice(8, 10) > "15") ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_friday_uncrowded") {
        if (weekdayMon0(ev.entryDate) !== 4) ok = false;
        else if (!marginGate(false)) ok = false;
      }
      if (lid === "event_skip_monday_easing") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (weekdayMon0(ev.entryDate) === 0) ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_afterclose_skip_monday") {
        if (!ev.after || weekdayMon0(ev.entryDate) === 0) ok = false;
      }
      if (lid === "event_easing_skip_friday") {
        const prevs = Object.keys(overnight)
          .filter((x) => x < ev.entryDate)
          .sort();
        const on = overnight[ev.entryDate];
        if (weekdayMon0(ev.entryDate) === 4) ok = false;
        else if (
          !prevs.length ||
          on === undefined ||
          on >= overnight[prevs[prevs.length - 1]]
        )
          ok = false;
      }
      if (lid === "event_first_half_uncrowded") {
        if (ev.entryDate.slice(8, 10) > "15") ok = false;
        else if (!marginGate(false)) ok = false;
      }
      if (lid === "event_tue_thu_steep") {
        const sp = spread[ev.entryDate];
        if (![1, 2, 3].includes(weekdayMon0(ev.entryDate))) ok = false;
        else if (sp === undefined || sp <= 0) ok = false;
      }
      if (lid === "event_midmonth_steep") {
        const dd = ev.entryDate.slice(8, 10);
        const sp = spread[ev.entryDate];
        if (dd < "10" || dd > "20") ok = false;
        else if (sp === undefined || sp <= 0) ok = false;
      }
      const comboGates = comboGatesOf(params as Record<string, unknown>);
      if (comboGatesImplemented(comboGates)) {
        ok = comboGates.every((g) =>
          comboEventGateOk(g, ev, overnight, spread, minHist, panel),
        );
        if (String(params.side || "orig") === "flip") sgn = -ev.sign;
      }
      if (!ok) continue;
      let i0 = ev.entryIdx;
      if (lid === "event_skip_announce_day") i0 += 1;
      if (lid === "event_afterclose_delay2") i0 += 2;
      const end = Math.min(ev.entryIdx + holdDays, pack.dlist.length);
      if (lid === "event_late_hold_only") i0 = Math.max(i0, end - 2);
      if (i0 >= end || i0 >= pack.dlist.length) continue;
      for (let j = i0; j < end; j++) arr[j] = sgn;
      nOn += 1;
    }
    for (let i = 0; i < pack.dlist.length; i++) {
      if (arr[i] !== null) pos[pack.dlist[i]] = arr[i] as number;
    }
    held[code] = pos;
  }

  if (lid === "disclosure_cluster_mom_gate") {
    const cs = csHeld(panel.bars, 5, 10, 0.3, 0.3, false);
    const dates = unionDates(panel.bars);
    const gated: Record<string, Record<string, number>> = {};
    for (const [code, cmap] of Object.entries(cs)) {
      gated[code] = {};
      for (const [d, v] of Object.entries(cmap)) {
        const nDisc = discDates.filter(
          (x) => x < d && x >= addDays(d, -clusterLookback),
        ).length;
        const med = pitMedian(
          Object.fromEntries(
            dates.map((dd) => [
              dd,
              discDates.filter(
                (x) => x < dd && x >= addDays(dd, -clusterLookback),
              ).length,
            ]),
          ),
          d,
          10,
        );
        if (med === null || nDisc < med) continue;
        gated[code][d] = v;
      }
    }
    return gated;
  }

  if (
    lid.startsWith("surprise_xs_") ||
    lid === "surprise_xs_rank_hold" ||
    lid === "surprise_xs_rank_flip" ||
    lid === "surprise_xs_rank_adaptive" ||
    lid === "surprise_xs_rank_easy_funding" ||
    lid === "surprise_xs_rank_steep_curve" ||
    lid === "surprise_xs_month_start" ||
    lid === "surprise_xs_fy_end" ||
    lid === "surprise_xs_afterclose" ||
    lid === "surprise_xs_tue_thu" ||
    lid === "surprise_xs_midmonth" ||
    lid === "surprise_xs_easing_change" ||
    lid === "surprise_xs_afterclose_easing" ||
    lid === "surprise_xs_skip_monday" ||
    lid === "surprise_xs_friday_skip" ||
    lid === "surprise_xs_uncrowded" ||
    lid === "surprise_xs_first_half" ||
    lid === "surprise_xs_afterclose_skip_monday" ||
    lid === "surprise_xs_steep_skip_monday" ||
    lid === "surprise_xs_uncrowded_skip_monday"
  ) {
    const invert = lid.includes("flip");
    const dates = unionDates(panel.bars);
    const comboGates = comboGatesOf(params as Record<string, unknown>);
    const surpriseByDate: Record<string, Record<string, number>> = {};
    for (const pack of Object.values(perCode)) {
      for (const ev of pack.entries) {
        if (comboGatesImplemented(comboGates)) {
          if (
            !comboGates.every((g) =>
              comboEventGateOk(g, ev, overnight, spread, minHist, panel),
            )
          )
            continue;
        } else if (
          lid === "surprise_xs_rank_easy_funding"
        ) {
          const on = overnight[ev.entryDate];
          const med = pitMedian(overnight, ev.entryDate, minHist);
          if (on === undefined || med === null || on >= med) continue;
        }
        if (lid === "surprise_xs_rank_steep_curve") {
          const sp = spread[ev.entryDate];
          if (sp === undefined || sp <= 0) continue;
        }
        if (lid === "surprise_xs_month_start" && ev.entryDate.slice(8, 10) > "05")
          continue;
        if (
          lid === "surprise_xs_fy_end" &&
          !(ev.entryDate.slice(5, 7) === "03" && ev.entryDate.slice(8, 10) >= "15")
        )
          continue;
        if (lid === "surprise_xs_afterclose") {
          const dd = ev.entryDate.slice(8, 10);
          if (!ev.after || dd < "10" || dd > "20") continue;
        }
        if (
          lid === "surprise_xs_tue_thu" &&
          ![1, 2, 3].includes(weekdayMon0(ev.entryDate))
        )
          continue;
        if (lid === "surprise_xs_midmonth") {
          const dd = ev.entryDate.slice(8, 10);
          if (dd < "10" || dd > "20") continue;
        }
        if (lid === "surprise_xs_easing_change") {
          const prevs = Object.keys(overnight)
            .filter((x) => x < ev.entryDate)
            .sort();
          const on = overnight[ev.entryDate];
          if (
            !prevs.length ||
            on === undefined ||
            on >= overnight[prevs[prevs.length - 1]]
          )
            continue;
        }
        if (lid === "surprise_xs_afterclose_easing") {
          const prevs = Object.keys(overnight)
            .filter((x) => x < ev.entryDate)
            .sort();
          const on = overnight[ev.entryDate];
          if (!ev.after) continue;
          if (
            !prevs.length ||
            on === undefined ||
            on >= overnight[prevs[prevs.length - 1]]
          )
            continue;
        }
        if (lid === "surprise_xs_skip_monday" && weekdayMon0(ev.entryDate) === 0)
          continue;
        if (lid === "surprise_xs_friday_skip" && weekdayMon0(ev.entryDate) === 4)
          continue;
        if (lid === "surprise_xs_uncrowded") {
          const levels = panel.flow_regime?.margin_level_by_code?.[ev.code] || {};
          const prior = Object.keys(levels)
            .filter((d) => d < ev.entryDate)
            .sort();
          if (!prior.length) continue;
          const lastD = prior[prior.length - 1];
          const med = pitMedian(levels, ev.entryDate, minHist);
          if (med === null || (levels[lastD] as number) >= med) continue;
        }
        if (lid === "surprise_xs_first_half" && ev.entryDate.slice(8, 10) > "15")
          continue;
        if (
          lid === "surprise_xs_afterclose_skip_monday" &&
          (!ev.after || weekdayMon0(ev.entryDate) === 0)
        )
          continue;
        if (lid === "surprise_xs_steep_skip_monday") {
          const sp = spread[ev.entryDate];
          if (weekdayMon0(ev.entryDate) === 0 || sp === undefined || sp <= 0)
            continue;
        }
        if (lid === "surprise_xs_uncrowded_skip_monday") {
          if (weekdayMon0(ev.entryDate) === 0) continue;
          const levels = panel.flow_regime?.margin_level_by_code?.[ev.code] || {};
          const prior = Object.keys(levels)
            .filter((d) => d < ev.entryDate)
            .sort();
          if (!prior.length) continue;
          const lastD = prior[prior.length - 1];
          const med = pitMedian(levels, ev.entryDate, minHist);
          if (med === null || (levels[lastD] as number) >= med) continue;
        }
        for (let j = ev.entryIdx; j < Math.min(ev.entryIdx + holdDays, pack.dlist.length); j++) {
          const d = pack.dlist[j];
          if (!surpriseByDate[d]) surpriseByDate[d] = {};
          surpriseByDate[d][ev.code] = ev.surprise;
        }
      }
    }
    const dailyRank: Record<string, Record<string, number | null>> = {};
    for (const d of dates) {
      const ranks = csRank(surpriseByDate[d] || {}, 0.3, 0.3);
      for (const [code, sign] of Object.entries(ranks)) {
        if (!dailyRank[code]) dailyRank[code] = {};
        dailyRank[code][d] = invert ? -sign : sign;
      }
    }
    const xsHeld: Record<string, Record<string, number>> = {};
    const gatedSparse =
      comboGatesImplemented(comboGates) ||
      lid === "surprise_xs_afterclose" ||
      lid === "surprise_xs_tue_thu" ||
      lid === "surprise_xs_month_start" ||
      lid === "surprise_xs_fy_end" ||
      lid === "surprise_xs_midmonth" ||
      lid === "surprise_xs_easing_change" ||
      lid === "surprise_xs_afterclose_easing" ||
      lid === "surprise_xs_skip_monday" ||
      lid === "surprise_xs_friday_skip" ||
      lid === "surprise_xs_uncrowded" ||
      lid === "surprise_xs_first_half" ||
      lid === "surprise_xs_afterclose_skip_monday" ||
      lid === "surprise_xs_steep_skip_monday" ||
      lid === "surprise_xs_uncrowded_skip_monday";
    for (const [code, pack] of Object.entries(perCode)) {
      xsHeld[code] = {};
      if (gatedSparse) {
        for (const d of pack.dlist) {
          const pos = dailyRank[code]?.[d];
          if (pos) xsHeld[code][d] = pos;
        }
        continue;
      }
      const entries = pack.dlist.map((d) => dailyRank[code]?.[d] ?? null);
      const sticky = stickyHold(entries, holdDays);
      for (let i = 0; i < pack.dlist.length; i++) {
        const pos = sticky[i];
        if (pos !== null) xsHeld[code][pack.dlist[i]] = pos;
      }
    }
    if (lid !== "surprise_xs_rank_adaptive") return xsHeld;
    // trail-K orig vs flip on completed daily orig nets
    const trailK = Math.max(5, Math.floor(finite(params.trail_k as number) ? (params.trail_k as number) : 10));
    const trailMin = Math.max(3, Math.floor(finite(params.trail_min as number) ? (params.trail_min as number) : 5));
    const origMtm = heldBookDailyMtm(xsHeld, closeMap, dates, holdDays, 0);
    const hist: number[] = [];
    const tilted: Record<string, Record<string, number>> = {};
    for (const code of Object.keys(xsHeld)) tilted[code] = {};
    for (let i = 0; i < dates.length; i++) {
      const lastk = hist.slice(-trailK);
      const tilt = lastk.length < trailMin ? 1 : lastk.reduce((a, b) => a + b, 0) / lastk.length >= 0 ? 1 : -1;
      for (const code of Object.keys(xsHeld)) {
        const v = xsHeld[code]?.[dates[i]];
        if (v) tilted[code][dates[i]] = v * tilt;
      }
      if (i > 0) hist.push(origMtm.net_daily[i] || 0);
    }
    return tilted;
  }

  if (lid === "event_funding_adaptive_side") {
    const trailK = Math.max(5, Math.floor(finite(params.trail_k as number) ? (params.trail_k as number) : 10));
    const trailMin = Math.max(3, Math.floor(finite(params.trail_min as number) ? (params.trail_min as number) : 5));
    type H = { holdEnd: string; orig: number; flip: number };
    const history: H[] = [];
    const adaptHeld: Record<string, Record<string, number>> = {};
    const ordered: Array<{ code: string; ev: Entry; dlist: string[] }> = [];
    for (const [code, pack] of Object.entries(perCode)) {
      for (const ev of pack.entries) {
        const on = overnight[ev.entryDate];
        const med = pitMedian(overnight, ev.entryDate, minHist);
        if (on === undefined || med === null || on >= med) continue;
        ordered.push({ code, ev, dlist: pack.dlist });
      }
    }
    ordered.sort((a, b) =>
      a.ev.entryDate < b.ev.entryDate ? -1 : a.ev.entryDate > b.ev.entryDate ? 1 : a.code.localeCompare(b.code),
    );
    for (const row of ordered) {
      const completed = history.filter((h) => h.holdEnd < row.ev.entryDate);
      const lastk = completed.slice(-trailK);
      let mult = 1;
      if (lastk.length >= trailMin) {
        const mOrig = lastk.reduce((s, h) => s + h.orig, 0) / lastk.length;
        const mFlip = lastk.reduce((s, h) => s + h.flip, 0) / lastk.length;
        if (mOrig < mFlip) mult = -1;
      }
      const end = Math.min(row.ev.entryIdx + holdDays, row.dlist.length);
      if (!adaptHeld[row.code]) adaptHeld[row.code] = {};
      for (let j = row.ev.entryIdx; j < end; j++) {
        adaptHeld[row.code][row.dlist[j]] = row.ev.sign * mult;
      }
      const i0 = row.ev.entryIdx;
      const i1 = end - 1;
      const c0 = closeMap[row.code]?.[row.dlist[i0]];
      const c1 = closeMap[row.code]?.[row.dlist[i1]];
      if (finite(c0) && finite(c1) && c0 !== 0 && i1 > i0) {
        const raw = c1 / c0 - 1;
        const cost = 2 * 0.001;
        history.push({
          holdEnd: row.dlist[i1],
          orig: row.ev.sign * raw - cost,
          flip: -row.ev.sign * raw - cost,
        });
      }
    }
    return adaptHeld;
  }

  if (nOn === 0) return {};
  return held;
}

function addDays(iso: string, n: number): string {
  const t = Date.parse(iso + "T00:00:00Z");
  if (!Number.isFinite(t)) return iso;
  const d = new Date(t + n * 86400000);
  return d.toISOString().slice(0, 10);
}

function gatedCsHeld(
  logic: LogicSpec,
  panel: PeriodPanel,
): Record<string, Record<string, number>> {
  const lid = String(logic.logic_id || "");
  const params = logic.params || {};
  if (lid === "xs_margin_delta_rank") {
    return xsMarginDeltaHeld(panel);
  }
  if (lid === "xs_low_vol_mom") {
    return xsLowVolMomHeld(panel);
  }
  if (lid === "idio_mom_macro_impulse") {
    return idioMomMacroHeld(panel);
  }
  const invert =
    lid === "xs_high_vol_fade" ||
    lid === "overnight_tight_cs_fade" ||
    lid === "curve_invert_cs_fade" ||
    lid === "fy_end_cs_fade" ||
    lid === "overnight_p90_cs_flip" ||
    lid === "flow_price_disagree_fade" ||
    lid === "basevol_up_day_fade" ||
    lid === "overnight_level_cs_tilt" ||
    lid === "month_end_cs_fade" ||
    lid === "overnight_up_cs_fade" ||
    lid === "cs_friday_fade" ||
    lid === "cs_friday_tight_fade" ||
    lid === "flow_disagree_midmonth" ||
    lid === "cs_midmonth_tight_fade" ||
    lid === "flow_disagree_tue_thu" ||
    lid === "flow_disagree_skip_monday" ||
    lid === "flow_disagree_skip_friday";
  const base = csHeld(panel.bars, 5, 10, 0.3, 0.3, invert);
  const overnight =
    panel.repo_rate_regime?.rates_by_date ||
    panel.repo_rate_regime?.rate_by_date ||
    panel.repo_rate_by_date ||
    {};
  const spread = panel.repo_rate_regime?.spread_by_date || {};
  const skew =
    panel.skew_series ||
    panel.opt225_regime?.skew?.rv_abs_by_date ||
    {};
  const nkyTerm =
    panel.nky_vol_series?.rv_ratio_by_date || {};
  const ivSpread = panel.iv_base_spread || {};
  const repo3mApprox = (d: string): number | undefined => {
    const on = overnight[d];
    const sp = spread[d];
    if (!finite(on) || !finite(sp)) return undefined;
    return on + sp;
  };
  const dates = unionDates(panel.bars);
  const onDates = Object.keys(overnight).sort();
  const onDelta: Record<string, number> = {};
  for (let i = 1; i < onDates.length; i++) {
    onDelta[onDates[i]] = overnight[onDates[i]] - overnight[onDates[i - 1]];
  }
  const absOnDelta: Record<string, number> = {};
  for (const [d, v] of Object.entries(onDelta)) absOnDelta[d] = Math.abs(v);
  const spDates = Object.keys(spread).sort();
  const spDelta: Record<string, number> = {};
  for (let i = 1; i < spDates.length; i++) {
    spDelta[spDates[i]] = spread[spDates[i]] - spread[spDates[i - 1]];
  }
  const absSpDelta: Record<string, number> = {};
  for (const [d, v] of Object.entries(spDelta)) absSpDelta[d] = Math.abs(v);
  const r3By: Record<string, number> = {};
  for (const d of dates) {
    const v = repo3mApprox(d);
    if (v !== undefined) r3By[d] = v;
  }
  const out: Record<string, Record<string, number>> = {};
  for (const [code, cmap] of Object.entries(base)) {
    out[code] = {};
    for (const [d, v] of Object.entries(cmap)) {
      let keep = true;
      let signed = v;
      const on = overnight[d];
      const medOn = pitMedian(overnight, d, 20);
      const i = dates.indexOf(d);
      const prev = i > 0 ? dates[i - 1] : null;
      if (lid === "cs_mom_easy_funding") {
        keep = on !== undefined && medOn !== null && on < medOn;
      } else if (lid === "overnight_tight_cs_fade") {
        keep = on !== undefined && medOn !== null && on >= medOn;
      } else if (lid === "curve_invert_cs_fade") {
        keep = spread[d] !== undefined && spread[d] <= 0;
      } else if (lid === "month_start_cs_follow") {
        keep = d.slice(8, 10) <= "05";
      } else if (lid === "rate_change_cs_confirm") {
        keep =
          prev !== null &&
          overnight[prev] !== undefined &&
          on !== undefined &&
          on > overnight[prev];
      } else if (lid === "opt225_skew_cs_gate") {
        const med = pitMedian(skew, d, 20);
        keep = med !== null && finite(skew[d]) && skew[d] >= med;
      } else if (lid === "nky_vol_term_cs_gate") {
        const med = pitMedian(nkyTerm, d, 20);
        keep = med !== null && finite(nkyTerm[d]) && nkyTerm[d] >= med;
      } else if (lid === "opt225_spread_cs_tilt") {
        const med = pitMedian(ivSpread, d, 20);
        keep = med !== null && finite(ivSpread[d]) && Math.abs(ivSpread[d]) >= med;
      } else if (lid === "repo_3m_change_cs") {
        const a = prev ? repo3mApprox(d) : undefined;
        const b = prev ? repo3mApprox(prev) : undefined;
        keep = a !== undefined && b !== undefined && a > b;
      } else if (
        lid === "flow_price_margin_triple" ||
        lid === "flow_margin_price_agree"
      ) {
        const chg = panel.flow_regime?.margin_change_by_code?.[code]?.[d];
        keep = finite(chg) && chg !== 0;
        if (lid === "flow_price_margin_triple" && finite(chg)) {
          keep = chg < 0; // de-crowd
        }
      } else if (lid === "fy_end_cs_fade") {
        keep = d.slice(5, 7) === "03" && d.slice(8, 10) >= "15";
      } else if (lid === "fy_start_cs_follow") {
        keep = d.slice(5, 7) === "04";
      } else if (lid === "curve_steep_cs_follow") {
        keep = spread[d] !== undefined && spread[d] > 0;
      } else if (lid === "overnight_p90_cs_flip") {
        const hist = Object.keys(overnight)
          .filter((x) => x < d)
          .map((x) => overnight[x])
          .filter((v) => finite(v))
          .sort((a, b) => a - b);
        if (hist.length < 20 || on === undefined) keep = false;
        else {
          const p90 = hist[Math.floor(0.9 * (hist.length - 1))];
          keep = on >= p90;
        }
      } else if (lid === "flow_price_disagree_fade") {
        const chg = panel.flow_regime?.margin_change_by_code?.[code]?.[d];
        keep = finite(chg) && chg > 0;
      } else if (lid === "nky_vol_compress_cs") {
        keep =
          prev !== null &&
          finite(nkyTerm[d]) &&
          finite(nkyTerm[prev]) &&
          nkyTerm[d] < nkyTerm[prev];
      } else if (lid === "opt225_skew_and_term_cs") {
        const medS = pitMedian(skew, d, 20);
        const medT = pitMedian(nkyTerm, d, 20);
        keep =
          medS !== null &&
          medT !== null &&
          finite(skew[d]) &&
          finite(nkyTerm[d]) &&
          skew[d] >= medS &&
          nkyTerm[d] >= medT;
      } else if (lid === "basevol_up_day_fade") {
        const bv = panel.base_vol_series || panel.opt225_regime?.basevol?.rv_abs_by_date || {};
        keep =
          prev !== null && finite(bv[d]) && finite(bv[prev]) && bv[d] > bv[prev];
      } else if (lid === "iv_below_basevol_cs") {
        keep = finite(ivSpread[d]) && ivSpread[d] < 0;
      } else if (lid === "cs_skip_monday") {
        keep = weekdayMon0(d) !== 0;
      } else if (lid === "cs_tue_thu_follow") {
        keep = [1, 2, 3].includes(weekdayMon0(d));
      } else if (lid === "overnight_down_cs_follow") {
        keep =
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "overnight_up_cs_fade") {
        keep =
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on > overnight[prev];
      } else if (lid === "cs_midmonth_follow") {
        const dd = d.slice(8, 10);
        keep = dd >= "10" && dd <= "20";
      } else if (lid === "cs_friday_fade") {
        keep = weekdayMon0(d) === 4;
      } else if (lid === "cs_not_month_end") {
        keep = d.slice(8, 10) < "28";
      } else if (lid === "cs_easing_midmonth") {
        const dd = d.slice(8, 10);
        keep =
          dd >= "10" &&
          dd <= "20" &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "cs_tue_thu_down") {
        keep =
          [1, 2, 3].includes(weekdayMon0(d)) &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "overnight_down_skip_monday_cs") {
        keep =
          weekdayMon0(d) !== 0 &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "cs_friday_tight_fade") {
        keep =
          weekdayMon0(d) === 4 &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on > overnight[prev];
      } else if (lid === "flow_disagree_midmonth") {
        const dd = d.slice(8, 10);
        const chg = panel.flow_regime?.margin_change_by_code?.[code]?.[d];
        keep = dd >= "10" && dd <= "20" && finite(chg) && chg > 0;
      } else if (lid === "curve_steep_midmonth_cs") {
        const dd = d.slice(8, 10);
        keep =
          dd >= "10" &&
          dd <= "20" &&
          spread[d] !== undefined &&
          spread[d] > 0;
      } else if (lid === "rate_up_tue_thu_cs") {
        keep =
          [1, 2, 3].includes(weekdayMon0(d)) &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on > overnight[prev];
      } else if (lid === "cs_steep_skip_monday") {
        keep = weekdayMon0(d) !== 0 && spread[d] !== undefined && spread[d] > 0;
      } else if (lid === "cs_midmonth_tight_fade") {
        const dd = d.slice(8, 10);
        keep =
          dd >= "10" &&
          dd <= "20" &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on > overnight[prev];
      } else if (lid === "flow_disagree_tue_thu") {
        const chg = panel.flow_regime?.margin_change_by_code?.[code]?.[d];
        keep = [1, 2, 3].includes(weekdayMon0(d)) && finite(chg) && chg > 0;
      } else if (lid === "iv_below_midmonth_cs") {
        keep = weekdayMon0(d) !== 0 && finite(ivSpread[d]) && ivSpread[d] < 0;
      } else if (lid === "overnight_down_first_half_cs") {
        keep =
          d.slice(8, 10) <= "15" &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "rate_up_midmonth_cs") {
        const dd = d.slice(8, 10);
        keep =
          dd >= "10" &&
          dd <= "20" &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on > overnight[prev];
      } else if (lid === "cs_month_start_easing") {
        keep =
          d.slice(8, 10) <= "10" &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "cs_friday_down") {
        keep =
          weekdayMon0(d) === 4 &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "cs_tue_thu_steep") {
        keep =
          [1, 2, 3].includes(weekdayMon0(d)) &&
          spread[d] !== undefined &&
          spread[d] > 0;
      } else if (lid === "overnight_up_skip_monday_cs") {
        keep =
          weekdayMon0(d) !== 0 &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on > overnight[prev];
      } else if (lid === "flow_disagree_skip_monday") {
        const chg = panel.flow_regime?.margin_change_by_code?.[code]?.[d];
        keep = weekdayMon0(d) !== 0 && finite(chg) && chg > 0;
      } else if (lid === "cs_easy_tue_thu") {
        keep =
          [1, 2, 3].includes(weekdayMon0(d)) &&
          on !== undefined &&
          medOn !== null &&
          on < medOn;
      } else if (lid === "cs_easy_skip_monday") {
        keep =
          weekdayMon0(d) !== 0 &&
          on !== undefined &&
          medOn !== null &&
          on < medOn;
      } else if (lid === "cs_not_friday_down") {
        keep =
          weekdayMon0(d) !== 4 &&
          prev !== null &&
          finite(overnight[prev]) &&
          on !== undefined &&
          on < overnight[prev];
      } else if (lid === "cs_midmonth_easy") {
        const dd = d.slice(8, 10);
        keep =
          dd >= "10" &&
          dd <= "20" &&
          on !== undefined &&
          medOn !== null &&
          on < medOn;
      } else if (lid === "cs_steep_friday") {
        keep =
          weekdayMon0(d) === 4 && spread[d] !== undefined && spread[d] > 0;
      } else if (lid === "nky_vol_compress_midmonth_cs") {
        const dd = d.slice(8, 10);
        keep =
          dd >= "10" &&
          dd <= "20" &&
          prev !== null &&
          finite(nkyTerm[d]) &&
          finite(nkyTerm[prev]) &&
          nkyTerm[d] < nkyTerm[prev];
      } else if (lid === "overnight_level_cs_tilt") {
        keep = on !== undefined && medOn !== null && on >= medOn;
      } else if (lid === "overnight_easy_cs_follow") {
        keep = on !== undefined && medOn !== null && on < medOn;
      } else if (lid === "month_end_cs_fade") {
        const ym = d.slice(0, 7);
        const inMonth = dates.filter((x) => x.slice(0, 7) === ym);
        keep = inMonth.slice(-3).includes(d);
      } else if (lid === "funding_impulse_cs_tilt") {
        const dv = onDelta[d];
        const medAbs = pitMedian(absOnDelta, d, 20);
        keep =
          on !== undefined &&
          finite(dv) &&
          medAbs !== null &&
          Math.abs(dv) >= medAbs;
        if (keep && finite(dv) && dv !== 0) signed = v * (dv > 0 ? -1 : 1);
      } else if (lid === "curve_steepen_impulse_cs") {
        const dv = spDelta[d];
        const medAbs = pitMedian(absSpDelta, d, 20);
        keep =
          finite(dv) &&
          dv > 0 &&
          medAbs !== null &&
          Math.abs(dv) >= medAbs;
      } else if (lid === "repo_3m_level_cs") {
        const r3 = r3By[d];
        const med = pitMedian(r3By, d, 20);
        keep = finite(r3) && med !== null && r3 >= med;
      } else {
        const csGate = String(params.cs_gate || "");
        if (csGate && csGate !== "None") {
          const chg = panel.flow_regime?.margin_change_by_code?.[code]?.[d];
          const fins = panel.fund_regime?.events_by_code?.[code] || [];
          let fin: (typeof fins)[number] | null = null;
          for (const ev of fins) {
            const dd = String(ev.disc_date || "").slice(0, 10);
            if (dd && dd <= d) fin = ev;
          }
          const pairs = panel.bars?.[code] || [];
          const close = pairs.find(([x]) => x === d)?.[1];
          const pbHist: Record<string, number> = {};
          const eyHist: Record<string, number> = {};
          const roeHist: Record<string, number> = {};
          for (const [dd, px] of pairs) {
            if (dd >= d) break;
            let f2: (typeof fins)[number] | null = null;
            for (const ev of fins) {
              const x = String(ev.disc_date || "").slice(0, 10);
              if (x && x <= dd) f2 = ev;
            }
            if (!f2) continue;
            if (finite(px) && finite(f2.bps) && (f2.bps as number) !== 0) {
              pbHist[dd] = (px as number) / (f2.bps as number);
            }
            if (finite(px) && finite(f2.eps) && (px as number) !== 0) {
              eyHist[dd] = (f2.eps as number) / (px as number);
            }
            if (finite(f2.roe)) roeHist[dd] = f2.roe as number;
          }
          const pb =
            finite(close) && fin && finite(fin.bps) && (fin.bps as number) !== 0
              ? (close as number) / (fin.bps as number)
              : null;
          const ey =
            finite(close) && fin && finite(fin.eps) && (close as number) !== 0
              ? (fin.eps as number) / (close as number)
              : null;
          const pbMed = pitMedian(pbHist, d, 20);
          const eyMed = pitMedian(eyHist, d, 20);
          const roeMed = pitMedian(roeHist, d, 10);
          const nky = panel.nky_vol_series?.rv_abs_by_date || {};
          const nkyMed = pitMedian(nky, d, 20);
          const sr = panel.flow_regime?.short_ratio_by_date || {};
          const g = comboCsGateOk(
            csGate,
            d,
            overnight,
            spread,
            prev,
            medOn,
            finite(chg) ? (chg as number) : null,
            {
              shortUp:
                prev !== null &&
                finite(sr[d]) &&
                finite(sr[prev]) &&
                sr[d] > sr[prev],
              nkyHigh:
                nkyMed !== null && finite(nky[d]) && nky[d] >= nkyMed,
              cheapPb: pb !== null && pbMed !== null && pb < pbMed,
              expensivePb: pb !== null && pbMed !== null && pb > pbMed,
              eyHigh: ey !== null && eyMed !== null && ey > eyMed,
              roeHigh:
                fin != null &&
                finite(fin.roe) &&
                roeMed !== null &&
                (fin.roe as number) >= roeMed,
              divPositive:
                fin != null &&
                finite(fin.div_ann) &&
                (fin.div_ann as number) > 0,
              npPositive:
                fin != null && finite(fin.np) && (fin.np as number) > 0,
              eqArHigh:
                fin != null &&
                finite(fin.eq_ar) &&
                (() => {
                  const h: Record<string, number> = {};
                  for (const ev of fins) {
                    const dd = String(ev.disc_date || "").slice(0, 10);
                    if (dd && dd < d && finite(ev.eq_ar))
                      h[dd] = ev.eq_ar as number;
                  }
                  const med = pitMedian(h, d, 8);
                  return med !== null && (fin.eq_ar as number) >= med;
                })(),
              eqArLow:
                fin != null &&
                finite(fin.eq_ar) &&
                (() => {
                  const h: Record<string, number> = {};
                  for (const ev of fins) {
                    const dd = String(ev.disc_date || "").slice(0, 10);
                    if (dd && dd < d && finite(ev.eq_ar))
                      h[dd] = ev.eq_ar as number;
                  }
                  const med = pitMedian(h, d, 8);
                  return med !== null && (fin.eq_ar as number) < med;
                })(),
              taUp:
                fin != null &&
                finite(fin.ta) &&
                finite(fin.prior_ta) &&
                (fin.ta as number) > (fin.prior_ta as number),
              cheapIv:
                finite(panel.atm_iv_series?.[d]) &&
                finite(panel.base_vol_series?.[d]) &&
                (panel.atm_iv_series as Record<string, number>)[d] <
                  (panel.base_vol_series as Record<string, number>)[d],
              tightOn: on !== undefined && medOn !== null && on >= medOn,
              shortDown:
                prev !== null &&
                finite(sr[d]) &&
                finite(sr[prev]) &&
                sr[d] < sr[prev],
            },
          );
          keep = g.keep;
          if (g.invert) signed = -v;
        }
      }
      if (keep) out[code][d] = signed;
    }
  }
  return out;
}

function xsMarginDeltaHeld(
  panel: PeriodPanel,
): Record<string, Record<string, number>> {
  const chgBy = panel.flow_regime?.margin_change_by_code || {};
  if (!Object.keys(chgBy).length) return {};
  const dates = unionDates(panel.bars);
  const byDate: Record<string, Record<string, number | null>> = {};
  for (const d of dates) {
    byDate[d] = {};
    for (const [code, cmap] of Object.entries(chgBy)) {
      const v = cmap?.[d];
      if (finite(v)) byDate[d][code] = v;
    }
  }
  const out: Record<string, Record<string, number>> = {};
  for (const [code, pairs] of Object.entries(panel.bars || {})) {
    if (code.startsWith("__") || !pairs) continue;
    const entries = pairs.map(([d]) => {
      const ranks = csRank(byDate[d] || {}, 0.3, 0.3);
      return ranks[code] ?? 0;
    });
    const sticky = stickyHold(entries, 10);
    out[code] = {};
    for (let i = 0; i < pairs.length; i++) {
      const pos = sticky[i];
      if (pos) out[code][pairs[i][0]] = pos as number;
    }
  }
  return out;
}

function xsLowVolMomHeld(
  panel: PeriodPanel,
): Record<string, Record<string, number>> {
  const bars = panel.bars || {};
  const dates = unionDates(bars);
  const volN = 20;
  const volByCodeDate: Record<string, Record<string, number | null>> = {};
  for (const [code, pairs] of Object.entries(bars)) {
    if (code.startsWith("__") || !pairs) continue;
    volByCodeDate[code] = {};
    const rets: Array<number | null> = [];
    for (let i = 0; i < pairs.length; i++) {
      const d = pairs[i][0];
      if (i === 0) {
        rets.push(null);
        volByCodeDate[code][d] = null;
        continue;
      }
      const c0 = pairs[i - 1][1];
      const c1 = pairs[i][1];
      rets.push(c0 && finite(c0) && finite(c1) ? c1 / c0 - 1 : null);
      const window = rets.slice(-volN).filter((x): x is number => x !== null);
      if (window.length < 8) {
        volByCodeDate[code][d] = null;
        continue;
      }
      const m = window.reduce((a, b) => a + b, 0) / window.length;
      const v =
        window.reduce((a, b) => a + (b - m) ** 2, 0) / (window.length - 1);
      volByCodeDate[code][d] = v > 0 ? Math.sqrt(v) : 0;
    }
  }
  const csMedBy: Record<string, number> = {};
  for (const d of dates) {
    const vs = Object.values(volByCodeDate)
      .map((m) => m[d])
      .filter((x): x is number => finite(x));
    if (vs.length < 2) continue;
    const s = vs.slice().sort((a, b) => a - b);
    csMedBy[d] = s[Math.floor(s.length / 2)];
  }
  const byDate: Record<string, Record<string, number | null>> = {};
  for (const [code, pairs] of Object.entries(bars)) {
    if (code.startsWith("__") || !pairs) continue;
    const moms = pairs.map(([d, px], i) => {
      if (i < 5) return [d, null] as [string, number | null];
      const b = pairs[i - 5][1];
      if (!b) return [d, null] as [string, number | null];
      return [d, (px - b) / b] as [string, number | null];
    });
    for (const [d, m] of moms) {
      if (!byDate[d]) byDate[d] = {};
      byDate[d][code] = m;
    }
  }
  const out: Record<string, Record<string, number>> = {};
  for (const [code, pairs] of Object.entries(bars)) {
    if (code.startsWith("__") || !pairs) continue;
    const entries = pairs.map(([d]) => {
      const csMed = csMedBy[d];
      const medHist = pitMedian(csMedBy, d, 20);
      if (!finite(csMed) || medHist === null || csMed < medHist) return 0;
      const vol = volByCodeDate[code]?.[d];
      if (!finite(vol) || vol >= csMed) return 0;
      const scores: Record<string, number | null> = {};
      for (const [c, mom] of Object.entries(byDate[d] || {})) {
        const v = volByCodeDate[c]?.[d];
        if (finite(v) && v < csMed) scores[c] = mom;
      }
      const ranks = csRank(scores, 0.3, 0.3);
      return ranks[code] ?? 0;
    });
    const sticky = stickyHold(entries, 10);
    out[code] = {};
    for (let i = 0; i < pairs.length; i++) {
      const pos = sticky[i];
      if (pos) out[code][pairs[i][0]] = pos as number;
    }
  }
  return out;
}

function idioMomMacroHeld(
  panel: PeriodPanel,
): Record<string, Record<string, number>> {
  const idx = panel.bars?.["__NKY_PROXY__"] || [];
  if (idx.length < 6) return {};
  const idxMom: Record<string, number> = {};
  for (let i = 5; i < idx.length; i++) {
    const b = idx[i - 5][1];
    const last = idx[i][1];
    if (b && finite(b) && finite(last)) idxMom[idx[i][0]] = (last - b) / b;
  }
  const absMom: Record<string, number> = {};
  for (const [d, v] of Object.entries(idxMom)) absMom[d] = Math.abs(v);
  const byDate: Record<string, Record<string, number | null>> = {};
  for (const [code, pairs] of Object.entries(panel.bars || {})) {
    if (code.startsWith("__") || !pairs) continue;
    for (let i = 5; i < pairs.length; i++) {
      const b = pairs[i - 5][1];
      const last = pairs[i][1];
      const d = pairs[i][0];
      if (!b || !finite(b) || !finite(last)) continue;
      if (!byDate[d]) byDate[d] = {};
      const nameMom = (last - b) / b;
      const im = idxMom[d];
      byDate[d][code] = finite(im) ? nameMom - im : nameMom;
    }
  }
  const out: Record<string, Record<string, number>> = {};
  for (const [code, pairs] of Object.entries(panel.bars || {})) {
    if (code.startsWith("__") || !pairs) continue;
    const entries = pairs.map(([d]) => {
      const im = idxMom[d];
      const med = pitMedian(absMom, d, 20);
      if (!finite(im) || med === null || Math.abs(im) < med) return 0;
      const ranks = csRank(byDate[d] || {}, 0.3, 0.3);
      return ranks[code] ?? 0;
    });
    const sticky = stickyHold(entries, 10);
    out[code] = {};
    for (let i = 0; i < pairs.length; i++) {
      const pos = sticky[i];
      if (pos) out[code][pairs[i][0]] = pos as number;
    }
  }
  return out;
}

export function evalLogicDailyPathOnPanel(
  logic: LogicSpec,
  panel: PeriodPanel,
  oneWay: number,
): Record<string, unknown> {
  const pid = panel.period_id;
  if (panel.status !== "ok" || !panel.bars || !Object.keys(panel.bars).length) {
    return {
      period_id: pid,
      year: panel.year,
      status: "data_missing",
      daily_path_complete: false,
      skip_reason: "empty_or_missing_bars",
    };
  }
  const params = logic.params || {};
  const holdDays = Math.floor(
    finite(params.hold_days as number)
      ? (params.hold_days as number)
      : finite(params.post_hold_days as number)
        ? (params.post_hold_days as number)
        : 10,
  );
  const lid = String(logic.logic_id || "");
  let evalPath = "unknown";
  let pathFallback: string | undefined;
  let held: Record<string, Record<string, number>> = {};
  if (isEventLogic(lid)) {
    held = eventHeld(logic, panel) || {};
    evalPath = "event";
  } else if (
    (CF_UNIQUE_CS_LOGIC_IDS as readonly string[]).includes(lid) ||
    (CF_NEW_CS_THESIS_IDS as readonly string[]).includes(lid)
  ) {
    held = gatedCsHeld(logic, panel);
    evalPath = "gated_cs";
  } else {
    const bn = barNativeHeldBook(logic, panel);
    if (bn) {
      held = bn.held;
      evalPath = bn.path;
      pathFallback = bn.fallback;
    } else if (usesCrossSection(logic)) {
      // Unwired CS overlay — do not silently share the generic CS book.
      held = {};
      evalPath = "cs_generic";
      pathFallback = "path_broken";
    } else {
      held = {};
      evalPath = "mdh_generic";
      pathFallback = "path_broken";
    }
  }
  const dates = unionDates(panel.bars);
  const pack = heldBookDailyMtm(
    held,
    closeByMap(panel.bars),
    dates,
    holdDays,
    oneWay,
    panel.repo_rate_regime?.rates_by_date ||
      panel.repo_rate_regime?.rate_by_date ||
      panel.repo_rate_by_date ||
      undefined,
    panel.adv_by_code || undefined,
  );
  if (pack.net_daily.length < 2) {
    return {
      period_id: pid,
      year: panel.year,
      status: "insufficient_dates",
      daily_path_complete: false,
    };
  }
  let eq = 1;
  const equities: number[] = [];
  for (let i = 0; i < pack.net_daily.length; i++) {
    if (i === 0) equities.push(1);
    else {
      eq = eq * (1 + pack.net_daily[i]);
      equities.push(eq);
    }
  }
  const dd = equityPathDrawdown(equities, pack.dates);
  const pathBroken = isPathBroken(evalPath, pathFallback);
  const complete =
    !pathBroken &&
    dd.max_dd !== null &&
    dd.dd_duration_days !== null &&
    dd.recovered !== null &&
    dd.total_return !== null;
  const nets = pack.net_daily.slice(1);
  const tStat = tStatVsZero(nets);
  const sh = sharpePeriod(nets);
  return {
    period_id: pid,
    year: panel.year,
    status: "ok",
    logic_id: lid,
    window_id: pid,
    dates: pack.dates,
    net_daily: pack.net_daily,
    occupancy_frac: pack.occupancy,
    occupancy: pack.occupancy,
    n_gate_on_days: pack.n_gate_on,
    n_days: pack.dates.length,
    daily_path_DD: dd.max_dd,
    total_ret_net: dd.total_return,
    dd_duration: dd.dd_duration_days,
    recovered: dd.recovered,
    recovery_days: dd.recovery_days,
    t_stat: tStat,
    sharpe_daily: sh,
    eval_path: evalPath,
    path_fallback: pathFallback || null,
    daily_path_complete: complete,
    method: dd.method,
    survived: false,
    promote_as_main: false,
    go: false,
    candidate_grade: true,
    period_net_dd_only_pass_forbidden: true,
  };
}

export function cellsFromPeriodPacks(
  logicId: string,
  packs: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const cells: Array<Record<string, unknown>> = [];
  for (const p of packs) {
    if (p.status !== "ok") {
      cells.push({
        logic_id: logicId,
        window: p.period_id || p.window_id,
        window_id: p.period_id || p.window_id,
        daily_path_complete: false,
        survived: false,
        promote_as_main: false,
        go: false,
        incomplete_reason: p.skip_reason || p.status,
        period_net_dd_only_pass_forbidden: true,
      });
      continue;
    }
    cells.push({
      logic_id: logicId,
      window: p.window_id || p.period_id,
      window_id: p.window_id || p.period_id,
      daily_path_DD: p.daily_path_DD,
      total_ret_net: p.total_ret_net,
      occupancy_frac: p.occupancy_frac,
      occupancy: p.occupancy_frac,
      dates: p.dates,
      net_daily: p.net_daily,
      dd_duration: p.dd_duration,
      recovered: p.recovered,
      recovery_days: p.recovery_days,
      n_days: p.n_days,
      t_stat: p.t_stat,
      sharpe_daily: p.sharpe_daily,
      eval_path: p.eval_path,
      path_fallback: p.path_fallback ?? null,
      daily_path_complete:
        Boolean(p.daily_path_complete) &&
        !isPathBroken(p.eval_path, p.path_fallback),
      survived: false,
      promote_as_main: false,
      go: false,
      candidate_grade: true,
      period_net_dd_only_pass_forbidden: true,
      method: p.method,
    });
  }
  return cells;
}
