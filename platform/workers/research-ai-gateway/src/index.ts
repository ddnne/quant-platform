/// <reference types="@cloudflare/workers-types" />

import { BudgetLedger } from "./budget_do";
import { json } from "./http_json";
import {
  decodeGatewayRequest,
  decodeTypedArtifact,
  estimateCostUsd,
  parseModelJson,
  type GatewayOk,
} from "./schema";

export { BudgetLedger };

export interface GatewayEnv {
  AI?: Ai;
  GATEWAY_TOKEN?: string;
  /** Separate mass-eval secret. Never a GATEWAY_TOKEN substitute. */
  MASS_EVAL_TOKEN?: string;
  BUDGET_LEDGER?: DurableObjectNamespace;
}

function timingSafeEqualBytes(a: ArrayBuffer, b: ArrayBuffer): boolean {
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

async function tokenMatches(provided: string, expected: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(provided)),
    crypto.subtle.digest("SHA-256", enc.encode(expected)),
  ]);
  return timingSafeEqualBytes(a, b);
}

/** GATEWAY_TOKEN vs X-Gateway-Token only. MASS_EVAL_TOKEN is a different check. */
export async function authorized(request: Request, env: GatewayEnv): Promise<boolean> {
  const expected = env.GATEWAY_TOKEN;
  if (!expected) return false;
  const got = request.headers.get("X-Gateway-Token") || "";
  if (!got) return false;
  return tokenMatches(got, expected);
}

async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
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

type BudgetRpc = {
  ok: boolean;
  status?: number;
  error?: string;
  detail?: string;
  lease_id?: string;
};

async function budgetRpc(
  env: GatewayEnv,
  budgetId: string,
  path: string,
  body: unknown,
): Promise<BudgetRpc> {
  if (!env.BUDGET_LEDGER) {
    return { ok: false, status: 503, error: "budget_ledger_unbound" };
  }
  const id = env.BUDGET_LEDGER.idFromName(budgetId);
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
  return {
    ok: rec.ok === true,
    status: res.status,
    error: typeof rec.error === "string" ? rec.error : undefined,
    detail: typeof rec.detail === "string" ? rec.detail : undefined,
    lease_id: typeof lease.lease_id === "string" ? lease.lease_id : undefined,
  };
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
    const estimatedInput = Math.ceil(prompt.length / 4);
    const estimatedCost = estimateCostUsd(req.model, estimatedInput, req.max_tokens);
    const idempotencyKey =
      request.headers.get("Idempotency-Key")?.trim() || crypto.randomUUID();
    const reserved = await budgetRpc(env, req.budget_id, "/reserve", {
      idempotency_key: idempotencyKey,
      acquire_lease: true,
      amounts: {
        model_calls: 1,
        input_tokens: estimatedInput,
        output_tokens: req.max_tokens,
        cost_usd: estimatedCost,
      },
    });
    if (!reserved.ok) {
      return json(
        { ok: false, error: reserved.error || "budget_exhausted", detail: reserved.detail },
        reserved.status || 429,
      );
    }
    const release = () =>
      budgetRpc(env, req.budget_id, "/release", {
        idempotency_key: idempotencyKey,
        lease_id: reserved.lease_id,
      });
    try {
      const res = await env.AI.run(req.model, {
        messages: req.messages,
        max_tokens: req.max_tokens,
      });
      const extracted = extractModelValue(res);
      if (!extracted.ok) {
        await release();
        return json({ ok: false, error: extracted.error }, 400);
      }
      const decoded = decodeTypedArtifact(extracted.value, req.expected_schema);
      if (!decoded.ok) {
        await release();
        return json({ ok: false, error: decoded.error }, 400);
      }
      const tokens = tokenCount(res, extracted.rawForTokens, prompt);
      const canonical = JSON.stringify(decoded.value.artifact);
      const outputDigest = `sha256:${await sha256Hex(canonical)}`;
      await budgetRpc(env, req.budget_id, "/reconcile", {
        idempotency_key: idempotencyKey,
        lease_id: reserved.lease_id,
        usage: {
          model_calls: 1,
          input_tokens: tokens.input,
          output_tokens: tokens.output,
          cost_usd: estimateCostUsd(req.model, tokens.input, tokens.output),
        },
      });
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
      };
      return json(payload);
    } catch (e) {
      await release();
      const msg = e instanceof Error ? e.message : String(e);
      return json({ ok: false, error: "ai_run_failed", detail: msg.slice(0, 180) }, 502);
    }
  },
};
