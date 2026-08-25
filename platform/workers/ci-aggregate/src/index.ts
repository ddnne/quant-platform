/// <reference types="@cloudflare/workers-types" />

import { json } from "./http_json";
import { authorized } from "./authorized";
import {
  REQUIRED_WORKERS,
  SHA_RE,
  collectReceipts,
  evaluateReceipts,
  type GateVerdict,
} from "./receipts_gate";

export { authorized } from "./authorized";
export {
  REQUIRED_WORKERS,
  collectReceipts,
  evaluateReceipts,
} from "./receipts_gate";
export type {
  RequiredWorker,
  LaneReceipt,
  GateOk,
  GateFail,
  GateVerdict,
} from "./receipts_gate";

export const DEFAULT_STATUS_CONTEXT = "ci-aggregate";
export const DEFAULT_GITHUB_REPOSITORY = "ddnne/quant-platform";

export interface AggregateEnv {
  CI_LANE_TOKEN?: string;
  GITHUB_STATUS_TOKEN?: string;
  GITHUB_REPOSITORY?: string;
  GITHUB_STATUS_CONTEXT?: string;
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
