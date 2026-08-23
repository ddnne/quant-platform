/** Fail-closed six-lane same-SHA receipts gate. HTTP/GitHub stay in index.ts. Not GO. */

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

export const SHA_RE = /^[0-9a-f]{40}$/i;

export interface LaneReceipt {
  worker: string;
  sha: string;
  result: "pass" | "fail";
  command: string;
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

export function parseOneReceipt(raw: unknown, index: number): LaneReceipt | GateFail {
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
