/// <reference types="@cloudflare/workers-types" />

import {
  netsOnlyGate,
  researchCapabilities,
  requireCapability,
} from "./capabilities";
import {
  authorized,
  freezePayload,
  isObject,
  json,
} from "./http";
import { runProposeThesis } from "./propose_thesis";
import type { Env, LogicSpec, MassEvalJobResult, MassEvalRequest } from "./types";

const MAX_LOGICS = 200;
const MAX_PERIODS = 24;

export type MassEvalFetchHandlers = {
  runMassEval: (env: Env, req: MassEvalRequest) => Promise<MassEvalJobResult>;
  runDailyPath: (
    env: Env,
    req: MassEvalRequest,
  ) => Promise<Record<string, unknown>>;
};

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

/** HTTP path dispatch. Orchestration stays in index.ts; R2 put stays in http.ts. */
export async function dispatchMassEvalFetch(
  request: Request,
  env: Env,
  handlers: MassEvalFetchHandlers,
): Promise<Response> {
  const url = new URL(request.url);

  if (url.pathname === "/health" || url.pathname === "/") {
    if (request.method !== "GET") {
      return json({ error: "GET required" }, 405);
    }
    return json({
      ok: true,
      service: "quant-platform-research-mass-eval",
      version: env.MASS_EVAL_VERSION || "research-mass-eval/v142-63-failclosed",
    });
  }

  if (url.pathname === "/v1/mass-eval") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const massCaps = researchCapabilities(env);
    const massGate = requireCapability("mass_screen", massCaps);
    if (!massGate.allowed) {
      return json(
        {
          ok: false,
          error: "capability_missing",
          capability: "mass_screen",
          reasons: massGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
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
    const netsGate = netsOnlyGate(parsed.value.mode, env, massGate.allowed);
    if (!netsGate.allowed) {
      return json(
        {
          ok: false,
          error: "nets_only_denied",
          capability: "mass_screen",
          reasons: netsGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }

    try {
      const result = await handlers.runMassEval(env, parsed.value);
      return json({
        ok: true,
        ...result,
      });
    } catch (e) {
      const code = (e as { code?: string }).code;
      if (code === "artifact_conflict") {
        return json(
          {
            ok: false,
            error: "artifact_conflict",
            job_id: parsed.value.job_id,
            go: false,
            not_a_pass: true,
          },
          409,
        );
      }
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
    const pathCaps = researchCapabilities(env);
    const pathGate = requireCapability("mass_screen", pathCaps);
    if (!pathGate.allowed) {
      return json(
        {
          ok: false,
          error: "capability_missing",
          capability: "mass_screen",
          reasons: pathGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
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
    const netsGate = netsOnlyGate(parsed.value.mode, env, pathGate.allowed);
    if (!netsGate.allowed) {
      return json(
        {
          ok: false,
          error: "nets_only_denied",
          capability: "mass_screen",
          reasons: netsGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }
    parsed.value.eval_kind = "daily_path";
    if ((body as { write_artifacts?: boolean }).write_artifacts !== true) {
      parsed.value.write_artifacts = false;
    }
    try {
      const result = await handlers.runDailyPath(env, parsed.value);
      if (result.artifact_conflict === true) {
        return json(
          {
            ok: false,
            error: "artifact_conflict",
            job_id: parsed.value.job_id,
            r2_keys: result.r2_keys,
            go: false,
            not_a_pass: true,
          },
          409,
        );
      }
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

  if (url.pathname === "/v1/propose-thesis") {
    if (request.method !== "POST") {
      return json({ error: "POST required" }, 405);
    }
    if (!(await authorized(request, env.MASS_EVAL_TOKEN))) {
      return json({ error: "unauthorized" }, 401);
    }
    const genCaps = researchCapabilities(env);
    const genGate = requireCapability("generation", genCaps);
    if (!genGate.allowed) {
      return json(
        {
          ok: false,
          error: "capability_missing",
          capability: "generation",
          reasons: genGate.reasons,
          go: false,
          not_a_pass: true,
        },
        403,
      );
    }
    let body: unknown = {};
    const text = await request.text();
    if (text.trim()) {
      try {
        body = JSON.parse(text);
      } catch {
        return json({ error: "invalid JSON body" }, 400);
      }
    }
    if (text.trim() && !isObject(body)) {
      return json({ error: "body must be JSON object" }, 400);
    }
    const obj = isObject(body) ? body : {};
    try {
      const result = await runProposeThesis(env, obj);
      // llm_failed is fail-closed success-of-contract (HTTP 200, ok:false).
      const status =
        result.error === "window_tweak_only_forbidden" ||
        result.error === "job_id required for write_artifacts" ||
        result.error === "STRUCTURED_BUCKET not bound"
          ? 400
          : 200;
      return json(result, status);
    } catch (e) {
      const msg = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
      return json(
        {
          ok: false,
          error: "propose_thesis_failed",
          detail: msg,
          auto_inject: false,
          go: false,
          not_a_pass: true,
          freezes: freezePayload(env),
        },
        500,
      );
    }
  }

  return json({ error: "not found", path: url.pathname }, 404);
}
