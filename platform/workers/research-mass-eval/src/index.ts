/// <reference types="@cloudflare/workers-types" />

import { evaluateLogicAcrossPeriods, rankSurvivors } from "./eval";
import {
  cellsFromPeriodPacks,
  evalLogicDailyPathOnPanel,
} from "./daily_path";
import {
  buildSyntheticPanels,
  defaultPeriodsFromRequest,
  loadD1BarsPanels,
  loadR2Panels,
} from "./panels";
import type { Env, LogicSpec, MassEvalJobResult, MassEvalRequest } from "./types";

const RESEARCH_PREFIX = "research/mass_eval";
const MAX_LOGICS = 200;
const MAX_PERIODS = 24;

function freezePayload(env: Env) {
  return {
    mass_research: env.MASS_RESEARCH || "NO-GO",
    phase7: env.PHASE7 || "OFF",
    ready_declared: String(env.READY_DECLARED || "false") === "true",
    operational_go: String(env.OPERATIONAL_GO || "false") === "true",
    continuous_paper: env.CONTINUOUS_PAPER || "UNARMED",
    frozen_defaults_retuned: false,
    connected_to_ready: false,
    connected_to_mass: false,
  };
}

async function tokenMatches(provided: string, expected: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(provided)),
    crypto.subtle.digest("SHA-256", enc.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

async function authorized(request: Request, expected?: string): Promise<boolean> {
  if (!expected) return true;
  const got =
    request.headers.get("X-Mass-Eval-Token") ||
    request.headers.get("X-Ingestion-Token") ||
    "";
  if (!got) return false;
  return tokenMatches(got, expected);
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function parseRequest(body: unknown): { ok: true; value: MassEvalRequest } | { ok: false; error: string } {
  if (!isObject(body)) return { ok: false, error: "body must be JSON object" };

  const jobId = String(body.job_id ?? "").trim();
  if (!jobId) return { ok: false, error: "job_id required" };
  if (/[\\/]|\.\./.test(jobId)) {
    return { ok: false, error: "job_id must not contain path separators" };
  }

  const seed = Number(body.seed);
  if (!Number.isFinite(seed)) return { ok: false, error: "seed must be a number" };

  if (!Array.isArray(body.logics) || body.logics.length === 0) {
    return { ok: false, error: "logics[] required (non-empty)" };
  }
  if (body.logics.length > MAX_LOGICS) {
    return { ok: false, error: `logics length exceeds max ${MAX_LOGICS}` };
  }

  const logics: LogicSpec[] = [];
  for (let i = 0; i < body.logics.length; i++) {
    const raw = body.logics[i];
    if (!isObject(raw)) return { ok: false, error: `logics[${i}] must be object` };
    const logicId = String(raw.logic_id ?? raw.family_id ?? "").trim();
    if (!logicId) return { ok: false, error: `logics[${i}].logic_id required` };
    logics.push({
      logic_id: logicId,
      family_id: raw.family_id != null ? String(raw.family_id) : undefined,
      strategy_id: raw.strategy_id != null ? String(raw.strategy_id) : undefined,
      params: isObject(raw.params) ? (raw.params as Record<string, unknown>) : {},
      period_nets: Array.isArray(raw.period_nets)
        ? (raw.period_nets as Array<number | null>)
        : undefined,
      period_grosses: Array.isArray(raw.period_grosses)
        ? (raw.period_grosses as Array<number | null>)
        : undefined,
    });
  }

  let periods: MassEvalRequest["periods"];
  if (body.periods !== undefined) {
    if (!Array.isArray(body.periods)) {
      return { ok: false, error: "periods must be array when provided" };
    }
    if (body.periods.length > MAX_PERIODS) {
      return { ok: false, error: `periods length exceeds max ${MAX_PERIODS}` };
    }
    periods = body.periods.map((p, i) => {
      const o = isObject(p) ? p : {};
      const pStart =
        o.period_start != null
          ? String(o.period_start)
          : o.start != null
            ? String(o.start)
            : undefined;
      const pEnd =
        o.period_end != null
          ? String(o.period_end)
          : o.end != null
            ? String(o.end)
            : undefined;
      return {
        period_id: String(o.period_id ?? `p${i}`),
        year: o.year != null ? Number(o.year) : undefined,
        period_start: pStart,
        period_end: pEnd,
      };
    });
  }

  const modeRaw = body.mode != null ? String(body.mode) : "synthetic";
  const allowedModes = new Set(["synthetic", "r2_panels", "d1_bars", "nets_only"]);
  if (!allowedModes.has(modeRaw)) {
    return {
      ok: false,
      error: "mode must be synthetic | r2_panels | d1_bars | nets_only",
    };
  }

  return {
    ok: true,
    value: {
      seed,
      logics,
      periods,
      job_id: jobId,
      mode: modeRaw as MassEvalRequest["mode"],
      panels_prefix:
        body.panels_prefix != null ? String(body.panels_prefix) : undefined,
      one_way_cost:
        body.one_way_cost != null ? Number(body.one_way_cost) : undefined,
      eval_kind:
        body.eval_kind === "daily_path" ? "daily_path" : "screen",
      write_artifacts:
        body.write_artifacts === false ? false : true,
      max_codes: body.max_codes != null ? Number(body.max_codes) : undefined,
      max_days: body.max_days != null ? Number(body.max_days) : undefined,
      near_zero_abs:
        body.near_zero_abs != null ? Number(body.near_zero_abs) : undefined,
      min_activation:
        body.min_activation != null ? Number(body.min_activation) : undefined,
    },
  };
}

async function putJson(
  bucket: R2Bucket,
  key: string,
  data: unknown,
): Promise<{ key: string; bytes: number }> {
  const body = JSON.stringify(data, null, 2);
  const bytes = new TextEncoder().encode(body);
  await bucket.put(key, bytes, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    customMetadata: {
      plane: "research_mass_eval",
      wave: "research-mass-eval",
    },
  });
  return { key, bytes: bytes.byteLength };
}

async function runMassEval(
  env: Env,
  req: MassEvalRequest,
): Promise<MassEvalJobResult> {
  const t0 = Date.now();
  const version = env.MASS_EVAL_VERSION || "research-mass-eval/v21-cs-hoist";
  const wave = env.MASS_EVAL_WAVE || "research-mass-eval";
  const mode = req.mode || "synthetic";
  const oneWay = req.one_way_cost ?? 0.001;
  const maxCodes = Math.max(2, Math.min(40, req.max_codes ?? 8));
  const maxDays = Math.max(20, Math.min(260, req.max_days ?? 120));
  const periodSpecs = defaultPeriodsFromRequest(req.periods, req.seed);
  const panelsPrefix =
    req.panels_prefix || `research/mass_eval/job=${req.job_id}/panels`;

  let panels =
    mode === "nets_only"
      ? []
      : buildSyntheticPanels(periodSpecs, req.seed, maxCodes, maxDays);
  let panelNotes: string[] = [];

  if (mode === "r2_panels") {
    const loaded = await loadR2Panels(
      env.STRUCTURED_BUCKET,
      periodSpecs,
      panelsPrefix,
    );
    panels = loaded.panels;
    panelNotes = loaded.notes;
  } else if (mode === "d1_bars") {
    if (!env.DB) {
      panelNotes = ["d1_not_bound"];
      panels = periodSpecs.map((p) => ({
        period_id: String(p.period_id),
        year: Number(p.year ?? 0),
        period_start: p.period_start || "",
        period_end: p.period_end || "",
        status: "data_missing" as const,
        bars: {},
        source: "d1_not_bound",
      }));
    } else {
      const loaded = await loadD1BarsPanels(
        env.DB,
        periodSpecs,
        maxCodes,
        maxDays,
      );
      panels = loaded.panels;
      panelNotes = loaded.notes;
    }
  }

  const results = req.logics.map((logic, index) =>
    evaluateLogicAcrossPeriods(logic, panels, {
      oneWayCost: oneWay,
      nearZeroAbs: req.near_zero_abs,
      minActivation: req.min_activation,
      seed: req.seed,
      index,
    }),
  );

  const ranking = rankSurvivors(results);
  const nOk = results.filter((r) => r.status === "ok").length;
  const nFail = results.length - nOk;
  const nSurvivors = ranking.length;

  const prefix = `${RESEARCH_PREFIX}/job=${req.job_id}`;
  const freezes = freezePayload(env);

  const summary = {
    version,
    wave,
    job_id: req.job_id,
    seed: req.seed,
    mode,
    n_logics: req.logics.length,
    n_periods: periodSpecs.length,
    n_eval_ok: nOk,
    n_eval_fail: nFail,
    n_survivors: nSurvivors,
    n_survivors_are_not_a_pass: true,
    screen_kind: "period_net",
    daily_path_complete: false,
    candidate_grade: false,
    wall_time_ms: Date.now() - t0,
    freezes,
    note: "Period-net screen only; n_survivors is not a pass.",
  };

  const manifest = {
    version,
    wave,
    job_id: req.job_id,
    created_at: new Date().toISOString(),
    bucket: "quant-structured",
    prefix,
    keys: {
      manifest: `${prefix}/manifest.json`,
      request: `${prefix}/request.json`,
      summary: `${prefix}/summary.json`,
      results: `${prefix}/results.json`,
      ranking: `${prefix}/ranking.json`,
      panels_meta: `${prefix}/panels_meta.json`,
    },
    freezes,
  };

  const panelsMeta = {
    mode,
    n_panels: panels.length,
    notes: panelNotes,
    panels: panels.map((p) => ({
      period_id: p.period_id,
      year: p.year,
      status: p.status,
      source: p.source,
      n_codes: Object.keys(p.bars || {}).length,
      n_days: Object.values(p.bars || {})[0]?.length ?? 0,
    })),
  };

  await Promise.all([
    putJson(env.STRUCTURED_BUCKET, manifest.keys.manifest, manifest),
    putJson(env.STRUCTURED_BUCKET, manifest.keys.request, {
      ...req,
      freezes,
      received_at: new Date().toISOString(),
    }),
    putJson(env.STRUCTURED_BUCKET, manifest.keys.summary, summary),
    putJson(env.STRUCTURED_BUCKET, manifest.keys.results, {
      version,
      wave,
      job_id: req.job_id,
      results,
      freezes,
    }),
    putJson(env.STRUCTURED_BUCKET, manifest.keys.ranking, {
      version,
      wave,
      job_id: req.job_id,
      ranking,
      freezes,
    }),
    putJson(env.STRUCTURED_BUCKET, manifest.keys.panels_meta, panelsMeta),
  ]);

  return {
    version,
    wave,
    job_id: req.job_id,
    seed: req.seed,
    mode,
    n_logics: req.logics.length,
    n_periods: periodSpecs.length,
    n_eval_ok: nOk,
    n_eval_fail: nFail,
    n_survivors: nSurvivors,
    n_survivors_are_not_a_pass: true,
    screen_kind: "period_net",
    daily_path_complete: false,
    candidate_grade: false,
    wall_time_ms: Date.now() - t0,
    ranking,
    results,
    r2_keys: manifest.keys,
    freezes,
    note: summary.note,
  };
}

async function runDailyPath(
  env: Env,
  req: MassEvalRequest,
): Promise<Record<string, unknown>> {
  const t0 = Date.now();
  const version = env.MASS_EVAL_VERSION || "research-mass-eval/v21-cs-hoist";
  const mode = req.mode || "r2_panels";
  const oneWay = req.one_way_cost ?? 0.001;
  const maxCodes = Math.max(2, Math.min(40, req.max_codes ?? 8));
  const maxDays = Math.max(20, Math.min(260, req.max_days ?? 120));
  const periodSpecs = defaultPeriodsFromRequest(req.periods, req.seed);
  const panelsPrefix =
    req.panels_prefix || `research/mass_eval/job=${req.job_id}/panels`;

  let panels =
    mode === "nets_only"
      ? []
      : buildSyntheticPanels(periodSpecs, req.seed, maxCodes, maxDays);
  let panelNotes: string[] = [];
  if (mode === "r2_panels") {
    const loaded = await loadR2Panels(
      env.STRUCTURED_BUCKET,
      periodSpecs,
      panelsPrefix,
    );
    panels = loaded.panels;
    panelNotes = loaded.notes;
  } else if (mode === "d1_bars" && env.DB) {
    const loaded = await loadD1BarsPanels(
      env.DB,
      periodSpecs,
      maxCodes,
      maxDays,
    );
    panels = loaded.panels;
    panelNotes = loaded.notes;
  }

  const cells: Array<Record<string, unknown>> = [];
  for (const logic of req.logics) {
    const packs = panels.map((p) =>
      evalLogicDailyPathOnPanel(logic, p, oneWay),
    );
    cells.push(...cellsFromPeriodPacks(String(logic.logic_id), packs));
  }

  const nComplete = cells.filter((c) => c.daily_path_complete).length;
  const freezes = freezePayload(env);
  const payload: Record<string, unknown> = {
    version,
    wave: env.MASS_EVAL_WAVE || "research-mass-eval",
    job_id: req.job_id,
    eval_kind: "daily_path",
    candidate_grade: true,
    parallel_model: "isolate_fanout_one_logic",
    mode,
    n_logics: req.logics.length,
    n_periods: periodSpecs.length,
    n_cells: cells.length,
    n_daily_path_complete: nComplete,
    cells,
    panel_notes: panelNotes,
    panels_prefix: panelsPrefix,
    wall_time_ms: Date.now() - t0,
    survived: false,
    promote_as_main: false,
    go: false,
    freezes,
    note: "Candidate-grade daily MTM. Not a promotion.",
  };
  if (req.write_artifacts === true) {
    const prefix = `research/eval/job=${req.job_id}`;
    await putJson(env.STRUCTURED_BUCKET, `${prefix}/daily_path.json`, payload);
    payload.r2_keys = { daily_path: `${prefix}/daily_path.json` };
  }
  return payload;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health" || url.pathname === "/") {
      if (request.method !== "GET") {
        return json({ error: "GET required" }, 405);
      }
      return json({
        ok: true,
        service: "quant-platform-research-mass-eval",
        version: env.MASS_EVAL_VERSION || "research-mass-eval/v21-cs-hoist",
        wave: env.MASS_EVAL_WAVE || "research-mass-eval",
        has_structured_bucket: Boolean(env.STRUCTURED_BUCKET),
        has_d1: Boolean(env.DB),
        token_required: Boolean(env.MASS_EVAL_TOKEN),
        freezes: freezePayload(env),
      });
    }

    if (url.pathname === "/v1/mass-eval") {
      if (request.method !== "POST") {
        return json({ error: "POST required" }, 405);
      }
      if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
        return json({ error: "unauthorized" }, 401);
      }
      if (!env.STRUCTURED_BUCKET) {
        return json({ error: "STRUCTURED_BUCKET not bound" }, 500);
      }

      let body: unknown;
      try {
        body = await request.json();
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }

      const parsed = parseRequest(body);
      if (!parsed.ok) {
        return json({ error: parsed.error }, 400);
      }

      try {
        const result = await runMassEval(env, parsed.value);
        return json({
          ok: true,
          ...result,
        });
      } catch (e) {
        const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
        return json(
          {
            ok: false,
            error: "mass_eval_failed",
            detail: msg,
            freezes: freezePayload(env),
          },
          500,
        );
      }
    }

    if (url.pathname === "/v1/daily-path") {
      if (request.method !== "POST") {
        return json({ error: "POST required" }, 405);
      }
      if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
        return json({ error: "unauthorized" }, 401);
      }
      if (!env.STRUCTURED_BUCKET) {
        return json({ error: "STRUCTURED_BUCKET not bound" }, 500);
      }
      let body: unknown;
      try {
        body = await request.json();
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }
      const parsed = parseRequest(body);
      if (!parsed.ok) {
        return json({ error: parsed.error }, 400);
      }
      parsed.value.eval_kind = "daily_path";
      if ((body as { write_artifacts?: boolean }).write_artifacts !== true) {
        parsed.value.write_artifacts = false;
      }
      try {
        const result = await runDailyPath(env, parsed.value);
        return json({ ok: true, ...result });
      } catch (e) {
        const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
        return json(
          {
            ok: false,
            error: "daily_path_failed",
            detail: msg,
            freezes: freezePayload(env),
          },
          500,
        );
      }
    }

    return json({ error: "not found", path: url.pathname }, 404);
  },
};
