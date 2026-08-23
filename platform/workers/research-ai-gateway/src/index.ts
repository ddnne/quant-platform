/// <reference types="@cloudflare/workers-types" />

import {
  decodeGatewayRequest,
  estimateCostUsd,
  type GatewayOk,
} from "./schema";

export interface GatewayEnv {
  AI?: Ai;
  GATEWAY_TOKEN?: string;
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

async function authorized(request: Request, expected?: string): Promise<boolean> {
  if (!expected) return false;
  const got =
    request.headers.get("X-Mass-Eval-Token") ||
    request.headers.get("X-Gateway-Token") ||
    "";
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

function extractText(res: unknown): string {
  if (typeof res === "string") return res;
  if (res && typeof res === "object") {
    const rec = res as Record<string, unknown>;
    if (typeof rec.response === "string") return rec.response;
    if (typeof rec.text === "string") return rec.text;
  }
  if (Array.isArray(res)) return JSON.stringify(res);
  return "";
}

function tokenCount(res: unknown, fallbackText: string, prompt: string): {
  input: number;
  output: number;
} {
  const rec = res && typeof res === "object" ? (res as Record<string, unknown>) : {};
  const usage = rec.usage && typeof rec.usage === "object" ? (rec.usage as Record<string, unknown>) : {};
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
    if (!(await authorized(request, env.GATEWAY_TOKEN || undefined))) {
      return json({ error: "unauthorized" }, 401);
    }
    if (!env.AI) {
      return json({ ok: false, error: "ai_binding_unbound" }, 503);
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
    const prompt = req.messages.map((m) => `${m.role}:${m.content}`).join("\n");
    const promptDigest = req.prompt_digest || `sha256:${await sha256Hex(prompt)}`;
    try {
      const res = await env.AI.run(req.model, {
        messages: req.messages,
        max_tokens: req.max_tokens,
      });
      const text = extractText(res);
      const tokens = tokenCount(res, text, prompt);
      const outputDigest = `sha256:${await sha256Hex(text)}`;
      const payload: GatewayOk = {
        ok: true,
        text,
        model: req.model,
        input_tokens: tokens.input,
        output_tokens: tokens.output,
        monetary_cost_usd: estimateCostUsd(req.model, tokens.input, tokens.output),
        prompt_digest: promptDigest,
        output_digest: outputDigest,
        ready_snapshot_id: req.ready_snapshot_id ?? null,
        experiment_id: req.experiment_id ?? null,
      };
      // budget_id is echoed as null here; Python AIGateway charges ResearchBudgetCapability.
      // Do not grant generation. Unknown request fields remain rejected.
      return json({ ...payload, budget_id: null });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return json({ ok: false, error: "ai_run_failed", detail: msg.slice(0, 180) }, 502);
    }
  },
};
