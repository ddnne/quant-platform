/// <reference types="@cloudflare/workers-types" />

import { authorized } from "./authorized";
import {
  bindIdempotencyKey,
  CONTROL_PLANE_LEDGER_NAME,
  PILOT_BUDGET_CAPS,
} from "./budget_do";
import { BudgetLedger } from "./budget_http";
import { json } from "./http_json";
import {
  decodeGatewayRequest,
  decodeTypedArtifact,
  estimateCostUsd,
  parseModelJson,
  type GatewayOk,
  type GatewayRequest,
} from "./schema";
import { sha256Hex } from "./sha256";

export { authorized } from "./authorized";
export { BudgetLedger };

export interface GatewayEnv {
  AI?: Ai;
  GATEWAY_TOKEN?: string;
  /** Separate mass-eval secret. Never a GATEWAY_TOKEN substitute. */
  MASS_EVAL_TOKEN?: string;
  BUDGET_LEDGER?: DurableObjectNamespace;
}

function extractModelValue(
  res: unknown,
): { ok: true; value: unknown; rawForTokens: string } | { ok: false; error: string } {
  if (typeof res === "string") {
    const parsed = parseModelJson(res);
    if (!parsed.ok) return parsed;
    return { ok: true, value: parsed.value, rawForTokens: res };
  }
  if (res && typeof res === "object" && !Array.isArray(res)) {
    const rec = res as Record<string, unknown>;
    if (typeof rec.response === "string") {
      const parsed = parseModelJson(rec.response);
      if (!parsed.ok) return parsed;
      return { ok: true, value: parsed.value, rawForTokens: rec.response };
    }
    if (rec.response && typeof rec.response === "object") {
      return {
        ok: true,
        value: rec.response,
        rawForTokens: JSON.stringify(rec.response),
      };
    }
    if (typeof rec.text === "string") {
      const parsed = parseModelJson(rec.text);
      if (!parsed.ok) return parsed;
      return { ok: true, value: parsed.value, rawForTokens: rec.text };
    }
  }
  return { ok: false, error: "model output is not JSON" };
}

type CachedBudgetBody = { http_status: number; body: unknown };

type BudgetRpc = {
  ok: boolean;
  status?: number;
  error?: string;
  detail?: string;
  lease_id?: string;
  existing?: boolean;
  budget_run_id?: string;
  reservation_status?: string;
  cached_result?: CachedBudgetBody | null;
};

function parseCachedResult(raw: unknown): CachedBudgetBody | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const rec = raw as Record<string, unknown>;
  const httpStatus = Number(rec.http_status);
  if (!Number.isInteger(httpStatus) || httpStatus < 1) return null;
  return { http_status: httpStatus, body: rec.body };
}

async function budgetRpc(env: GatewayEnv, path: string, body: unknown): Promise<BudgetRpc> {
  if (!env.BUDGET_LEDGER) {
    return { ok: false, status: 503, error: "budget_ledger_unbound" };
  }
  const id = env.BUDGET_LEDGER.idFromName(CONTROL_PLANE_LEDGER_NAME);
  const stub = env.BUDGET_LEDGER.get(id);
  const res = await stub.fetch(
    new Request(`https://budget${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
  let parsed: unknown;
  try {
    parsed = await res.json();
  } catch {
    return { ok: false, status: res.status, error: "budget_rpc_invalid_json" };
  }
  if (!parsed || typeof parsed !== "object") {
    return { ok: false, status: res.status, error: "budget_rpc_invalid_json" };
  }
  const rec = parsed as Record<string, unknown>;
  const lease =
    rec.lease && typeof rec.lease === "object" ? (rec.lease as Record<string, unknown>) : {};
  const reservation =
    rec.reservation && typeof rec.reservation === "object"
      ? (rec.reservation as Record<string, unknown>)
      : {};
  const budgetRunId =
    (typeof rec.budget_run_id === "string" && rec.budget_run_id) ||
    (typeof reservation.reservation_id === "string" && reservation.reservation_id) ||
    undefined;
  return {
    ok: rec.ok === true,
    status: res.status,
    error: typeof rec.error === "string" ? rec.error : undefined,
    detail: typeof rec.detail === "string" ? rec.detail : undefined,
    lease_id: typeof lease.lease_id === "string" ? lease.lease_id : undefined,
    existing: rec.existing === true,
    budget_run_id: budgetRunId,
    reservation_status:
      typeof reservation.status === "string" ? reservation.status : undefined,
    cached_result: parseCachedResult(reservation.cached_result),
  };
}

function completeRequestDigestPayload(req: GatewayRequest): string {
  return JSON.stringify({
    model: req.model,
    messages: req.messages,
    max_tokens: req.max_tokens,
    expected_schema: req.expected_schema ?? "",
    prompt_digest: req.prompt_digest ?? "",
    experiment_id: req.experiment_id ?? "",
    ready_snapshot_id: req.ready_snapshot_id ?? "",
  });
}

function cachedResponse(cached: CachedBudgetBody): Response {
  return json(cached.body, cached.http_status);
}

function tokenCount(
  res: unknown,
  fallbackText: string,
  prompt: string,
): { input: number; output: number } {
  const rec = res && typeof res === "object" ? (res as Record<string, unknown>) : {};
  const usage =
    rec.usage && typeof rec.usage === "object" ? (rec.usage as Record<string, unknown>) : {};
  const input = Number(usage.prompt_tokens ?? usage.input_tokens ?? 0);
  const output = Number(usage.completion_tokens ?? usage.output_tokens ?? 0);
  return {
    input: Number.isFinite(input) && input > 0 ? input : Math.ceil(prompt.length / 4),
    output: Number.isFinite(output) && output > 0 ? output : Math.ceil(fallbackText.length / 4),
  };
}

export default {
  async fetch(request: Request, env: GatewayEnv): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" || url.pathname === "/") {
      if (request.method !== "GET") return json({ error: "GET required" }, 405);
      return json({ ok: true, service: "quant-platform-research-ai-gateway" });
    }
    if (url.pathname !== "/v1/complete") {
      return json({ error: "not found" }, 404);
    }
    if (request.method !== "POST") return json({ error: "POST required" }, 405);
    if (!(await authorized(request, env))) {
      return json({ error: "unauthorized" }, 401);
    }
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json({ ok: false, error: "invalid JSON body" }, 400);
    }
    const parsed = decodeGatewayRequest(body);
    if (!parsed.ok) {
      return json({ ok: false, error: parsed.error }, 400);
    }
    const req = parsed.value;
    if (!env.BUDGET_LEDGER) {
      return json({ ok: false, error: "budget_ledger_unbound" }, 503);
    }
    if (!env.AI) {
      return json({ ok: false, error: "ai_binding_unbound" }, 503);
    }
    const prompt = req.messages.map((m) => `${m.role}:${m.content}`).join("\n");
    const promptDigest = req.prompt_digest || `sha256:${await sha256Hex(prompt)}`;
    const requestDigest = await sha256Hex(completeRequestDigestPayload(req));
    const bound = bindIdempotencyKey(request.headers.get("Idempotency-Key"), requestDigest);
    if (!bound.ok) {
      return json({ ok: false, error: bound.error }, 400);
    }
    const estimatedInput = Math.min(
      PILOT_BUDGET_CAPS.max_input_tokens,
      Math.max(64, Math.ceil(prompt.length / 2)),
    );
    const estimatedCost = estimateCostUsd(req.model, estimatedInput, req.max_tokens);
    const reserveAmounts = {
      model_calls: 1,
      input_tokens: estimatedInput,
      output_tokens: req.max_tokens,
      cost_usd: estimatedCost,
    };
    const reserved = await budgetRpc(env, "/reserve", {
      idempotency_key: bound.idempotency_key,
      request_digest: bound.request_digest,
      acquire_lease: true,
      amounts: reserveAmounts,
    });
    if (!reserved.ok) {
      return json(
        { ok: false, error: reserved.error || "budget_exhausted", detail: reserved.detail },
        reserved.status || 429,
      );
    }
    const budgetRunId = reserved.budget_run_id;
    if (reserved.cached_result) {
      return cachedResponse(reserved.cached_result);
    }
    if (reserved.existing) {
      return json(
        {
          ok: false,
          error: "budget_in_progress",
          budget_run_id: budgetRunId,
        },
        409,
      );
    }

    const failClosed = async (
      errorBody: Record<string, unknown>,
      httpStatus: number,
      amounts: {
        model_calls: number;
        input_tokens: number;
        output_tokens: number;
        cost_usd: number;
      },
    ): Promise<Response> => {
      const body = { ...errorBody, budget_run_id: budgetRunId };
      const finalized = await budgetRpc(env, "/finalize", {
        idempotency_key: bound.idempotency_key,
        amounts,
        result: { http_status: httpStatus, body },
      });
      if (!finalized.ok) {
        return json(
          {
            ok: false,
            error: finalized.error || "budget_finalize_failed",
            detail: finalized.detail,
            budget_run_id: budgetRunId,
          },
          finalized.status || 500,
        );
      }
      return json(body, httpStatus);
    };

    try {
      const res = await env.AI.run(req.model, {
        messages: req.messages,
        max_tokens: req.max_tokens,
      });
      const extracted = extractModelValue(res);
      const tokens = tokenCount(
        res,
        extracted.ok ? extracted.rawForTokens : "",
        prompt,
      );
      const actual = {
        model_calls: 1,
        input_tokens: tokens.input,
        output_tokens: tokens.output,
        cost_usd: estimateCostUsd(req.model, tokens.input, tokens.output),
      };
      if (!extracted.ok) {
        return failClosed({ ok: false, error: extracted.error }, 400, actual);
      }
      const decoded = decodeTypedArtifact(extracted.value, req.expected_schema);
      if (!decoded.ok) {
        return failClosed({ ok: false, error: decoded.error }, 400, actual);
      }
      const canonical = JSON.stringify(decoded.value.artifact);
      const outputDigest = `sha256:${await sha256Hex(canonical)}`;
      const payload: GatewayOk = {
        ok: true,
        schema: decoded.value.schema_name,
        schema_version: decoded.value.schema_version,
        artifact: decoded.value.artifact,
        model: req.model,
        input_tokens: tokens.input,
        output_tokens: tokens.output,
        monetary_cost_usd: estimateCostUsd(req.model, tokens.input, tokens.output),
        prompt_digest: promptDigest,
        output_digest: outputDigest,
        ready_snapshot_id: req.ready_snapshot_id ?? null,
        experiment_id: req.experiment_id ?? null,
        budget_id: req.budget_id,
        budget_run_id: budgetRunId || "",
      };
      const finalized = await budgetRpc(env, "/finalize", {
        idempotency_key: bound.idempotency_key,
        amounts: actual,
        result: { http_status: 200, body: payload },
      });
      if (!finalized.ok) {
        return json(
          {
            ok: false,
            error: finalized.error || "budget_finalize_failed",
            detail: finalized.detail,
            budget_run_id: budgetRunId,
          },
          finalized.status || 500,
        );
      }
      return json(payload);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return failClosed(
        { ok: false, error: "ai_run_failed", detail: msg.slice(0, 180) },
        502,
        reserveAmounts,
      );
    }
  },
};
