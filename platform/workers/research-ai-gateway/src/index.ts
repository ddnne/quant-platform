/// <reference types="@cloudflare/workers-types" />

import { WorkerEntrypoint } from "cloudflare:workers";
import { authorized } from "./authorized";
import {
  bindIdempotencyKey,
  CONTROL_PLANE_LEDGER_NAME,
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
import {
  AI_GATEWAY_PRICING_POLICY_DIGEST,
  AI_GATEWAY_PRICING_POLICY_ID,
} from "./pricing_policy";

export { BudgetLedger };

/** Generated bindings plus the HTTP-defense secret. */
export type GatewayEnv = Cloudflare.Env & {
  GATEWAY_TOKEN?: string;
};

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
  settlement_capability?: string | null;
};

type BudgetLedgerRpc = {
  reserve(input: unknown): Promise<unknown>;
  markProviderStarted(input: unknown): Promise<unknown>;
  finalizeExact(input: unknown): Promise<unknown>;
  settleUncertain(input: unknown): Promise<unknown>;
  release(input: unknown): Promise<unknown>;
};

function parseCachedResult(raw: unknown): CachedBudgetBody | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const rec = raw as Record<string, unknown>;
  const httpStatus = Number(rec.http_status);
  if (!Number.isInteger(httpStatus) || httpStatus < 200 || httpStatus > 599) return null;
  return { http_status: httpStatus, body: rec.body };
}

function rpcStatus(error: string | undefined, ok: boolean): number {
  if (ok) return 200;
  if (error === "budget_exhausted") return 429;
  if (
    error === "reservation_not_found" ||
    error === "lease_not_active" ||
    error === "lease_reservation_mismatch" ||
    error === "budget_frozen" ||
    error === "actual_exceeds_reserved" ||
    error === "provider_usage_uncertain" ||
    error === "provider_not_started" ||
    error === "idempotency_digest_conflict" ||
    error === "reservation_released" ||
    error === "settlement_capability_required" ||
    error === "settlement_capability_invalid" ||
    error === "settlement_capability_consumed" ||
    error === "request_digest_mismatch" ||
    error === "lease_mismatch" ||
    error === "caller_settlement_rejected"
  ) {
    return 409;
  }
  return 400;
}

async function budgetRpc(
  env: GatewayEnv,
  method: keyof BudgetLedgerRpc,
  body: unknown,
): Promise<BudgetRpc> {
  if (!env.BUDGET_LEDGER) {
    return { ok: false, status: 503, error: "budget_ledger_unbound" };
  }
  let parsed: unknown;
  try {
    const id = env.BUDGET_LEDGER.idFromName(CONTROL_PLANE_LEDGER_NAME);
    const stub = env.BUDGET_LEDGER.get(id) as DurableObjectStub & BudgetLedgerRpc;
    const fn = stub[method];
    if (typeof fn !== "function") {
      return { ok: false, status: 500, error: "budget_rpc_unavailable" };
    }
    parsed = await fn.call(stub, body);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      status: 500,
      error: "budget_rpc_failed",
      detail: detail.slice(0, 180),
    };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
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
  const ok = rec.ok === true;
  return {
    ok,
    status: rpcStatus(typeof rec.error === "string" ? rec.error : undefined, ok),
    error: typeof rec.error === "string" ? rec.error : undefined,
    detail: typeof rec.detail === "string" ? rec.detail : undefined,
    lease_id: typeof lease.lease_id === "string" ? lease.lease_id : undefined,
    existing: rec.existing === true,
    budget_run_id: budgetRunId,
    reservation_status:
      typeof reservation.status === "string" ? reservation.status : undefined,
    cached_result: parseCachedResult(reservation.cached_result),
    settlement_capability:
      typeof rec.settlement_capability === "string" ? rec.settlement_capability : null,
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

function plainDataRecord(value: unknown): Record<string, unknown> | null {
  try {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) return null;
    const ownKeys = Reflect.ownKeys(value);
    if (ownKeys.some((key) => typeof key !== "string")) return null;
    const descriptors = Object.getOwnPropertyDescriptors(value);
    const record: Record<string, unknown> = {};
    for (const key of ownKeys as string[]) {
      const descriptor = descriptors[key];
      if (!descriptor?.enumerable || !("value" in descriptor)) return null;
      record[key] = descriptor.value;
    }
    return record;
  } catch {
    return null;
  }
}

function finiteTokenCount(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
}

function tokenCount(
  res: unknown,
): { input: number; output: number; cached: number; actualCostUsd: number | null; measured: boolean } {
  const rec = plainDataRecord(res);
  const usage = rec && Object.prototype.hasOwnProperty.call(rec, "usage")
    ? plainDataRecord(rec.usage)
    : null;
  const invalid = {
    input: 0,
    output: 0,
    cached: 0,
    actualCostUsd: null,
    measured: false,
  } as const;
  if (!usage) return invalid;

  const allowedUsageKeys = new Set([
    "prompt_tokens",
    "input_tokens",
    "completion_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "input_tokens_details",
    "prompt_tokens_details",
    "cost_usd",
    "monetary_cost_usd",
  ]);
  if (Object.keys(usage).some((key) => !allowedUsageKeys.has(key))) return invalid;

  const oneAlias = (aliases: readonly string[]): number | null => {
    const present = aliases.filter((key) => Object.prototype.hasOwnProperty.call(usage, key));
    if (present.length !== 1) return null;
    return finiteTokenCount(usage[present[0]]);
  };
  const input = oneAlias(["prompt_tokens", "input_tokens"]);
  const output = oneAlias(["completion_tokens", "output_tokens"]);
  if (input === null || output === null) return invalid;

  if (Object.prototype.hasOwnProperty.call(usage, "total_tokens")) {
    const total = finiteTokenCount(usage.total_tokens);
    if (total === null || total !== input + output) return invalid;
  }

  const detailAliases = ["input_tokens_details", "prompt_tokens_details"].filter((key) =>
    Object.prototype.hasOwnProperty.call(usage, key),
  );
  if (detailAliases.length > 1) return invalid;
  let detailCached: number | null = null;
  if (detailAliases.length === 1) {
    const details = plainDataRecord(usage[detailAliases[0]]);
    if (
      !details ||
      Object.keys(details).length !== 1 ||
      !Object.prototype.hasOwnProperty.call(details, "cached_tokens")
    ) {
      return invalid;
    }
    detailCached = finiteTokenCount(details.cached_tokens);
    if (detailCached === null) return invalid;
  }
  const hasTopCached = Object.prototype.hasOwnProperty.call(usage, "cached_tokens");
  if (hasTopCached && detailCached !== null) return invalid;
  const cached = hasTopCached ? finiteTokenCount(usage.cached_tokens) : detailCached ?? 0;
  if (cached === null) return invalid;

  const costAliases = ["cost_usd", "monetary_cost_usd"].filter((key) =>
    Object.prototype.hasOwnProperty.call(usage, key),
  );
  if (costAliases.length > 1) return invalid;
  let providerCost: number | null = null;
  if (costAliases.length === 1) {
    const value = usage[costAliases[0]];
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
      return invalid;
    }
    providerCost = value;
  }
  return {
    input,
    output,
    cached,
    actualCostUsd: providerCost,
    measured: true,
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
    const reserved = await budgetRpc(env, "reserve", {
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
      await budgetRpc(env, "release", {
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
    const startInput = {
      idempotency_key: bound.idempotency_key,
      lease_id: reserved.lease_id,
      request_digest: bound.request_digest,
    };
    let providerStarted = await budgetRpc(env, "markProviderStarted", startInput);
    if (!providerStarted.ok || !providerStarted.settlement_capability) {
      // Lost RPC response / eviction: the DO may already have minted. Retry
      // recovers the same one-shot capability instead of creating a phantom.
      providerStarted = await budgetRpc(env, "markProviderStarted", startInput);
    }
    const settlementCapability = providerStarted.settlement_capability;
    if (!providerStarted.ok || !settlementCapability) {
      // No provider call was made. If the marker itself committed but its
      // capability cannot be recovered, release conservatively charges and
      // freezes. The alarm remains the final recovery path if this RPC fails.
      await budgetRpc(env, "release", {
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
    let measuredUsage: {
      model_calls: number;
      input_tokens: number;
      output_tokens: number;
      cached_tokens: number;
      cost_usd: number;
      cost_source: "provider" | "pricing_policy_estimate";
      provider_model: string;
      pricing_policy_id: string | null;
      pricing_policy_digest: string | null;
    } | null = null;
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
        const usesPricingPolicy = tokens.actualCostUsd === null;
        const exactUsage = {
          model_calls: 1,
          input_tokens: tokens.input,
          output_tokens: tokens.output,
          cached_tokens: tokens.cached,
          cost_usd:
            tokens.actualCostUsd ?? estimateCostUsd(req.model, tokens.input, tokens.output),
          cost_source: usesPricingPolicy
            ? ("pricing_policy_estimate" as const)
            : ("provider" as const),
          provider_model: req.model,
          pricing_policy_id: usesPricingPolicy ? AI_GATEWAY_PRICING_POLICY_ID : null,
          pricing_policy_digest: usesPricingPolicy
            ? AI_GATEWAY_PRICING_POLICY_DIGEST
            : null,
        };
        measuredUsage = exactUsage;
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
              monetary_cost_usd: exactUsage.cost_usd,
              monetary_cost_source: exactUsage.cost_source,
              pricing_policy_id: exactUsage.pricing_policy_id,
              pricing_policy_digest: exactUsage.pricing_policy_digest,
              prompt_digest: promptDigest,
              output_digest: outputDigest,
              ready_snapshot_id: req.ready_snapshot_id ?? null,
              experiment_id: req.experiment_id ?? null,
              budget_id: req.budget_id,
              budget_run_id: budgetRunId,
            };
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
      const uncertain = await budgetRpc(env, "settleUncertain", {
        idempotency_key: bound.idempotency_key,
        request_digest: bound.request_digest,
        lease_id: reserved.lease_id,
        settlement_capability: settlementCapability,
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

    if (!measuredUsage) {
      // Defensive guard: provider success with known usage always creates an
      // exact settlement above. The persisted provider-started marker and alarm
      // still guarantee conservative recovery.
      await budgetRpc(env, "settleUncertain", {
        idempotency_key: bound.idempotency_key,
        request_digest: bound.request_digest,
        lease_id: reserved.lease_id,
        settlement_capability: settlementCapability,
        reason: "worker_interrupted",
      });
      return json(
        { ok: false, error: "budget_settlement_missing", budget_run_id: budgetRunId },
        500,
      );
    }

    const finalized = await budgetRpc(env, "finalizeExact", {
      idempotency_key: bound.idempotency_key,
      request_digest: bound.request_digest,
      lease_id: reserved.lease_id,
      settlement_capability: settlementCapability,
      usage: measuredUsage,
      terminal_result: { http_status: responseStatus, body: responseBody },
    });
    if (!finalized.ok) {
      // If finalize committed but its response was lost or malformed, this is
      // an idempotent no-op. Otherwise it immediately charges the reservation
      // maximum; the lease alarm remains the final persistent recovery layer.
      await budgetRpc(env, "settleUncertain", {
        idempotency_key: bound.idempotency_key,
        request_digest: bound.request_digest,
        lease_id: reserved.lease_id,
        settlement_capability: settlementCapability,
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
