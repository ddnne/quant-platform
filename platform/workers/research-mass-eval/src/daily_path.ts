import { barNativeHeldBook } from "./eval";
import { sharpePeriod, tStatVsZero } from "./metrics";
import { isPathBroken } from "./path_broken";
import { afterClose, pitEventEntryShift } from "./event_entry";
import type { BarsByCode, LogicSpec, PeriodPanel } from "./types";
import {
  CF_EVENT_LOGIC_IDS,
  CF_NEW_CS_THESIS_IDS,
  CF_NEW_EVENT_THESIS_IDS,
  CF_UNIQUE_CS_LOGIC_IDS,
} from "./catalog_ids";
import {
  clusterWindowSeries,
  comboCsGateOk,
  comboEventGateOk,
  comboGatesImplemented,
  comboGatesOf,
  lastPriorFundNum,
  matchingFundNum,
} from "./combo_gates";
export {
  CF_EVENT_LOGIC_IDS,
  CF_NEW_CS_THESIS_IDS,
  CF_NEW_EVENT_THESIS_IDS,
  CF_UNIQUE_CS_LOGIC_IDS,
} from "./catalog_ids";

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
  cost_adv_incomplete: boolean;
} {
  const h = Math.max(1, Math.floor(holdDays));
  const dailyCost = amortizedOneWayCost(oneWay, h) / h;
  const netDaily: number[] = [];
  let nOn = 0;
  let costAdvIncomplete = false;
  if (dates.length < 2) {
    return {
      dates: [],
      net_daily: [],
      occupancy: null,
      n_gate_on: 0,
      cost_adv_incomplete: false,
    };
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
      const adv = advByCode?.[code];
      if (!finite(adv)) {
        costAdvIncomplete = true;
        continue;
      }
      const c0 = closeBy[code]?.[prev];
      const c1 = closeBy[code]?.[d];
      if (!finite(c0) || !finite(c1) || c0 === 0) continue;
      contribs.push(pos * (c1 / c0 - 1));
      if (pos < 0) nShort += 1;
      // Match cost_models LIQUIDITY_TX_MULT high/mid/low (1.0/1.5/2.5); local, no import.
      if (adv >= 1e9) liqMults.push(1.0);
      else if (adv >= 1e8) liqMults.push(1.5);
      else liqMults.push(2.5);
    }
    let net = 0;
    if (contribs.length) {
      const g = contribs.reduce((a, b) => a + b, 0) / contribs.length;
      const liq = liqMults.reduce((a, b) => a + b, 0) / liqMults.length;
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
  return {
    dates,
    net_daily: netDaily,
    occupancy: occ,
    n_gate_on: nOn,
    cost_adv_incomplete: costAdvIncomplete,
  };
}


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

export const CF_EVENT_FIDELITY = {
  surprise: "aligned: feps-eps else eps-prior_eps (no invent)",
  adaptive_trail_k: "aligned: last K completed holds orig vs flip; min K",
  margin_pit: "aligned: last print < entry, stale<=14d, level < PIT median",
  surprise_xs: "aligned: rank surprise among in-window names (not price mom)",
  intended_lite_windows: "Worker period shards vs Python HONEST_3Y stitch",
  intended_lite_entry: "disc_time hour>=15 vs full event_post_entry_bar_index",
} as const;




function isEventLogic(lid: string): boolean {
  if ((CF_EVENT_LOGIC_IDS as readonly string[]).includes(lid)) return true;
  // YAML combo IDs are event_/surprise_xs_; prefix covers deploy lag vs catalog_ids.
  return lid.startsWith("event_") || lid.startsWith("surprise_xs_");
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
    sales?: number | null;
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
      const shift = pitEventEntryShift(ev.disc_time);
      if (i === undefined) {
        const later = dlist.find((d) => d > disc);
        if (later === undefined) continue;
        i = idx[later];
      } else if (shift === 1) {
        if (i + 1 >= dlist.length) continue;
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
        np: finite(ev.np) ? ev.np : matchingFundNum(panel, code, disc, "np"),
        roe: finite(ev.roe) ? ev.roe : matchingFundNum(panel, code, disc, "roe"),
        ta: finite(ev.ta) ? ev.ta : matchingFundNum(panel, code, disc, "ta"),
        eq_ar: finite(ev.eq_ar)
          ? ev.eq_ar
          : matchingFundNum(panel, code, disc, "eq_ar"),
        prior_ta: finite(ev.prior_ta)
          ? ev.prior_ta
          : lastPriorFundNum(panel, code, "ta", disc),
        sales: finite(ev.sales)
          ? ev.sales
          : matchingFundNum(panel, code, disc, "sales"),
      });
      absSurprises.push({ d: disc, abs: Math.abs(sur) });
    }
    perCode[code] = { dlist, entries };
  }

  const comboGates = comboGatesOf(params as Record<string, unknown>);
  const comboImpl = comboGatesImplemented(comboGates);

  const held: Record<string, Record<string, number>> = {};
  let nOn = 0;
  for (const [code, pack] of Object.entries(perCode)) {
    const pos: Record<string, number> = {};
    const arr: Array<number | null> = pack.dlist.map(() => null);
    for (const ev of pack.entries) {
      let ok = true;
      let sgn = ev.sign;
      if (comboImpl) {
        ok = comboGates.every((g) =>
          comboEventGateOk(g, ev, overnight, spread, minHist, panel),
        );
        if (String(params.side || "orig") === "flip") sgn = -ev.sign;
      }
      // Leftover occupancy is Worker policy in daily_path.ts (no params.gates).
      // Park reasons also recorded in Python UNIQUE22_PARK_REASONS.
      // Compiled catalog is SoT; yaml_still_present false. Combo gates use comboEventGateOk.
      // Do not drop without occupancy-equal re-eval.
      if (!comboImpl) {
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
        // Occupancy vs Python unique: momentumAt(entryIdx), not entryIdx-1.
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
          if (!Number.isFinite(ageDays) || ageDays > 14 || med === null) ok = false;
          else if ((levels[lastD] as number) >= med) ok = false;
        }
      }
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
    const series = clusterWindowSeries(panel);
    const gated: Record<string, Record<string, number>> = {};
    for (const [code, cmap] of Object.entries(cs)) {
      gated[code] = {};
      for (const [d, v] of Object.entries(cmap)) {
        const nDisc = series[d];
        if (nDisc === undefined) continue;
        const med = pitMedian(series, d, 10);
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
    const surpriseByDate: Record<string, Record<string, number>> = {};
    for (const pack of Object.values(perCode)) {
      for (const ev of pack.entries) {
        if (comboImpl) {
          if (
            !comboGates.every((g) =>
              comboEventGateOk(g, ev, overnight, spread, minHist, panel),
            )
          )
            continue;
        }
        // Catalog gate is first_half_month (dd<=15); leftover is dd>"05".
        if (lid === "surprise_xs_month_start" && ev.entryDate.slice(8, 10) > "05")
          continue;
        // Catalog fy_end is Mar>=15 (same predicate). Keep leftover so
        // occupancy cannot widen if comboImpl/gate drift.
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
    const gatedSparse =
      comboImpl ||
      lid === "surprise_xs_month_start" ||
      lid === "surprise_xs_fy_end";
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
    const trailK = Math.max(5, Math.floor(finite(params.trail_k as number) ? (params.trail_k as number) : 10));
    const trailMin = Math.max(3, Math.floor(finite(params.trail_min as number) ? (params.trail_min as number) : 5));
    const origMtm = heldBookDailyMtm(
      xsHeld,
      closeMap,
      dates,
      holdDays,
      0,
      undefined,
      panel.adv_by_code || undefined,
    );
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


type CsFundSnap = {
  cheapPb: boolean;
  expensivePb: boolean;
  eyHigh: boolean;
  roeHigh: boolean;
  roeLow: boolean;
  divPositive: boolean;
  npPositive: boolean;
  npNegative: boolean;
  eqArHigh: boolean;
  eqArLow: boolean;
  eqArRising: boolean;
  eqArFalling: boolean;
  taUp: boolean;
  taDown: boolean;
  pbRising: boolean;
  salesDown: boolean;
};

function csFundSnaps(
  panel: PeriodPanel,
  code: string,
  dates: string[],
): Record<string, CsFundSnap> {
  const fins = [...(panel.fund_regime?.events_by_code?.[code] || [])].sort(
    (a, b) =>
      String(a.disc_date || "").localeCompare(String(b.disc_date || "")),
  );
  const closeBy: Record<string, number> = {};
  for (const [dd, px] of panel.bars?.[code] || []) {
    if (finite(px)) closeBy[String(dd).slice(0, 10)] = px as number;
  }
  const eqArPrints: Record<string, number> = {};
  const roePrints: Record<string, number> = {};
  for (const ev of fins) {
    const dd = String(ev.disc_date || "").slice(0, 10);
    if (dd && finite(ev.eq_ar)) eqArPrints[dd] = ev.eq_ar as number;
    if (dd && finite(ev.roe)) roePrints[dd] = ev.roe as number;
  }
  let fi = 0;
  let last: (typeof fins)[number] | null = null;
  let prevEqAr: number | null = null;
  let prevSales: number | null = null;
  const pbBy: Record<string, number> = {};
  const eyBy: Record<string, number> = {};
  const out: Record<string, CsFundSnap> = {};
  for (const d of dates) {
    while (fi < fins.length) {
      const dd = String(fins[fi].disc_date || "").slice(0, 10);
      if (!dd || dd > d) break;
      if (last != null) {
        if (finite(last.eq_ar)) prevEqAr = last.eq_ar as number;
        if (finite(last.sales)) prevSales = last.sales as number;
      }
      last = fins[fi];
      fi += 1;
    }
    const close = closeBy[d];
    const bps =
      last && finite(last.bps) && (last.bps as number) !== 0
        ? (last.bps as number)
        : null;
    const pb = finite(close) && bps !== null ? (close as number) / bps : null;
    if (pb !== null) pbBy[d] = pb;
    const eps = last && finite(last.eps) ? (last.eps as number) : null;
    const ey =
      finite(close) &&
      eps !== null &&
      (close as number) !== 0
        ? eps / (close as number)
        : null;
    if (ey !== null) eyBy[d] = ey;
    const pbMed = pitMedian(pbBy, d, 20);
    const eyMed = pitMedian(eyBy, d, 20);
    const eqMed = pitMedian(eqArPrints, d, 8);
    const roeMed = pitMedian(roePrints, d, 10);
    const eqAr =
      last && finite(last.eq_ar) ? (last.eq_ar as number) : null;
    out[d] = {
      cheapPb: pb !== null && pbMed !== null && pb < pbMed,
      expensivePb: pb !== null && pbMed !== null && pb > pbMed,
      pbRising: pb !== null && pbMed !== null && pb > pbMed,
      eyHigh: ey !== null && eyMed !== null && ey > eyMed,
      roeHigh:
        last != null &&
        finite(last.roe) &&
        roeMed !== null &&
        (last.roe as number) >= roeMed,
      roeLow:
        last != null &&
        finite(last.roe) &&
        roeMed !== null &&
        (last.roe as number) < roeMed,
      divPositive:
        last != null &&
        finite(last.div_ann) &&
        (last.div_ann as number) > 0,
      npPositive:
        last != null && finite(last.np) && (last.np as number) > 0,
      npNegative:
        last != null && finite(last.np) && (last.np as number) < 0,
      eqArHigh: eqAr !== null && eqMed !== null && eqAr >= eqMed,
      eqArLow: eqAr !== null && eqMed !== null && eqAr < eqMed,
      eqArRising:
        eqAr !== null && prevEqAr !== null && eqAr > prevEqAr,
      eqArFalling:
        eqAr !== null && prevEqAr !== null && eqAr < prevEqAr,
      taUp:
        last != null &&
        finite(last.ta) &&
        finite(last.prior_ta) &&
        (last.ta as number) > (last.prior_ta as number),
      taDown:
        last != null &&
        finite(last.ta) &&
        finite(last.prior_ta) &&
        (last.ta as number) < (last.prior_ta as number),
      salesDown:
        last != null &&
        finite(last.sales) &&
        prevSales !== null &&
        (last.sales as number) < prevSales,
    };
  }
  return out;
}

function gatedCsHeld(
  logic: LogicSpec,
  panel: PeriodPanel,
): Record<string, Record<string, number>> {
  // Unique-22 leftover CS books (xs_margin_delta / xs_low_vol / idio) and
  // lid invert list are leftover occupancy Worker policy here, not comboCsGateOk.
  // Park reasons also recorded in Python UNIQUE22_PARK_REASONS.
  // Compiled catalog is SoT; yaml_still_present false.
  // Do not drop without occupancy-equal re-eval. Parked leftover stay non-candidate.
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
  const medOnByDate: Record<string, number | null> = {};
  for (const d of dates) medOnByDate[d] = pitMedian(overnight, d, 20);
  const fundSnaps: Record<string, Record<string, CsFundSnap>> = {};
  for (const code of Object.keys(base)) {
    fundSnaps[code] = csFundSnaps(panel, code, dates);
  }
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
      const medOn = medOnByDate[d] ?? null;
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
          const snap = fundSnaps[code]?.[d];
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
              cheapPb: snap?.cheapPb === true,
              expensivePb: snap?.expensivePb === true,
              eyHigh: snap?.eyHigh === true,
              roeHigh: snap?.roeHigh === true,
              divPositive: snap?.divPositive === true,
              npPositive: snap?.npPositive === true,
              eqArHigh: snap?.eqArHigh === true,
              eqArLow: snap?.eqArLow === true,
              eqArRising: snap?.eqArRising === true,
              eqArFalling: snap?.eqArFalling === true,
              taUp: snap?.taUp === true,
              taDown: snap?.taDown === true,
              pbRising: snap?.pbRising === true,
              roeLow: snap?.roeLow === true,
              salesDown: snap?.salesDown === true,
              npNegative: snap?.npNegative === true,
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
    cost_adv_incomplete: pack.cost_adv_incomplete,
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
    candidate_grade: false,
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
      candidate_grade: false,
      period_net_dd_only_pass_forbidden: true,
      method: p.method,
    });
  }
  return cells;
}
