/// <reference types="@cloudflare/workers-types" />

import { WorkerEntrypoint } from "cloudflare:workers";
import { authorized } from "./authorized";
import {
  bindIdempotencyKey,
  CONTROL_PLANE_LEDGER_NAME,
  type BudgetSettlement,
  type UncertainProviderReason,
} from "./budget_do";
import { BudgetLedger } from "./budget_http";
import { json } from "./http_json";
import {
  decodeGatewayRequest,
  decodeTypedArtifact,
  estimateCostUsd,
  parseModelJson,
  providerInputBounds,
  type GatewayOk,
  type GatewayRequest,
} from "./schema";
import { sha256Hex } from "./sha256";
import { AI_CALL_TIMEOUT_MS } from "./runtime_policy";

export { BudgetLedger };

export interface GatewayEnv {
  AI?: Ai;
  GATEWAY_TOKEN?: string;
  BUDGET_LEDGER?: DurableObjectNamespace;
}

export type GatewayServiceResult = {
  http_status: number;
  body: unknown;
};

function extractModelValue(
  res: unknown,
): { ok: true; value: unknown } | { ok: false; error: string } {
  if (typeof res === "string") {
    const parsed = parseModelJson(res);
    if (!parsed.ok) return parsed;
    return { ok: true, value: parsed.value };
  }
  if (res && typeof res === "object" && !Array.isArray(res)) {
    const rec = res as Record<string, unknown>;
    if (typeof rec.response === "string") {
      const parsed = parseModelJson(rec.response);
      if (!parsed.ok) return parsed;
      return { ok: true, value: parsed.value };
    }
    if (rec.response && typeof rec.response === "object") {
      return {
        ok: true,
        value: rec.response,
      };
    }
    if (typeof rec.text === "string") {
      const parsed = parseModelJson(rec.text);
      if (!parsed.ok) return parsed;
      return { ok: true, value: parsed.value };
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
  if (!Number.isInteger(httpStatus) || httpStatus < 200 || httpStatus > 599) return null;
  return { http_status: httpStatus, body: rec.body };
}

async function budgetRpc(env: GatewayEnv, path: string, body: unknown): Promise<BudgetRpc> {
  if (!env.BUDGET_LEDGER) {
    return { ok: false, status: 503, error: "budget_ledger_unbound" };
  }
  let res: Response;
  try {
    const id = env.BUDGET_LEDGER.idFromName(CONTROL_PLANE_LEDGER_NAME);
    const stub = env.BUDGET_LEDGER.get(id);
    res = await stub.fetch(
      new Request(`https://budget${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      status: 500,
      error: "budget_rpc_failed",
      detail: detail.slice(0, 180),
    };
  }
  let parsed: unknown;
  try {
    parsed = await res.json();
  } catch {
    return { ok: false, status: 500, error: "budget_rpc_invalid_json" };
  }
  if (!parsed || typeof parsed !== "object") {
    return { ok: false, status: 500, error: "budget_rpc_invalid_json" };
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
    ok: res.ok && rec.ok === true,
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
    budget_id: req.budget_id,
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
): { input: number; output: number; cached: number; actualCostUsd: number | null; measured: boolean } {
  const rec = res && typeof res === "object" ? (res as Record<string, unknown>) : {};
  const usage =
    rec.usage && typeof rec.usage === "object" ? (rec.usage as Record<string, unknown>) : {};
  const inputDetails =
    usage.input_tokens_details && typeof usage.input_tokens_details === "object"
      ? (usage.input_tokens_details as Record<string, unknown>)
      : {};
  const measuredNumber = (
    source: Record<string, unknown>,
    keys: string[],
  ): number | null => {
    for (const key of keys) {
      if (!Object.prototype.hasOwnProperty.call(source, key)) continue;
      const value = Number(source[key]);
      if (Number.isSafeInteger(value) && value >= 0) return value;
    }
    return null;
  };
  const input = measuredNumber(usage, ["prompt_tokens", "input_tokens"]);
  const output = measuredNumber(usage, ["completion_tokens", "output_tokens"]);
  const cached =
    measuredNumber(usage, ["cached_tokens"]) ??
    measuredNumber(inputDetails, ["cached_tokens"]);
  const providerCost = ["cost_usd", "monetary_cost_usd"]
    .map((key) => Number(usage[key]))
    .find((value) => Number.isFinite(value) && value >= 0);
  return {
    input: input ?? 0,
    output: output ?? 0,
    cached: cached ?? 0,
    actualCostUsd: providerCost ?? null,
    measured: input !== null && output !== null,
  };
}

class GatewayProviderTimeout extends Error {
  constructor() {
    super("Workers AI call timed out");
    this.name = "GatewayProviderTimeout";
  }
}

async function handleGatewayRequest(
  request: Request,
  env: GatewayEnv,
  serviceBindingAuthorized = false,
): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health" || url.pathname === "/") {
      if (request.method !== "GET") return json({ error: "GET required" }, 405);
      return json({ ok: true, service: "quant-platform-research-ai-gateway" });
    }
    if (url.pathname !== "/v1/complete") {
      return json({ error: "not found" }, 404);
    }
    if (request.method !== "POST") return json({ error: "POST required" }, 405);
    if (!serviceBindingAuthorized && !(await authorized(request, env))) {
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
    const inputBounds = providerInputBounds(req.messages);
    const estimatedInput = inputBounds.token_upper_bound;
    const estimatedCost = estimateCostUsd(req.model, estimatedInput, req.max_tokens);
    const reserveAmounts = {
      model_calls: 1,
      input_tokens: estimatedInput,
      output_tokens: req.max_tokens,
      cached_tokens: estimatedInput,
      cost_usd: estimatedCost,
    };
    const reserved = await budgetRpc(env, "/reserve", {
      idempotency_key: bound.idempotency_key,
      request_digest: bound.request_digest,
      acquire_lease: true,
      amounts: reserveAmounts,
    });
    if (!reserved.ok) {
      const publicDetail =
        reserved.error === "budget_exhausted" || reserved.error === "budget_frozen"
          ? reserved.detail
          : undefined;
      return json(
        { ok: false, error: reserved.error || "budget_exhausted", detail: publicDetail },
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
    if (!budgetRunId || !reserved.lease_id) {
      // The request key is enough to cancel a reserve that committed despite a
      // malformed/lost response. No provider marker exists yet.
      await budgetRpc(env, "/release", {
        idempotency_key: bound.idempotency_key,
      });
      return json(
        {
          ok: false,
          error: "budget_reserve_invalid_response",
          budget_run_id: budgetRunId,
        },
        500,
      );
    }

    // This durable marker is the recovery boundary. Workers AI is never called
    // unless the ledger has persisted that provider usage may now exist.
    const providerStarted = await budgetRpc(env, "/provider-started", {
      idempotency_key: bound.idempotency_key,
      lease_id: reserved.lease_id,
    });
    if (!providerStarted.ok) {
      // No provider call was made. If the marker itself committed but its
      // response was lost, /release conservatively charges and freezes because
      // the durable record is intentionally indistinguishable from a crash at
      // the provider boundary. Otherwise this is a zero-cost pre-provider
      // release. The alarm remains the final recovery path if this RPC fails.
      await budgetRpc(env, "/release", {
        idempotency_key: bound.idempotency_key,
        lease_id: reserved.lease_id,
      });
      return json(
        {
          ok: false,
          error: "budget_provider_start_failed",
          budget_run_id: budgetRunId,
        },
        500,
      );
    }

    let responseStatus = 502;
    let responseBody: Record<string, unknown> = {
      ok: false,
      error: "ai_run_failed",
    };
    let billed = {
      model_calls: 1,
      input_tokens: estimatedInput,
      output_tokens: req.max_tokens,
      cached_tokens: estimatedInput,
      cost_usd: estimatedCost,
    };
    let settlement: BudgetSettlement | null = null;
    let uncertainReason: UncertainProviderReason | null = null;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    try {
      const res = await Promise.race([
        env.AI.run(req.model, {
          messages: req.messages,
          max_tokens: req.max_tokens,
        }),
        new Promise<never>((_resolve, reject) => {
          timeoutId = setTimeout(
            () => reject(new GatewayProviderTimeout()),
            AI_CALL_TIMEOUT_MS,
          );
        }),
      ]);
      const extracted = extractModelValue(res);
      const tokens = tokenCount(res);
      if (!tokens.measured) {
        uncertainReason = "usage_unavailable";
        responseStatus = 500;
        responseBody = { ok: false, error: "provider_usage_unavailable" };
      } else {
        billed = {
          model_calls: 1,
          input_tokens: tokens.input,
          output_tokens: tokens.output,
          cached_tokens: tokens.cached,
          cost_usd:
            tokens.actualCostUsd ?? estimateCostUsd(req.model, tokens.input, tokens.output),
        };
        settlement = {
          outcome: "schema_reject",
          usage_source: "provider",
          estimated_cost_usd: estimatedCost,
          actual_cost_usd: tokens.actualCostUsd,
          billed_cost_usd: billed.cost_usd,
          actual_input_tokens: tokens.input,
          actual_output_tokens: tokens.output,
          actual_cached_tokens: tokens.cached,
        };
        if (!extracted.ok) {
          responseStatus = 400;
          responseBody = { ok: false, error: extracted.error };
        } else {
          const decoded = decodeTypedArtifact(extracted.value, req.expected_schema);
          if (!decoded.ok) {
            responseStatus = 400;
            responseBody = { ok: false, error: decoded.error };
          } else {
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
              cached_tokens: tokens.cached,
              monetary_cost_usd: billed.cost_usd,
              prompt_digest: promptDigest,
              output_digest: outputDigest,
              ready_snapshot_id: req.ready_snapshot_id ?? null,
              experiment_id: req.experiment_id ?? null,
              budget_id: req.budget_id,
              budget_run_id: budgetRunId,
            };
            settlement.outcome = "success";
            responseStatus = 200;
            responseBody = payload;
          }
        }
      }
    } catch (e) {
      const timedOut = e instanceof GatewayProviderTimeout;
      uncertainReason = timedOut ? "timeout" : "provider_error";
      responseStatus = timedOut ? 504 : 502;
      responseBody = {
        ok: false,
        error: timedOut ? "ai_run_timeout" : "ai_run_failed",
      };
    } finally {
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    }
    responseBody = { ...responseBody, budget_run_id: budgetRunId };

    if (uncertainReason) {
      const uncertain = await budgetRpc(env, "/settle-uncertain", {
        idempotency_key: bound.idempotency_key,
        reason: uncertainReason,
      });
      if (uncertain.ok && uncertain.cached_result) {
        return cachedResponse(uncertain.cached_result);
      }
      return json(
        {
          ok: false,
          error: "budget_settlement_recovery_pending",
          budget_run_id: budgetRunId,
        },
        500,
      );
    }

    if (!settlement) {
      // Defensive guard: provider success with known usage always creates an
      // exact settlement above. The persisted provider-started marker and alarm
      // still guarantee conservative recovery.
      await budgetRpc(env, "/settle-uncertain", {
        idempotency_key: bound.idempotency_key,
        reason: "worker_interrupted",
      });
      return json(
        { ok: false, error: "budget_settlement_missing", budget_run_id: budgetRunId },
        500,
      );
    }

    const finalized = await budgetRpc(env, "/finalize", {
      idempotency_key: bound.idempotency_key,
      amounts: billed,
      settlement,
      result: { http_status: responseStatus, body: responseBody },
    });
    if (!finalized.ok) {
      // If /finalize committed but its response was lost or malformed, this is
      // an idempotent no-op. Otherwise it immediately charges the reservation
      // maximum; the lease alarm remains the final persistent recovery layer.
      await budgetRpc(env, "/settle-uncertain", {
        idempotency_key: bound.idempotency_key,
        reason: "finalize_failed",
      });
      return json(
        {
          ok: false,
          error: "budget_finalize_failed",
          budget_run_id: budgetRunId,
        },
        500,
      );
    }
    return json(responseBody, responseStatus);
}

export class GatewayService extends WorkerEntrypoint<GatewayEnv> {
  async complete(
    body: unknown,
    options: { idempotency_key?: string } = {},
  ): Promise<GatewayServiceResult> {
    const headers = new Headers({ "content-type": "application/json" });
    if (options.idempotency_key) {
      headers.set("Idempotency-Key", options.idempotency_key);
    }
    const response = await handleGatewayRequest(
      new Request("https://service-binding/v1/complete", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      }),
      this.env,
      true,
    );
    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      parsed = { ok: false, error: "gateway_invalid_json" };
    }
    return { http_status: response.status, body: parsed };
  }
}

export default {
  fetch(request: Request, env: GatewayEnv): Promise<Response> {
    return handleGatewayRequest(request, env, false);
  },
};
