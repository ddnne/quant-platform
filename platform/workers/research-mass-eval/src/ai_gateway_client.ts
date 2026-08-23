import type { Env } from "./types";

export type GatewayComplete =
  | {
      ok: true;
      artifact: Record<string, unknown>;
      schema_name: string;
      schema_version: string;
      model: string;
      input_tokens: number;
      output_tokens: number;
      monetary_cost_usd: number;
      prompt_digest?: string;
      output_digest?: string;
      budget_id: string;
    }
  | { ok: false; reason: string };

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function gatewayToken(env: Env): string | undefined {
  const rec = env as Env & { GATEWAY_TOKEN?: string };
  return rec.GATEWAY_TOKEN;
}

/** Research Worker talks only to AI Gateway. Direct env.AI is not available. */
export async function completeViaGateway(
  env: Env,
  body: {
    model: string;
    messages: Array<{ role: string; content: string }>;
    max_tokens: number;
    expected_schema?: string;
    budget_id?: string;
    experiment_id?: string;
    ready_snapshot_id?: string;
    prompt_digest?: string;
  },
): Promise<GatewayComplete> {
  if (!env.AI_GATEWAY) {
    return { ok: false, reason: "ai_gateway_unbound" };
  }
  const token = gatewayToken(env);
  if (!token) {
    return { ok: false, reason: "gateway_token_unbound" };
  }
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "X-Gateway-Token": token,
  };
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
  if (!isObj(parsed)) {
    return { ok: false, reason: "gateway_invalid_json" };
  }
  if (!res.ok || parsed.ok !== true) {
    return {
      ok: false,
      reason: String(parsed.error || parsed.reason || `gateway_http_${res.status}`),
    };
  }
  if (Object.prototype.hasOwnProperty.call(parsed, "text")) {
    return { ok: false, reason: "gateway_raw_text_rejected" };
  }
  if (!isObj(parsed.artifact)) {
    return { ok: false, reason: "gateway_artifact_missing" };
  }
  if (typeof parsed.schema !== "string" || typeof parsed.schema_version !== "string") {
    return { ok: false, reason: "gateway_schema_missing" };
  }
  if (typeof parsed.budget_id !== "string" || !parsed.budget_id) {
    return { ok: false, reason: "gateway_budget_id_missing" };
  }
  return {
    ok: true,
    artifact: parsed.artifact,
    schema_name: parsed.schema,
    schema_version: parsed.schema_version,
    model: typeof parsed.model === "string" ? parsed.model : body.model,
    input_tokens: Number(parsed.input_tokens || 0),
    output_tokens: Number(parsed.output_tokens || 0),
    monetary_cost_usd: Number(parsed.monetary_cost_usd || 0),
    prompt_digest: typeof parsed.prompt_digest === "string" ? parsed.prompt_digest : undefined,
    output_digest: typeof parsed.output_digest === "string" ? parsed.output_digest : undefined,
    budget_id: parsed.budget_id,
  };
}

export function hasAiGateway(env: Env): boolean {
  return Boolean(env.AI_GATEWAY);
}
