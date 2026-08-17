/**
 * W90 / w0816y — CF multi-logic × multi-period mass eval Worker.
 *
 * Research factory only:
 *  - Does NOT arm Mass / READY / operational GO / continuous paper / live
 *  - Lite shard: bounded codes × days × periods × logics
 *  - Writes R2 quant-structured under research/mass_factory/job={id}/
 *
 * Endpoints:
 *  GET  /health
 *  POST /v1/research/mass_eval   (Bearer RESEARCH_RUN_TOKEN)
 */

export interface Env {
  STRUCTURED_BUCKET: R2Bucket;
  DB: D1Database;
  AI?: Ai;
  RESEARCH_RUN_TOKEN?: string;
  INGESTION_RUN_TOKEN?: string;
  MASS_RESEARCH?: string;
  PHASE7?: string;
  READY_DECLARED?: string;
  OPERATIONAL_GO?: string;
  CONTINUOUS_PAPER?: string;
  WAVE?: string;
  VERSION?: string;
  DEFAULT_MAX_CODES?: string;
  DEFAULT_MAX_DAYS?: string;
}

interface LogicSpec {
  logic_id: string;
  family_id: string;
  params?: Record<string, unknown>;
  thesis?: string;
  signal_definition?: string;
  position_rule?: string;
  datasets_used?: string[];
  logic_fingerprint?: string;
}

interface PeriodSpec {
  period_id: string;
  start: string;
  end: string;
}

interface JobSpec {
  job_id: string;
  version?: string;
  wave?: string;
  seed?: number;
  logics: LogicSpec[];
  periods: PeriodSpec[];
  max_codes?: number;
  max_days?: number;
  one_way_cost?: number;
  artifact?: {
    bucket?: string;
    prefix?: string;
    batch_summary_r2_key?: string;
    results_r2_key?: string;
    screens_r2_key?: string;
    ranking_r2_key?: string;
    manifest_r2_key?: string;
    input_plan_r2_key?: string;
  };
}

type BarPoint = { date: string; close: number };
type BarsByCode = Record<string, BarPoint[]>;

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-mass-research": "NO-GO",
      "x-ready-declared": "false",
      "x-continuous-paper": "UNARMED",
    },
  });
}

function unauthorized(msg = "unauthorized"): Response {
  return json({ error: msg, status: "unauthorized" }, 401);
}

function freeze(env: Env) {
  return {
    mass_research: env.MASS_RESEARCH || "NO-GO",
    phase7: env.PHASE7 || "OFF",
    ready_declared: false,
    operational_go: false,
    continuous_paper: env.CONTINUOUS_PAPER || "UNARMED",
    live_orders: false,
    s1_s5_unreject: false,
    simple_daily_sign_as_diversity: false,
    frozen_defaults_retuned: false,
  };
}

function checkToken(env: Env, request: Request): boolean {
  const expected =
    (env.RESEARCH_RUN_TOKEN || env.INGESTION_RUN_TOKEN || "").trim();
  // Fail-open only when no secret is bound (local smoke); production must set secret.
  if (!expected) return true;
  const auth = request.headers.get("Authorization") || "";
  const bearer = auth.toLowerCase().startsWith("bearer ")
    ? auth.slice(7).trim()
    : "";
  const headerTok = (request.headers.get("X-Research-Run-Token") || "").trim();
  return bearer === expected || headerTok === expected;
}

function mean(xs: number[]): number | null {
  if (!xs.length) return null;
  let s = 0;
  for (const x of xs) s += x;
  return s / xs.length;
}

function tStat(xs: number[]): number | null {
  if (xs.length < 2) return null;
  const m = mean(xs);
  if (m === null) return null;
  let v = 0;
  for (const x of xs) v += (x - m) * (x - m);
  const sd = Math.sqrt(v / (xs.length - 1));
  if (!(sd > 0)) return null;
  return m / (sd / Math.sqrt(xs.length));
}

function sharpe(xs: number[]): number | null {
  if (xs.length < 2) return null;
  const m = mean(xs);
  if (m === null) return null;
  let v = 0;
  for (const x of xs) v += (x - m) * (x - m);
  const sd = Math.sqrt(v / (xs.length - 1));
  if (!(sd > 0)) return null;
  return m / sd;
}

/** Sorted unique trading dates present in bars. */
function allDates(bars: BarsByCode): string[] {
  const set = new Set<string>();
  for (const pts of Object.values(bars)) {
    for (const p of pts) set.add(p.date);
  }
  return [...set].sort();
}

function closeOn(pts: BarPoint[], date: string): number | null {
  // binary search-ish linear (panels are small)
  for (let i = pts.length - 1; i >= 0; i--) {
    if (pts[i].date === date) return pts[i].close;
    if (pts[i].date < date) break;
  }
  // map lookup alternative
  const hit = pts.find((p) => p.date === date);
  return hit ? hit.close : null;
}

function buildCloseIndex(pts: BarPoint[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const p of pts) m.set(p.date, p.close);
  return m;
}

function momentum(
  idx: Map<string, number>,
  dates: string[],
  i: number,
  n: number
): number | null {
  if (i - n < 0) return null;
  const c0 = idx.get(dates[i - n]);
  const c1 = idx.get(dates[i]);
  if (c0 == null || c1 == null || !(c0 > 0)) return null;
  return c1 / c0 - 1;
}

function fwdReturn(
  idx: Map<string, number>,
  dates: string[],
  i: number,
  hold: number
): number | null {
  if (i + hold >= dates.length) return null;
  const c0 = idx.get(dates[i]);
  const c1 = idx.get(dates[i + hold]);
  if (c0 == null || c1 == null || !(c0 > 0)) return null;
  return c1 / c0 - 1;
}

function realizedVol(
  idx: Map<string, number>,
  dates: string[],
  i: number,
  n: number
): number | null {
  if (i - n < 1) return null;
  const rets: number[] = [];
  for (let k = i - n + 1; k <= i; k++) {
    const a = idx.get(dates[k - 1]);
    const b = idx.get(dates[k]);
    if (a == null || b == null || !(a > 0)) continue;
    rets.push(b / a - 1);
  }
  if (rets.length < 2) return null;
  const m = mean(rets)!;
  let v = 0;
  for (const r of rets) v += (r - m) * (r - m);
  return Math.sqrt(v / (rets.length - 1));
}

/** Cross-section rank L-S sticky / daily. */
function evalXs(
  bars: BarsByCode,
  params: Record<string, unknown>,
  oneWay: number
): { status: string; net: number | null; gross: number | null; n: number; activation: number | null } {
  const momN = Number(params.momentum_n ?? 5);
  const hold = Number(params.hold_days ?? 10);
  const longFrac = Number(params.long_frac ?? 0.3);
  const shortFrac = Number(params.short_frac ?? 0.3);
  const dates = allDates(bars);
  if (dates.length < momN + hold + 2) {
    return { status: "data_missing", net: null, gross: null, n: 0, activation: null };
  }
  const codes = Object.keys(bars);
  const indexes: Record<string, Map<string, number>> = {};
  for (const c of codes) indexes[c] = buildCloseIndex(bars[c]);

  const dayRets: number[] = [];
  let actSum = 0;
  let actN = 0;
  // sample every `hold` days to approximate sticky (lite)
  const step = Math.max(1, Math.min(hold, 5));
  for (let i = momN; i + hold < dates.length; i += step) {
    const scored: { code: string; mom: number }[] = [];
    for (const c of codes) {
      const m = momentum(indexes[c], dates, i, momN);
      if (m == null) continue;
      scored.push({ code: c, mom: m });
    }
    if (scored.length < 4) continue;
    scored.sort((a, b) => b.mom - a.mom);
    const nLong = Math.max(1, Math.floor(scored.length * longFrac));
    const nShort = Math.max(1, Math.floor(scored.length * shortFrac));
    const longs = scored.slice(0, nLong);
    const shorts = scored.slice(-nShort);
    const rets: number[] = [];
    for (const L of longs) {
      const r = fwdReturn(indexes[L.code], dates, i, hold);
      if (r != null) rets.push(r);
    }
    for (const S of shorts) {
      const r = fwdReturn(indexes[S.code], dates, i, hold);
      if (r != null) rets.push(-r);
    }
    if (!rets.length) continue;
    const g = mean(rets)!;
    // amortize round-trip cost over hold
    const cost = (2 * oneWay) / Math.max(1, hold);
    dayRets.push(g - cost);
    actSum += (longs.length + shorts.length) / scored.length;
    actN += 1;
  }
  if (!dayRets.length) {
    return { status: "data_missing", net: null, gross: null, n: 0, activation: null };
  }
  const net = mean(dayRets);
  return {
    status: "ok",
    net,
    gross: net === null ? null : net + (2 * oneWay) / Math.max(1, hold),
    n: dayRets.length,
    activation: actN ? actSum / actN : null,
  };
}

/** Multi-day hold momentum / mean-reversion (sign polarity). */
function evalMdh(
  bars: BarsByCode,
  params: Record<string, unknown>,
  oneWay: number,
  polarity: number
): { status: string; net: number | null; gross: number | null; n: number; activation: number | null } {
  const hold = Number(params.hold_days ?? params.momentum_n ?? 10);
  const momN = Number(params.momentum_n ?? hold);
  const dates = allDates(bars);
  if (dates.length < momN + hold + 2) {
    return { status: "data_missing", net: null, gross: null, n: 0, activation: null };
  }
  const codes = Object.keys(bars);
  const indexes: Record<string, Map<string, number>> = {};
  for (const c of codes) indexes[c] = buildCloseIndex(bars[c]);
  const dayRets: number[] = [];
  let actSum = 0;
  let actN = 0;
  const step = Math.max(1, Math.min(hold, 5));
  for (let i = momN; i + hold < dates.length; i += step) {
    const rets: number[] = [];
    let active = 0;
    for (const c of codes) {
      const m = momentum(indexes[c], dates, i, momN);
      if (m == null) continue;
      const sign = Math.sign(m) * polarity;
      if (sign === 0) continue;
      const r = fwdReturn(indexes[c], dates, i, hold);
      if (r == null) continue;
      rets.push(sign * r);
      active += 1;
    }
    if (!rets.length) continue;
    const g = mean(rets)!;
    const cost = (2 * oneWay) / Math.max(1, hold);
    dayRets.push(g - cost);
    actSum += active / Math.max(1, codes.length);
    actN += 1;
  }
  if (!dayRets.length) {
    return { status: "data_missing", net: null, gross: null, n: 0, activation: null };
  }
  const net = mean(dayRets);
  return {
    status: "ok",
    net,
    gross: net === null ? null : net + (2 * oneWay) / Math.max(1, hold),
    n: dayRets.length,
    activation: actN ? actSum / actN : null,
  };
}

/** Vol-risk-adjusted: mom / vol gate. */
function evalVol(
  bars: BarsByCode,
  params: Record<string, unknown>,
  oneWay: number
): { status: string; net: number | null; gross: number | null; n: number; activation: number | null } {
  const hold = Number(params.hold_days ?? 5);
  const volN = Number(params.vol_n ?? 10);
  const thr = Number(params.vol_threshold ?? 1.0);
  const gate = String(params.gate_mode ?? "mom_over_vol");
  const dates = allDates(bars);
  if (dates.length < volN + hold + 2) {
    return { status: "data_missing", net: null, gross: null, n: 0, activation: null };
  }
  const codes = Object.keys(bars);
  const indexes: Record<string, Map<string, number>> = {};
  for (const c of codes) indexes[c] = buildCloseIndex(bars[c]);
  const dayRets: number[] = [];
  let actSum = 0;
  let actN = 0;
  const step = Math.max(1, Math.min(hold, 5));
  for (let i = volN; i + hold < dates.length; i += step) {
    const rets: number[] = [];
    let active = 0;
    for (const c of codes) {
      const m = momentum(indexes[c], dates, i, Math.min(5, volN));
      const v = realizedVol(indexes[c], dates, i, volN);
      if (m == null || v == null || !(v > 0)) continue;
      let take = false;
      let sign = Math.sign(m);
      if (gate === "low_vol_long") {
        take = v < thr * 0.02 && m > 0;
        sign = 1;
      } else {
        // mom_over_vol: trade when |mom|/vol exceeds threshold proxy
        take = Math.abs(m) / v >= thr * 0.5;
      }
      if (!take || sign === 0) continue;
      const r = fwdReturn(indexes[c], dates, i, hold);
      if (r == null) continue;
      rets.push(sign * r);
      active += 1;
    }
    if (!rets.length) continue;
    const g = mean(rets)!;
    const cost = (2 * oneWay) / Math.max(1, hold);
    dayRets.push(g - cost);
    actSum += active / Math.max(1, codes.length);
    actN += 1;
  }
  if (!dayRets.length) {
    return { status: "data_missing", net: null, gross: null, n: 0, activation: null };
  }
  const net = mean(dayRets);
  return {
    status: "ok",
    net,
    gross: net === null ? null : net + (2 * oneWay) / Math.max(1, hold),
    n: dayRets.length,
    activation: actN ? actSum / actN : null,
  };
}

function evaluateLogicOnBars(
  logic: LogicSpec,
  bars: BarsByCode,
  oneWay: number
): {
  status: string;
  net: number | null;
  gross: number | null;
  n: number;
  activation: number | null;
  note?: string;
} {
  const fid = logic.family_id || "";
  const lid = logic.logic_id || "";
  const params = logic.params || {};
  // Bar-native families only on CF lite path
  if (
    fid === "cross_section_relative" ||
    lid.startsWith("xs_")
  ) {
    return evalXs(bars, params, oneWay);
  }
  if (fid === "multi_day_hold" || lid.startsWith("mdh_")) {
    const pol = Number(params.signal_polarity ?? (lid.includes("reversion") ? -1 : 1));
    return evalMdh(bars, params, oneWay, pol);
  }
  if (fid === "vol_risk_adjusted" || lid.startsWith("vol_")) {
    return evalVol(bars, params, oneWay);
  }
  // Non-bar-native on CF without extra panels → data_missing (honest)
  return {
    status: "data_missing",
    net: null,
    gross: null,
    n: 0,
    activation: null,
    note: "non_bar_native_on_cf_lite_requires_extra_panel",
  };
}

async function loadBarsPanel(
  env: Env,
  period: PeriodSpec,
  maxCodes: number,
  maxDays: number
): Promise<{ bars: BarsByCode; n_rows: number; codes: string[]; dates: string[] }> {
  // Pick active codes by row count in window
  const codeRows = await env.DB.prepare(
    `SELECT code, COUNT(*) AS n
     FROM jquants_daily_bars
     WHERE date >= ? AND date <= ?
       AND adjustment_close IS NOT NULL
     GROUP BY code
     HAVING n >= 10
     ORDER BY n DESC
     LIMIT ?`
  )
    .bind(period.start, period.end, maxCodes)
    .all<{ code: string; n: number }>();

  const codes = (codeRows.results || []).map((r) => r.code);
  if (!codes.length) {
    return { bars: {}, n_rows: 0, codes: [], dates: [] };
  }

  // Load bars for selected codes
  const placeholders = codes.map(() => "?").join(",");
  const barRows = await env.DB.prepare(
    `SELECT code, date,
            COALESCE(adjustment_close, close) AS px
     FROM jquants_daily_bars
     WHERE date >= ? AND date <= ?
       AND code IN (${placeholders})
       AND COALESCE(adjustment_close, close) IS NOT NULL
     ORDER BY date, code`
  )
    .bind(period.start, period.end, ...codes)
    .all<{ code: string; date: string; px: number }>();

  const bars: BarsByCode = {};
  let n = 0;
  const dateSet = new Set<string>();
  for (const row of barRows.results || []) {
    const px = Number(row.px);
    if (!Number.isFinite(px) || !(px > 0)) continue;
    if (!bars[row.code]) bars[row.code] = [];
    bars[row.code].push({ date: row.date, close: px });
    dateSet.add(row.date);
    n += 1;
  }
  // Cap days from the end of the window
  const dates = [...dateSet].sort();
  const keepDates =
    dates.length > maxDays ? new Set(dates.slice(-maxDays)) : new Set(dates);
  if (dates.length > maxDays) {
    for (const c of Object.keys(bars)) {
      bars[c] = bars[c].filter((p) => keepDates.has(p.date));
      if (!bars[c].length) delete bars[c];
    }
  }
  return {
    bars,
    n_rows: n,
    codes: Object.keys(bars),
    dates: [...keepDates].sort(),
  };
}

function screenOne(
  meanNet: number | null,
  nOk: number,
  activation: number | null
): { survived: boolean; reject_reasons: string[] } {
  const reasons: string[] = [];
  if (nOk <= 0) reasons.push("no_ok_periods");
  if (meanNet == null && nOk > 0) reasons.push("near_zero_after_cost");
  if (meanNet != null && Math.abs(meanNet) < 0.0005) reasons.push("near_zero_after_cost");
  if (activation != null && activation < 0.01 && nOk > 0) reasons.push("low_activation");
  // both-sign not evaluated on CF lite; original sign only
  return { survived: reasons.length === 0 && nOk > 0, reject_reasons: reasons };
}

async function runMassEval(env: Env, job: JobSpec): Promise<Record<string, unknown>> {
  const t0 = Date.now();
  const maxCodes = Math.max(
    3,
    Math.min(Number(job.max_codes ?? env.DEFAULT_MAX_CODES ?? 15), 40)
  );
  const maxDays = Math.max(
    15,
    Math.min(Number(job.max_days ?? env.DEFAULT_MAX_DAYS ?? 60), 120)
  );
  const oneWay = Number(job.one_way_cost ?? 0.001);
  const logics = job.logics || [];
  const periods = job.periods || [];
  if (!job.job_id) throw new Error("job_id required");
  if (!logics.length) throw new Error("logics required");
  if (!periods.length) throw new Error("periods required");

  // Load panels per period
  const panels: {
    period_id: string;
    start: string;
    end: string;
    n_rows: number;
    n_codes: number;
    n_dates: number;
    bars: BarsByCode;
  }[] = [];
  for (const p of periods) {
    const loaded = await loadBarsPanel(env, p, maxCodes, maxDays);
    panels.push({
      period_id: p.period_id,
      start: p.start,
      end: p.end,
      n_rows: loaded.n_rows,
      n_codes: loaded.codes.length,
      n_dates: loaded.dates.length,
      bars: loaded.bars,
    });
  }

  const results: Record<string, unknown>[] = [];
  const screens: Record<string, unknown>[] = [];

  for (const logic of logics) {
    const periodRows: Record<string, unknown>[] = [];
    const nets: number[] = [];
    const acts: number[] = [];
    for (const panel of panels) {
      if (!Object.keys(panel.bars).length) {
        periodRows.push({
          period_id: panel.period_id,
          status: "data_missing",
          net: null,
          gross: null,
          n: 0,
        });
        continue;
      }
      const ev = evaluateLogicOnBars(logic, panel.bars, oneWay);
      periodRows.push({
        period_id: panel.period_id,
        status: ev.status,
        net: ev.net,
        gross: ev.gross,
        n: ev.n,
        activation: ev.activation,
        note: ev.note,
      });
      if (ev.status === "ok" && ev.net != null && Number.isFinite(ev.net)) {
        nets.push(ev.net);
        if (ev.activation != null) acts.push(ev.activation);
      }
    }
    const meanNet = mean(nets);
    const meanGross = mean(
      periodRows
        .map((r) => r.gross as number | null)
        .filter((x): x is number => x != null && Number.isFinite(x))
    );
    const meanAct = mean(acts);
    const ts = tStat(nets);
    const sh = sharpe(nets);
    const nOk = nets.length;
    const scr = screenOne(meanNet, nOk, meanAct);
    const row = {
      strategy_id: `cf:${logic.logic_id}`,
      logic_id: logic.logic_id,
      family_id: logic.family_id,
      thesis: logic.thesis,
      params: logic.params || {},
      n_periods_ok: nOk,
      n_periods_total: panels.length,
      mean_net: meanNet,
      mean_gross: meanGross,
      t_stat: ts,
      sharpe_period: sh,
      mean_activation: meanAct,
      chosen_sign: 1,
      period_rows: periodRows,
      status: nOk > 0 ? "evaluated" : "data_missing",
      screen: scr,
    };
    results.push(row);
    screens.push({
      strategy_id: row.strategy_id,
      logic_id: logic.logic_id,
      family_id: logic.family_id,
      survived: scr.survived,
      reject_reasons: scr.reject_reasons,
      mean_net: meanNet,
      t_stat: ts,
      sharpe_period: sh,
      chosen_sign: 1,
      n_periods_ok: nOk,
    });
  }

  const survivors = screens.filter((s) => s.survived);
  const ranking = [...survivors].sort((a, b) => {
    const ta = Math.abs(Number(a.t_stat ?? -1));
    const tb = Math.abs(Number(b.t_stat ?? -1));
    if (tb !== ta) return tb - ta;
    return Number(b.mean_net ?? -1e9) - Number(a.mean_net ?? -1e9);
  });

  const prefix =
    job.artifact?.prefix || `research/mass_factory/job=${job.job_id}`;
  const keys = {
    manifest_r2_key:
      job.artifact?.manifest_r2_key || `${prefix}/manifest.json`,
    input_plan_r2_key:
      job.artifact?.input_plan_r2_key || `${prefix}/input_plan.json`,
    batch_summary_r2_key:
      job.artifact?.batch_summary_r2_key || `${prefix}/batch_summary.json`,
    results_r2_key: job.artifact?.results_r2_key || `${prefix}/results.json`,
    screens_r2_key: job.artifact?.screens_r2_key || `${prefix}/screens.json`,
    ranking_r2_key: job.artifact?.ranking_r2_key || `${prefix}/ranking.json`,
  };

  const summary = {
    status: "ok",
    version: env.VERSION || "cf-mass-eval-job/v1",
    wave: env.WAVE || "W90 / w0816y",
    job_id: job.job_id,
    seed: job.seed ?? null,
    n_logics: logics.length,
    n_periods: periods.length,
    n_logic_period_cells: logics.length * periods.length,
    n_evaluated: results.filter((r) => r.status === "evaluated").length,
    n_survivors: survivors.length,
    n_screen_rejected: screens.length - survivors.length,
    fail_rate: 0,
    max_codes: maxCodes,
    max_days: maxDays,
    one_way_cost: oneWay,
    panel_stats: panels.map((p) => ({
      period_id: p.period_id,
      start: p.start,
      end: p.end,
      n_rows: p.n_rows,
      n_codes: p.n_codes,
      n_dates: p.n_dates,
    })),
    artifact_keys: keys,
    wall_time_ms: Date.now() - t0,
    ...freeze(env),
  };

  // Write R2 artifacts
  const r2_puts: Record<string, unknown>[] = [];
  const put = async (key: string, body: unknown) => {
    const bytes = new TextEncoder().encode(JSON.stringify(body, null, 2));
    await env.STRUCTURED_BUCKET.put(key, bytes, {
      httpMetadata: { contentType: "application/json" },
    });
    r2_puts.push({
      bucket: "quant-structured",
      key,
      bytes: bytes.byteLength,
      status: "put_ok",
    });
  };

  await put(keys.manifest_r2_key, {
    job_id: job.job_id,
    version: summary.version,
    wave: summary.wave,
    artifact: keys,
    ...freeze(env),
  });
  await put(keys.input_plan_r2_key, {
    job_id: job.job_id,
    logics: logics.map((l) => ({
      logic_id: l.logic_id,
      family_id: l.family_id,
      params: l.params,
    })),
    periods,
    max_codes: maxCodes,
    max_days: maxDays,
  });
  await put(keys.batch_summary_r2_key, summary);
  await put(keys.results_r2_key, results);
  await put(keys.screens_r2_key, screens);
  await put(keys.ranking_r2_key, ranking);

  return {
    ...summary,
    results,
    screens,
    ranking,
    r2_puts,
  };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json({
        ok: true,
        service: "quant-platform-mass-eval",
        version: env.VERSION || "cf-mass-eval-job/v1",
        wave: env.WAVE || "W90 / w0816y",
        ...freeze(env),
        endpoints: ["GET /health", "POST /v1/research/mass_eval"],
      });
    }

    if (request.method === "POST" && url.pathname === "/v1/research/mass_eval") {
      if (!checkToken(env, request)) return unauthorized();
      let body: JobSpec;
      try {
        body = (await request.json()) as JobSpec;
      } catch {
        return json({ error: "invalid_json", status: "error" }, 400);
      }
      try {
        const out = await runMassEval(env, body);
        return json(out, 200);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return json(
          {
            status: "worker_error",
            error: msg,
            job_id: body?.job_id ?? null,
            ...freeze(env),
          },
          500
        );
      }
    }

    return json({ error: "not_found", path: url.pathname }, 404);
  },
};
