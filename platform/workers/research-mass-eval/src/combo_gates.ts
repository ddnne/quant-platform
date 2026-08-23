/** PRODUCTION combo gate SoT. Unknown gate fails closed. Leftover occupancy stays in daily_path.ts. Not GO. */

import type { PeriodPanel } from "./types";
import { COMBO_EVENT_GATES } from "./catalog_ids";

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function signNum(v: number | null | undefined): number | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  if (v > 0) return 1;
  if (v < 0) return -1;
  return 0;
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

function addDays(iso: string, n: number): string {
  const t = Date.parse(iso + "T00:00:00Z");
  if (!Number.isFinite(t)) return iso;
  const d = new Date(t + n * 86400000);
  return d.toISOString().slice(0, 10);
}

export function comboGatesOf(params: Record<string, unknown>): string[] {
  const g = params.gates;
  if (Array.isArray(g)) return g.map((x) => String(x)).filter(Boolean);
  return [];
}

export function comboGatesImplemented(gates: string[]): boolean {
  return gates.length > 0 && gates.every((g) => COMBO_EVENT_GATES.has(g));
}

const clusterWindowCache = new WeakMap<object, Record<string, number>>();

export function clusterWindowSeries(panel: PeriodPanel): Record<string, number> {
  const hit = clusterWindowCache.get(panel as object);
  if (hit) return hit;
  const freq: Record<string, number> = {};
  for (const rows of Object.values(panel.fund_regime?.events_by_code || {})) {
    for (const row of rows || []) {
      const x = String(row.disc_date || "").slice(0, 10);
      if (x) freq[x] = (freq[x] || 0) + 1;
    }
  }
  const uniq = Object.keys(freq).sort();
  const series: Record<string, number> = {};
  let lo = 0;
  let run = 0;
  for (let i = 0; i < uniq.length; i++) {
    const d = uniq[i];
    const cut = addDays(d, -5);
    while (lo < i && uniq[lo] < cut) {
      run -= freq[uniq[lo]] || 0;
      lo += 1;
    }
    series[d] = run;
    run += freq[d] || 0;
  }
  clusterWindowCache.set(panel as object, series);
  return series;
}

const impulseFlagCache = new WeakMap<object, Record<string, boolean>>();

function impulseFlags(
  overnight: Record<string, number>,
  minHist: number,
): Record<string, boolean> {
  const hit = impulseFlagCache.get(overnight);
  if (hit) return hit;
  const keys = Object.keys(overnight).sort();
  const absCh: Record<string, number> = {};
  for (let i = 1; i < keys.length; i++) {
    absCh[keys[i]] = Math.abs(overnight[keys[i]] - overnight[keys[i - 1]]);
  }
  const out: Record<string, boolean> = {};
  for (const d of keys) {
    const med = pitMedian(absCh, d, minHist);
    out[d] = med !== null && finite(absCh[d]) && absCh[d] >= med;
  }
  impulseFlagCache.set(overnight, out);
  return out;
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

function overnightTightened(
  overnight: Record<string, number>,
  d: string,
): boolean {
  const prevs = Object.keys(overnight)
    .filter((x) => x < d)
    .sort();
  const on = overnight[d];
  if (!prevs.length || on === undefined) return false;
  return on > overnight[prevs[prevs.length - 1]];
}

type FundPrintField = "eq_ar" | "sales" | "ta" | "eps" | "roe" | "np";

export function lastPriorFundNum(
  panel: PeriodPanel,
  code: string,
  field: FundPrintField,
  before: string,
): number | null {
  if (!before) return null;
  let bestD = "";
  let best: number | null = null;
  for (const row of panel.fund_regime?.events_by_code?.[code] || []) {
    const dd = String(row.disc_date || "").slice(0, 10);
    if (!dd || dd >= before) continue;
    const v = row[field];
    if (!finite(v)) continue;
    if (!bestD || dd >= bestD) {
      bestD = dd;
      best = v as number;
    }
  }
  return best;
}

export function matchingFundNum(
  panel: PeriodPanel,
  code: string,
  disc: string,
  field: FundPrintField | "prior_ta" | "prior_eps" | "bps",
): number | null {
  if (!disc) return null;
  for (const row of panel.fund_regime?.events_by_code?.[code] || []) {
    if (String(row.disc_date || "").slice(0, 10) !== disc) continue;
    const v = (row as Record<string, unknown>)[field];
    if (finite(v)) return v as number;
  }
  return null;
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
    sales?: number | null;
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
  if (gate === "month_end_skip") return dd < "28";
  if (gate === "fy_end") return d.slice(5, 7) === "03" && dd >= "15";
  if (gate === "fy_results") return d.slice(5, 7) === "05";
  if (gate === "fy_start") return d.slice(5, 7) === "04";
  if (gate === "midmonth") return dd >= "10" && dd <= "20";
  if (gate === "afterclose") return ev.after;
  if (gate === "overnight_easing") return overnightEased(overnight, d);
  if (gate === "overnight_tightening") return overnightTightened(overnight, d);
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
  if (gate === "uncrowded_margin" || gate === "crowded_margin") {
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
    const crowded = (levels[lastD] as number) >= med;
    return gate === "crowded_margin" ? crowded : !crowded;
  }
  if (gate === "cluster") {
    const series = clusterWindowSeries(panel);
    const nDisc = series[ev.disc];
    if (nDisc === undefined) return false;
    const med = pitMedian(series, ev.disc, 10);
    return med !== null && nDisc >= med;
  }
  if (gate === "invert_curve") {
    const sp = spread[d];
    return sp !== undefined && sp <= 0;
  }
  if (gate === "on_impulse") {
    return impulseFlags(overnight, minHist)[d] === true;
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
    // Event cheap_pb is bars×fins (close/bps). Not csFundSnaps.
    // CS cheap_pb uses extras.cheapPb from csFundSnaps. Do not unify.
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
  if (gate === "ta_down") {
    return (
      ev.ta != null &&
      ev.prior_ta != null &&
      finite(ev.ta) &&
      finite(ev.prior_ta) &&
      (ev.ta as number) < (ev.prior_ta as number)
    );
  }
  if (gate === "eps_down") {
    return (
      ev.eps != null &&
      ev.prior_eps != null &&
      finite(ev.eps) &&
      finite(ev.prior_eps) &&
      (ev.eps as number) < (ev.prior_eps as number)
    );
  }
  if (gate === "eq_ar_rising" || gate === "eq_ar_falling") {
    const cur = finite(ev.eq_ar)
      ? (ev.eq_ar as number)
      : matchingFundNum(panel, ev.code, ev.disc, "eq_ar");
    const prior = lastPriorFundNum(panel, ev.code, "eq_ar", ev.disc);
    if (cur === null || prior === null) return false;
    return gate === "eq_ar_rising" ? cur > prior : cur < prior;
  }
  if (gate === "pb_rising") {
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
    return med !== null && pb > med;
  }
  if (gate === "np_negative") {
    const np = finite(ev.np)
      ? (ev.np as number)
      : matchingFundNum(panel, ev.code, ev.disc, "np");
    return np !== null && np < 0;
  }
  if (gate === "sales_down") {
    const cur = finite(ev.sales)
      ? (ev.sales as number)
      : matchingFundNum(panel, ev.code, ev.disc, "sales");
    const prior = lastPriorFundNum(panel, ev.code, "sales", ev.disc);
    if (cur === null || prior === null) return false;
    return cur < prior;
  }
  if (gate === "roe_low") {
    const roe = finite(ev.roe)
      ? (ev.roe as number)
      : matchingFundNum(panel, ev.code, ev.disc, "roe");
    if (roe === null) return false;
    const hist: Record<string, number> = {};
    for (const row of panel.fund_regime?.events_by_code?.[ev.code] || []) {
      const dd = String(row.disc_date || "").slice(0, 10);
      if (dd && dd < ev.disc && finite(row.roe)) hist[dd] = row.roe as number;
    }
    const med = pitMedian(hist, d, 8);
    return med !== null && roe < med;
  }
  if (gate === "pre_mom") {
    const pairs = panel.bars?.[ev.code] || [];
    const j = ev.entryIdx - 1;
    const i = j - 5;
    if (i < 0 || j < 0 || j >= pairs.length || !pairs[i] || !pairs[j])
      return false;
    const c0 = pairs[i][1];
    const c1 = pairs[j][1];
    if (!finite(c0) || !finite(c1) || (c0 as number) === 0) return false;
    const mom = (c1 as number) / (c0 as number) - 1;
    const ms = signNum(mom);
    return ms !== null && ms !== 0 && ms === ev.sign;
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
    eqArRising?: boolean;
    eqArFalling?: boolean;
    taUp?: boolean;
    taDown?: boolean;
    pbRising?: boolean;
    roeLow?: boolean;
    salesDown?: boolean;
    npNegative?: boolean;
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
  else if (gate === "fy_end_invert") {
    keep = d.slice(5, 7) === "03" && dd >= "15";
    invert = true;
  } else if (gate === "fy_start") {
    keep = d.slice(5, 7) === "04";
  } else if (gate === "overnight_easy_skip_friday") {
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
    keep = impulseFlags(overnight, 20)[d] === true;
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
    // CS cheap_pb is csFundSnaps extras.cheapPb. Event cheap_pb is bars×fins.
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
    keep =
      extras?.eqArHigh === true && impulseFlags(overnight, 20)[d] === true;
  } else if (gate === "cheap_pb_margin_down") {
    keep =
      extras?.cheapPb === true &&
      marginChg !== null &&
      marginChg < 0;
  } else if (gate === "eq_ar_low_margin_up_invert") {
    keep =
      extras?.eqArLow === true &&
      marginChg !== null &&
      marginChg > 0;
    invert = true;
  } else if (gate === "ta_down") {
    keep = extras?.taDown === true;
  } else if (gate === "eq_ar_rising") {
    keep = extras?.eqArRising === true;
  } else if (gate === "eq_ar_falling") {
    keep = extras?.eqArFalling === true;
  } else if (gate === "pb_rising") {
    keep = extras?.pbRising === true;
  } else if (gate === "roe_low") {
    keep = extras?.roeLow === true;
  } else if (gate === "sales_down") {
    keep = extras?.salesDown === true;
  } else if (gate === "np_negative") {
    keep = extras?.npNegative === true;
  } else {
    return { keep: false, invert: false };
  }
  return { keep, invert };
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
