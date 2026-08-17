/**
 * Period panels for CF multi-logic mass-eval (W91 / w0818a).
 *
 * * mode=synthetic: deterministic PRNG panels (W90 smoke default)
 * * mode=r2_panels: staged COMPLETE-backed real bars under
 *     {panels_prefix}/{period_id}.json
 *     (default prefix: research/mass_eval/panels)
 *     also tries job-scoped research/mass_eval/job={id}/panels/{period_id}.json
 * * mode=d1_bars: live tip extract from D1 jquants_records (hot window only)
 */

import type { BarsByCode, Env, PeriodPanel, PeriodSpec } from "./types";

const DEFAULT_YEARS = [2015, 2017, 2019, 2021, 2023, 2025];
const DEFAULT_CODES = ["13010", "72030", "67580", "99840", "83060", "65010", "68610", "80350"];

/** Mulberry32 PRNG — deterministic from seed. */
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
  // Oct 1 .. mid-Dec lite window (trading-day proxy: weekdays only-ish)
  const out: string[] = [];
  const start = new Date(Date.UTC(year, 9, 1)); // month 9 = Oct
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
    // stop if past year end
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
      // mild drift + noise; code-specific bias for diversity
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
  // Default lite multi-year Q4 set (seed-stable order)
  const years = DEFAULT_YEARS.slice();
  // mild permutation by seed without dropping years
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

/** Build equal-weight market index RV series from panel bars (CF lite proxy). */
function buildNkyVolFromBars(
  bars: BarsByCode,
  shortN = 10,
  longN = 40,
): PeriodPanel["nky_vol_series"] {
  // Equal-weight average close path as Nikkei proxy when futures not staged.
  const codes = Object.keys(bars);
  if (!codes.length) return null;
  const dateSet = new Set<string>();
  for (const c of codes) for (const [d] of bars[c] || []) dateSet.add(d);
  const dates = [...dateSet].sort();
  const idxCloses: number[] = [];
  const idxDates: string[] = [];
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
    if (n > 0) {
      idxDates.push(d);
      idxCloses.push(s / n);
    }
  }
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
    source: "synthetic_ew_panel_proxy",
    short_n: shortN,
    long_n: longN,
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

/**
 * Load staged panels from R2 if present.
 *
 * Lookup order per period:
 *   1. {panelsPrefix}/{period_id}.json  (explicit / job-scoped preferred)
 *   2. research/mass_eval/panels/{period_id}.json  (shared staged)
 *
 * Shape: { period_id, year, bars: { code: [[date, close], ...] } }
 */
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
    // de-dupe if primary equals default
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
        dataset?: string;
        source?: string;
      };
      const bars = normalizeBars(raw.bars || {});
      const nCodes = Object.keys(bars).length;
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
      panels.push({
        period_id: String(raw.period_id || p.period_id),
        year: Number(raw.year ?? p.year ?? 0),
        period_start: raw.period_start || p.period_start || "",
        period_end: raw.period_end || p.period_end || "",
        status: "ok",
        bars,
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

/** Accept [[date, close]] or {date, close}[] panel bar shapes. */
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

/**
 * Load tip bars from D1 jquants_records (equities_bars_daily).
 *
 * Honest limit: D1 is hot-window only (currently ~tip month(s)), not
 * multi-year COMPLETE history. Multi-year research must use r2_panels.
 */
export async function loadD1BarsPanels(
  db: D1Database,
  periods: PeriodSpec[],
  maxCodes: number,
  maxDays: number,
): Promise<{ panels: PeriodPanel[]; notes: string[] }> {
  const panels: PeriodPanel[] = [];
  const notes: string[] = [];
  const codesCap = Math.max(2, Math.min(40, maxCodes));
  const daysCap = Math.max(10, Math.min(260, maxDays));

  for (const p of periods) {
    const start =
      (p.period_start && String(p.period_start).slice(0, 10)) ||
      (p.year ? `${p.year}-01-01` : "2000-01-01");
    const end =
      (p.period_end && String(p.period_end).slice(0, 10)) ||
      (p.year ? `${p.year}-12-31` : "2099-12-31");
    try {
      // Prefer codes that appear most in the window.
      const codeRows = await db
        .prepare(
          `SELECT json_extract(payload, '$.Code') AS code, COUNT(*) AS n
           FROM jquants_records
           WHERE dataset = 'equities_bars_daily'
             AND substr(event_time, 1, 10) >= ?
             AND substr(event_time, 1, 10) <= ?
             AND json_extract(payload, '$.Code') IS NOT NULL
           GROUP BY 1
           HAVING n >= 5
           ORDER BY n DESC
           LIMIT ?`,
        )
        .bind(start, end, codesCap)
        .all<{ code: string; n: number }>();
      const codes = (codeRows.results || [])
        .map((r) => String(r.code || "").trim())
        .filter(Boolean);
      if (!codes.length) {
        notes.push(`d1_empty_codes:${p.period_id}:${start}..${end}`);
        panels.push({
          period_id: String(p.period_id),
          year: Number(p.year ?? 0),
          period_start: start,
          period_end: end,
          status: "data_missing",
          bars: {},
          source: "d1_bars_empty",
        });
        continue;
      }
      const placeholders = codes.map(() => "?").join(",");
      const barRows = await db
        .prepare(
          `SELECT json_extract(payload, '$.Code') AS code,
                  substr(event_time, 1, 10) AS d,
                  COALESCE(
                    json_extract(payload, '$.AdjC'),
                    json_extract(payload, '$.C'),
                    json_extract(payload, '$.close')
                  ) AS px
           FROM jquants_records
           WHERE dataset = 'equities_bars_daily'
             AND substr(event_time, 1, 10) >= ?
             AND substr(event_time, 1, 10) <= ?
             AND json_extract(payload, '$.Code') IN (${placeholders})
           ORDER BY d, code`,
        )
        .bind(start, end, ...codes)
        .all<{ code: string; d: string; px: number }>();

      const bars: BarsByCode = {};
      const dateSet = new Set<string>();
      for (const row of barRows.results || []) {
        const code = String(row.code || "").trim();
        const d = String(row.d || "").slice(0, 10);
        const px = Number(row.px);
        if (!code || !d || !Number.isFinite(px) || !(px > 0)) continue;
        if (!bars[code]) bars[code] = [];
        bars[code].push([d, px]);
        dateSet.add(d);
      }
      const dates = [...dateSet].sort();
      const keep =
        dates.length > daysCap
          ? new Set(dates.slice(-daysCap))
          : new Set(dates);
      if (dates.length > daysCap) {
        for (const c of Object.keys(bars)) {
          bars[c] = bars[c].filter((pt) => keep.has(pt[0]));
          if (!bars[c].length) delete bars[c];
        }
      }
      const nCodes = Object.keys(bars).length;
      if (!nCodes) {
        notes.push(`d1_no_bars:${p.period_id}`);
        panels.push({
          period_id: String(p.period_id),
          year: Number(p.year ?? 0),
          period_start: start,
          period_end: end,
          status: "data_missing",
          bars: {},
          source: "d1_bars_empty",
        });
        continue;
      }
      notes.push(
        `d1_loaded:${p.period_id}:codes=${nCodes}:days=${keep.size}:window=${start}..${end}`,
      );
      panels.push({
        period_id: String(p.period_id),
        year: Number(p.year ?? start.slice(0, 4)),
        period_start: start,
        period_end: end,
        status: "ok",
        bars,
        source: "d1:jquants_records:equities_bars_daily",
      });
    } catch (e) {
      notes.push(`d1_error:${p.period_id}:${String(e)}`);
      panels.push({
        period_id: String(p.period_id),
        year: Number(p.year ?? 0),
        period_start: start,
        period_end: end,
        status: "data_missing",
        bars: {},
        source: "d1_bars_error",
      });
    }
  }
  return { panels, notes };
}
