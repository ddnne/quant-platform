import type { Env } from "./types";

export type GatewayComplete = {
  ok: boolean;
  text?: string;
  model?: string;
  reason?: string;
  input_tokens?: number;
  output_tokens?: number;
  monetary_cost_usd?: number;
  prompt_digest?: string;
  output_digest?: string;
};

/** Research Worker talks only to AI Gateway. Direct env.AI is not available. */
export async function completeViaGateway(
  env: Env,
  body: {
    model: string;
    messages: Array<{ role: string; content: string }>;
    max_tokens: number;
  },
): Promise<GatewayComplete> {
  if (!env.AI_GATEWAY) {
    return { ok: false, reason: "ai_gateway_unbound" };
  }
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };
  if (env.MASS_EVAL_TOKEN) headers["X-Mass-Eval-Token"] = env.MASS_EVAL_TOKEN;
  const res = await env.AI_GATEWAY.fetch(
    new Request("https://ai-gateway/v1/complete", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    }),
  );
  let parsed: unknown = null;
  try {
    parsed = await res.json();
  } catch {
    return { ok: false, reason: `gateway_http_${res.status}` };
  }
  if (!parsed || typeof parsed !== "object") {
    return { ok: false, reason: "gateway_invalid_json" };
  }
  const rec = parsed as Record<string, unknown>;
  if (!res.ok || rec.ok !== true) {
    return {
      ok: false,
      reason: String(rec.error || rec.reason || `gateway_http_${res.status}`),
    };
  }
  return {
    ok: true,
    text: typeof rec.text === "string" ? rec.text : "",
    model: typeof rec.model === "string" ? rec.model : body.model,
    input_tokens: Number(rec.input_tokens || 0),
    output_tokens: Number(rec.output_tokens || 0),
    monetary_cost_usd: Number(rec.monetary_cost_usd || 0),
    prompt_digest: typeof rec.prompt_digest === "string" ? rec.prompt_digest : undefined,
    output_digest: typeof rec.output_digest === "string" ? rec.output_digest : undefined,
  };
}

export function hasAiGateway(env: Env): boolean {
  return Boolean(env.AI_GATEWAY);
}
