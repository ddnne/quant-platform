/**
 * Candidate-grade daily MTM path on staged panels (not period-net screen).
 *
 * One Worker isolate evaluates one (or few) logics. The Python driver
 * fans out concurrent POSTs so batch wall-clock ≈ longest isolate.
 * n_survivors from /v1/mass-eval is not a pass.
 */
import type { BarsByCode, LogicSpec, PeriodPanel } from "./types";

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
    for (const [code, cmap] of Object.entries(held)) {
      const pos = cmap[prev];
      if (!pos) continue;
      const c0 = closeBy[code]?.[prev];
      const c1 = closeBy[code]?.[d];
      if (!finite(c0) || !finite(c1) || c0 === 0) continue;
      contribs.push(pos * (c1 / c0 - 1));
      if (pos < 0) nShort += 1;
    }
    let net = 0;
    if (contribs.length) {
      const g = contribs.reduce((a, b) => a + b, 0) / contribs.length;
      let shortDrag = 0;
      const repo = repoByDate?.[prev];
      if (nShort && finite(repo)) {
        // JSDA percent → daily fraction. Missing repo → no invent, tx-only.
        shortDrag = (nShort / contribs.length) * ((repo as number) / 100 / 252);
      }
      net = g - dailyCost - shortDrag;
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
] as const;

function usesCrossSection(logic: LogicSpec): boolean {
  const lid = String(logic.logic_id || "");
  const fam = String(logic.family_id || "");
  return (
    (CF_UNIQUE_CS_LOGIC_IDS as readonly string[]).includes(lid) ||
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
    lid === "surprise_xs_rank_hold" ||
    lid === "surprise_xs_rank_flip" ||
    lid === "surprise_xs_rank_adaptive" ||
    lid === "surprise_xs_rank_easy_funding" ||
    lid === "surprise_xs_rank_steep_curve" ||
    lid === "surprise_xs_month_start" ||
    lid === "surprise_xs_fy_end"
  ) {
    const invert = lid.includes("flip");
    const dates = unionDates(panel.bars);
    const surpriseByDate: Record<string, Record<string, number>> = {};
    for (const pack of Object.values(perCode)) {
      for (const ev of pack.entries) {
        if (
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
    for (const [code, pack] of Object.entries(perCode)) {
      const entries = pack.dlist.map((d) => dailyRank[code]?.[d] ?? null);
      const sticky = stickyHold(entries, holdDays);
      xsHeld[code] = {};
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
  const invert =
    lid === "xs_high_vol_fade" ||
    lid === "overnight_tight_cs_fade" ||
    lid === "curve_invert_cs_fade" ||
    lid === "fy_end_cs_fade" ||
    lid === "overnight_p90_cs_flip" ||
    lid === "flow_price_disagree_fade" ||
    lid === "basevol_up_day_fade";
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
  const out: Record<string, Record<string, number>> = {};
  for (const [code, cmap] of Object.entries(base)) {
    out[code] = {};
    for (const [d, v] of Object.entries(cmap)) {
      let keep = true;
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
      }
      if (keep) out[code][d] = v;
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
  const momN = Math.floor(
    finite(params.momentum_n as number) ? (params.momentum_n as number) : 5,
  );
  const lf = finite(params.long_frac as number) ? (params.long_frac as number) : 0.3;
  const sf = finite(params.short_frac as number)
    ? (params.short_frac as number)
    : 0.3;
  const lid = String(logic.logic_id || "");
  const invert = lid.includes("reversion") || lid.includes("fade");
  const polarity = lid.includes("reversion") ? -1 : 1;
  const held = isEventLogic(lid)
    ? eventHeld(logic, panel) || {}
    : (CF_NEW_CS_THESIS_IDS as readonly string[]).includes(lid)
      ? gatedCsHeld(logic, panel)
      : usesCrossSection(logic)
        ? csHeld(panel.bars, momN, holdDays, lf, sf, invert)
        : mdhHeld(panel.bars, holdDays, polarity);
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
  const complete =
    dd.max_dd !== null &&
    dd.dd_duration_days !== null &&
    dd.recovered !== null &&
    dd.total_return !== null;
  return {
    period_id: pid,
    year: panel.year,
    status: "ok",
    logic_id: lid,
    window_id: pid,
    dates: pack.dates,
    net_daily: pack.net_daily,
    occupancy_frac: pack.occupancy,
    n_gate_on_days: pack.n_gate_on,
    n_days: pack.dates.length,
    daily_path_DD: dd.max_dd,
    total_ret_net: dd.total_return,
    dd_duration: dd.dd_duration_days,
    recovered: dd.recovered,
    recovery_days: dd.recovery_days,
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
      dd_duration: p.dd_duration,
      recovered: p.recovered,
      recovery_days: p.recovery_days,
      n_days: p.n_days,
      daily_path_complete: Boolean(p.daily_path_complete),
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
