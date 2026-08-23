/// <reference types="@cloudflare/workers-types" />

import type { Env } from "./types";
import { isObject, putJson } from "./http";
import { completeViaGateway, hasAiGateway } from "./ai_gateway_client";
import {
  DEFAULT_PROPOSE_DATASETS,
  PROMPT_DIRECTION_ECHO_X,
  PROPOSE_ALLOWED_DATASETS,
  PROPOSE_ALLOWED_GATES,
  PROPOSE_PROMPT_BAD,
  PROPOSE_PROMPT_GOOD,
  PROPOSE_PROMPT_PREFER_GATES,
  PROPOSE_TWEAK_WORDS,
  PROPOSE_WHY_AVOID_LIMIT,
} from "./propose_allowed";
import {
  EXTRA_TITLE_GATES,
  GATE_OCCUPANCY_LABEL,
  GATE_TITLE_CONTRA,
  OCCUPANCY_EXTRA_TITLE,
  OCCUPANCY_LABEL_EXCEPTIONS,
  PROPOSE_CONTRADICTORY_GATE_PAIRS,
  SPARSE_GATE_COMBOS_REVIEW,
  TITLE_OCCUPANCY_META,
} from "./propose_review_tables";

function hasWorkersAi(env: Env): boolean {
  return hasAiGateway(env);
}

/** CF-internal only. 70B first; GLM flash then 8B. Never leave CF. */
const PROPOSE_AI_MODELS = [
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/zai-org/glm-4.7-flash",
  "@cf/meta/llama-3.1-8b-instruct-fp8",
] as const;

function coerceGateList(raw: unknown): string[] {
  const gateAllow = new Set<string>(PROPOSE_ALLOWED_GATES);
  const parts: string[] = [];
  if (Array.isArray(raw)) {
    for (const x of raw) parts.push(String(x));
  } else if (typeof raw === "string") {
    for (const x of raw.split(/[+,]/)) parts.push(x);
  }
  const out: string[] = [];
  const seen = new Set<string>();
  for (const p of parts) {
    const g = p.trim();
    if (!g || !gateAllow.has(g) || seen.has(g)) continue;
    seen.add(g);
    out.push(g);
  }
  return out;
}

function gateAndToken(gates: string[]): string {
  return [...gates].filter(Boolean).sort().join("+");
}

function normalizeProposalRow(
  row: Record<string, unknown>,
  avoidTokens: Set<string>,
): Record<string, unknown> | null {
  const thesis = String(row.thesis ?? "").trim();
  const gates = coerceGateList(row.gates);
  if (!thesis || gates.length < 2 || gates.length > 3) return null;
  let signal = String(row.signal_definition ?? row.signal ?? "").trim();
  if (!signal) signal = `AND(${gates.join(", ")}) PIT; skip missing prints (no invent).`;
  let position = String(row.position_rule ?? row.position ?? "").trim();
  if (!position) {
    position =
      "Event-hold original surprise sign when gates are PIT-true; otherwise flat.";
  }
  const allow = new Set<string>(PROPOSE_ALLOWED_DATASETS);
  let datasets = (
    Array.isArray(row.datasets) ? row.datasets : []
  )
    .map((x) => String(x))
    .filter((x) => allow.has(x));
  if (datasets.length < 1) datasets = [...DEFAULT_PROPOSE_DATASETS];
  if (
    isWindowTweakOnly({
      ...row,
      thesis,
      signal_definition: signal,
      position_rule: position,
      datasets,
    })
  ) {
    return null;
  }
  const gset = new Set(gates);
  if (PROPOSE_CONTRADICTORY_GATE_PAIRS.some((pair) => pair.every((g) => gset.has(g)))) {
    return null;
  }
  if (avoidTokens.has(gateAndToken(gates))) return null;
  const title = thesis.toLowerCase().replace(/×/g, "x");
  if (PROMPT_DIRECTION_ECHO_X.some((echo) => title.includes(echo))) {
    return null;
  }
  if (titleOccupancyBad(title, gates)) return null;
  const why = Array.isArray(row.why_different_from)
    ? row.why_different_from.map((x) => String(x)).filter(Boolean)
    : [];
  return {
    thesis,
    signal_definition: signal,
    position_rule: position,
    datasets,
    gates,
    why_different_from: why,
    not_injected: true,
    status: "llm_not_catalog",
  };
}

function decodeProposalArtifact(
  artifact: Record<string, unknown>,
  n: number,
  avoidTokens: Set<string>,
): Array<Record<string, unknown>> {
  const rows = Array.isArray(artifact.proposals) ? artifact.proposals : [];
  const out: Array<Record<string, unknown>> = [];
  for (const row of rows) {
    if (!isObject(row)) continue;
    const norm = normalizeProposalRow(row, avoidTokens);
    if (!norm) continue;
    out.push(norm);
    if (out.length >= n) break;
  }
  return out;
}

async function llmProposals(
  env: Env,
  n: number,
  whyAvoid: string[],
  budgetId: string,
): Promise<{
  rows: Array<Record<string, unknown>> | null;
  reason: string | null;
  model: string | null;
}> {
  if (!env.AI_GATEWAY) return { rows: null, reason: "ai_gateway_unbound", model: null };
  if (!budgetId) return { rows: null, reason: "budget_id required", model: null };
  const avoidList = whyAvoid.filter(Boolean).slice(0, PROPOSE_WHY_AVOID_LIMIT);
  const avoidTokens = new Set(avoidList.map((t) => t.trim()).filter(Boolean));
  const avoid = avoidList.join(", ") || "(none)";
  const sparseBan = SPARSE_GATE_COMBOS_REVIEW.filter((c) => c.length === 2)
    .map((c) => `Do not pair ${c[0]} with ${c[1]}.`)
    .join(" ");
  const system =
    "Return ONLY a JSON array. Each object: thesis, signal_definition, " +
    "position_rule, datasets, gates, why_different_from. " +
    `gates: 2 or 3 from ${PROPOSE_ALLOWED_GATES.join(", ")}. ` +
    `Prefer ${PROPOSE_PROMPT_PREFER_GATES.join(", ")}. ` +
    sparseBan +
    " Do not start with cheap_pb. No weekday. No opposite pairs. " +
    "Thesis is an occupancy sentence matching gate polarity. EqAR is not risk appetite. " +
    "ta_up is total assets, not technical analysis. No A×B×C labels. " +
    "If GOOD gates are not in Avoid, copy that AND with occupancy sentences. " +
    "Do not invent datasets, fields, or gates. No logic_id. No inject.";
  const user =
    `Propose exactly ${n} JSON theses. Avoid: ${avoid}.\n` +
    `GOOD: ${JSON.stringify(PROPOSE_PROMPT_GOOD)}\n` +
    `BAD: ${PROPOSE_PROMPT_BAD}.`;
  let lastReason = "parse_empty";
  let lastModel: string | null = null;
  const notes: string[] = [];
  for (const model of PROPOSE_AI_MODELS) {
    lastModel = model;
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const gw = await completeViaGateway(env, {
          model,
          messages: [
            { role: "system", content: system },
            { role: "user", content: user },
          ],
          max_tokens: 1400,
          expected_schema: "ThesisProposalList",
          budget_id: budgetId,
        });
        if (!gw.ok) {
          lastReason = `gateway:${gw.reason || "failed"}:${model}:attempt=${attempt}`;
          continue;
        }
        const rows = decodeProposalArtifact(gw.artifact, n, avoidTokens);
        if (rows.length) return { rows, reason: null, model };
        lastReason = `parse_empty:${model}:attempt=${attempt}:avoid_filtered`;
      } catch (e) {
        lastReason = `ai_error:${model}:${e instanceof Error ? e.message : String(e)}`.slice(
          0,
          180,
        );
      }
    }
    notes.push(lastReason);
  }
  return { rows: null, reason: notes.join("|") || lastReason, model: lastModel };
}

/** Drop inverted / slang titles so they do not occupy an ok:true slot.
 * Python review_proposal_row remains the adopt gate. Never injects.
 */
function occupancyExceptionTokens(gate: string): string[] {
  for (const [g, tokens] of OCCUPANCY_LABEL_EXCEPTIONS) {
    if (g === gate) return tokens;
  }
  if (gate.startsWith("eq_ar")) return ["eqar", "eq ar", "equity to asset"];
  if (gate.startsWith("ta_")) return ["total assets"];
  return [];
}

function titleOccupancyBad(title: string, gates: string[]): boolean {
  const polar = title.replace(/_/g, " ").replace(/-/g, " ");
  const gset = new Set(gates);
  if (TITLE_OCCUPANCY_META.some((p) => polar.includes(p))) return true;
  for (const [gate, words] of GATE_TITLE_CONTRA) {
    if (!gset.has(gate)) continue;
    if (words.some((w) => polar.includes(w))) return true;
  }
  for (const [gate, words] of GATE_OCCUPANCY_LABEL) {
    if (!gset.has(gate)) continue;
    if (!words.some((w) => polar.includes(w))) continue;
    if (occupancyExceptionTokens(gate).some((t) => polar.includes(t))) continue;
    return true;
  }
  if (SPARSE_GATE_COMBOS_REVIEW.some((combo) => combo.every((g) => gset.has(g)))) {
    return true;
  }
  if (
    OCCUPANCY_EXTRA_TITLE.some(
      ([phrase, owners]) => polar.includes(phrase) && !owners.some((g) => gset.has(g)),
    )
  ) {
    return true;
  }
  if (EXTRA_TITLE_GATES.some(([phrase, gate]) => polar.includes(phrase) && !gset.has(gate))) {
    return true;
  }
  return false;
}

function isWindowTweakOnly(o: Record<string, unknown>): boolean {
  const keys = [
    "thesis",
    "signal_definition",
    "signal",
    "position_rule",
    "position",
  ];
  const hasProposalFields = keys.some((k) =>
    Object.prototype.hasOwnProperty.call(o, k),
  );
  if (!hasProposalFields) return false;
  const thesis = String(o.thesis ?? "").trim();
  const signal = String(o.signal_definition ?? o.signal ?? "").trim();
  const position = String(o.position_rule ?? o.position ?? "").trim();
  if (!thesis || !signal || !position) return true;
  const blob = `${thesis} ${signal}`.toLowerCase();
  if (PROPOSE_TWEAK_WORDS.some((w) => blob.includes(w)) && !blob.includes("factor")) {
    const ds = o.datasets ?? o.datasets_used;
    if (!Array.isArray(ds) || ds.length === 0) return true;
  }
  return false;
}

export async function runProposeThesis(
  env: Env,
  body: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  if (isWindowTweakOnly(body)) {
    return {
      ok: false,
      error: "window_tweak_only_forbidden",
      auto_inject: false,
      go: false,
      not_a_pass: true,
    };
  }
  if (Array.isArray(body.proposals)) {
    for (const raw of body.proposals) {
      if (isObject(raw) && isWindowTweakOnly(raw)) {
        return {
          ok: false,
          error: "window_tweak_only_forbidden",
          auto_inject: false,
          go: false,
          not_a_pass: true,
        };
      }
    }
  }
  const nRaw = body.n != null ? Number(body.n) : 3;
  const n = Number.isFinite(nRaw)
    ? Math.max(1, Math.min(3, Math.floor(nRaw)))
    : 3;
  const whyAvoid = Array.isArray(body.why_avoid)
    ? body.why_avoid.map((x) => String(x))
    : [];
  const writeArtifacts = body.write_artifacts === true;
  const budgetId =
    typeof body.budget_id === "string" && body.budget_id.trim()
      ? body.budget_id.trim()
      : "";
  const llm = await llmProposals(env, n, whyAvoid, budgetId);
  const usedLlm = Array.isArray(llm.rows) && llm.rows.length > 0;
  const payload: Record<string, unknown> = usedLlm
    ? {
        ok: true,
        proposals: llm.rows as Array<Record<string, unknown>>,
        auto_inject: false,
        go: false,
        not_a_pass: true,
        catalog_written: false,
        ids_injected: false,
        workers_ai_bound: hasWorkersAi(env),
        workers_ai_used: true,
        proposal_source: "workers_ai",
        propose_ai_model: llm.model,
        llm_fallback_reason: null,
      }
    : {
        ok: false,
        error: "llm_failed",
        proposals: [],
        auto_inject: false,
        go: false,
        not_a_pass: true,
        catalog_written: false,
        ids_injected: false,
        workers_ai_bound: hasWorkersAi(env),
        workers_ai_used: false,
        proposal_source: "llm_failed",
        propose_ai_model: llm.model,
        llm_fallback_reason: llm.reason,
      };
  if (writeArtifacts) {
    const jobId = String(body.job_id ?? "").trim();
    if (!jobId || /[\\/]|\.\./.test(jobId)) {
      return {
        ok: false,
        error: "job_id required for write_artifacts",
        auto_inject: false,
        go: false,
        not_a_pass: true,
      };
    }
    if (!env.STRUCTURED_BUCKET) {
      return {
        ok: false,
        error: "STRUCTURED_BUCKET not bound",
        auto_inject: false,
        go: false,
        not_a_pass: true,
      };
    }
    const key = `research/eval/job=${jobId}/propose_thesis.json`;
    await putJson(env.STRUCTURED_BUCKET, key, payload);
    payload.r2_keys = { propose_thesis: key };
  }
  return payload;
}

