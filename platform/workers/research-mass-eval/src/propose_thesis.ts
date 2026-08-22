/// <reference types="@cloudflare/workers-types" />

import type { Env } from "./types";
import { isObject, putJson } from "./http";

function hasWorkersAi(env: Env): boolean {
  return Boolean(env.AI);
}

/** Prefer 70B instruct; 8B is CF-internal fallback only. Never leave CF. */
const PROPOSE_AI_MODELS = [
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/meta/llama-3.1-8b-instruct-fp8",
] as const;

const PROPOSE_ALLOWED_DATASETS = [
  "equities_bars_daily",
  "fins_summary",
  "jsda_tokyo_repo_rates",
  "markets_calendar",
  "markets_margin_interest",
  "markets_short_ratio",
] as const;

/** Economic gates only. Weekday/calendar permutations are not a new thesis. */
const PROPOSE_ALLOWED_GATES = [
  "afterclose",
  "cheap_iv",
  "cheap_pb",
  "cluster",
  "crowded_margin",
  "curve_flatten",
  "div_positive",
  "easy_funding",
  "eps_down",
  "eps_up",
  "eq_ar_falling",
  "eq_ar_high",
  "eq_ar_low",
  "eq_ar_rising",
  "invert_curve",
  "large_surprise",
  "liq_high",
  "margin_down",
  "margin_up",
  "nky_vol_high_skip",
  "np_negative",
  "on_impulse",
  "overnight_easing",
  "overnight_p10",
  "overnight_tightening",
  "pb_rising",
  "positive_eps",
  "pre_mom",
  "price_down",
  "repo_3m_down",
  "rich_iv",
  "roe_low",
  "sales_down",
  "steep_curve",
  "ta_down",
  "ta_up",
  "tight_funding",
  "uncrowded_margin",
] as const;

function normalizeProposalRow(
  row: Record<string, unknown>,
): Record<string, unknown> | null {
  if (isWindowTweakOnly(row)) return null;
  const thesis = String(row.thesis ?? "").trim();
  const signal = String(row.signal_definition ?? row.signal ?? "").trim();
  const position = String(row.position_rule ?? row.position ?? "").trim();
  if (!thesis || !signal || !position) return null;
  const allow = new Set<string>(PROPOSE_ALLOWED_DATASETS);
  const datasets = (
    Array.isArray(row.datasets) ? row.datasets : []
  )
    .map((x) => String(x))
    .filter((x) => allow.has(x));
  if (datasets.length < 1) return null;
  const gateAllow = new Set<string>(PROPOSE_ALLOWED_GATES);
  const gates = (Array.isArray(row.gates) ? row.gates : [])
    .map((x) => String(x))
    .filter((x) => gateAllow.has(x));
  if (gates.length < 2 || gates.length > 3) return null;
  const gset = new Set(gates);
  const contra: string[][] = [
    ["easy_funding", "tight_funding"],
    ["crowded_margin", "uncrowded_margin"],
    ["eq_ar_high", "eq_ar_low"],
    ["eq_ar_rising", "eq_ar_falling"],
    ["cheap_iv", "rich_iv"],
    ["ta_up", "ta_down"],
    ["overnight_easing", "overnight_tightening"],
    ["margin_up", "margin_down"],
    ["eps_up", "eps_down"],
  ];
  if (contra.some((pair) => pair.every((g) => gset.has(g)))) return null;
  const title = thesis.toLowerCase().replace(/×/g, "x");
  if (
    title.includes("liquidity x fundamentals") ||
    title.includes("margin x price") ||
    title.includes("disclosure x funding")
  ) {
    return null;
  }
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

function parseProposalArray(raw: string, n: number): Array<Record<string, unknown>> {
  const text = String(raw || "");
  const out: Array<Record<string, unknown>> = [];
  const tryParse = (blob: string): unknown => {
    try {
      return JSON.parse(blob);
    } catch {
      return null;
    }
  };
  const arrStart = text.indexOf("[");
  const arrEnd = text.lastIndexOf("]");
  let parsed: unknown = null;
  if (arrStart >= 0 && arrEnd > arrStart) {
    parsed = tryParse(text.slice(arrStart, arrEnd + 1));
  }
  if (parsed == null) {
    const oStart = text.indexOf("{");
    const oEnd = text.lastIndexOf("}");
    if (oStart >= 0 && oEnd > oStart) {
      parsed = tryParse(text.slice(oStart, oEnd + 1));
    }
  }
  const rows = Array.isArray(parsed)
    ? parsed
    : isObject(parsed)
      ? [parsed]
      : [];
  for (const row of rows) {
    if (!isObject(row)) continue;
    const norm = normalizeProposalRow(row);
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
): Promise<{
  rows: Array<Record<string, unknown>> | null;
  reason: string | null;
  model: string | null;
}> {
  if (!env.AI) return { rows: null, reason: "ai_unbound", model: null };
  const avoid = whyAvoid.filter(Boolean).slice(0, 24).join(", ") || "(none)";
  const system =
    "Return ONLY a JSON array. Each object: thesis, signal_definition, " +
    "position_rule, datasets, gates, why_different_from. " +
    "gates: 2 or 3 from margin_up, margin_down, crowded_margin, uncrowded_margin, " +
    "repo_3m_down, overnight_easing, overnight_tightening, steep_curve, " +
    "invert_curve, eq_ar_rising, eq_ar_falling, ta_up, ta_down, cheap_iv, " +
    "rich_iv, nky_vol_high_skip, large_surprise, on_impulse, pre_mom, " +
    "liq_high, eps_up, eps_down, sales_down, np_negative, price_down, " +
    "easy_funding, tight_funding, cluster. Prefer margin/repo/EqAR-TA/vol. " +
    "Do not start with cheap_pb. No weekday. No opposite pairs. " +
    "Thesis is an occupancy sentence matching gate polarity. No A×B×C labels. " +
    "Do not invent datasets, fields, or gates. No logic_id. No inject.";
  const user =
    `Propose exactly ${n} JSON theses. Avoid: ${avoid}.\n` +
    "GOOD: {\"thesis\":\"PEAD when overnight funding is tight AND sales contracted.\"," +
    "\"gates\":[\"tight_funding\",\"sales_down\"]}\n" +
    "BAD: thesis \"Rising Sales\" with gates sales_down, or \"Liquidity × Price × Margin\".";
  let lastReason = "parse_empty";
  let lastModel: string | null = null;
  const notes: string[] = [];
  for (const model of PROPOSE_AI_MODELS) {
    lastModel = model;
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const res = await env.AI.run(model, {
          messages: [
            { role: "system", content: system },
            { role: "user", content: user },
          ],
          max_tokens: 1400,
        });
        const text =
          typeof res === "string"
            ? res
            : isObject(res)
              ? String(
                  (res as { response?: unknown }).response ??
                    (res as { result?: unknown }).result ??
                    JSON.stringify(res),
                )
              : "";
        const rows = parseProposalArray(text, n);
        if (rows.length) return { rows, reason: null, model };
        lastReason = `parse_empty:${model}:raw_len=${text.length}:attempt=${attempt}`;
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
  const tweakWords = ["window", "hold_days only", "mom only", "frac only"];
  if (tweakWords.some((w) => blob.includes(w)) && !blob.includes("factor")) {
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
  const llm = await llmProposals(env, n, whyAvoid);
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

