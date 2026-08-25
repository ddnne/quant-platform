/** Strict AI Gateway request/response. Unknown fields rejected. */

import { PILOT_BUDGET_CAPS } from "./budget_do";

export const ALLOWED_MODELS = [
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/zai-org/glm-4.7-flash",
  "@cf/meta/llama-3.1-8b-instruct-fp8",
] as const;

export type AllowedModel = (typeof ALLOWED_MODELS)[number];

export const ALLOWED_OUTPUT_SCHEMAS = [
  "Insight",
  "ResearchMemo",
  "FeatureProposal",
  "StrategySpec",
  "SelectionDecision",
  "ThesisProposalList",
] as const;

export type AllowedOutputSchema = (typeof ALLOWED_OUTPUT_SCHEMAS)[number];

export const INSIGHT_SCHEMA_VERSION = "insight/v1";
export const THESIS_PROPOSAL_SCHEMA_VERSION = "thesis-proposal/v1";
export const STRATEGY_SPEC_V2 = "strategy-spec/v2";
export const STRATEGY_SPEC_V3 = "strategy-spec/v3";

const ALLOWED_MODEL_SET = new Set<string>(ALLOWED_MODELS);
const ALLOWED_SCHEMA_SET = new Set<string>(ALLOWED_OUTPUT_SCHEMAS);
const ALLOWED_ROLES = new Set(["system", "user", "assistant"]);
const REQUEST_KEYS = new Set([
  "model",
  "messages",
  "max_tokens",
  "prompt_digest",
  "ready_snapshot_id",
  "experiment_id",
  "expected_schema",
  "budget_id",
]);

const BANNED_KEYS = new Set([
  "code",
  "python",
  "exec",
  "eval",
  "script",
  "shell",
  "bytecode",
  "payload_code",
]);

const ENVELOPE_KEYS = new Set(["schema", "gateway"]);
const FEATURE_ROLES = new Set(["signal", "state", "structural", "utility"]);
const SELECTION_DECISIONS = new Set(["PROMOTE", "HOLD", "REJECT"]);
const FEATURE_PARAM_RESERVED = new Set(["code", "as_of", "db_path", "version"]);
const IDENTIFIER_RE = /^[A-Za-z0-9._-]+$/;

/**
 * Per-call bounds are derived from the canonical controlled-pilot policy. Two
 * calls may occupy the ledger concurrently, so neither may reserve more than
 * its equal share of the global input cap.
 */
export const MAX_GATEWAY_MESSAGES = PILOT_BUDGET_CAPS.max_model_calls;
export const MAX_GATEWAY_INPUT_TOKENS = Math.floor(
  PILOT_BUDGET_CAPS.max_input_tokens / PILOT_BUDGET_CAPS.max_parallel_experiments,
);
export const MAX_GATEWAY_PROMPT_UTF8_BYTES = Math.floor(MAX_GATEWAY_INPUT_TOKENS / 2);
export const PROVIDER_CHAT_ENVELOPE_TOKENS = Math.max(
  1_024,
  Math.floor(MAX_GATEWAY_INPUT_TOKENS / 50),
);

export type ProviderInputBounds = {
  utf8_bytes: number;
  token_upper_bound: number;
};

/**
 * Byte-level tokenizers cannot emit more content tokens than a conservative
 * two-token-per-byte bound. A separate envelope allowance covers provider chat
 * templates and model control tokens. Measured usage above this reservation is
 * still frozen and audited by the ledger.
 */
export function providerInputBounds(
  messages: ReadonlyArray<{ role: string; content: string }>,
): ProviderInputBounds {
  const canonical = JSON.stringify(messages);
  const utf8Bytes = new TextEncoder().encode(canonical).byteLength;
  return {
    utf8_bytes: utf8Bytes,
    token_upper_bound: utf8Bytes * 2 + PROVIDER_CHAT_ENVELOPE_TOKENS,
  };
}

export type GatewayMessage = { role: "system" | "user" | "assistant"; content: string };

export type GatewayRequest = {
  model: AllowedModel;
  messages: GatewayMessage[];
  max_tokens: number;
  budget_id: string;
  prompt_digest?: string;
  ready_snapshot_id?: string;
  experiment_id?: string;
  expected_schema?: AllowedOutputSchema;
};

export type TypedArtifact = {
  schema_name: AllowedOutputSchema;
  schema_version: string;
  artifact: Record<string, unknown>;
};

export type GatewayOk = {
  ok: true;
  schema: AllowedOutputSchema;
  schema_version: string;
  artifact: Record<string, unknown>;
  model: AllowedModel;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  monetary_cost_usd: number;
  prompt_digest: string;
  output_digest: string;
  ready_snapshot_id: string | null;
  experiment_id: string | null;
  budget_id: string;
  budget_run_id: string;
};

export type DecodeResult<T> = { ok: true; value: T } | { ok: false; error: string };

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function fail(error: string): { ok: false; error: string } {
  return { ok: false, error };
}

function optionalNonEmptyString(
  obj: Record<string, unknown>,
  key: string,
): DecodeResult<string | undefined> {
  if (obj[key] === undefined) return { ok: true, value: undefined };
  if (typeof obj[key] !== "string" || !obj[key].trim()) {
    return fail(`${key} must be a non-empty string`);
  }
  return { ok: true, value: obj[key] };
}

function findBanned(obj: unknown, path = ""): string[] {
  const found: string[] = [];
  if (isObj(obj)) {
    for (const [k, v] of Object.entries(obj)) {
      const here = path ? `${path}.${k}` : k;
      if (BANNED_KEYS.has(k) || k === "operator_override") found.push(here);
      found.push(...findBanned(v, here));
    }
  } else if (Array.isArray(obj)) {
    obj.forEach((v, i) => found.push(...findBanned(v, `${path}[${i}]`)));
  }
  return found;
}

function unknownFields(
  obj: Record<string, unknown>,
  allowed: Set<string>,
  where: string,
): string | null {
  const extra = Object.keys(obj).filter((k) => !allowed.has(k));
  if (extra.length) return `${where} unknown field: ${extra.sort().join(",")}`;
  return null;
}

function stripEnvelope(raw: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (!ENVELOPE_KEYS.has(k)) out[k] = v;
  }
  return out;
}

/**
 * budget_id is a caller correlation/capability label, not occupancy.
 * Occupancy is reserved by the control-plane Budget Durable Object, which
 * issues an opaque Budget Run ID. Presence of budget_id is not a reserve.
 * Create is not reserve. Missing budget_id refuses decode, not occupancy.
 * Live Edge occupancy is unproven.
 */
export function decodeGatewayRequest(raw: unknown): DecodeResult<GatewayRequest> {
  if (!isObj(raw)) return fail("body must be a JSON object");
  const unknown = unknownFields(raw, REQUEST_KEYS, "request");
  if (unknown) return fail(unknown);

  const model = raw.model;
  if (typeof model !== "string" || !ALLOWED_MODEL_SET.has(model)) {
    return fail("model not allowed");
  }
  if (!Array.isArray(raw.messages) || raw.messages.length < 1) {
    return fail("messages[] required");
  }
  if (raw.messages.length > MAX_GATEWAY_MESSAGES) {
    return fail(`messages[] exceeds hard limit ${MAX_GATEWAY_MESSAGES}`);
  }
  const messages: GatewayMessage[] = [];
  for (let i = 0; i < raw.messages.length; i++) {
    const m = raw.messages[i];
    if (!isObj(m)) return fail(`messages[${i}] must be object`);
    const msgUnknown = unknownFields(m, new Set(["role", "content"]), `messages[${i}]`);
    if (msgUnknown) return fail(msgUnknown);
    if (typeof m.role !== "string" || !ALLOWED_ROLES.has(m.role)) {
      return fail(`messages[${i}].role invalid`);
    }
    if (typeof m.content !== "string") {
      return fail(`messages[${i}].content must be string`);
    }
    messages.push({
      role: m.role as GatewayMessage["role"],
      content: m.content,
    });
  }
  const inputBounds = providerInputBounds(messages);
  if (inputBounds.utf8_bytes > MAX_GATEWAY_PROMPT_UTF8_BYTES) {
    return fail(
      `messages UTF-8 bytes exceed hard limit ${MAX_GATEWAY_PROMPT_UTF8_BYTES}`,
    );
  }
  if (inputBounds.token_upper_bound > MAX_GATEWAY_INPUT_TOKENS) {
    return fail(
      `messages token upper bound exceeds hard limit ${MAX_GATEWAY_INPUT_TOKENS}`,
    );
  }
  const maxTokens = Number(raw.max_tokens);
  if (!Number.isInteger(maxTokens) || maxTokens < 1 || maxTokens > 1400) {
    return fail("max_tokens must be integer 1..1400");
  }
  if (typeof raw.budget_id !== "string" || !raw.budget_id.trim()) {
    return fail("budget_id required");
  }

  const out: GatewayRequest = {
    model: model as AllowedModel,
    messages,
    max_tokens: maxTokens,
    budget_id: raw.budget_id.trim(),
  };

  const promptDigest = optionalNonEmptyString(raw, "prompt_digest");
  if (!promptDigest.ok) return promptDigest;
  if (promptDigest.value !== undefined) out.prompt_digest = promptDigest.value;

  const ready = optionalNonEmptyString(raw, "ready_snapshot_id");
  if (!ready.ok) return ready;
  if (ready.value !== undefined) out.ready_snapshot_id = ready.value;

  const experiment = optionalNonEmptyString(raw, "experiment_id");
  if (!experiment.ok) return experiment;
  if (experiment.value !== undefined) out.experiment_id = experiment.value;

  if (raw.expected_schema !== undefined) {
    if (typeof raw.expected_schema !== "string" || !ALLOWED_SCHEMA_SET.has(raw.expected_schema)) {
      return fail("expected_schema not allowed");
    }
    out.expected_schema = raw.expected_schema as AllowedOutputSchema;
  }
  return { ok: true, value: out };
}

/** Strict JSON only. A whole-document markdown fence is stripped; no raw substring recovery. */
export function parseModelJson(raw: string): DecodeResult<unknown> {
  const trimmed = String(raw || "").trim();
  if (!trimmed) return fail("empty model output");
  const tryParse = (s: string): DecodeResult<unknown> | null => {
    try {
      return { ok: true, value: JSON.parse(s) };
    } catch {
      return null;
    }
  };
  const direct = tryParse(trimmed);
  if (direct) return direct;
  const fence = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fence) {
    const inner = tryParse(fence[1].trim());
    if (inner) return inner;
  }
  return fail("model output is not JSON");
}

function requireString(obj: Record<string, unknown>, key: string, where: string): DecodeResult<string> {
  if (typeof obj[key] !== "string") return fail(`${where}.${key} must be string`);
  return { ok: true, value: obj[key] };
}

function stringList(raw: unknown, where: string): DecodeResult<string[]> {
  if (!Array.isArray(raw)) return fail(`${where} must be a list`);
  const out: string[] = [];
  for (let i = 0; i < raw.length; i++) {
    if (typeof raw[i] !== "string") return fail(`${where}[${i}] must be string`);
    out.push(raw[i]);
  }
  return { ok: true, value: out };
}

function identifier(value: unknown, where: string): DecodeResult<string> {
  if (typeof value !== "string" || !value.trim() || !IDENTIFIER_RE.test(value.trim())) {
    return fail(`${where} must be a non-empty safe identifier`);
  }
  return { ok: true, value: value.trim() };
}

function finiteNumber(value: unknown, where: string): DecodeResult<number> {
  if (typeof value === "boolean" || typeof value !== "number" || !Number.isFinite(value)) {
    return fail(`${where} must be a finite number`);
  }
  return { ok: true, value: value };
}

function decodeInsight(body: Record<string, unknown>): DecodeResult<TypedArtifact> {
  const err = unknownFields(
    body,
    new Set(["role", "task", "summary", "prompt_chars", "schema_version"]),
    "Insight",
  );
  if (err) return fail(err);
  for (const key of ["role", "task", "summary"] as const) {
    if (body[key] !== undefined && typeof body[key] !== "string") {
      return fail(`Insight.${key} must be string`);
    }
  }
  if (body.prompt_chars !== undefined) {
    const n = finiteNumber(body.prompt_chars, "Insight.prompt_chars");
    if (!n.ok) return n;
  }
  const version =
    body.schema_version === undefined
      ? INSIGHT_SCHEMA_VERSION
      : typeof body.schema_version === "string"
        ? body.schema_version
        : null;
  if (version !== INSIGHT_SCHEMA_VERSION) {
    return fail("Insight.schema_version must be insight/v1");
  }
  return {
    ok: true,
    value: {
      schema_name: "Insight",
      schema_version: version,
      artifact: { ...body, schema_version: version },
    },
  };
}

function decodeFeatureProposal(body: Record<string, unknown>): DecodeResult<Record<string, unknown>> {
  const err = unknownFields(
    body,
    new Set([
      "feature_id",
      "intended_role",
      "rationale",
      "status",
      "inputs",
      "transform_declaration",
      "expected_rationale",
      "horizon",
      "cost_estimate",
      "provenance",
    ]),
    "FeatureProposal",
  );
  if (err) return fail(err);
  for (const key of ["feature_id", "intended_role", "rationale"] as const) {
    if (typeof body[key] !== "string" || !body[key]) {
      return fail(`FeatureProposal missing field: ${key}`);
    }
  }
  if (!FEATURE_ROLES.has(String(body.intended_role))) {
    return fail("FeatureProposal.intended_role invalid");
  }
  const status = body.status === undefined ? "candidate" : body.status;
  if (status !== "candidate") return fail("FeatureProposal.status must be candidate");
  if (body.inputs !== undefined) {
    const inputs = stringList(body.inputs, "FeatureProposal.inputs");
    if (!inputs.ok) return inputs;
  }
  for (const key of [
    "transform_declaration",
    "expected_rationale",
    "horizon",
    "cost_estimate",
    "provenance",
  ] as const) {
    if (body[key] !== undefined && typeof body[key] !== "string") {
      return fail(`FeatureProposal.${key} must be string`);
    }
  }
  return {
    ok: true,
    value: {
      feature_id: body.feature_id,
      intended_role: body.intended_role,
      rationale: body.rationale,
      status,
      inputs: Array.isArray(body.inputs) ? body.inputs : [],
      transform_declaration: body.transform_declaration ?? "",
      expected_rationale: body.expected_rationale ?? "",
      horizon: body.horizon ?? "",
      cost_estimate: body.cost_estimate ?? "",
      provenance: body.provenance ?? "",
    },
  };
}

function decodeResearchMemo(body: Record<string, unknown>): DecodeResult<TypedArtifact> {
  const err = unknownFields(
    body,
    new Set(["role", "as_of", "thesis", "evidence", "feature_proposals"]),
    "ResearchMemo",
  );
  if (err) return fail(err);
  for (const key of ["role", "as_of", "thesis"] as const) {
    const s = requireString(body, key, "ResearchMemo");
    if (!s.ok) return s;
  }
  let evidenceList: string[] = [];
  if (body.evidence !== undefined) {
    const evidence = stringList(body.evidence, "ResearchMemo.evidence");
    if (!evidence.ok) return evidence;
    evidenceList = evidence.value;
  }
  let proposals: Record<string, unknown>[] = [];
  if (body.feature_proposals !== undefined) {
    if (!Array.isArray(body.feature_proposals)) {
      return fail("ResearchMemo.feature_proposals must be a list");
    }
    for (let i = 0; i < body.feature_proposals.length; i++) {
      const row = body.feature_proposals[i];
      if (!isObj(row)) return fail(`ResearchMemo.feature_proposals[${i}] must be object`);
      const decoded = decodeFeatureProposal(row);
      if (!decoded.ok) return decoded;
      proposals.push(decoded.value);
    }
  }
  return {
    ok: true,
    value: {
      schema_name: "ResearchMemo",
      schema_version: "ResearchMemo",
      artifact: {
        role: body.role,
        as_of: body.as_of,
        thesis: body.thesis,
        evidence: evidenceList,
        feature_proposals: proposals,
      },
    },
  };
}

function decodeSelectionDecision(body: Record<string, unknown>): DecodeResult<TypedArtifact> {
  const err = unknownFields(
    body,
    new Set(["decision", "reason_codes", "subject_id", "evidence"]),
    "SelectionDecision",
  );
  if (err) return fail(err);
  if (typeof body.decision !== "string" || !SELECTION_DECISIONS.has(body.decision)) {
    return fail("SelectionDecision.decision invalid");
  }
  const codes = stringList(body.reason_codes, "SelectionDecision.reason_codes");
  if (!codes.ok) return codes;
  if (codes.value.length < 1) return fail("SelectionDecision.reason_codes must be non-empty");
  if (typeof body.subject_id !== "string" || !body.subject_id) {
    return fail("SelectionDecision.subject_id must be string");
  }
  if (body.evidence !== undefined && !isObj(body.evidence)) {
    return fail("SelectionDecision.evidence must be object");
  }
  const artifact: Record<string, unknown> = {
    decision: body.decision,
    reason_codes: codes.value,
    subject_id: body.subject_id,
  };
  if (body.evidence !== undefined) artifact.evidence = body.evidence;
  return {
    ok: true,
    value: {
      schema_name: "SelectionDecision",
      schema_version: "SelectionDecision",
      artifact,
    },
  };
}

function decodeFeatureParams(
  raw: unknown,
): DecodeResult<Record<string, string | number | boolean | null>> {
  if (raw === undefined) return { ok: true, value: {} };
  if (!isObj(raw)) return fail("FeatureRef.params must be an object");
  const reserved = Object.keys(raw).filter((k) => FEATURE_PARAM_RESERVED.has(k));
  if (reserved.length) {
    return fail(`FeatureRef.params may not set runtime-owned field(s): ${reserved.sort().join(",")}`);
  }
  const params: Record<string, string | number | boolean | null> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (!k) return fail("feature parameter names must be non-empty strings");
    if (v !== null && typeof v !== "string" && typeof v !== "number" && typeof v !== "boolean") {
      return fail(`feature parameter ${k} must be a JSON scalar`);
    }
    if (typeof v === "number" && !Number.isFinite(v)) {
      return fail(`feature parameter ${k} must be finite`);
    }
    params[k] = v as string | number | boolean | null;
  }
  return { ok: true, value: params };
}

function decodeFeatureRef(raw: unknown, where: string): DecodeResult<Record<string, unknown>> {
  if (!isObj(raw)) return fail(`${where} must be a FeatureRef object`);
  const err = unknownFields(raw, new Set(["id", "version", "params"]), "FeatureRef");
  if (err) return fail(err);
  const id = identifier(raw.id, `${where}.id`);
  if (!id.ok) return id;
  const version = identifier(raw.version, `${where}.version`);
  if (!version.ok) return version;
  const params = decodeFeatureParams(raw.params);
  if (!params.ok) return params;
  return {
    ok: true,
    value: { id: id.value, version: version.value, params: params.value },
  };
}

function frac(value: unknown, where: string): DecodeResult<number> {
  const n = finiteNumber(value, where);
  if (!n.ok) return n;
  if (n.value <= 0 || n.value > 1) return fail(`${where} must be in (0, 1]`);
  return n;
}

function signalSign(value: unknown, where: string): DecodeResult<number> {
  if (value === undefined) return { ok: true, value: 1 };
  if (typeof value === "boolean" || typeof value !== "number" || (value !== 1 && value !== -1)) {
    return fail(`${where} must be +1 or -1`);
  }
  return { ok: true, value: value };
}

function decodeRule(
  raw: unknown,
  version: string,
): DecodeResult<Record<string, unknown>> {
  if (!isObj(raw)) return fail("rule must be an object");
  const ruleType = raw.type;
  const v2 = new Set(["threshold", "top_k"]);
  const v3 = new Set(["threshold", "top_k", "cross_section_rank", "value_momentum_agree"]);
  const allowed = version === STRATEGY_SPEC_V2 ? v2 : v3;
  if (typeof ruleType !== "string" || !allowed.has(ruleType)) {
    return fail(`unknown rule type ${String(ruleType)}; allowed: ${[...allowed].sort().join(",")}`);
  }
  if (ruleType === "threshold") {
    const err = unknownFields(raw, new Set(["type", "feature", "threshold"]), "threshold rule");
    if (err) return fail(err);
    const feature = decodeFeatureRef(raw.feature, "threshold.feature");
    if (!feature.ok) return feature;
    const threshold = finiteNumber(raw.threshold, "threshold");
    if (!threshold.ok) return threshold;
    return { ok: true, value: { type: "threshold", feature: feature.value, threshold: threshold.value } };
  }
  if (ruleType === "top_k") {
    const err = unknownFields(raw, new Set(["type", "feature", "k", "min_score"]), "top_k rule");
    if (err) return fail(err);
    const feature = decodeFeatureRef(raw.feature, "top_k.feature");
    if (!feature.ok) return feature;
    if (typeof raw.k === "boolean" || typeof raw.k !== "number" || !Number.isInteger(raw.k) || raw.k < 1) {
      return fail("top_k.k must be an integer >= 1");
    }
    const out: Record<string, unknown> = { type: "top_k", feature: feature.value, k: raw.k };
    if (raw.min_score !== undefined) {
      const min = finiteNumber(raw.min_score, "top_k.min_score");
      if (!min.ok) return min;
      out.min_score = min.value;
    }
    return { ok: true, value: out };
  }
  if (ruleType === "cross_section_rank") {
    const err = unknownFields(
      raw,
      new Set(["type", "feature", "long_frac", "short_frac", "allow_short", "signal_sign"]),
      "cross_section_rank rule",
    );
    if (err) return fail(err);
    const feature = decodeFeatureRef(raw.feature, "cross_section_rank.feature");
    if (!feature.ok) return feature;
    const longFrac = frac(raw.long_frac === undefined ? 0.3 : raw.long_frac, "cross_section_rank.long_frac");
    if (!longFrac.ok) return longFrac;
    const shortFrac = frac(raw.short_frac === undefined ? 0.3 : raw.short_frac, "cross_section_rank.short_frac");
    if (!shortFrac.ok) return shortFrac;
    if (raw.allow_short !== undefined && typeof raw.allow_short !== "boolean") {
      return fail("cross_section_rank.allow_short must be a boolean");
    }
    const sign = signalSign(raw.signal_sign, "cross_section_rank.signal_sign");
    if (!sign.ok) return sign;
    const out: Record<string, unknown> = {
      type: "cross_section_rank",
      feature: feature.value,
      long_frac: longFrac.value,
      short_frac: shortFrac.value,
      allow_short: raw.allow_short === undefined ? true : raw.allow_short,
    };
    if (sign.value !== 1) out.signal_sign = sign.value;
    return { ok: true, value: out };
  }
  const err = unknownFields(
    raw,
    new Set(["type", "value_feature", "momentum_feature", "mode", "allow_short", "signal_sign"]),
    "value_momentum_agree rule",
  );
  if (err) return fail(err);
  const valueFeature = decodeFeatureRef(raw.value_feature, "value_momentum_agree.value_feature");
  if (!valueFeature.ok) return valueFeature;
  const momentumFeature = decodeFeatureRef(raw.momentum_feature, "value_momentum_agree.momentum_feature");
  if (!momentumFeature.ok) return momentumFeature;
  const mode = String(raw.mode ?? "value_momentum_agree").trim().toLowerCase();
  if (mode !== "value_momentum_agree" && mode !== "value_only") {
    return fail("value_momentum_agree.mode must be value_momentum_agree|value_only");
  }
  if (raw.allow_short !== undefined && typeof raw.allow_short !== "boolean") {
    return fail("value_momentum_agree.allow_short must be a boolean");
  }
  const sign = signalSign(raw.signal_sign, "value_momentum_agree.signal_sign");
  if (!sign.ok) return sign;
  const out: Record<string, unknown> = {
    type: "value_momentum_agree",
    value_feature: valueFeature.value,
    momentum_feature: momentumFeature.value,
    mode,
    allow_short: raw.allow_short === undefined ? true : raw.allow_short,
  };
  if (sign.value !== 1) out.signal_sign = sign.value;
  return { ok: true, value: out };
}

function decodeStrategySpec(body: Record<string, unknown>): DecodeResult<TypedArtifact> {
  const err = unknownFields(
    body,
    new Set(["version", "strategy_id", "rule", "rationale", "rebalance", "hold_days"]),
    "StrategySpec",
  );
  if (err) return fail(err);
  const version = body.version === undefined ? STRATEGY_SPEC_V3 : body.version;
  if (version !== STRATEGY_SPEC_V2 && version !== STRATEGY_SPEC_V3) {
    return fail("unsupported StrategySpec version");
  }
  const strategyId = identifier(body.strategy_id, "strategy_id");
  if (!strategyId.ok) return strategyId;
  const rule = decodeRule(body.rule, version);
  if (!rule.ok) return rule;
  if (body.rationale !== undefined && typeof body.rationale !== "string") {
    return fail("rationale must be a string");
  }
  const rebalance = String(body.rebalance ?? "daily").trim().toLowerCase();
  const allowedReb = version === STRATEGY_SPEC_V2 ? new Set(["daily"]) : new Set(["daily", "fixed_horizon"]);
  if (!allowedReb.has(rebalance)) {
    return fail(`unsupported rebalance ${rebalance} for ${version}`);
  }
  if (rebalance === "fixed_horizon") {
    if (typeof body.hold_days === "boolean" || typeof body.hold_days !== "number" || !Number.isInteger(body.hold_days) || body.hold_days < 1) {
      return fail("hold_days is required when rebalance=fixed_horizon");
    }
  } else if (body.hold_days !== undefined) {
    if (typeof body.hold_days === "boolean" || typeof body.hold_days !== "number" || !Number.isInteger(body.hold_days) || body.hold_days < 1) {
      return fail("hold_days must be an integer >= 1");
    }
  }
  const artifact: Record<string, unknown> = {
    version,
    strategy_id: strategyId.value,
    rule: rule.value,
    rationale: body.rationale ?? "",
    rebalance,
  };
  if (body.hold_days !== undefined) artifact.hold_days = body.hold_days;
  return {
    ok: true,
    value: { schema_name: "StrategySpec", schema_version: version, artifact },
  };
}

function decodeThesisProposalRow(
  raw: unknown,
  index: number,
): DecodeResult<Record<string, unknown>> {
  if (!isObj(raw)) return fail(`proposals[${index}] must be object`);
  const err = unknownFields(
    raw,
    new Set([
      "thesis",
      "signal_definition",
      "position_rule",
      "datasets",
      "gates",
      "why_different_from",
    ]),
    `proposals[${index}]`,
  );
  if (err) return fail(err);
  if (typeof raw.thesis !== "string" || !raw.thesis.trim()) {
    return fail(`proposals[${index}].thesis must be string`);
  }
  if (!Array.isArray(raw.gates)) return fail(`proposals[${index}].gates must be a list`);
  const gates: string[] = [];
  for (let i = 0; i < raw.gates.length; i++) {
    if (typeof raw.gates[i] !== "string" || !raw.gates[i].trim()) {
      return fail(`proposals[${index}].gates[${i}] must be string`);
    }
    gates.push(raw.gates[i]);
  }
  const out: Record<string, unknown> = { thesis: raw.thesis, gates };
  if (raw.signal_definition !== undefined) {
    if (typeof raw.signal_definition !== "string") {
      return fail(`proposals[${index}].signal_definition must be string`);
    }
    out.signal_definition = raw.signal_definition;
  }
  if (raw.position_rule !== undefined) {
    if (typeof raw.position_rule !== "string") {
      return fail(`proposals[${index}].position_rule must be string`);
    }
    out.position_rule = raw.position_rule;
  }
  if (raw.datasets !== undefined) {
    const ds = stringList(raw.datasets, `proposals[${index}].datasets`);
    if (!ds.ok) return ds;
    out.datasets = ds.value;
  }
  if (raw.why_different_from !== undefined) {
    const why = stringList(raw.why_different_from, `proposals[${index}].why_different_from`);
    if (!why.ok) return why;
    out.why_different_from = why.value;
  }
  return { ok: true, value: out };
}

function decodeThesisProposalList(raw: unknown): DecodeResult<TypedArtifact> {
  let body: Record<string, unknown>;
  if (Array.isArray(raw)) {
    body = { schema_version: THESIS_PROPOSAL_SCHEMA_VERSION, proposals: raw };
  } else if (isObj(raw)) {
    body = raw;
  } else {
    return fail("ThesisProposalList must be an object or array");
  }
  const err = unknownFields(
    body,
    new Set(["schema_version", "proposals"]),
    "ThesisProposalList",
  );
  if (err) return fail(err);
  const version =
    body.schema_version === undefined
      ? THESIS_PROPOSAL_SCHEMA_VERSION
      : body.schema_version;
  if (version !== THESIS_PROPOSAL_SCHEMA_VERSION) {
    return fail("ThesisProposalList.schema_version must be thesis-proposal/v1");
  }
  if (!Array.isArray(body.proposals)) return fail("ThesisProposalList.proposals must be a list");
  const proposals: Record<string, unknown>[] = [];
  for (let i = 0; i < body.proposals.length; i++) {
    const row = decodeThesisProposalRow(body.proposals[i], i);
    if (!row.ok) return row;
    proposals.push(row.value);
  }
  return {
    ok: true,
    value: {
      schema_name: "ThesisProposalList",
      schema_version: THESIS_PROPOSAL_SCHEMA_VERSION,
      artifact: { schema_version: THESIS_PROPOSAL_SCHEMA_VERSION, proposals },
    },
  };
}

function inferSchema(body: Record<string, unknown>): AllowedOutputSchema | null {
  const named = body.schema;
  if (typeof named === "string" && ALLOWED_SCHEMA_SET.has(named)) {
    return named as AllowedOutputSchema;
  }
  const version = body.schema_version ?? body.version;
  if (version === INSIGHT_SCHEMA_VERSION) return "Insight";
  if (version === THESIS_PROPOSAL_SCHEMA_VERSION) return "ThesisProposalList";
  if (version === STRATEGY_SPEC_V2 || version === STRATEGY_SPEC_V3) return "StrategySpec";
  return null;
}

function decodeByName(
  schema: AllowedOutputSchema,
  body: Record<string, unknown> | unknown,
): DecodeResult<TypedArtifact> {
  if (schema === "ThesisProposalList") return decodeThesisProposalList(body);
  if (!isObj(body)) return fail(`${schema} must be an object`);
  if (schema === "Insight") return decodeInsight(body);
  if (schema === "ResearchMemo") return decodeResearchMemo(body);
  if (schema === "FeatureProposal") {
    const decoded = decodeFeatureProposal(body);
    if (!decoded.ok) return decoded;
    return {
      ok: true,
      value: {
        schema_name: "FeatureProposal",
        schema_version: "FeatureProposal",
        artifact: decoded.value,
      },
    };
  }
  if (schema === "SelectionDecision") return decodeSelectionDecision(body);
  return decodeStrategySpec(body);
}

export function decodeTypedArtifact(
  raw: unknown,
  expectedSchema?: string,
): DecodeResult<TypedArtifact> {
  if (expectedSchema !== undefined && !ALLOWED_SCHEMA_SET.has(expectedSchema)) {
    return fail("expected_schema not allowed");
  }
  if (expectedSchema === "ThesisProposalList") {
    const banned = findBanned(raw);
    if (banned.length) return fail(`banned executable field(s): ${banned.join(",")}`);
    return decodeThesisProposalList(raw);
  }
  if (!isObj(raw) && !Array.isArray(raw)) {
    return fail("artifact must be a JSON object");
  }
  const banned = findBanned(raw);
  if (banned.length) return fail(`banned executable field(s): ${banned.join(",")}`);
  if (isObj(raw) && "operator_override" in raw) {
    return fail("operator_override rejected");
  }
  let schema: AllowedOutputSchema | null =
    expectedSchema && ALLOWED_SCHEMA_SET.has(expectedSchema)
      ? (expectedSchema as AllowedOutputSchema)
      : isObj(raw)
        ? inferSchema(raw)
        : null;
  if (!schema) return fail("expected_schema required or schema_version in output");
  if (isObj(raw) && typeof raw.schema === "string" && raw.schema !== schema) {
    return fail(`provider schema ${raw.schema} != expected ${schema}`);
  }
  const body = isObj(raw) ? stripEnvelope(raw) : raw;
  return decodeByName(schema, body);
}

/** Rough USD per 1k tokens. Ledger charge uses these measured tokens. */
export function estimateCostUsd(
  model: string,
  inputTokens: number,
  outputTokens: number,
): number {
  const perK =
    model.includes("70b") ? 0.0003 : model.includes("glm") ? 0.00008 : 0.00004;
  return Number((((inputTokens + outputTokens) / 1000) * perK).toFixed(8));
}
