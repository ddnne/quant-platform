/**
 * Deterministic synthetic period panels for CF lite mass-eval.
 *
 * Mirrors mass_strategy_factory._synthetic_batch_context so the worker can
 * run without Python and without requiring full R2 history loads.
 *
 * mode=r2_panels: optional staged panels under
 *   research/mass_eval/panels/{period_id}.json
 */

import type { BarsByCode, PeriodPanel, PeriodSpec } from "./types";

const DEFAULT_YEARS = [2019, 2021, 2023, 2024, 2025];
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
      source: "synthetic_cf_lite",
    };
  });
}

/**
 * Load staged panels from R2 if present.
 * Expected key: research/mass_eval/panels/{period_id}.json
 * Shape: { period_id, year, bars: { code: [[date, close], ...] } }
 */
export async function loadR2Panels(
  bucket: R2Bucket,
  periods: PeriodSpec[],
): Promise<{ panels: PeriodPanel[]; notes: string[] }> {
  const panels: PeriodPanel[] = [];
  const notes: string[] = [];
  for (const p of periods) {
    const key = `research/mass_eval/panels/${p.period_id}.json`;
    const obj = await bucket.get(key);
    if (!obj) {
      notes.push(`missing:${key}`);
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
      };
      const bars = raw.bars || {};
      const nCodes = Object.keys(bars).length;
      if (nCodes === 0) {
        notes.push(`empty_bars:${key}`);
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
        source: `r2:${key}`,
      });
    } catch (e) {
      notes.push(`parse_error:${key}:${String(e)}`);
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
