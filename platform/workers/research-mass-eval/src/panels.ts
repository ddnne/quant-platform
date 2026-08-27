import type { BarsByCode, PeriodPanel, PeriodSpec } from "./types";

const DEFAULT_YEARS = [2015, 2017, 2019, 2021, 2023, 2025];
const DEFAULT_CODES = ["13010", "72030", "67580", "99840", "83060", "65010", "68610", "80350"];

function mulberry32(seed: number): () => number {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function q4Dates(year: number, maxDays: number): string[] {
  const out: string[] = [];
  const start = new Date(Date.UTC(year, 9, 1));
  let d = start;
  while (out.length < maxDays) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) {
      const y = d.getUTCFullYear();
      const m = String(d.getUTCMonth() + 1).padStart(2, "0");
      const day = String(d.getUTCDate()).padStart(2, "0");
      out.push(`${y}-${m}-${day}`);
    }
    d = new Date(d.getTime() + 86400000);
    if (d.getUTCFullYear() > year) break;
  }
  return out;
}

function buildBarsForPeriod(
  year: number,
  seed: number,
  maxCodes: number,
  maxDays: number,
): BarsByCode {
  const rng = mulberry32((seed ^ (year * 0x9e3779b9)) >>> 0);
  const dates = q4Dates(year, maxDays);
  const codes = DEFAULT_CODES.slice(0, Math.max(2, Math.min(maxCodes, DEFAULT_CODES.length)));
  const bars: BarsByCode = {};
  for (let ci = 0; ci < codes.length; ci++) {
    const code = codes[ci];
    const base = 100 + 10 * ci + (year % 10);
    const series: Array<[string, number]> = [];
    let px = base;
    for (let i = 0; i < dates.length; i++) {
      const drift = 0.0004 * (1 + (ci % 3)) + (ci % 2 === 0 ? 0.0002 : -0.0001);
      const noise = (rng() - 0.5) * 0.02;
      px = Math.max(1, px * (1 + drift + noise));
      series.push([dates[i], Math.round(px * 100) / 100]);
    }
    bars[code] = series;
  }
  return bars;
}

export function defaultPeriodsFromRequest(
  periods: PeriodSpec[] | undefined,
  seed: number,
): PeriodSpec[] {
  if (periods && periods.length > 0) {
    return periods.map((p, i) => ({
      period_id: String(p.period_id || `p${i}`),
      year: p.year ?? DEFAULT_YEARS[i % DEFAULT_YEARS.length],
      period_start: p.period_start,
      period_end: p.period_end,
    }));
  }
  const years = DEFAULT_YEARS.slice();
  const rng = mulberry32(seed >>> 0);
  for (let i = years.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [years[i], years[j]] = [years[j], years[i]];
  }
  return years.map((y) => ({
    period_id: `y${y}_q4_lite`,
    year: y,
  }));
}

function buildNkyVolFromBars(
  bars: BarsByCode,
  shortN = 10,
  longN = 60,
): PeriodPanel["nky_vol_series"] {
  const proxyCodes = ["__NKY_PROXY__", "__TOPIX__", "__NK225F__", "__INDEX__"];
  let idxSeries: Array<[string, number]> | null = null;
  for (const pc of proxyCodes) {
    if (bars[pc] && bars[pc].length >= shortN + 2) {
      idxSeries = bars[pc].map(([d, c]) => [d, c] as [string, number]);
      break;
    }
  }
  if (!idxSeries) {
    const codes = Object.keys(bars).filter((c) => !c.startsWith("__"));
    if (!codes.length) return null;
    const dateSet = new Set<string>();
    for (const c of codes) for (const [d] of bars[c] || []) dateSet.add(d);
    const dates = [...dateSet].sort();
    idxSeries = [];
    for (const d of dates) {
      let s = 0;
      let n = 0;
      for (const c of codes) {
        const hit = (bars[c] || []).find((p) => p[0] === d);
        if (hit) {
          s += hit[1];
          n += 1;
        }
      }
      if (n > 0) idxSeries.push([d, s / n]);
    }
  }
  if (!idxSeries.length) return null;
  const idxDates = idxSeries.map(([d]) => d);
  const idxCloses = idxSeries.map(([, c]) => c);
  const ann = Math.sqrt(252);
  const rvShort: Record<string, number> = {};
  const rvLong: Record<string, number> = {};
  const rvRatio: Record<string, number> = {};
  function rvAt(end: number, win: number): number | null {
    if (end < win || win < 2) return null;
    const rets: number[] = [];
    for (let j = end - win + 1; j <= end; j++) {
      const c0 = idxCloses[j - 1];
      const c1 = idxCloses[j];
      if (!c0) return null;
      rets.push(c1 / c0 - 1);
    }
    if (rets.length < 2) return null;
    const m = rets.reduce((a, b) => a + b, 0) / rets.length;
    let v = 0;
    for (const r of rets) v += (r - m) * (r - m);
    v /= rets.length - 1;
    return Math.sqrt(Math.max(0, v)) * ann;
  }
  for (let i = 0; i < idxDates.length; i++) {
    const d = idxDates[i];
    const s = rvAt(i, shortN);
    const lo = rvAt(i, longN);
    if (s !== null) rvShort[d] = s;
    if (lo !== null) rvLong[d] = lo;
    if (s !== null && lo !== null && lo > 1e-12) rvRatio[d] = s / lo;
  }
  return {
    rv_short_by_date: rvShort,
    rv_long_by_date: rvLong,
    rv_abs_by_date: rvShort,
    rv_ratio_by_date: rvRatio,
  };
}

export function buildSyntheticPanels(
  periods: PeriodSpec[],
  seed: number,
  maxCodes: number,
  maxDays: number,
): PeriodPanel[] {
  return periods.map((p) => {
    const year = Number(p.year ?? 2023);
    const bars = buildBarsForPeriod(year, seed, maxCodes, maxDays);
    const dates = Object.values(bars)[0] || [];
    const start = p.period_start || (dates[0]?.[0] ?? `${year}-10-01`);
    const end =
      p.period_end || (dates[dates.length - 1]?.[0] ?? `${year}-12-15`);
    return {
      period_id: String(p.period_id),
      year,
      period_start: start,
      period_end: end,
      status: "ok" as const,
      bars,
      nky_vol_series: buildNkyVolFromBars(bars),
      source: "synthetic_cf_lite",
    };
  });
}

export async function loadR2Panels(
  bucket: R2Bucket,
  periods: PeriodSpec[],
  panelsPrefix?: string,
): Promise<{ panels: PeriodPanel[]; notes: string[] }> {
  const panels: PeriodPanel[] = [];
  const notes: string[] = [];
  const primaryPrefix = (panelsPrefix || "research/mass_eval/panels").replace(
    /\/+$/,
    "",
  );
  for (const p of periods) {
    const candidates = [
      `${primaryPrefix}/${p.period_id}.json`,
      `research/mass_eval/panels/${p.period_id}.json`,
    ];
    const keys = [...new Set(candidates)];
    let obj: R2ObjectBody | null = null;
    let keyUsed = keys[0];
    for (const key of keys) {
      const hit = await bucket.get(key);
      if (hit) {
        obj = hit;
        keyUsed = key;
        break;
      }
    }
    if (!obj) {
      notes.push(`missing:${keys.join("|")}`);
      panels.push({
        period_id: String(p.period_id),
        year: Number(p.year ?? 0),
        period_start: p.period_start || "",
        period_end: p.period_end || "",
        status: "data_missing",
        bars: {},
        source: "r2_panels_missing",
      });
      continue;
    }
    try {
      const raw = (await obj.json()) as {
        period_id?: string;
        year?: number;
        period_start?: string;
        period_end?: string;
        bars?: BarsByCode;
        source?: string;
        nky_vol_series?: PeriodPanel["nky_vol_series"];
        opt225_regime?: PeriodPanel["opt225_regime"];
        base_vol_series?: PeriodPanel["base_vol_series"];
        atm_iv_series?: PeriodPanel["atm_iv_series"];
        iv_base_spread?: PeriodPanel["iv_base_spread"];
        skew_series?: PeriodPanel["skew_series"];
        cm_term_series?: PeriodPanel["cm_term_series"];
        basevol_delta_series?: PeriodPanel["basevol_delta_series"];
        repo_rate_regime?: PeriodPanel["repo_rate_regime"];
        repo_rate_by_date?: PeriodPanel["repo_rate_by_date"];
        calendar?: PeriodPanel["calendar"];
        flow_regime?: PeriodPanel["flow_regime"];
        fund_regime?: PeriodPanel["fund_regime"];
        adv_by_code?: PeriodPanel["adv_by_code"];
      };
      const bars = normalizeBars(raw.bars || {});
      const nCodes = Object.keys(bars).filter((c) => !c.startsWith("__")).length;
      if (nCodes === 0) {
        notes.push(`empty_bars:${keyUsed}`);
        panels.push({
          period_id: String(p.period_id),
          year: Number(raw.year ?? p.year ?? 0),
          period_start: raw.period_start || p.period_start || "",
          period_end: raw.period_end || p.period_end || "",
          status: "data_missing",
          bars: {},
          source: "r2_panels_empty",
        });
        continue;
      }
      const nky =
        raw.nky_vol_series &&
        (raw.nky_vol_series.rv_short_by_date ||
          raw.nky_vol_series.rv_abs_by_date)
          ? raw.nky_vol_series
          : buildNkyVolFromBars(bars);
      const opt225 = raw.opt225_regime || null;
      const baseVolSeries =
        raw.base_vol_series ||
        (opt225 && opt225.basevol && opt225.basevol.rv_abs_by_date) ||
        null;
      const atmIvSeries =
        raw.atm_iv_series ||
        (opt225 && opt225.atm_iv && opt225.atm_iv.rv_abs_by_date) ||
        null;
      const ivBaseSpread =
        raw.iv_base_spread ||
        (opt225 && opt225.spread && opt225.spread.rv_abs_by_date) ||
        null;
      const skewSeries =
        raw.skew_series ||
        (opt225 && opt225.skew && opt225.skew.rv_abs_by_date) ||
        null;
      const cmTermSeries =
        raw.cm_term_series ||
        (opt225 && opt225.cm_term && opt225.cm_term.rv_abs_by_date) ||
        null;
      const basevolDeltaSeries =
        raw.basevol_delta_series ||
        (opt225 && opt225.basevol_delta && opt225.basevol_delta.rv_abs_by_date) ||
        null;
      const repoRegime = raw.repo_rate_regime || null;
      const repoByDate =
        raw.repo_rate_by_date ||
        (repoRegime && (repoRegime.rates_by_date || repoRegime.rate_by_date)) ||
        null;
      const calendar = raw.calendar || null;
      const flowRegime = raw.flow_regime || null;
      const fundRegime = raw.fund_regime || null;
      const advByCode = raw.adv_by_code || null;
      panels.push({
        period_id: String(raw.period_id || p.period_id),
        year: Number(raw.year ?? p.year ?? 0),
        period_start: raw.period_start || p.period_start || "",
        period_end: raw.period_end || p.period_end || "",
        status: "ok",
        bars,
        nky_vol_series: nky,
        opt225_regime: opt225,
        base_vol_series: baseVolSeries,
        atm_iv_series: atmIvSeries,
        iv_base_spread: ivBaseSpread,
        skew_series: skewSeries,
        cm_term_series: cmTermSeries,
        basevol_delta_series: basevolDeltaSeries,
        repo_rate_regime: repoRegime,
        repo_rate_by_date: repoByDate,
        calendar,
        flow_regime: flowRegime,
        fund_regime: fundRegime,
        adv_by_code: advByCode,
        source: raw.source || `r2:${keyUsed}`,
      });
      notes.push(`loaded:${keyUsed}:codes=${nCodes}`);
    } catch (e) {
      notes.push(`parse_error:${keyUsed}:${String(e)}`);
      panels.push({
        period_id: String(p.period_id),
        year: Number(p.year ?? 0),
        period_start: "",
        period_end: "",
        status: "data_missing",
        bars: {},
        source: "r2_panels_parse_error",
      });
    }
  }
  return { panels, notes };
}

function normalizeBars(raw: unknown): BarsByCode {
  if (!raw || typeof raw !== "object") return {};
  const out: BarsByCode = {};
  for (const [code, series] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(series)) continue;
    const pairs: Array<[string, number]> = [];
    for (const pt of series) {
      if (Array.isArray(pt) && pt.length >= 2) {
        const d = String(pt[0]).slice(0, 10);
        const px = Number(pt[1]);
        if (d && Number.isFinite(px) && px > 0) pairs.push([d, px]);
      } else if (pt && typeof pt === "object") {
        const o = pt as Record<string, unknown>;
        const d = String(o.date ?? o.Date ?? "").slice(0, 10);
        const px = Number(o.close ?? o.Close ?? o.AdjC ?? o.px ?? NaN);
        if (d && Number.isFinite(px) && px > 0) pairs.push([d, px]);
      }
    }
    pairs.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
    if (pairs.length) out[code] = pairs;
  }
  return out;
}
