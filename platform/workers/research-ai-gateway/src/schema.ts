/** Strict AI Gateway request/response. Unknown fields rejected. */

export const ALLOWED_MODELS = [
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/zai-org/glm-4.7-flash",
  "@cf/meta/llama-3.1-8b-instruct-fp8",
] as const;

export type AllowedModel = (typeof ALLOWED_MODELS)[number];

const ALLOWED_MODEL_SET = new Set<string>(ALLOWED_MODELS);
const ALLOWED_ROLES = new Set(["system", "user", "assistant"]);
const REQUEST_KEYS = new Set([
  "model",
  "messages",
  "max_tokens",
  "prompt_digest",
  "ready_snapshot_id",
  "experiment_id",
]);

export type GatewayMessage = { role: "system" | "user" | "assistant"; content: string };

export type GatewayRequest = {
  model: AllowedModel;
  messages: GatewayMessage[];
  max_tokens: number;
  prompt_digest?: string;
  ready_snapshot_id?: string;
  experiment_id?: string;
};

export type GatewayOk = {
  ok: true;
  text: string;
  model: AllowedModel;
  input_tokens: number;
  output_tokens: number;
  monetary_cost_usd: number;
  prompt_digest: string;
  output_digest: string;
  ready_snapshot_id: string | null;
  experiment_id: string | null;
};

export function decodeGatewayRequest(
  raw: unknown,
): { ok: true; value: GatewayRequest } | { ok: false; error: string } {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const obj = raw as Record<string, unknown>;
  for (const key of Object.keys(obj)) {
    if (!REQUEST_KEYS.has(key)) {
      return { ok: false, error: `unknown field: ${key}` };
    }
  }
  const model = obj.model;
  if (typeof model !== "string" || !ALLOWED_MODEL_SET.has(model)) {
    return { ok: false, error: "model not allowed" };
  }
  if (!Array.isArray(obj.messages) || obj.messages.length < 1) {
    return { ok: false, error: "messages[] required" };
  }
  const messages: GatewayMessage[] = [];
  for (let i = 0; i < obj.messages.length; i++) {
    const m = obj.messages[i];
    if (typeof m !== "object" || m === null || Array.isArray(m)) {
      return { ok: false, error: `messages[${i}] must be object` };
    }
    const rec = m as Record<string, unknown>;
    for (const k of Object.keys(rec)) {
      if (k !== "role" && k !== "content") {
        return { ok: false, error: `messages[${i}] unknown field: ${k}` };
      }
    }
    if (typeof rec.role !== "string" || !ALLOWED_ROLES.has(rec.role)) {
      return { ok: false, error: `messages[${i}].role invalid` };
    }
    if (typeof rec.content !== "string") {
      return { ok: false, error: `messages[${i}].content must be string` };
    }
    messages.push({
      role: rec.role as GatewayMessage["role"],
      content: rec.content,
    });
  }
  const maxTokens = Number(obj.max_tokens);
  if (!Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 1400) {
    return { ok: false, error: "max_tokens must be integer 1..1400" };
  }
  const out: GatewayRequest = {
    model: model as AllowedModel,
    messages,
    max_tokens: maxTokens,
  };
  if (obj.prompt_digest !== undefined) {
    if (typeof obj.prompt_digest !== "string") {
      return { ok: false, error: "prompt_digest must be string" };
    }
    out.prompt_digest = obj.prompt_digest;
  }
  if (obj.ready_snapshot_id !== undefined) {
    if (typeof obj.ready_snapshot_id !== "string") {
      return { ok: false, error: "ready_snapshot_id must be string" };
    }
    out.ready_snapshot_id = obj.ready_snapshot_id;
  }
  if (obj.experiment_id !== undefined) {
    if (typeof obj.experiment_id !== "string") {
      return { ok: false, error: "experiment_id must be string" };
    }
    out.experiment_id = obj.experiment_id;
  }
  return { ok: true, value: out };
}

/** Rough USD per 1k tokens. Ledger charge uses these measured tokens. */
export function estimateCostUsd(
  model: string,
  inputTokens: number,
  outputTokens: number,
): number {
  const perK =
    model.includes("70b") ? 0.0003 : model.includes("glm") ? 0.00008 : 0.00004;
  return Number(
    (((inputTokens + outputTokens) / 1000) * perK).toFixed(8),
  );
}
