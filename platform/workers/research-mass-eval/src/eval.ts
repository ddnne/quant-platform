/**
 * Pure-TS lite multi-period logic evaluation for CF Workers.
 *
 * Ports the essential multi_day_hold + cross_section_relative paths used by
 * mass_strategy_factory.evaluate_one_strategy / class_hyp_eval.
 *
 * W93: macro_repo_rate_* consume staged repo_rate_regime when present.
 * Full flow/fund factor legs remain not-yet-implemented on CF (use local
 * factory; sidecars are staged on r2_panels for thicken / future).
 */

import {
  invertNets,
  sampleMean,
  sharpePeriod,
  tStatVsZero,
} from "./metrics";
import type {
  BarSeries,
  BarsByCode,
  LogicEvalResult,
  LogicSpec,
  NkyVolSeries,
  PeriodEvalRow,
  PeriodPanel,
} from "./types";

const DEFAULT_ONE_WAY = 0.001;
const DEFAULT_NEAR_ZERO = 1e-6;
const DEFAULT_MIN_ACTIVATION = 0.02;

function signFromNumeric(v: number | null | undefined): number | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  if (v > 0) return 1;
  if (v < 0) return -1;
  return 0;
}

function amortizedOneWayCost(oneWay: number, holdDays: number): number {
  const h = Math.max(1, Math.floor(holdDays));
  return (2 * oneWay) / h;
}

function momentumSeries(pairs: BarSeries, n: number): Array<[string, number | null]> {
  const nI = Math.max(1, Math.floor(n));
  const out: Array<[string, number | null]> = [];
  for (let i = 0; i < pairs.length; i++) {
    const d = pairs[i][0];
    if (i < nI) {
      out.push([d, null]);
      continue;
    }
    const base = pairs[i - nI][1];
    const last = pairs[i][1];
    if (base === 0) out.push([d, null]);
    else out.push([d, (last - base) / base]);
  }
  return out;
}

function multiDayForwardReturn(
  closes: number[],
  holdDays: number,
  entryIndex: number,
): number | null {
  const h = Math.max(1, Math.floor(holdDays));
  const j = entryIndex + h;
  if (entryIndex < 0 || j >= closes.length) return null;
  const c0 = closes[entryIndex];
  const c1 = closes[j];
  if (!Number.isFinite(c0) || !Number.isFinite(c1) || c0 === 0) return null;
  return c1 / c0 - 1;
}

function applyStickyHold(
  dailyEntrySigns: Array<number | null>,
  holdDays: number,
  rebalanceMode: string,
): Array<number | null> {
  const h = Math.max(1, Math.floor(holdDays));
  const n = dailyEntrySigns.length;
  const out: Array<number | null> = new Array(n).fill(null);
  let held: number | null = null;
  let heldFor = 0;
  let daysSinceRebalance = 0;

  for (let i = 0; i < n; i++) {
    const raw = dailyEntrySigns[i];
    const entry = signFromNumeric(raw);
    if (rebalanceMode === "fixed_horizon") {
      if (i === 0 || daysSinceRebalance >= h) {
        if (entry !== null && entry !== 0) held = entry;
        else if (entry === 0) held = 0;
        daysSinceRebalance = 1;
      } else {
        daysSinceRebalance += 1;
      }
      out[i] = held;
    } else {
      // min_hold
      if (held === null) {
        if (entry !== null && entry !== 0) {
          held = entry;
          heldFor = 1;
        } else if (entry === 0) {
          held = 0;
          heldFor = 1;
        }
        out[i] = held;
        continue;
      }
      heldFor += 1;
      if (heldFor >= h && entry !== null && entry !== held) {
        held = entry;
        heldFor = 1;
      }
      out[i] = held;
    }
  }
  return out;
}

function crossSectionRankSigns(
  scores: Record<string, number | null>,
  longFrac: number,
  shortFrac: number,
): Record<string, number | null> {
  const items = Object.entries(scores)
    .filter(([, v]) => v !== null && Number.isFinite(v as number))
    .map(([c, v]) => [c, v as number] as [string, number])
    .sort((a, b) => b[1] - a[1]);
  const n = items.length;
  const out: Record<string, number | null> = {};
  for (const c of Object.keys(scores)) out[c] = 0;
  if (n === 0) return out;
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

function repoRatesFromPanel(panel: PeriodPanel): Record<string, number> {
  const regime = panel.repo_rate_regime;
  const fromRegime =
    (regime && (regime.rates_by_date || regime.rate_by_date)) || null;
  const flat = panel.repo_rate_by_date || null;
  return { ...(fromRegime || {}), ...(flat || {}) };
}

function repoRegimeLabel(
  rate: number | null,
  prev: number | null,
  mode: string,
  highThreshold: number,
  lowThreshold: number,
  eps: number,
): string | null {
  if (rate === null || !Number.isFinite(rate)) return null;
  const m = String(mode || "rate_change").toLowerCase();
  if (m.includes("level")) {
    if (rate >= highThreshold) return "high";
    if (rate <= lowThreshold) return "low";
    return "mid";
  }
  // rate_change
  if (prev === null || !Number.isFinite(prev)) return null;
  const delta = rate - prev;
  if (delta > eps) return "rate_up";
  if (delta < -eps) return "rate_down";
  return "flat";
}

function conditionMomOnRepoRegime(
  entrySign: number | null,
  regime: string | null,
  mode: string,
): number | null {
  if (entrySign === null || regime === null) return null;
  const m = String(mode || "rate_change").toLowerCase();
  if (m.includes("level")) {
    if (regime === "low") return entrySign > 0 ? entrySign : null;
    if (regime === "high") return entrySign < 0 ? entrySign : null;
    return null; // mid → no trade
  }
  if (regime === "rate_down") return entrySign > 0 ? entrySign : null;
  if (regime === "rate_up") return entrySign < 0 ? entrySign : null;
  return null; // flat → no trade
}

/**
 * W93: macro-conditioned momentum using staged jsda_tokyo_repo_rates.
 * Falls back to plain MDH when repo map is empty (disclosed).
 */
function evalMacroRepoConditioned(
  bars: BarsByCode,
  ratesByDate: Record<string, number>,
  mode: string,
  momentumN: number,
  holdDays: number,
  oneWay: number,
  highThreshold: number,
  lowThreshold: number,
): {
  gross: number | null;
  net: number | null;
  amCost: number;
  nActive: number;
  activation: number | null;
  signalId: string;
} {
  const n = Math.max(1, Math.floor(momentumN));
  const h = Math.max(1, Math.floor(holdDays));
  const amCost = amortizedOneWayCost(oneWay, h);
  const rateDates = Object.keys(ratesByDate).sort();
  if (rateDates.length < 2) {
    // No staged repo → honest MDH fallback tag.
    const fb = evalMultiDayHold(bars, h, oneWay, "fixed_horizon", 1);
    return { ...fb, signalId: `c21_lite_fallback_mdh:macro_conditioned` };
  }
  const prevMap: Record<string, number | null> = {};
  for (let i = 0; i < rateDates.length; i++) {
    prevMap[rateDates[i]] = i > 0 ? ratesByDate[rateDates[i - 1]] : null;
  }
  const signed: number[] = [];
  let nActive = 0;
  let nCodeDays = 0;
  const eps = 1e-6;

  for (const code of Object.keys(bars).sort()) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    if (!pairs || pairs.length < n + 2) continue;
    const moms = momentumSeries(pairs, n);
    const entrySigns = moms.map(([, m]) => signFromNumeric(m));
    // Apply regime filter to daily entries, then sticky hold.
    const conditioned: Array<number | null> = [];
    for (let i = 0; i < moms.length; i++) {
      const d = moms[i][0];
      let rate = ratesByDate[d];
      let prev = prevMap[d] ?? null;
      if (rate === undefined) {
        // last repo date ≤ d (no invent/ffill beyond observed as_of)
        const earlier = rateDates.filter((x) => x <= d);
        if (!earlier.length) {
          conditioned.push(null);
          continue;
        }
        const last = earlier[earlier.length - 1];
        rate = ratesByDate[last];
        prev = prevMap[last] ?? null;
      }
      const regime = repoRegimeLabel(
        rate,
        prev,
        mode,
        highThreshold,
        lowThreshold,
        eps,
      );
      conditioned.push(conditionMomOnRepoRegime(entrySigns[i], regime, mode));
    }
    const held = applyStickyHold(conditioned, h, "fixed_horizon");
    const closes = pairs.map(([, c]) => c);
    for (let i = 0; i < held.length; i++) {
      nCodeDays += 1;
      const pos = held[i];
      if (pos === null || pos === 0) continue;
      if (i % h !== 0) continue;
      const fwd = multiDayForwardReturn(closes, h, i);
      if (fwd === null) continue;
      nActive += 1;
      signed.push(pos * fwd);
    }
  }
  const gross = signed.length ? sampleMean(signed) : null;
  const net = gross !== null ? gross - amCost : null;
  const modeTag = String(mode || "rate_change").includes("level")
    ? "rate_level"
    : "rate_change";
  return {
    gross,
    net,
    amCost,
    nActive,
    activation: nCodeDays > 0 ? nActive / nCodeDays : null,
    signalId: `c21_macro_repo_${modeTag}`,
  };
}

function evalMultiDayHold(
  bars: BarsByCode,
  holdDays: number,
  oneWay: number,
  rebalanceMode: string,
  polarity: number,
): {
  gross: number | null;
  net: number | null;
  amCost: number;
  nActive: number;
  activation: number | null;
  signalId: string;
} {
  const h = Math.max(1, Math.floor(holdDays));
  const amCost = amortizedOneWayCost(oneWay, h);
  const signed: number[] = [];
  let nActive = 0;
  let nCodeDays = 0;
  const pol = polarity < 0 ? -1 : 1;

  for (const code of Object.keys(bars).sort()) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    if (!pairs || pairs.length < h + 2) continue;
    const moms = momentumSeries(pairs, h);
    const entrySigns = moms.map(([, m]) => {
      const s = signFromNumeric(m);
      return s === null ? null : s * pol;
    });
    const held = applyStickyHold(entrySigns, h, rebalanceMode);
    const closes = pairs.map(([, c]) => c);
    for (let i = 0; i < held.length; i++) {
      nCodeDays += 1;
      const pos = held[i];
      if (pos === null || pos === 0) continue;
      if (rebalanceMode === "fixed_horizon" && i % h !== 0) continue;
      const fwd = multiDayForwardReturn(closes, h, i);
      if (fwd === null) continue;
      nActive += 1;
      signed.push(pos * fwd);
    }
  }
  const gross = signed.length ? sampleMean(signed) : null;
  const net = gross !== null ? gross - amCost : null;
  return {
    gross,
    net,
    amCost,
    nActive,
    activation: nCodeDays > 0 ? nActive / nCodeDays : null,
    signalId: polarity < 0 ? "c21_multi_day_hold_reversion" : "c21_multi_day_hold",
  };
}

function evalCrossSection(
  bars: BarsByCode,
  momentumN: number,
  holdDays: number,
  longFrac: number,
  shortFrac: number,
  oneWay: number,
): {
  gross: number | null;
  net: number | null;
  amCost: number;
  nActive: number;
  activation: number | null;
  signalId: string;
} {
  const n = Math.max(1, Math.floor(momentumN));
  const h = Math.max(1, Math.floor(holdDays));
  const byDate: Record<string, Record<string, number | null>> = {};
  const datesByCode: Record<string, string[]> = {};
  const closesList: Record<string, number[]> = {};
  for (const code of Object.keys(bars)) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    const moms = momentumSeries(pairs, n);
    for (const [d, m] of moms) {
      if (!byDate[d]) byDate[d] = {};
      byDate[d][code] = m;
    }
    datesByCode[code] = pairs.map(([d]) => d);
    closesList[code] = pairs.map(([, c]) => c);
  }
  const dates = Object.keys(byDate).sort();
  const signed: number[] = [];
  let nActive = 0;

  let amCost: number;
  if (h <= 1) {
    amCost = oneWay;
    const closeBy: Record<string, Record<string, number>> = {};
    for (const code of Object.keys(bars)) {
      closeBy[code] = {};
      for (const [d, c] of bars[code]) closeBy[code][d] = c;
    }
    for (let i = 0; i < dates.length - 1; i++) {
      const d = dates[i];
      const nxt = dates[i + 1];
      const ranks = crossSectionRankSigns(byDate[d], longFrac, shortFrac);
      for (const [code, sign] of Object.entries(ranks)) {
        if (sign === null || sign === 0) continue;
        const c0 = closeBy[code]?.[d];
        const c1 = closeBy[code]?.[nxt];
        if (c0 === undefined || c1 === undefined || c0 === 0) continue;
        nActive += 1;
        signed.push(sign * (c1 / c0 - 1));
      }
    }
  } else {
    amCost = amortizedOneWayCost(oneWay, h);
    const dailyRank: Record<string, Record<string, number | null>> = {};
    for (const d of dates) {
      const ranks = crossSectionRankSigns(byDate[d], longFrac, shortFrac);
      for (const [code, sign] of Object.entries(ranks)) {
        if (!dailyRank[code]) dailyRank[code] = {};
        dailyRank[code][d] = sign;
      }
    }
    for (const code of Object.keys(datesByCode)) {
      const dlist = datesByCode[code];
      const entries = dlist.map((d) => dailyRank[code]?.[d] ?? null);
      const held = applyStickyHold(entries, h, "fixed_horizon");
      const closes = closesList[code];
      for (let i = 0; i < held.length; i++) {
        const pos = held[i];
        if (pos === null || pos === 0) continue;
        if (i % h !== 0) continue;
        const fwd = multiDayForwardReturn(closes, h, i);
        if (fwd === null) continue;
        nActive += 1;
        signed.push(pos * fwd);
      }
    }
  }

  const nCodes = Object.keys(bars).length;
  const nTradingDays = dates.length;
  const nCodeDays = nTradingDays * nCodes;
  const gross = signed.length ? sampleMean(signed) : null;
  const net = gross !== null ? gross - amCost : null;
  return {
    gross,
    net,
    amCost,
    nActive,
    activation: nCodeDays > 0 ? nActive / nCodeDays : null,
    signalId: "c21_cross_section_relative",
  };
}

function numParam(params: Record<string, unknown>, key: string, fallback: number): number {
  const v = params[key];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return fallback;
}

function strParam(params: Record<string, unknown>, key: string, fallback: string): string {
  const v = params[key];
  if (typeof v === "string" && v.trim()) return v;
  return fallback;
}

/**
 * W91 index-level Nikkei/TOPIX vol regime × CS book (lite TS port).
 * Distinct from per-name vol_risk_adjusted / vol_breakout_expand.
 */
function evalNkyVolRegime(
  bars: BarsByCode,
  nky: NkyVolSeries | null,
  mode: string,
  momentumN: number,
  holdDays: number,
  longFrac: number,
  shortFrac: number,
  oneWay: number,
  highThr: number,
  lowThr: number,
  expandRatio: number,
  compressRatio: number,
): {
  gross: number | null;
  net: number | null;
  amCost: number;
  nActive: number;
  activation: number | null;
  signalId: string;
} {
  const h = Math.max(1, Math.floor(holdDays));
  const n = Math.max(1, Math.floor(momentumN));
  const amCost = amortizedOneWayCost(oneWay, h);
  const m = (mode || "nky_vol_abs_level").toLowerCase();
  if (!nky) {
    return {
      gross: null,
      net: null,
      amCost,
      nActive: 0,
      activation: null,
      signalId: `c21_nky_vol_${m}_missing_series`,
    };
  }
  const absBy = nky.rv_abs_by_date || nky.rv_short_by_date || {};
  const shortBy = nky.rv_short_by_date || {};
  const longBy = nky.rv_long_by_date || {};

  const byDate: Record<string, Record<string, number | null>> = {};
  const datesByCode: Record<string, string[]> = {};
  const closesList: Record<string, number[]> = {};
  for (const [code, pairs] of Object.entries(bars)) {
    // Skip reserved index proxy codes from CS universe.
    if (String(code).startsWith("__")) continue;
    const moms = momentumSeries(pairs, n);
    for (const [d, mom] of moms) {
      if (!byDate[d]) byDate[d] = {};
      byDate[d][code] = mom;
    }
    datesByCode[code] = pairs.map((p) => p[0]);
    closesList[code] = pairs.map((p) => p[1]);
  }
  const dates = Object.keys(byDate).sort();
  const dailyAdj: Record<string, Record<string, number | null>> = {};
  for (const code of Object.keys(bars)) dailyAdj[code] = {};

  function regimeFor(d: string): string | null {
    const dk = d.slice(0, 10);
    if (m.includes("term_ratio") || m === "nky_vol_term_ratio") {
      const s = shortBy[dk];
      const lo = longBy[dk];
      if (s === undefined || lo === undefined || !(lo > 1e-12)) return null;
      const ratio = s / lo;
      if (ratio >= expandRatio) return "expanding";
      if (ratio <= compressRatio) return "compressing";
      return "mid";
    }
    if (m.includes("term_levels") || m === "nky_vol_term_levels") {
      const s = shortBy[dk];
      const lo = longBy[dk];
      if (s === undefined || lo === undefined) return null;
      const sLab = s >= highThr ? "high" : s <= lowThr ? "low" : "mid";
      const lLab = lo >= highThr ? "high" : lo <= lowThr ? "low" : "mid";
      if (sLab === "high" && lLab === "high") return "high";
      if (sLab === "low" && lLab === "low") return "low";
      return "mid";
    }
    // abs level
    const v = absBy[dk];
    if (v === undefined) return null;
    if (v >= highThr) return "high";
    if (v <= lowThr) return "low";
    return "mid";
  }

  function adjust(cs: number | null, reg: string | null): number | null {
    if (cs === null || reg === null) return null;
    if (cs === 0) return 0;
    if (m.includes("term_ratio") || m === "nky_vol_term_ratio") {
      if (reg === "compressing") return cs;
      if (reg === "expanding") return -cs;
      return null;
    }
    if (reg === "low") return cs;
    if (reg === "high") return -cs;
    return null;
  }

  for (const d of dates) {
    const ranks = crossSectionRankSigns(byDate[d], longFrac, shortFrac);
    const reg = regimeFor(d);
    for (const [code, cs] of Object.entries(ranks)) {
      dailyAdj[code][d] = adjust(cs, reg);
    }
  }

  const signed: number[] = [];
  let nActive = 0;
  let nCodeDays = 0;
  for (const code of Object.keys(datesByCode)) {
    const dlist = datesByCode[code];
    const entries = dlist.map((d) => dailyAdj[code]?.[d] ?? null);
    const held = applyStickyHold(entries, h, "fixed_horizon");
    const closes = closesList[code];
    for (let i = 0; i < held.length; i++) {
      nCodeDays += 1;
      const pos = held[i];
      if (pos === null || pos === 0) continue;
      if (i % h !== 0) continue;
      const fwd = multiDayForwardReturn(closes, h, i);
      if (fwd === null) continue;
      nActive += 1;
      signed.push(pos * fwd);
    }
  }
  const gross = signed.length ? sampleMean(signed) : null;
  const net = gross !== null ? gross - amCost : null;
  const sid =
    m.includes("term_ratio")
      ? "c21_nky_vol_term_ratio_xs"
      : m.includes("term_levels")
        ? "c21_nky_vol_term_levels_xs"
        : "c21_nky_vol_abs_level_xs";
  return {
    gross,
    net,
    amCost,
    nActive,
    activation: nCodeDays > 0 ? nActive / nCodeDays : null,
    signalId: sid,
  };
}

/** Evaluate one logic on one panel. */
export function evalLogicOnPanel(
  logic: LogicSpec,
  panel: PeriodPanel,
  oneWay: number,
): PeriodEvalRow {
  const pid = panel.period_id;
  if (panel.status !== "ok" || !panel.bars || Object.keys(panel.bars).length === 0) {
    return {
      period_id: pid,
      year: panel.year,
      status: "data_missing",
      gross_signed_mean_active: null,
      net_one_way_mean_active: null,
      skip_reason: "empty_or_missing_bars",
    };
  }

  const family = String(logic.family_id || logic.logic_id || "multi_day_hold");
  const params = logic.params || {};
  const lid = String(logic.logic_id || family);

  try {
    let out: {
      gross: number | null;
      net: number | null;
      amCost: number;
      nActive: number;
      activation: number | null;
      signalId: string;
    };
    let holdDays = 5;

    if (
      family === "cross_section_relative" ||
      lid.includes("cross_section") ||
      lid.startsWith("xs_")
    ) {
      holdDays = Math.floor(numParam(params, "hold_days", 10));
      out = evalCrossSection(
        panel.bars,
        numParam(params, "momentum_n", 5),
        holdDays,
        numParam(params, "long_frac", 0.3),
        numParam(params, "short_frac", 0.3),
        oneWay,
      );
    } else if (
      family === "index_vol_regime" ||
      lid.startsWith("nky_vol_")
    ) {
      holdDays = Math.floor(numParam(params, "hold_days", 10));
      const mode = strParam(params, "mode", lid || "nky_vol_abs_level");
      out = evalNkyVolRegime(
        panel.bars,
        panel.nky_vol_series || null,
        mode,
        numParam(params, "momentum_n", 5),
        holdDays,
        numParam(params, "long_frac", 0.3),
        numParam(params, "short_frac", 0.3),
        oneWay,
        numParam(params, "high_threshold", 0.2),
        numParam(params, "low_threshold", 0.1),
        numParam(params, "expand_ratio", 1.2),
        numParam(params, "compress_ratio", 0.8),
      );
    } else if (
      family === "options_vol_regime" ||
      lid.startsWith("opt225_")
    ) {
      holdDays = Math.floor(numParam(params, "hold_days", 10));
      const mode = strParam(params, "mode", lid || "opt225_basevol_abs_level");
      const seriesKind = strParam(params, "series_kind", "basevol");
      const bundle = panel.opt225_regime || null;
      let series =
        bundle && seriesKind in bundle
          ? (bundle as Record<string, unknown>)[seriesKind]
          : null;
      if (!series && bundle) {
        if (mode.includes("spread_change")) series = bundle.spread_change;
        else if (mode.includes("spread")) series = bundle.spread;
        else if (mode.includes("atm_iv")) series = bundle.atm_iv;
        else series = bundle.basevol;
      }
      // Fallback: build abs map from top-level by-date series on the panel.
      if (!series) {
        const absMap = mode.includes("spread")
          ? panel.iv_base_spread
          : mode.includes("atm_iv")
            ? panel.atm_iv_series
            : panel.base_vol_series;
        if (absMap && Object.keys(absMap).length > 0) {
          series = {
            source: "panel_top_level_series",
            rv_abs_by_date: absMap,
            rv_short_by_date: absMap,
            rv_long_by_date: absMap,
            rv_ratio_by_date: {},
          };
        }
      }
      // Reuse nky regime evaluator; thresholds are percent vol points for opt225.
      const defaultHigh = mode.includes("spread") ? 1.0 : 24.0;
      const defaultLow = mode.includes("spread") ? -0.5 : 12.0;
      out = evalNkyVolRegime(
        panel.bars,
        (series as PeriodPanel["nky_vol_series"]) || null,
        mode.includes("term_ratio")
          ? "nky_vol_term_ratio"
          : mode.includes("term_levels")
            ? "nky_vol_term_levels"
            : "nky_vol_abs_level",
        numParam(params, "momentum_n", 5),
        holdDays,
        numParam(params, "long_frac", 0.3),
        numParam(params, "short_frac", 0.3),
        oneWay,
        numParam(params, "high_threshold", defaultHigh),
        numParam(params, "low_threshold", defaultLow),
        numParam(params, "expand_ratio", 1.2),
        numParam(params, "compress_ratio", 0.8),
      );
      // Retag signal id for options_225 family.
      out = {
        ...out,
        signalId: `c21_${mode}_xs`,
      };
    } else if (
      family === "macro_conditioned" ||
      lid.startsWith("macro_repo_rate_")
    ) {
      holdDays = Math.floor(numParam(params, "hold_days", 10));
      const mode = strParam(params, "mode", lid.includes("level") ? "rate_level" : "rate_change");
      out = evalMacroRepoConditioned(
        panel.bars,
        repoRatesFromPanel(panel),
        mode,
        numParam(params, "momentum_n", 10),
        holdDays,
        oneWay,
        numParam(params, "high_threshold", 0.05),
        numParam(params, "low_threshold", 0.0),
      );
    } else {
      // multi_day_hold + generic fallback for flow/fund/multi_factor/etc.
      // Flow/fund factor legs not-yet-implemented on CF pure-TS path
      // (sidecars staged on r2_panels; local factory evaluates).
      holdDays = Math.floor(
        numParam(params, "hold_days", numParam(params, "post_hold_days", 5)),
      );
      const polarity = Math.floor(numParam(params, "signal_polarity", 1));
      const rebalance = strParam(params, "rebalance_mode", "fixed_horizon");
      out = evalMultiDayHold(panel.bars, holdDays, oneWay, rebalance, polarity);
      // tag fallback families honestly
      if (
        family !== "multi_day_hold" &&
        !lid.includes("multi_day") &&
        family !== "vol_risk_adjusted" &&
        family !== "index_vol_regime" &&
        family !== "options_vol_regime" &&
        family !== "macro_conditioned" &&
        !lid.startsWith("opt225_") &&
        !lid.startsWith("nky_vol_") &&
        !lid.startsWith("macro_repo_rate_")
      ) {
        out = {
          ...out,
          signalId: `c21_lite_fallback_mdh:${family}`,
        };
      }
    }

    return {
      period_id: pid,
      year: panel.year,
      status: "ok",
      gross_signed_mean_active: out.gross,
      net_one_way_mean_active: out.net,
      amortized_one_way_cost: out.amCost,
      n_active_positions: out.nActive,
      activation_rate: out.activation,
      hold_days: holdDays,
      signal_id: out.signalId,
    };
  } catch (e) {
    return {
      period_id: pid,
      year: panel.year,
      status: "error",
      gross_signed_mean_active: null,
      net_one_way_mean_active: null,
      error: e instanceof Error ? `${e.name}: ${e.message}` : String(e),
    };
  }
}

function freezeFields() {
  return {
    mass_research: "NO-GO",
    phase7: "OFF",
    ready_declared: false,
    operational_go: false,
    continuous_paper: "UNARMED",
    frozen_defaults_retuned: false,
  };
}

export function evaluateLogicAcrossPeriods(
  logic: LogicSpec,
  panels: PeriodPanel[],
  opts: {
    oneWayCost?: number;
    nearZeroAbs?: number;
    minActivation?: number;
    seed?: number;
    index?: number;
  } = {},
): LogicEvalResult {
  const oneWay = opts.oneWayCost ?? DEFAULT_ONE_WAY;
  const nearZero = opts.nearZeroAbs ?? DEFAULT_NEAR_ZERO;
  const minAct = opts.minActivation ?? DEFAULT_MIN_ACTIVATION;
  const family = String(logic.family_id || logic.logic_id || "multi_day_hold");
  const logicId = String(logic.logic_id || family);
  const sid =
    String(logic.strategy_id || "").trim() ||
    `msf_cf_${String(opts.seed ?? 0).padStart(8, "0")}_${String(opts.index ?? 0).padStart(4, "0")}_${logicId}`;

  const periodRows: PeriodEvalRow[] = [];
  const errors: string[] = [];

  // nets_only path: use embedded period nets
  if (
    Array.isArray(logic.period_nets) &&
    logic.period_nets.length > 0 &&
    panels.length === 0
  ) {
    for (let i = 0; i < logic.period_nets.length; i++) {
      const net = logic.period_nets[i];
      const gross = Array.isArray(logic.period_grosses)
        ? logic.period_grosses[i] ?? null
        : net;
      periodRows.push({
        period_id: `p${i}`,
        status: net === null || net === undefined ? "data_missing" : "ok",
        gross_signed_mean_active:
          gross === null || gross === undefined ? null : Number(gross),
        net_one_way_mean_active:
          net === null || net === undefined ? null : Number(net),
        amortized_one_way_cost: oneWay,
      });
    }
  } else {
    for (const panel of panels) {
      const row = evalLogicOnPanel(logic, panel, oneWay);
      if (row.status === "error" && row.error) errors.push(row.error);
      periodRows.push(row);
    }
  }

  const okRows = periodRows.filter((r) => r.status === "ok");
  const grosses = okRows.map((r) => r.gross_signed_mean_active);
  const nets = okRows.map((r) => r.net_one_way_mean_active);
  const costs = okRows.map((r) => r.amortized_one_way_cost ?? null);
  const actRates = okRows
    .map((r) => r.activation_rate)
    .filter((x): x is number => x !== null && x !== undefined && Number.isFinite(x));

  const meanGross = sampleMean(grosses);
  const meanNetOrig = sampleMean(nets);
  const tOrig = tStatVsZero(nets);
  const sharpeOrig = sharpePeriod(nets);

  const netsInv = invertNets(nets, costs);
  const meanNetInv = sampleMean(netsInv);
  const tInv = tStatVsZero(netsInv);
  const sharpeInv = sharpePeriod(netsInv);

  // choose_sign: prefer side with |t| higher among non-near-zero positive mean
  let chosen: "original" | "inverted" | "reject" = "reject";
  const origOk =
    meanNetOrig !== null &&
    Math.abs(meanNetOrig) > nearZero &&
    meanNetOrig > 0 &&
    tOrig !== null;
  const invOk =
    meanNetInv !== null &&
    Math.abs(meanNetInv) > nearZero &&
    meanNetInv > 0 &&
    tInv !== null;
  if (origOk && invOk) {
    chosen = Math.abs(tOrig!) >= Math.abs(tInv!) ? "original" : "inverted";
  } else if (origOk) {
    chosen = "original";
  } else if (invOk) {
    chosen = "inverted";
  } else if (
    meanNetOrig !== null &&
    Math.abs(meanNetOrig) > nearZero &&
    tOrig !== null
  ) {
    // keep original if any signal but non-positive → reject for screen
    chosen = "reject";
  }

  const meanNet = chosen === "inverted" ? meanNetInv : meanNetOrig;
  const tStat = chosen === "inverted" ? tInv : tOrig;
  const sharpe = chosen === "inverted" ? sharpeInv : sharpeOrig;
  const meanActivation = sampleMean(actRates);

  const rejectReasons: string[] = [];
  if (okRows.length < 2) rejectReasons.push("insufficient_periods");
  if (meanNet === null || !Number.isFinite(meanNet) || meanNet <= nearZero) {
    rejectReasons.push("non_positive_mean_net");
  }
  if (tStat === null || !Number.isFinite(tStat) || Math.abs(tStat) < 0.5) {
    rejectReasons.push("weak_t_stat");
  }
  if (
    meanActivation !== null &&
    meanActivation < minAct &&
    family !== "event_post"
  ) {
    rejectReasons.push("low_activation");
  }
  if (chosen === "reject") rejectReasons.push("sign_selection_reject");

  const survived = rejectReasons.length === 0;
  const freezes = freezeFields();

  return {
    strategy_id: sid,
    logic_id: logicId,
    family_id: family,
    params: logic.params || {},
    thesis: logic.thesis,
    status: errors.length && okRows.length === 0 ? "eval_error" : "ok",
    n_periods_ok: okRows.length,
    n_periods_total: periodRows.length,
    period_rows: periodRows,
    mean_gross: meanGross,
    mean_net: meanNet,
    mean_net_inverted: meanNetInv,
    t_stat: tStat,
    t_stat_inverted: tInv,
    sharpe_period: sharpe,
    sharpe_period_inverted: sharpeInv,
    chosen_sign: chosen,
    mean_activation: meanActivation,
    screen: {
      survived,
      reject_reasons: rejectReasons,
      mean_net: meanNet,
      t_stat: tStat,
      sharpe_period: sharpe,
      chosen_sign: chosen,
      family_id: family,
      logic_id: logicId,
      strategy_id: sid,
    },
    errors,
    ...freezes,
  };
}

export function rankSurvivors(results: LogicEvalResult[]): Array<Record<string, unknown>> {
  const survivors = results.filter((r) => r.screen?.survived);
  survivors.sort((a, b) => {
    const ta = a.t_stat !== null && Number.isFinite(a.t_stat) ? Math.abs(a.t_stat) : -1;
    const tb = b.t_stat !== null && Number.isFinite(b.t_stat) ? Math.abs(b.t_stat) : -1;
    if (tb !== ta) return tb - ta;
    const ma = a.mean_net ?? -1e9;
    const mb = b.mean_net ?? -1e9;
    return mb - ma;
  });
  return survivors.map((s, i) => ({
    rank: i + 1,
    strategy_id: s.strategy_id,
    logic_id: s.logic_id,
    family_id: s.family_id,
    mean_net: s.mean_net,
    t_stat: s.t_stat,
    sharpe_period: s.sharpe_period,
    chosen_sign: s.chosen_sign,
    mean_activation: s.mean_activation,
  }));
}
