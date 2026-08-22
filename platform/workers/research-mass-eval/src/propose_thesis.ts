/// <reference types="@cloudflare/workers-types" />

import type { Env } from "./types";
import { isObject, putJson } from "./http";

const PROPOSE_STUB_TEMPLATES: Array<{
  thesis: string;
  signal_definition: string;
  position_rule: string;
  datasets: string[];
  gates: string[];
  why_different_from: string[];
}> = [
  {
    thesis:
      "STUB (not catalog): liquidity × fundamentals — high-ADV names with conservative EqAR/TA change after disclosure.",
    signal_definition:
      "AND(liq_high, EqAR-or-TA-change) on the event window; skip missing ADV/EqAR/TA (no invent).",
    position_rule:
      "Event-hold original surprise sign when both gates are PIT-true; otherwise flat.",
    datasets: ["equities_bars_daily", "fins_summary", "markets_calendar"],
    gates: ["liq_high", "eq_ar_high"],
    why_different_from: ["ungated PEAD", "always-on CS EqAR sticky"],
  },
  {
    thesis:
      "STUB (not catalog): margin × price disagreement — fade names where margin is crowded while price still rises.",
    signal_definition:
      "AND(crowded_margin, price_up) occupancy; skip missing margin PIT prints (no ffill).",
    position_rule:
      "CS fade (invert mom) while both gates hold; otherwise flat.",
    datasets: [
      "equities_bars_daily",
      "markets_margin_interest",
      "markets_calendar",
    ],
    gates: ["crowded_margin"],
    why_different_from: ["ungated CS mom", "margin-only crowd fade"],
  },
  {
    thesis:
      "STUB (not catalog): disclosure × funding — PEAD only when overnight repo eased into the print cluster.",
    signal_definition:
      "AND(afterclose-or-cluster, overnight_easing) on disclosure; skip missing repo (no invent).",
    position_rule:
      "Event-hold original surprise sign when funding eased; otherwise flat.",
    datasets: [
      "equities_bars_daily",
      "fins_summary",
      "jsda_tokyo_repo_rates",
      "markets_calendar",
    ],
    gates: ["afterclose", "overnight_easing"],
    why_different_from: ["ungated PEAD", "overnight-level CS sticky"],
  },
];

function hasWorkersAi(env: Env): boolean {
  return Boolean(env.AI);
}

const PROPOSE_AI_MODEL = "@cf/meta/llama-3.1-8b-instruct-fp8";

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
): Promise<Array<Record<string, unknown>> | null> {
  if (!env.AI) return null;
  const avoid = whyAvoid.filter(Boolean).slice(0, 12).join(", ") || "(none)";
  try {
    const res = await env.AI.run(PROPOSE_AI_MODEL, {
      messages: [
        {
          role: "system",
          content:
            "You propose Japanese-equity overnight/event/CS profit theses. " +
            "Return ONLY a JSON array of exactly the requested length. " +
            "Each object: thesis, signal_definition, position_rule, " +
            "datasets (string array), gates (string array), why_different_from (string array). " +
            "datasets MUST be a subset of: equities_bars_daily, fins_summary, " +
            "markets_calendar, markets_margin_interest, markets_short_ratio, " +
            "jsda_tokyo_repo_rates. gates MUST be 2 or 3 distinct economic gates " +
            "(AND-cross, not a single-gate PEAD filter, not 4+ sparse AND) from: liq_high, cheap_pb, " +
            "eq_ar_high, eq_ar_rising, ta_up, ta_down, margin_up, margin_down, " +
            "crowded_margin, uncrowded_margin, easy_funding, tight_funding, " +
            "afterclose, cluster, pre_mom, price_down, eps_up, eps_down, " +
            "np_negative, pb_rising, roe_low, sales_down, steep_curve, " +
            "overnight_easing, overnight_tightening, on_impulse, large_surprise, " +
            "repo_3m_down, cheap_iv, rich_iv. No opposite pairs (easy+tight). " +
            "No weekday-only gates. Thesis title must NOT be the labels " +
            "'Liquidity × Fundamentals', 'Margin × Price', or 'Disclosure × Funding'. " +
            "Do not invent datasets, fields, or gates. " +
            "No logic_id. No hold_days/window/mom-only tweaks. No catalog inject. " +
            "Skip missing prints (no invent). Economic difference only.",
        },
        {
          role: "user",
          content:
            `Propose exactly ${n} theses as a JSON array. Avoid resembling: ${avoid}. ` +
            "Use AND-crosses of 2+ economic gates. Do not echo direction labels as titles.",
        },
      ],
      max_tokens: 900,
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
    return rows.length ? rows : null;
  } catch {
    return null;
  }
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

function stubProposals(
  n: number,
  whyAvoid: string[],
): Array<Record<string, unknown>> {
  const avoid = new Set(whyAvoid.map((x) => String(x)));
  const out: Array<Record<string, unknown>> = [];
  for (const t of PROPOSE_STUB_TEMPLATES) {
    if (out.length >= n) break;
    out.push({
      thesis: t.thesis,
      signal_definition: t.signal_definition,
      position_rule: t.position_rule,
      datasets: t.datasets,
      gates: t.gates,
      why_different_from: t.why_different_from.filter((x) => !avoid.has(x)),
      not_injected: true,
      status: "stub_not_catalog",
    });
  }
  return out;
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
  const usedLlm = Array.isArray(llm) && llm.length > 0;
  const proposals = usedLlm ? llm : stubProposals(n, whyAvoid);
  const payload: Record<string, unknown> = {
    ok: true,
    proposals,
    auto_inject: false,
    go: false,
    not_a_pass: true,
    catalog_written: false,
    ids_injected: false,
    workers_ai_bound: hasWorkersAi(env),
    workers_ai_used: usedLlm,
    proposal_source: usedLlm ? "workers_ai" : "stub",
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

