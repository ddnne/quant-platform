/**
 * Pure-TS lite multi-period logic evaluation for CF Workers.
 *
 * Ports the essential multi_day_hold + cross_section_relative paths used by
 * mass_strategy_factory.evaluate_one_strategy / class_hyp_eval.
 *
 * W93: macro_repo_rate_* consume staged repo_rate_regime when present.
 * W94: flow_margin_* / fund_* / mf_* consume staged flow_regime / fund_regime
 * when present. Missing sidecars → disclosed MDH fallback
 * (`c21_lite_fallback_mdh:<family>`), never silent.
 */

import {
  hasPairwiseLowVarianceArtifact,
  invertNets,
  sampleMean,
  sharpePeriod,
  tStatVsZero,
  tStatVsZeroDetail,
} from "./metrics";
import { isMdhCollapseSignal, isPathCollapsedRow } from "./mdh_collapse";
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

type EvalOut = {
  gross: number | null;
  net: number | null;
  amCost: number;
  nActive: number;
  activation: number | null;
  signalId: string;
};

function mdhFallback(
  bars: BarsByCode,
  holdDays: number,
  oneWay: number,
  familyTag: string,
): EvalOut {
  const fb = evalMultiDayHold(bars, holdDays, oneWay, "fixed_horizon", 1);
  return { ...fb, signalId: `c21_lite_fallback_mdh:${familyTag}` };
}

/** PIT latest fins event with disc_date ≤ asOf. */
function finsAsof(
  events: Array<{
    disc_date?: string;
    eps?: number | null;
    bps?: number | null;
  }>,
  asOf: string,
): { eps: number | null; bps: number | null } | null {
  let best: { eps: number | null; bps: number | null } | null = null;
  let bestD = "";
  for (const ev of events || []) {
    const d = String(ev.disc_date || "").slice(0, 10);
    if (!d || d > asOf) continue;
    if (d >= bestD) {
      bestD = d;
      best = {
        eps:
          ev.eps === null || ev.eps === undefined || !Number.isFinite(ev.eps)
            ? null
            : Number(ev.eps),
        bps:
          ev.bps === null || ev.bps === undefined || !Number.isFinite(ev.bps)
            ? null
            : Number(ev.bps),
      };
    }
  }
  return best;
}

/** Prefer BPS/price else EPS/price (matches class_signals.fundamental_value_score). */
function fundamentalValueScore(
  close: number,
  eps: number | null,
  bps: number | null,
): number | null {
  if (!Number.isFinite(close) || close === 0) return null;
  if (bps !== null && Number.isFinite(bps)) return bps / close;
  if (eps !== null && Number.isFinite(eps)) return eps / close;
  return null;
}

function shortChangeByDate(
  shortByDate: Record<string, number> | null | undefined,
): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  const dates = Object.keys(shortByDate || {}).sort();
  for (let i = 0; i < dates.length; i++) {
    const d = dates[i];
    if (i === 0) {
      out[d] = null;
      continue;
    }
    const prev = (shortByDate as Record<string, number>)[dates[i - 1]];
    const cur = (shortByDate as Record<string, number>)[d];
    out[d] = prev === 0 ? null : (cur - prev) / prev;
  }
  return out;
}

function flowConfirmEntry(
  marginChange: number | null,
  shortChange: number | null,
  mode: string,
): number | null {
  const ms = signFromNumeric(marginChange);
  const ss = signFromNumeric(shortChange);
  const m = String(mode || "off").toLowerCase();
  if (ms === null) return null;
  if (m === "hard") {
    if (ss === null) return null;
    if (ss === 0 || ms === 0) return 0;
    if ((ss > 0) !== (ms > 0)) return null;
    return ms;
  }
  if (m === "soft") {
    if (ss === null) return ms; // gap → margin-only
    if (ss === 0 || ms === 0) return 0;
    // conflict keeps margin (soft)
    return ms;
  }
  // off
  return ms;
}

function fundEntrySign(
  valueScore: number | null,
  momentum: number | null,
  benchmark: number | null,
  mode: string,
): number | null {
  if (valueScore === null) return null;
  const bench = benchmark === null ? 0 : benchmark;
  const vs = signFromNumeric(valueScore - bench);
  const mom = signFromNumeric(momentum);
  const m = String(mode || "value_momentum_agree").toLowerCase();
  if (m === "value_only") return vs;
  // value_momentum_agree
  if (vs === null || mom === null || vs === 0) return vs === null ? null : 0;
  if (mom === 0) return null;
  if ((vs > 0 && mom > 0) || (vs < 0 && mom < 0)) return vs;
  return null;
}

function repoLevelRegime(
  rate: number | null,
  highThr: number,
  lowThr: number,
): string | null {
  if (rate === null || !Number.isFinite(rate)) return null;
  if (rate >= highThr) return "high";
  if (rate <= lowThr) return "low";
  return "mid";
}

/**
 * W94: flow_margin_* using staged flow_regime (margin change ± short confirm).
 * Falls back to disclosed MDH when margin map empty.
 */
function evalFlowDemand(
  bars: BarsByCode,
  flow: PeriodPanel["flow_regime"],
  shortConfirmMode: string,
  holdDays: number,
  oneWay: number,
): EvalOut {
  const h = Math.max(1, Math.floor(holdDays));
  const amCost = amortizedOneWayCost(oneWay, h);
  const mode = String(shortConfirmMode || "off").toLowerCase();
  const changeByCode = (flow && flow.margin_change_by_code) || null;
  const levelByCode = (flow && flow.margin_level_by_code) || null;
  const nCodesWithMargin = changeByCode
    ? Object.keys(changeByCode).length
    : levelByCode
      ? Object.keys(levelByCode).length
      : 0;
  if (!flow || nCodesWithMargin === 0) {
    return mdhFallback(bars, h, oneWay, "flow_demand");
  }
  const shortChg = shortChangeByDate(flow.short_ratio_by_date || null);
  const shortDates = Object.keys(shortChg).sort();
  const signed: number[] = [];
  let nActive = 0;
  let nCodeDays = 0;

  for (const code of Object.keys(bars).sort()) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    if (!pairs || pairs.length < h + 2) continue;
    let chgMap = (changeByCode && changeByCode[code]) || null;
    if (!chgMap && levelByCode && levelByCode[code]) {
      // derive change from levels if only levels staged
      const levelDates = Object.keys(levelByCode[code]).sort();
      const derived: Record<string, number> = {};
      for (let i = 1; i < levelDates.length; i++) {
        const d0 = levelDates[i - 1];
        const d1 = levelDates[i];
        const v0 = levelByCode[code][d0];
        const v1 = levelByCode[code][d1];
        if (v0 !== 0) derived[d1] = v1 / v0 - 1;
      }
      chgMap = derived;
    }
    if (!chgMap || Object.keys(chgMap).length === 0) continue;

    let lastShort: number | null = null;
    const entrySigns: Array<number | null> = [];
    for (const [d] of pairs) {
      // last short change ≤ d
      if (shortDates.length) {
        const earlier = shortDates.filter((x) => x <= d);
        if (earlier.length) {
          const last = earlier[earlier.length - 1];
          const sc = shortChg[last];
          if (sc !== null && sc !== undefined) lastShort = sc;
        }
      }
      if (Object.prototype.hasOwnProperty.call(chgMap, d)) {
        entrySigns.push(flowConfirmEntry(chgMap[d], lastShort, mode));
      } else {
        entrySigns.push(null); // between margin prints
      }
    }
    const held = applyStickyHold(entrySigns, h, "min_hold");
    const closes = pairs.map(([, c]) => c);
    for (let i = 0; i < held.length; i++) {
      nCodeDays += 1;
      const pos = held[i];
      if (pos === null || pos === 0) continue;
      // Score on fresh margin entry days (matches local factory).
      if (entrySigns[i] === null || entrySigns[i] === 0) continue;
      const fwd = multiDayForwardReturn(closes, h, i);
      if (fwd === null) continue;
      nActive += 1;
      signed.push(pos * fwd);
    }
  }
  const gross = signed.length ? sampleMean(signed) : null;
  const net = gross !== null ? gross - amCost : null;
  const modeTag = mode === "hard" ? "hard" : mode === "soft" ? "soft" : "off";
  return {
    gross,
    net,
    amCost,
    nActive,
    activation: nCodeDays > 0 ? nActive / nCodeDays : null,
    signalId: `c21_flow_demand_${modeTag}`,
  };
}

/**
 * W94: fund_value_* using staged fund_regime events + bars.
 * Falls back to disclosed MDH when events empty.
 */
function evalFundPrice(
  bars: BarsByCode,
  fund: PeriodPanel["fund_regime"],
  mode: string,
  momentumN: number,
  holdDays: number,
  oneWay: number,
): EvalOut {
  const h = Math.max(1, Math.floor(holdDays));
  const n = Math.max(1, Math.floor(momentumN));
  const amCost = amortizedOneWayCost(oneWay, h);
  const events = (fund && fund.events_by_code) || null;
  if (!fund || !events || Object.keys(events).length === 0) {
    return mdhFallback(bars, h, oneWay, "fundamentals_price");
  }

  // Pass 1: value scores + global median benchmark.
  const valueByCodeDate: Record<string, Record<string, number | null>> = {};
  const allScores: number[] = [];
  for (const code of Object.keys(bars)) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    const evs = events[code] || [];
    valueByCodeDate[code] = {};
    for (const [d, close] of pairs) {
      const fin = finsAsof(evs, d);
      if (!fin) {
        valueByCodeDate[code][d] = null;
        continue;
      }
      const score = fundamentalValueScore(close, fin.eps, fin.bps);
      valueByCodeDate[code][d] = score;
      if (score !== null) allScores.push(score);
    }
  }
  let median: number | null = null;
  if (allScores.length) {
    const ss = [...allScores].sort((a, b) => a - b);
    median = ss[Math.floor(ss.length / 2)];
  }

  const signed: number[] = [];
  let nActive = 0;
  let nCodeDays = 0;
  const m = String(mode || "value_momentum_agree").toLowerCase();

  for (const code of Object.keys(bars).sort()) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    if (!pairs || pairs.length < Math.max(h, n) + 2) continue;
    const moms = momentumSeries(pairs, n);
    const momByDate: Record<string, number | null> = {};
    for (const [d, mom] of moms) momByDate[d] = mom;
    const entries: Array<number | null> = [];
    for (const [d] of pairs) {
      entries.push(
        fundEntrySign(valueByCodeDate[code]?.[d] ?? null, momByDate[d] ?? null, median, m),
      );
    }
    const held = applyStickyHold(entries, h, "fixed_horizon");
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
  return {
    gross,
    net,
    amCost,
    nActive,
    activation: nCodeDays > 0 ? nActive / nCodeDays : null,
    signalId:
      m === "value_only" ? "c21_fund_value_only" : "c21_fund_value_mom_agree",
  };
}

/**
 * W94: mf_value_mom_rate — value×mom agree + funding-level alignment.
 */
function evalMfValueMomRate(
  bars: BarsByCode,
  fund: PeriodPanel["fund_regime"],
  ratesByDate: Record<string, number>,
  momentumN: number,
  holdDays: number,
  oneWay: number,
  highThr: number,
  lowThr: number,
): EvalOut {
  const h = Math.max(1, Math.floor(holdDays));
  const n = Math.max(1, Math.floor(momentumN));
  const amCost = amortizedOneWayCost(oneWay, h);
  const events = (fund && fund.events_by_code) || null;
  const rateDates = Object.keys(ratesByDate).sort();
  if (!fund || !events || Object.keys(events).length === 0 || rateDates.length < 1) {
    return mdhFallback(bars, h, oneWay, "multi_factor");
  }

  const valueByCodeDate: Record<string, Record<string, number | null>> = {};
  const allScores: number[] = [];
  for (const code of Object.keys(bars)) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    const evs = events[code] || [];
    valueByCodeDate[code] = {};
    for (const [d, close] of pairs) {
      const fin = finsAsof(evs, d);
      if (!fin) {
        valueByCodeDate[code][d] = null;
        continue;
      }
      const score = fundamentalValueScore(close, fin.eps, fin.bps);
      valueByCodeDate[code][d] = score;
      if (score !== null) allScores.push(score);
    }
  }
  let median: number | null = null;
  if (allScores.length) {
    const ss = [...allScores].sort((a, b) => a - b);
    median = ss[Math.floor(ss.length / 2)];
  }

  const signed: number[] = [];
  let nActive = 0;
  let nCodeDays = 0;

  for (const code of Object.keys(bars).sort()) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    if (!pairs || pairs.length < Math.max(h, n) + 2) continue;
    const moms = momentumSeries(pairs, n);
    const momByDate: Record<string, number | null> = {};
    for (const [d, mom] of moms) momByDate[d] = mom;
    const entries: Array<number | null> = [];
    for (const [d] of pairs) {
      const base = fundEntrySign(
        valueByCodeDate[code]?.[d] ?? null,
        momByDate[d] ?? null,
        median,
        "value_momentum_agree",
      );
      let rate: number | null = null;
      if (ratesByDate[d] !== undefined) rate = ratesByDate[d];
      else {
        const earlier = rateDates.filter((x) => x <= d);
        if (earlier.length) rate = ratesByDate[earlier[earlier.length - 1]];
      }
      const regime = repoLevelRegime(rate, highThr, lowThr);
      if (base === null) {
        entries.push(null);
      } else if (base === 0) {
        entries.push(0);
      } else if (regime === null) {
        entries.push(null);
      } else if (base > 0 && (regime === "low" || regime === "mid")) {
        entries.push(base);
      } else if (base < 0 && (regime === "high" || regime === "mid")) {
        entries.push(base);
      } else {
        entries.push(null);
      }
    }
    const held = applyStickyHold(entries, h, "fixed_horizon");
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
  return {
    gross,
    net,
    amCost,
    nActive,
    activation: nCodeDays > 0 ? nActive / nCodeDays : null,
    signalId: "c21_mf_value_mom_rate",
  };
}

/**
 * W94: mf_flow_price — margin flow × price mom agree.
 */
function evalMfFlowPrice(
  bars: BarsByCode,
  flow: PeriodPanel["flow_regime"],
  momentumN: number,
  holdDays: number,
  oneWay: number,
): EvalOut {
  const h = Math.max(1, Math.floor(holdDays));
  const n = Math.max(1, Math.floor(momentumN));
  const amCost = amortizedOneWayCost(oneWay, h);
  const changeByCode = (flow && flow.margin_change_by_code) || null;
  const levelByCode = (flow && flow.margin_level_by_code) || null;
  const nCodesWithMargin = changeByCode
    ? Object.keys(changeByCode).length
    : levelByCode
      ? Object.keys(levelByCode).length
      : 0;
  if (!flow || nCodesWithMargin === 0) {
    return mdhFallback(bars, h, oneWay, "multi_factor");
  }

  const signed: number[] = [];
  let nActive = 0;
  let nCodeDays = 0;

  for (const code of Object.keys(bars).sort()) {
    if (String(code).startsWith("__")) continue;
    const pairs = bars[code];
    if (!pairs || pairs.length < Math.max(h, n) + 2) continue;
    let chgMap = (changeByCode && changeByCode[code]) || null;
    if (!chgMap && levelByCode && levelByCode[code]) {
      const levelDates = Object.keys(levelByCode[code]).sort();
      const derived: Record<string, number> = {};
      for (let i = 1; i < levelDates.length; i++) {
        const d0 = levelDates[i - 1];
        const d1 = levelDates[i];
        const v0 = levelByCode[code][d0];
        const v1 = levelByCode[code][d1];
        if (v0 !== 0) derived[d1] = v1 / v0 - 1;
      }
      chgMap = derived;
    }
    if (!chgMap || Object.keys(chgMap).length === 0) continue;

    const moms = momentumSeries(pairs, n);
    const momByDate: Record<string, number | null> = {};
    for (const [d, mom] of moms) momByDate[d] = mom;
    const entrySigns: Array<number | null> = [];
    for (const [d] of pairs) {
      if (Object.prototype.hasOwnProperty.call(chgMap, d)) {
        const fs = signFromNumeric(chgMap[d]);
        const ms = signFromNumeric(momByDate[d] ?? null);
        if (fs === null) entrySigns.push(null);
        else if (ms === null || ms === 0) entrySigns.push(null);
        else if (fs === 0) entrySigns.push(0);
        else if ((fs > 0 && ms > 0) || (fs < 0 && ms < 0)) entrySigns.push(fs);
        else entrySigns.push(null);
      } else {
        entrySigns.push(null);
      }
    }
    const held = applyStickyHold(entrySigns, h, "min_hold");
    const closes = pairs.map(([, c]) => c);
    for (let i = 0; i < held.length; i++) {
      nCodeDays += 1;
      const pos = held[i];
      if (pos === null || pos === 0) continue;
      if (entrySigns[i] === null || entrySigns[i] === 0) continue;
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
    signalId: "c21_mf_flow_price",
  };
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
        if (mode.includes("spread_change") || seriesKind === "spread_change")
          series = bundle.spread_change;
        else if (mode.includes("spread") || seriesKind === "spread")
          series = bundle.spread;
        else if (mode.includes("skew") || seriesKind === "skew")
          series = bundle.skew;
        else if (mode.includes("cm_term") || seriesKind === "cm_term")
          series = bundle.cm_term;
        else if (
          mode.includes("basevol_delta") ||
          seriesKind === "basevol_delta"
        )
          series = bundle.basevol_delta;
        else if (mode.includes("atm_iv") || seriesKind === "atm_iv")
          series = bundle.atm_iv;
        else series = bundle.basevol;
      }
      // Fallback: build abs map from top-level by-date series on the panel.
      if (!series) {
        const absMap =
          seriesKind === "skew" || mode.includes("skew")
            ? panel.skew_series
            : seriesKind === "cm_term" || mode.includes("cm_term")
              ? panel.cm_term_series
              : seriesKind === "basevol_delta" || mode.includes("basevol_delta")
                ? panel.basevol_delta_series
                : mode.includes("spread")
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
      const defaultHigh =
        seriesKind === "skew" || mode.includes("skew")
          ? 3.0
          : seriesKind === "cm_term" || mode.includes("cm_term")
            ? 2.0
            : seriesKind === "basevol_delta" || mode.includes("basevol_delta")
              ? 1.0
              : mode.includes("spread")
                ? 1.0
                : 24.0;
      const defaultLow =
        seriesKind === "skew" || mode.includes("skew")
          ? 0.5
          : seriesKind === "cm_term" || mode.includes("cm_term")
            ? -1.0
            : seriesKind === "basevol_delta" || mode.includes("basevol_delta")
              ? -1.0
              : mode.includes("spread")
                ? -0.5
                : 12.0;
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
    } else if (
      family === "flow_demand" ||
      lid.startsWith("flow_margin_")
    ) {
      holdDays = Math.floor(numParam(params, "hold_days", 10));
      let mode = strParam(params, "short_confirm_mode", "off");
      if (lid.includes("short_hard")) mode = "hard";
      else if (lid.includes("short_soft")) mode = "soft";
      else if (lid.includes("pressure")) mode = "off";
      if (params.require_short_confirm === true && mode === "off") mode = "hard";
      out = evalFlowDemand(
        panel.bars,
        panel.flow_regime || null,
        mode,
        holdDays,
        oneWay,
      );
    } else if (
      family === "fundamentals_price" ||
      lid.startsWith("fund_")
    ) {
      holdDays = Math.floor(numParam(params, "hold_days", 10));
      const mode = strParam(
        params,
        "mode",
        lid.includes("value_only") ? "value_only" : "value_momentum_agree",
      );
      out = evalFundPrice(
        panel.bars,
        panel.fund_regime || null,
        mode,
        numParam(params, "momentum_n", 10),
        holdDays,
        oneWay,
      );
    } else if (
      family === "multi_factor" ||
      lid.startsWith("mf_")
    ) {
      holdDays = Math.floor(numParam(params, "hold_days", 10));
      if (lid.includes("flow") || strParam(params, "mode", "") === "flow_price") {
        out = evalMfFlowPrice(
          panel.bars,
          panel.flow_regime || null,
          numParam(params, "momentum_n", 10),
          holdDays,
          oneWay,
        );
      } else {
        // default / value_mom_rate
        out = evalMfValueMomRate(
          panel.bars,
          panel.fund_regime || null,
          repoRatesFromPanel(panel),
          numParam(params, "momentum_n", 10),
          holdDays,
          oneWay,
          numParam(params, "high_threshold", 0.05),
          numParam(params, "low_threshold", 0.0),
        );
      }
    } else {
      // multi_day_hold + generic fallback for remaining families
      holdDays = Math.floor(
        numParam(params, "hold_days", numParam(params, "post_hold_days", 5)),
      );
      const polarity = Math.floor(numParam(params, "signal_polarity", 1));
      const rebalance = strParam(params, "rebalance_mode", "fixed_horizon");
      out = evalMultiDayHold(panel.bars, holdDays, oneWay, rebalance, polarity);
      // tag fallback families honestly (never silent MDH)
      if (
        family !== "multi_day_hold" &&
        !lid.includes("multi_day") &&
        !lid.startsWith("mdh_") &&
        family !== "vol_risk_adjusted" &&
        family !== "index_vol_regime" &&
        family !== "options_vol_regime" &&
        family !== "macro_conditioned" &&
        family !== "flow_demand" &&
        family !== "fundamentals_price" &&
        family !== "multi_factor" &&
        !lid.startsWith("opt225_") &&
        !lid.startsWith("nky_vol_") &&
        !lid.startsWith("macro_repo_rate_") &&
        !lid.startsWith("flow_margin_") &&
        !lid.startsWith("fund_") &&
        !lid.startsWith("mf_")
      ) {
        out = {
          ...out,
          signalId: `c21_lite_fallback_mdh:${family}`,
        };
      }
    }

    const collapsed = isMdhCollapseSignal(out.signalId);
    return {
      period_id: pid,
      year: panel.year,
      status: collapsed ? "path_collapsed" : "ok",
      gross_signed_mean_active: collapsed ? null : out.gross,
      net_one_way_mean_active: collapsed ? null : out.net,
      amortized_one_way_cost: out.amCost,
      n_active_positions: out.nActive,
      activation_rate: collapsed ? null : out.activation,
      hold_days: holdDays,
      signal_id: out.signalId,
      path_collapsed: collapsed,
      skip_reason: collapsed ? "unique_unsupported_on_period_net" : undefined,
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

/** Daily held book for bar-native families (not generic CS/MDH collapse). */
export type HeldBook = Record<string, Record<string, number>>;

function stickyToHeld(
  bars: BarsByCode,
  entriesByCode: Record<string, Array<number | null>>,
  holdDays: number,
  rebalance: string,
): HeldBook {
  const held: HeldBook = {};
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__") || !pairs) continue;
    const entries = entriesByCode[code];
    if (!entries) continue;
    const sticky = applyStickyHold(entries, holdDays, rebalance);
    held[code] = {};
    for (let i = 0; i < pairs.length; i++) {
      const pos = sticky[i];
      if (pos !== null && pos !== 0) held[code][pairs[i][0]] = pos;
    }
  }
  return held;
}

function realizedVol(pairs: BarSeries, endI: number, n: number): number | null {
  if (endI < n || n < 2) return null;
  const rets: number[] = [];
  for (let i = endI - n + 1; i <= endI; i++) {
    const c0 = pairs[i - 1]?.[1];
    const c1 = pairs[i]?.[1];
    if (!Number.isFinite(c0) || !Number.isFinite(c1) || c0 === 0) continue;
    rets.push(c1 / c0 - 1);
  }
  if (rets.length < 3) return null;
  const m = rets.reduce((a, b) => a + b, 0) / rets.length;
  let acc = 0;
  for (const r of rets) acc += (r - m) ** 2;
  const s = Math.sqrt(acc / (rets.length - 1));
  return Number.isFinite(s) && s > 0 ? s : null;
}

/**
 * Candidate-grade daily positions for bar-native logics.
 * Returns null when the caller should use eventHeld / gatedCsHeld.
 */
export function barNativeHeldBook(
  logic: LogicSpec,
  panel: PeriodPanel,
): { held: HeldBook; path: string; fallback?: string } | null {
  const lid = String(logic.logic_id || "");
  const fam = String(logic.family_id || "");
  const params = logic.params || {};
  if (
    lid.startsWith("event_") ||
    lid.startsWith("surprise_xs_") ||
    lid.startsWith("afterclose_") ||
    lid.startsWith("large_surprise_") ||
    lid.startsWith("disclosure_") ||
    lid.startsWith("curve_steep_event") ||
    fam.includes("event") ||
    fam.includes("surprise_xs")
  ) {
    return null;
  }
  const bars = panel.bars || {};
  const holdDays = Math.floor(numParam(params, "hold_days", numParam(params, "post_hold_days", 10)));
  const momN = Math.floor(numParam(params, "momentum_n", 5));
  const lf = numParam(params, "long_frac", 0.3);
  const sf = numParam(params, "short_frac", 0.3);

  if (lid.startsWith("nky_vol_") || fam === "index_vol_regime") {
    const nky = panel.nky_vol_series || null;
    if (!nky) return { held: {}, path: "nky_vol_missing", fallback: "path_broken_missing_sidecar" };
    const mode = strParam(params, "mode", lid);
    const highThr = numParam(params, "high_threshold", 0.2);
    const lowThr = numParam(params, "low_threshold", 0.1);
    const expandRatio = numParam(params, "expand_ratio", 1.2);
    const compressRatio = numParam(params, "compress_ratio", 0.8);
    const absBy = nky.rv_abs_by_date || nky.rv_short_by_date || {};
    const shortBy = nky.rv_short_by_date || {};
    const longBy = nky.rv_long_by_date || {};
    const byDate: Record<string, Record<string, number | null>> = {};
    const datesByCode: Record<string, string[]> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      const moms = momentumSeries(pairs, momN);
      datesByCode[code] = pairs.map(([d]) => d);
      for (const [d, mom] of moms) {
        if (!byDate[d]) byDate[d] = {};
        byDate[d][code] = mom;
      }
    }
    const m = mode.toLowerCase();
    function regimeFor(d: string): string | null {
      const dk = d.slice(0, 10);
      if (m.includes("term_ratio")) {
        const s = shortBy[dk];
        const lo = longBy[dk];
        if (s === undefined || lo === undefined || !(lo > 1e-12)) return null;
        const ratio = s / lo;
        if (ratio >= expandRatio) return "expanding";
        if (ratio <= compressRatio) return "compressing";
        return "mid";
      }
      if (m.includes("term_levels")) {
        const s = shortBy[dk];
        const lo = longBy[dk];
        if (s === undefined || lo === undefined) return null;
        const sLab = s >= highThr ? "high" : s <= lowThr ? "low" : "mid";
        const lLab = lo >= highThr ? "high" : lo <= lowThr ? "low" : "mid";
        if (sLab === "high" && lLab === "high") return "high";
        if (sLab === "low" && lLab === "low") return "low";
        return "mid";
      }
      const v = absBy[dk];
      if (v === undefined) return null;
      if (v >= highThr) return "high";
      if (v <= lowThr) return "low";
      return "mid";
    }
    const entriesByCode: Record<string, Array<number | null>> = {};
    for (const code of Object.keys(datesByCode)) {
      const dlist = datesByCode[code];
      entriesByCode[code] = dlist.map((d) => {
        const ranks = crossSectionRankSigns(byDate[d] || {}, lf, sf);
        const cs = ranks[code] ?? 0;
        const reg = regimeFor(d);
        if (cs === 0) return 0;
        if (reg === null) return null;
        if (m.includes("term_ratio")) {
          if (reg === "compressing") return cs;
          if (reg === "expanding") return -cs;
          return null;
        }
        if (reg === "low") return cs;
        if (reg === "high") return -cs;
        return null;
      });
    }
    return {
      held: stickyToHeld(bars, entriesByCode, holdDays, "fixed_horizon"),
      path: `nky_vol:${m}`,
    };
  }

  if (lid.startsWith("opt225_") || fam === "options_vol_regime") {
    const mode = strParam(params, "mode", lid);
    const sk = strParam(params, "series_kind", "");
    const bundle = panel.opt225_regime || null;
    let absMap: Record<string, number> | null = null;
    if (mode.includes("skew") || sk === "skew") {
      absMap = panel.skew_series || bundle?.skew?.rv_abs_by_date || null;
    } else if (mode.includes("cm_term") || sk === "cm_term") {
      absMap = panel.cm_term_series || bundle?.cm_term?.rv_abs_by_date || null;
    } else if (mode.includes("spread") || sk === "spread" || sk === "spread_change") {
      absMap = panel.iv_base_spread || bundle?.spread?.rv_abs_by_date || null;
    } else if (mode.includes("atm_iv") || sk === "atm_iv") {
      absMap = panel.atm_iv_series || bundle?.atm_iv?.rv_abs_by_date || null;
    } else if (mode.includes("basevol_delta") || sk === "basevol_delta") {
      absMap = panel.basevol_delta_series || bundle?.basevol_delta?.rv_abs_by_date || null;
    } else {
      absMap = panel.base_vol_series || bundle?.basevol?.rv_abs_by_date || null;
    }
    const wantChange = mode.includes("change") || sk === "spread_change";
    if (wantChange && absMap) {
      const ds = Object.keys(absMap).sort();
      const chg: Record<string, number> = {};
      for (let i = 1; i < ds.length; i++) {
        chg[ds[i]] = absMap[ds[i]] - absMap[ds[i - 1]];
      }
      absMap = chg;
    }
    const nkyLike: NkyVolSeries | null = absMap
      ? { rv_abs_by_date: absMap, rv_short_by_date: absMap, rv_long_by_date: absMap }
      : panel.nky_vol_series || null;
    const hiDefault = wantChange
      ? 0.5
      : mode.includes("skew") || sk === "skew"
        ? 3
        : mode.includes("spread") || sk === "spread"
          ? 1
          : 24;
    const loDefault = wantChange
      ? -0.5
      : mode.includes("skew") || sk === "skew"
        ? 0.5
        : mode.includes("spread") || sk === "spread"
          ? -0.5
          : 12;
    const inner = barNativeHeldBook(
      {
        ...logic,
        logic_id: mode.includes("term_ratio")
          ? "nky_vol_term_ratio"
          : mode.includes("term_levels")
            ? "nky_vol_term_levels"
            : "nky_vol_abs_level",
        family_id: "index_vol_regime",
        params: {
          ...params,
          high_threshold: numParam(params, "high_threshold", hiDefault),
          low_threshold: numParam(params, "low_threshold", loDefault),
        },
      },
      { ...panel, nky_vol_series: nkyLike },
    );
    if (!inner) return { held: {}, path: "opt225_unmapped", fallback: "path_broken" };
    return { held: inner.held, path: `opt225:${mode}` };
  }

  if (lid.startsWith("flow_margin_") || fam === "flow_demand") {
    const flow = panel.flow_regime || null;
    const changeByCode = flow?.margin_change_by_code || null;
    const levelByCode = flow?.margin_level_by_code || null;
    const nCodes = Object.keys(changeByCode || levelByCode || {}).length;
    if (!flow || nCodes === 0) {
      return {
        held: {},
        path: "flow_demand",
        fallback: "path_broken_missing_sidecar",
      };
    }
    let mode = strParam(params, "short_confirm_mode", "off");
    if (lid.includes("short_hard")) mode = "hard";
    else if (lid.includes("short_soft")) mode = "soft";
    else if (lid.includes("pressure")) mode = "off";
    const shortChg = shortChangeByDate(flow.short_ratio_by_date || undefined);
    const entriesByCode: Record<string, Array<number | null>> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      let chgMap = (changeByCode && changeByCode[code]) || null;
      if (!chgMap && levelByCode && levelByCode[code]) {
        const levelDates = Object.keys(levelByCode[code]).sort();
        const derived: Record<string, number> = {};
        for (let i = 1; i < levelDates.length; i++) {
          const v0 = levelByCode[code][levelDates[i - 1]];
          const v1 = levelByCode[code][levelDates[i]];
          if (v0 !== 0) derived[levelDates[i]] = v1 / v0 - 1;
        }
        chgMap = derived;
      }
      if (!chgMap) continue;
      entriesByCode[code] = pairs.map(([d]) =>
        Object.prototype.hasOwnProperty.call(chgMap, d)
          ? flowConfirmEntry(chgMap[d], shortChg[d] ?? null, mode)
          : null,
      );
    }
    return {
      held: stickyToHeld(bars, entriesByCode, holdDays, "min_hold"),
      path: `flow_demand:${mode}`,
    };
  }

  if (lid.startsWith("fund_") || fam === "fundamentals_price") {
    const events = panel.fund_regime?.events_by_code || null;
    if (!events || !Object.keys(events).length) {
      return {
        held: {},
        path: "fundamentals_price",
        fallback: "path_broken_missing_sidecar",
      };
    }
    const mode = strParam(params, "mode", lid.includes("value_only") ? "value_only" : "value_momentum_agree");
    const allScores: number[] = [];
    const valueBy: Record<string, Record<string, number | null>> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      valueBy[code] = {};
      for (const [d, close] of pairs) {
        const fin = finsAsof(events[code] || [], d);
        const score = fin ? fundamentalValueScore(close, fin.eps, fin.bps) : null;
        valueBy[code][d] = score;
        if (score !== null) allScores.push(score);
      }
    }
    const median = allScores.length ? [...allScores].sort((a, b) => a - b)[Math.floor(allScores.length / 2)] : null;
    const entriesByCode: Record<string, Array<number | null>> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      const moms = momentumSeries(pairs, momN);
      const momBy: Record<string, number | null> = {};
      for (const [d, m] of moms) momBy[d] = m;
      entriesByCode[code] = pairs.map(([d]) =>
        fundEntrySign(valueBy[code]?.[d] ?? null, momBy[d] ?? null, median, mode),
      );
    }
    return {
      held: stickyToHeld(bars, entriesByCode, holdDays, "fixed_horizon"),
      path: `fund:${mode}`,
    };
  }

  if (lid.startsWith("macro_repo_rate_") || fam === "macro_conditioned") {
    const rates = repoRatesFromPanel(panel);
    const mode = strParam(params, "mode", lid.includes("level") ? "rate_level" : "rate_change");
    if (Object.keys(rates).length < 2) {
      return {
        held: {},
        path: "macro_conditioned",
        fallback: "path_broken_missing_sidecar",
      };
    }
    const highThr = numParam(params, "high_threshold", 0.05);
    const lowThr = numParam(params, "low_threshold", 0.0);
    const rateDates = Object.keys(rates).sort();
    const prevMap: Record<string, number | null> = {};
    for (let i = 0; i < rateDates.length; i++) prevMap[rateDates[i]] = i > 0 ? rates[rateDates[i - 1]] : null;
    const entriesByCode: Record<string, Array<number | null>> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      const moms = momentumSeries(pairs, momN);
      entriesByCode[code] = moms.map(([d, m]) => {
        let rate = rates[d];
        let prev = prevMap[d] ?? null;
        if (rate === undefined) {
          const earlier = rateDates.filter((x) => x <= d);
          if (!earlier.length) return null;
          const last = earlier[earlier.length - 1];
          rate = rates[last];
          prev = prevMap[last] ?? null;
        }
        const regime = repoRegimeLabel(rate, prev, mode, highThr, lowThr, 1e-6);
        return conditionMomOnRepoRegime(signFromNumeric(m), regime, mode);
      });
    }
    return {
      held: stickyToHeld(bars, entriesByCode, holdDays, "fixed_horizon"),
      path: `macro:${mode}`,
    };
  }

  if (lid.startsWith("mf_") || fam === "multi_factor") {
    if (lid.includes("flow")) {
      const inner = barNativeHeldBook({ ...logic, logic_id: "flow_margin_pressure", family_id: "flow_demand" }, panel);
      return inner ? { held: inner.held, path: "mf_flow_price" } : { held: {}, path: "mf_flow_price", fallback: "empty" };
    }
    // Unique rate-gated value×mom (not an alias of fund_value_mom_agree).
    const events = panel.fund_regime?.events_by_code || null;
    const rates = repoRatesFromPanel(panel);
    if (!events || !Object.keys(events).length) {
      return {
        held: {},
        path: "mf_value_mom_rate",
        fallback: "path_broken_missing_sidecar",
      };
    }
    const highThr = numParam(params, "high_threshold", 0.05);
    const lowThr = numParam(params, "low_threshold", 0.0);
    const rateDates = Object.keys(rates).sort();
    const allScores: number[] = [];
    const valueBy: Record<string, Record<string, number | null>> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      valueBy[code] = {};
      for (const [d, close] of pairs) {
        const fin = finsAsof(events[code] || [], d);
        const score = fin ? fundamentalValueScore(close, fin.eps, fin.bps) : null;
        valueBy[code][d] = score;
        if (score !== null) allScores.push(score);
      }
    }
    const median = allScores.length
      ? [...allScores].sort((a, b) => a - b)[Math.floor(allScores.length / 2)]
      : null;
    const entriesByCode: Record<string, Array<number | null>> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      const moms = momentumSeries(pairs, momN);
      const momBy: Record<string, number | null> = {};
      for (const [d, m] of moms) momBy[d] = m;
      entriesByCode[code] = pairs.map(([d]) => {
        const base = fundEntrySign(
          valueBy[code]?.[d] ?? null,
          momBy[d] ?? null,
          median,
          "value_momentum_agree",
        );
        let rate: number | null = null;
        if (rates[d] !== undefined) rate = rates[d];
        else {
          const earlier = rateDates.filter((x) => x <= d);
          if (earlier.length) rate = rates[earlier[earlier.length - 1]];
        }
        const regime = repoLevelRegime(rate, highThr, lowThr);
        if (base === null) return null;
        if (base === 0) return 0;
        if (regime === null || rate === null) return null;
        let prevRate: number | null = null;
        const earlier = rateDates.filter((x) => x < d);
        if (earlier.length) prevRate = rates[earlier[earlier.length - 1]];
        if (prevRate === null) return null;
        // Skip mid AND require overnight change: otherwise occupancy stays always_on.
        if (base > 0 && regime === "low" && rate < prevRate) return base;
        if (base < 0 && regime === "high" && rate > prevRate) return base;
        return null;
      });
    }
    return {
      held: stickyToHeld(bars, entriesByCode, holdDays, "fixed_horizon"),
      path: "mf_value_mom_rate",
    };
  }

  if (lid === "vol_risk_adjusted_mom" || lid === "vol_breakout_expand" || fam === "vol_risk_adjusted") {
    const volN = Math.floor(numParam(params, "vol_n", 10));
    const thr = numParam(params, "vol_threshold", 1.0);
    const expand = lid.includes("breakout") || strParam(params, "gate_mode", "") === "vol_expand";
    const entriesByCode: Record<string, Array<number | null>> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      entriesByCode[code] = pairs.map((_, i) => {
        const mom = i >= momN && pairs[i - momN][1] !== 0 ? (pairs[i][1] - pairs[i - momN][1]) / pairs[i - momN][1] : null;
        if (mom === null || mom === 0) return mom === 0 ? 0 : null;
        const sgn = mom > 0 ? 1 : -1;
        if (expand) {
          const rec = realizedVol(pairs, i, volN);
          const pri = realizedVol(pairs, i - volN, volN);
          if (rec === null || pri === null || pri === 0) return null;
          return rec / pri >= thr ? sgn : 0;
        }
        const vol = realizedVol(pairs, i, volN);
        if (vol === null) return null;
        return Math.abs(mom) / vol >= thr ? sgn : 0;
      });
    }
    return {
      held: stickyToHeld(bars, entriesByCode, holdDays, "fixed_horizon"),
      path: expand ? "vol_breakout_expand" : "vol_risk_adjusted_mom",
    };
  }

  if (
    lid === "xs_rank_ls_sticky" ||
    lid === "xs_rank_ls_daily" ||
    (fam.includes("cross_section") &&
      !lid.startsWith("xs_margin") &&
      !lid.startsWith("xs_low_vol") &&
      !lid.startsWith("xs_high_vol"))
  ) {
    const daily = lid.includes("daily") || holdDays <= 1;
    const h = daily ? 1 : holdDays;
    const byDate: Record<string, Record<string, number | null>> = {};
    const datesByCode: Record<string, string[]> = {};
    for (const [code, pairs] of Object.entries(bars)) {
      if (code.startsWith("__") || !pairs) continue;
      datesByCode[code] = pairs.map(([d]) => d);
      const moms = momentumSeries(pairs, momN);
      for (const [d, m] of moms) {
        if (!byDate[d]) byDate[d] = {};
        byDate[d][code] = m;
      }
    }
    const entriesByCode: Record<string, Array<number | null>> = {};
    for (const code of Object.keys(datesByCode)) {
      entriesByCode[code] = datesByCode[code].map((d) => {
        const ranks = crossSectionRankSigns(byDate[d] || {}, lf, sf);
        return ranks[code] ?? 0;
      });
    }
    return {
      held: stickyToHeld(bars, entriesByCode, h, "fixed_horizon"),
      path: daily ? "xs_rank_daily" : "xs_rank_sticky",
    };
  }

  if (lid.startsWith("mdh_") || fam === "multi_day_hold") {
    const pol = lid.includes("reversion") ? -1 : 1;
    return { held: mdhHeldLocal(bars, holdDays, pol), path: pol < 0 ? "mdh_reversion" : "mdh_sticky" };
  }

  return null;
}

function mdhHeldLocal(bars: BarsByCode, holdDays: number, polarity: number): HeldBook {
  const entriesByCode: Record<string, Array<number | null>> = {};
  const n = Math.max(1, holdDays);
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__") || !pairs) continue;
    entriesByCode[code] = pairs.map((_, i) => {
      if (i < n) return null;
      const b = pairs[i - n][1];
      const last = pairs[i][1];
      if (!Number.isFinite(b) || !Number.isFinite(last) || b === 0) return null;
      const m = (last - b) / b;
      if (m > 0) return polarity;
      if (m < 0) return -polarity;
      return 0;
    });
  }
  return stickyToHeld(bars, entriesByCode, holdDays, "fixed_horizon");
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
  const tOrigDetail = tStatVsZeroDetail(nets);
  const tOrig = tOrigDetail.t_stat;
  const sharpeOrig = sharpePeriod(nets);
  const lowVarArtifact =
    tOrigDetail.reason === "low_variance_artifact" ||
    hasPairwiseLowVarianceArtifact(nets);

  const netsInv = invertNets(nets, costs);
  const meanNetInv = sampleMean(netsInv);
  const tInvDetail = tStatVsZeroDetail(netsInv);
  const tInv = tInvDetail.t_stat;
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
  const eventLike =
    family === "event_post" ||
    family.includes("event") ||
    family.includes("surprise") ||
    logicId.startsWith("event_") ||
    logicId.startsWith("surprise_");
  if (
    meanActivation !== null &&
    meanActivation < minAct &&
    !eventLike
  ) {
    rejectReasons.push("low_activation");
  }
  if (chosen === "reject") rejectReasons.push("sign_selection_reject");
  // W95: demote/exclude when full-window or any 2-period subset is an
  // inflated-t low-variance artifact (fund_value_mom_agree_slow 2017 case).
  if (lowVarArtifact) rejectReasons.push("inflated_t_low_variance");
  if (periodRows.some((r) => isPathCollapsedRow(r))) {
    rejectReasons.push("path_collapsed_unique_on_period_net");
  }

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
    t_stat_reason: tOrigDetail.reason,
    raw_t_stat: tOrigDetail.raw_t_stat,
    low_variance_artifact: lowVarArtifact,
    sharpe_period: sharpe,
    sharpe_period_inverted: sharpeInv,
    chosen_sign: chosen,
    mean_activation: meanActivation,
    screen: {
      survived,
      screen_kind: "period_net",
      daily_path_complete: false,
      candidate_grade: false,
      n_survivors_are_not_a_pass: true,
      reject_reasons: rejectReasons,
      mean_net: meanNet,
      t_stat: tStat,
      sharpe_period: sharpe,
      chosen_sign: chosen,
      family_id: family,
      logic_id: logicId,
      strategy_id: sid,
      low_variance_artifact: lowVarArtifact,
      t_stat_reason: tOrigDetail.reason,
      raw_t_stat: tOrigDetail.raw_t_stat,
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
    screen_kind: "period_net",
    daily_path_complete: false,
    candidate_grade: false,
    n_survivors_are_not_a_pass: true,
  }));
}
