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
] as const;

function isEventLogic(lid: string): boolean {
  return (CF_EVENT_LOGIC_IDS as readonly string[]).includes(lid);
}

function surpriseProxy(ev: {
  eps?: number | null;
  feps?: number | null;
}): number | null {
  const e = ev.eps;
  const f = ev.feps;
  if (finite(e) && finite(f)) return (f as number) - (e as number);
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
      if (lid === "event_margin_crowding_skip") {
        const levels =
          panel.flow_regime?.margin_level_by_code?.[code] || {};
        const prior = Object.keys(levels)
          .filter((d) => d < ev.entryDate)
          .sort();
        if (!prior.length) ok = false;
        else {
          const lastD = prior[prior.length - 1];
          const ageDays =
            (Date.parse(ev.entryDate + "T00:00:00Z") -
              Date.parse(lastD + "T00:00:00Z")) /
            86400000;
          const med = pitMedian(levels, ev.entryDate, minHist);
          if (!Number.isFinite(ageDays) || ageDays > 14 || med === null) {
            ok = false;
          } else if ((levels[lastD] as number) >= med) {
            ok = false;
          }
        }
      }
      if (!ok) continue;
      const end = Math.min(ev.entryIdx + holdDays, pack.dlist.length);
      for (let j = ev.entryIdx; j < end; j++) arr[j] = sgn;
      nOn += 1;
    }
    for (let i = 0; i < pack.dlist.length; i++) {
      if (arr[i] !== null) pos[pack.dlist[i]] = arr[i] as number;
    }
    held[code] = pos;
  }

  if (
    lid === "surprise_xs_rank_hold" ||
    lid === "surprise_xs_rank_flip" ||
    lid === "surprise_xs_rank_adaptive" ||
    lid === "disclosure_cluster_mom_gate"
  ) {
    const invert = lid.includes("flip");
    const cs = csHeld(
      panel.bars,
      5,
      10,
      0.3,
      0.3,
      invert,
    );
    if (lid === "disclosure_cluster_mom_gate") {
      const dates = unionDates(panel.bars);
      const gated: Record<string, Record<string, number>> = {};
      for (const [code, cmap] of Object.entries(cs)) {
        gated[code] = {};
        for (const [d, v] of Object.entries(cmap)) {
          const nDisc = discDates.filter((x) => x < d && x >= addDays(d, -clusterLookback)).length;
          const med = pitMedian(
            Object.fromEntries(dates.map((dd) => [dd, discDates.filter((x) => x < dd && x >= addDays(dd, -clusterLookback)).length])),
            d,
            10,
          );
          if (med === null || nDisc < med) continue;
          gated[code][d] = v;
        }
      }
      return gated;
    }
    return cs;
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
