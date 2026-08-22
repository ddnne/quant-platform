/// <reference types="@cloudflare/workers-types" />

import type { Env } from "./types";
import { isObject, putJson } from "./http";

function hasWorkersAi(env: Env): boolean {
  return Boolean(env.AI);
}

/** CF-internal only. 70B first; GLM flash then 8B. Never leave CF. */
const PROPOSE_AI_MODELS = [
  "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
  "@cf/zai-org/glm-4.7-flash",
  "@cf/meta/llama-3.1-8b-instruct-fp8",
] as const;

const DEFAULT_PROPOSE_DATASETS = [
  "equities_bars_daily",
  "fins_summary",
  "markets_calendar",
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

function normalizeProposalRow(
  row: Record<string, unknown>,
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

function extractAiText(res: unknown): string {
  if (typeof res === "string") return res;
  if (Array.isArray(res)) return JSON.stringify(res);
  if (!isObject(res)) return "";
  const nested =
    res.response ?? res.result ?? res.output_text ?? res.text ?? res.content;
  if (typeof nested === "string") return nested;
  if (Array.isArray(nested)) return JSON.stringify(nested);
  if (isObject(nested)) {
    if (typeof nested.response === "string") return nested.response;
    if (Array.isArray(nested.response)) return JSON.stringify(nested.response);
    return JSON.stringify(nested);
  }
  return JSON.stringify(res);
}

function parseProposalArray(raw: string, n: number): Array<Record<string, unknown>> {
  let text = String(raw || "").replace(/```(?:json)?/gi, "").trim();
  const out: Array<Record<string, unknown>> = [];
  const tryParse = (blob: string): unknown => {
    try {
      return JSON.parse(blob);
    } catch {
      try {
        return JSON.parse(blob.replace(/,\s*([}\]])/g, "$1"));
      } catch {
        return null;
      }
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
      ? Array.isArray((parsed as { proposals?: unknown }).proposals)
        ? ((parsed as { proposals: unknown[] }).proposals)
        : [parsed]
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
    "gates: 2 or 3 from curve_flatten, overnight_p10, pb_rising, roe_low, " +
    "eps_down, np_negative, sales_down, invert_curve, tight_funding, " +
    "overnight_tightening, margin_up, margin_down, crowded_margin, " +
    "uncrowded_margin, repo_3m_down, overnight_easing, steep_curve, " +
    "eq_ar_rising, eq_ar_falling, ta_up, ta_down, cheap_iv, rich_iv, " +
    "nky_vol_high_skip, large_surprise, on_impulse, pre_mom, liq_high, " +
    "eps_up, price_down, easy_funding, cluster, afterclose, positive_eps. " +
    "Prefer curve_flatten, overnight_p10, pb_rising, roe_low, eps_down, " +
    "np_negative, sales_down, invert_curve, tight_funding. " +
    "Do not pair nky_vol_high_skip with steep_curve. Do not pair cheap_iv with steep_curve. " +
    "Do not start with cheap_pb. No weekday. No opposite pairs. " +
    "Thesis is an occupancy sentence matching gate polarity. EqAR is not risk appetite. " +
    "ta_up is total assets, not technical analysis. No A×B×C labels. " +
    "Do not invent datasets, fields, or gates. No logic_id. No inject.";
  const user =
    `Propose exactly ${n} JSON theses. Avoid: ${avoid}.\n` +
    "GOOD: {\"thesis\":\"PEAD when overnight funding is tight AND sales contracted.\"," +
    "\"signal_definition\":\"AND(tight_funding, sales_down) PIT; skip missing.\"," +
    "\"position_rule\":\"Event-hold surprise sign when both gates hold; else flat.\"," +
    "\"datasets\":[\"equities_bars_daily\",\"fins_summary\",\"jsda_tokyo_repo_rates\"]," +
    "\"gates\":[\"tight_funding\",\"sales_down\"]," +
    "\"why_different_from\":[\"ungated PEAD\"]}\n" +
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
        if (Array.isArray(res)) {
          const direct = parseProposalArray(JSON.stringify(res), n);
          if (direct.length) return { rows: direct, reason: null, model };
        }
        const text = extractAiText(res);
        const rows = parseProposalArray(text, n);
        if (rows.length) return { rows, reason: null, model };
        const preview = text.replace(/\s+/g, " ").slice(0, 80);
        lastReason = `parse_empty:${model}:raw_len=${text.length}:attempt=${attempt}:preview=${preview}`;
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
function titleOccupancyBad(title: string, gates: string[]): boolean {
  const polar = title.replace(/_/g, " ").replace(/-/g, " ");
  const gset = new Set(gates);
  const contra: Array<[string, string[]]> = [
    ["sales_down", ["rising sales", "sales up", "sales growth", "high sales", "sales increase"]],
    ["np_negative", ["positive np", "positive profit", "rising profit", "profit up"]],
    ["price_down", ["price up", "rising price", "increase in price", "price increase"]],
    ["ta_down", ["ta up", "rising ta"]],
    ["ta_up", ["ta down", "falling ta"]],
    [
      "eq_ar_falling",
      [
        "rising eqar",
        "eqar rising",
        "eq ar rising",
        "high eqar",
        "high equity",
        "rising equity",
        "equity risk premium is rising",
        "rising equity risk",
      ],
    ],
    ["eq_ar_rising", ["falling eqar", "eqar falling", "eq ar falling"]],
    ["eq_ar_low", ["high eqar", "eqar high", "eq ar high"]],
    ["eq_ar_high", ["low eqar", "eqar low", "eq ar low"]],
    ["tight_funding", ["easy funding", "funding easing", "eased funding"]],
    ["easy_funding", ["tight funding", "funding tight"]],
    ["eps_down", ["eps up", "rising eps"]],
    ["eps_up", ["eps down", "falling eps"]],
    ["margin_down", ["margin up", "rising margin"]],
    ["margin_up", ["margin down", "falling margin"]],
    ["nky_vol_high_skip", ["volatility is high", "vol is high", "high volatility", "nky vol high"]],
    ["crowded_margin", ["uncrowded"]],
    ["uncrowded_margin", ["is crowded", "margin is crowded"]],
    ["cheap_iv", ["rich iv", "iv is rich", "expensive iv"]],
    ["rich_iv", ["cheap iv", "iv is cheap"]],
    ["overnight_easing", ["tightening"]],
    ["overnight_tightening", ["easing", "easy funding"]],
    ["repo_3m_down", ["high repo", "repo rate is high", "rising repo", "repo up"]],
  ];
  for (const [gate, words] of contra) {
    if (!gset.has(gate)) continue;
    if (words.some((w) => polar.includes(w))) return true;
  }
  const labels: Array<[string, string[]]> = [
    ["eq_ar_falling", ["risk appetite", "risk premia", "risk premium", "risk arbitrage"]],
    ["eq_ar_rising", ["risk appetite", "risk premia", "risk premium", "risk arbitrage"]],
    ["eq_ar_high", ["risk appetite", "risk premia", "risk premium", "risk arbitrage"]],
    ["eq_ar_low", ["risk appetite", "risk premia", "risk premium", "risk arbitrage"]],
    ["repo_3m_down", ["repo rates are low", "low repo", "repo is low"]],
    ["ta_up", ["technical analysis", "technical signal", "ta signals"]],
    ["ta_down", ["technical analysis", "technical signal", "ta signals"]],
    ["overnight_p10", ["at 10%", "funding at 10", "10 percent", "10% predicts"]],
    ["pb_rising", ["is rising", "pb rose", "rising price-to-book", "price-to-book is rising"]],
  ];
  for (const [gate, words] of labels) {
    if (!gset.has(gate)) continue;
    if (!words.some((w) => polar.includes(w))) continue;
    if (
      gate.startsWith("eq_ar") &&
      (polar.includes("eqar") ||
        polar.includes("eq ar") ||
        polar.includes("equity to asset"))
    ) {
      continue;
    }
    if (gate.startsWith("ta_") && polar.includes("total assets")) continue;
    if (
      gate === "overnight_p10" &&
      ["easiest", "percentile", "decile", "p10"].some((t) => polar.includes(t))
    ) {
      continue;
    }
    if (
      gate === "pb_rising" &&
      ["median", "pit median", "above median"].some((t) => polar.includes(t))
    ) {
      continue;
    }
    return true;
  }
  const sparse: string[][] = [
    ["nky_vol_high_skip", "steep_curve"],
    ["cheap_iv", "steep_curve"],
    ["cheap_iv", "cheap_pb"],
    ["cheap_iv", "margin_up", "repo_3m_down"],
    ["margin_down", "eq_ar_rising", "steep_curve"],
    ["rich_iv", "margin_up", "eq_ar_falling"],
    ["div_positive", "cheap_iv"],
  ];
  if (sparse.some((combo) => combo.every((g) => gset.has(g)))) return true;
  const extraTitle: Array<[string, string]> = [
    ["tight funding", "tight_funding"],
    ["easy funding", "easy_funding"],
    ["sales contraction", "sales_down"],
    ["sales contracted", "sales_down"],
  ];
  if (extraTitle.some(([phrase, gate]) => polar.includes(phrase) && !gset.has(gate))) {
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

