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
    for (const [code, cmap] of Object.entries(held)) {
      const pos = cmap[prev];
      if (!pos) continue;
      const c0 = closeBy[code]?.[prev];
      const c1 = closeBy[code]?.[d];
      if (!finite(c0) || !finite(c1) || c0 === 0) continue;
      contribs.push(pos * (c1 / c0 - 1));
    }
    let net = 0;
    if (contribs.length) {
      const g = contribs.reduce((a, b) => a + b, 0) / contribs.length;
      net = g - dailyCost;
      nOn += 1;
    }
    netDaily.push(net);
  }
  const occ = dates.length > 1 ? nOn / (dates.length - 1) : null;
  return { dates, net_daily: netDaily, occupancy: occ, n_gate_on: nOn };
}

function usesCrossSection(logic: LogicSpec): boolean {
  const lid = String(logic.logic_id || "");
  const fam = String(logic.family_id || "");
  return (
    lid.startsWith("xs_") ||
    lid.includes("cross_section") ||
    fam.includes("cross_section") ||
    lid.startsWith("nky_vol_") ||
    lid.startsWith("opt225_") ||
    lid.startsWith("fund_") ||
    lid.startsWith("mf_")
  );
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
    finite(params.hold_days as number) ? (params.hold_days as number) : 10,
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
  const held = usesCrossSection(logic)
    ? csHeld(panel.bars, momN, holdDays, lf, sf, invert)
    : mdhHeld(panel.bars, holdDays, polarity);
  const dates = unionDates(panel.bars);
  const pack = heldBookDailyMtm(
    held,
    closeByMap(panel.bars),
    dates,
    holdDays,
    oneWay,
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
