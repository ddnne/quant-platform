/// <reference types="@cloudflare/workers-types" />

import {
  decodeGatewayRequest,
  decodeTypedArtifact,
  estimateCostUsd,
  parseModelJson,
  type GatewayOk,
} from "./schema";

export interface GatewayEnv {
  AI?: Ai;
  GATEWAY_TOKEN?: string;
  /** Separate mass-eval secret. Never a GATEWAY_TOKEN substitute. */
  MASS_EVAL_TOKEN?: string;
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

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
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
    if (!env.AI) {
      return json({ ok: false, error: "ai_binding_unbound" }, 503);
    }
    const prompt = req.messages.map((m) => `${m.role}:${m.content}`).join("\n");
    const promptDigest = req.prompt_digest || `sha256:${await sha256Hex(prompt)}`;
    try {
      const res = await env.AI.run(req.model, {
        messages: req.messages,
        max_tokens: req.max_tokens,
      });
      const extracted = extractModelValue(res);
      if (!extracted.ok) {
        return json({ ok: false, error: extracted.error }, 400);
      }
      const decoded = decodeTypedArtifact(extracted.value, req.expected_schema);
      if (!decoded.ok) {
        return json({ ok: false, error: decoded.error }, 400);
      }
      const tokens = tokenCount(res, extracted.rawForTokens, prompt);
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
      };
      // Do not grant generation. READY is not required live. Unknown fields rejected.
      // budget_id is required above; Edge ledger is not yet transactional (no DO charge).
      return json(payload);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return json({ ok: false, error: "ai_run_failed", detail: msg.slice(0, 180) }, 502);
    }
  },
};
