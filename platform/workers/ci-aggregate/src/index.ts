/// <reference types="@cloudflare/workers-types" />

import { json } from "./http_json";
import { authorized } from "./authorized";

export { authorized } from "./authorized";

/** Six Workers Builds lanes that must all pass the same HEAD SHA. */
export const REQUIRED_WORKERS = [
  "ingestion-jsda",
  "ingestion-premium",
  "ingestion-secrets",
  "quant-ops-mcp",
  "research-ai-gateway",
  "research-mass-eval",
] as const;

export type RequiredWorker = (typeof REQUIRED_WORKERS)[number];

const REQUIRED_SET: ReadonlySet<string> = new Set(REQUIRED_WORKERS);

export const DEFAULT_STATUS_CONTEXT = "ci-aggregate";
export const DEFAULT_GITHUB_REPOSITORY = "ddnne/quant-platform";

const SHA_RE = /^[0-9a-f]{40}$/i;

export interface LaneReceipt {
  worker: string;
  sha: string;
  result: "pass" | "fail";
  command: string;
}

export interface AggregateEnv {
  CI_LANE_TOKEN?: string;
  GITHUB_STATUS_TOKEN?: string;
  GITHUB_REPOSITORY?: string;
  GITHUB_STATUS_CONTEXT?: string;
}

export type GateOk = {
  ok: true;
  sha: string;
  receipts: LaneReceipt[];
};

export type GateFail = {
  ok: false;
  reason:
    | "invalid_receipt"
    | "unknown_worker"
    | "duplicate_worker"
    | "sha_mismatch"
    | "missing_receipt"
    | "lane_failed";
  sha?: string;
  missing?: string[];
  failed?: string[];
  shas?: string[];
  detail?: string;
};

export type GateVerdict = GateOk | GateFail;

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

function parseOneReceipt(raw: unknown, index: number): LaneReceipt | GateFail {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      ok: false,
      reason: "invalid_receipt",
      detail: `receipts[${index}] must be an object`,
    };
  }
  const rec = raw as Record<string, unknown>;
  if (!isNonEmptyString(rec.worker)) {
    return {
      ok: false,
      reason: "invalid_receipt",
      detail: `receipts[${index}].worker is required`,
    };
  }
  if (!isNonEmptyString(rec.sha) || !SHA_RE.test(rec.sha.trim())) {
    return {
      ok: false,
      reason: "invalid_receipt",
      detail: `receipts[${index}].sha must be a 40-hex git SHA`,
    };
  }
  if (rec.result !== "pass" && rec.result !== "fail") {
    return {
      ok: false,
      reason: "invalid_receipt",
      detail: `receipts[${index}].result must be pass or fail`,
    };
  }
  if (!isNonEmptyString(rec.command)) {
    return {
      ok: false,
      reason: "invalid_receipt",
      detail: `receipts[${index}].command is required`,
    };
  }
  return {
    worker: rec.worker.trim(),
    sha: rec.sha.trim().toLowerCase(),
    result: rec.result,
    command: rec.command.trim(),
  };
}

/** Collect receipts from a POST body. PR comments are never read or accepted. */
export function collectReceipts(
  body: unknown,
): { ok: true; receipts: unknown[] } | GateFail {
  if (Array.isArray(body)) return { ok: true, receipts: body };
  if (body && typeof body === "object") {
    const rec = body as Record<string, unknown>;
    if (Array.isArray(rec.receipts)) return { ok: true, receipts: rec.receipts };
    if ("worker" in rec || "sha" in rec || "result" in rec || "command" in rec) {
      return { ok: true, receipts: [body] };
    }
  }
  return {
    ok: false,
    reason: "invalid_receipt",
    detail: "body must be {receipts:[...]} or a receipt object",
  };
}

/**
 * Fail-closed aggregate: same HEAD SHA, all six workers present, all pass.
 * A GitHub PR comment is not an input and cannot make this return ok.
 */
export function evaluateReceipts(rawReceipts: unknown[]): GateVerdict {
  const parsed: LaneReceipt[] = [];
  for (let i = 0; i < rawReceipts.length; i++) {
    const one = parseOneReceipt(rawReceipts[i], i);
    if ("ok" in one && one.ok === false) return one;
    parsed.push(one as LaneReceipt);
  }

  const byWorker = new Map<string, LaneReceipt>();
  const shas = new Set<string>();
  for (const r of parsed) {
    if (!REQUIRED_SET.has(r.worker)) {
      return {
        ok: false,
        reason: "unknown_worker",
        detail: r.worker,
        sha: r.sha,
      };
    }
    if (byWorker.has(r.worker)) {
      return {
        ok: false,
        reason: "duplicate_worker",
        detail: r.worker,
        sha: r.sha,
      };
    }
    byWorker.set(r.worker, r);
    shas.add(r.sha);
  }

  if (shas.size > 1) {
    return { ok: false, reason: "sha_mismatch", shas: [...shas].sort() };
  }

  const missing = REQUIRED_WORKERS.filter((w) => !byWorker.has(w));
  if (missing.length > 0) {
    return {
      ok: false,
      reason: "missing_receipt",
      missing: [...missing],
      sha: shas.size === 1 ? [...shas][0] : undefined,
    };
  }

  const failed = parsed.filter((r) => r.result === "fail").map((r) => r.worker);
  const sha = parsed[0].sha;
  if (failed.length > 0) {
    return { ok: false, reason: "lane_failed", failed, sha };
  }

  return { ok: true, sha, receipts: parsed };
}

function githubRepo(env: AggregateEnv): string | undefined {
  const raw = (env.GITHUB_REPOSITORY || DEFAULT_GITHUB_REPOSITORY).trim();
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(raw) ? raw : undefined;
}

function statusContext(env: AggregateEnv): string {
  const ctx = (env.GITHUB_STATUS_CONTEXT || DEFAULT_STATUS_CONTEXT).trim();
  return ctx || DEFAULT_STATUS_CONTEXT;
}

function secretBound(value?: string): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function tokenBound(env: AggregateEnv): string | undefined {
  return secretBound(env.GITHUB_STATUS_TOKEN);
}

export function githubStatusUrl(repo: string, sha: string): string {
  return `https://api.github.com/repos/${repo}/statuses/${sha}`;
}

export async function postCommitStatus(
  env: AggregateEnv,
  sha: string,
  state: "success" | "failure",
  description: string,
  fetchImpl: typeof fetch = fetch,
): Promise<{ posted: true } | { posted: false; error: string; httpStatus?: number }> {
  const token = tokenBound(env);
  if (!token) {
    return { posted: false, error: "unbound_github_status_token" };
  }
  const repo = githubRepo(env);
  if (!repo) {
    return { posted: false, error: "invalid_github_repository" };
  }
  const url = githubStatusUrl(repo, sha);
  const res = await fetchImpl(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "quant-platform-ci-aggregate",
    },
    body: JSON.stringify({
      state,
      context: statusContext(env),
      description: description.slice(0, 140),
    }),
  });
  if (!res.ok) {
    return {
      posted: false,
      error: `github_status_http_${res.status}`,
      httpStatus: res.status,
    };
  }
  return { posted: true };
}

function gateDescription(gate: GateVerdict): string {
  if (gate.ok) return "all six worker lanes passed";
  switch (gate.reason) {
    case "sha_mismatch":
      return "lane receipts do not share the same HEAD SHA";
    case "missing_receipt":
      return `missing receipts: ${(gate.missing || []).join(",")}`;
    case "lane_failed":
      return `lane failed: ${(gate.failed || []).join(",")}`;
    case "unknown_worker":
      return `unknown worker: ${gate.detail || ""}`;
    case "duplicate_worker":
      return `duplicate worker: ${gate.detail || ""}`;
    default:
      return gate.detail || gate.reason;
  }
}

async function handleReceipts(
  request: Request,
  env: AggregateEnv,
  fetchImpl: typeof fetch,
): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "invalid JSON body" }, 400);
  }

  const collected = collectReceipts(body);
  if (!collected.ok) {
    return json(collected, 400);
  }

  const gate = evaluateReceipts(collected.receipts);
  const token = tokenBound(env);
  if (!token) {
    // Fail-closed: never attest success (or failure) without a bound token.
    return json(
      {
        ok: false,
        reason: "unbound_github_status_token",
        gate,
      },
      503,
    );
  }

  if (!gate.ok) {
    const shas =
      gate.sha != null
        ? [gate.sha]
        : (gate.shas || []).filter((s) => SHA_RE.test(s));
    for (const sha of shas) {
      await postCommitStatus(env, sha, "failure", gateDescription(gate), fetchImpl);
    }
    return json(gate, 422);
  }

  const posted = await postCommitStatus(
    env,
    gate.sha,
    "success",
    gateDescription(gate),
    fetchImpl,
  );
  if (!posted.posted) {
    return json(
      { ok: false, reason: posted.error, sha: gate.sha },
      502,
    );
  }
  return json({
    ok: true,
    sha: gate.sha,
    context: statusContext(env),
    state: "success",
  });
}

export async function handleRequest(
  request: Request,
  env: AggregateEnv,
  fetchImpl: typeof fetch = fetch,
): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname === "/health" || url.pathname === "/") {
    if (request.method !== "GET") return json({ error: "GET required" }, 405);
    return json({
      ok: true,
      service: "quant-platform-ci-aggregate",
      research_api: false,
      required_workers: REQUIRED_WORKERS,
    });
  }
  if (url.pathname !== "/v1/receipts") {
    return json({ error: "not found" }, 404);
  }
  if (request.method !== "POST") return json({ error: "POST required" }, 405);
  if (!secretBound(env.CI_LANE_TOKEN)) {
    return json({ ok: false, reason: "unbound_ci_lane_token" }, 503);
  }
  if (!(await authorized(request, env))) {
    return json({ ok: false, reason: "unauthorized" }, 401);
  }
  return handleReceipts(request, env, fetchImpl);
}

export default {
  async fetch(request: Request, env: AggregateEnv): Promise<Response> {
    return handleRequest(request, env);
  },
};
