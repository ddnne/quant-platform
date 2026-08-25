import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_STATUS_CONTEXT,
  REQUIRED_WORKERS,
  evaluateReceipts,
  githubStatusUrl,
  handleRequest,
  type LaneReceipt,
} from "./index";

const SHA_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const SHA_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const LANE_TOKEN = "test-lane-token-not-real";
const STATUS_TOKEN = "test-token-not-real";
const LANE_HEADERS = { "X-CI-Lane-Token": LANE_TOKEN };
const BOUND_ENV = {
  CI_LANE_TOKEN: LANE_TOKEN,
  GITHUB_STATUS_TOKEN: STATUS_TOKEN,
  GITHUB_REPOSITORY: "ddnne/quant-platform",
};

function receipt(
  worker: string,
  sha: string,
  result: "pass" | "fail" = "pass",
  command = "npm test",
): LaneReceipt {
  return { worker, sha, result, command };
}

function allPass(sha: string): LaneReceipt[] {
  return REQUIRED_WORKERS.map((worker) => receipt(worker, sha));
}

describe("evaluateReceipts", () => {
  it("all-pass same SHA → ok", () => {
    const gate = evaluateReceipts(allPass(SHA_A));
    expect(gate.ok).toBe(true);
    if (gate.ok) expect(gate.sha).toBe(SHA_A);
  });

  it("one fail → not ok", () => {
    const receipts = allPass(SHA_A);
    receipts[2] = receipt(REQUIRED_WORKERS[2], SHA_A, "fail", "npm test");
    const gate = evaluateReceipts(receipts);
    expect(gate.ok).toBe(false);
    if (!gate.ok) {
      expect(gate.reason).toBe("lane_failed");
      expect(gate.failed).toEqual([REQUIRED_WORKERS[2]]);
      expect(gate.sha).toBe(SHA_A);
    }
  });

  it("mixed SHA → not ok", () => {
    const receipts = allPass(SHA_A);
    receipts[1] = receipt(REQUIRED_WORKERS[1], SHA_B);
    const gate = evaluateReceipts(receipts);
    expect(gate.ok).toBe(false);
    if (!gate.ok) {
      expect(gate.reason).toBe("sha_mismatch");
      expect(gate.shas?.sort()).toEqual([SHA_A, SHA_B].sort());
    }
  });

  it("missing worker receipt → not ok", () => {
    const receipts = allPass(SHA_A).slice(0, 5);
    const gate = evaluateReceipts(receipts);
    expect(gate.ok).toBe(false);
    if (!gate.ok) {
      expect(gate.reason).toBe("missing_receipt");
      expect(gate.missing).toEqual(["research-mass-eval"]);
    }
  });
});

type Posted = { url: string; state: string; context: string };

function mockGithub(opts: { httpStatus?: number } = {}) {
  const posted: Posted[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = JSON.parse(String(init?.body || "{}")) as {
      state: string;
      context: string;
    };
    posted.push({ url, state: body.state, context: body.context });
    return new Response("{}", { status: opts.httpStatus ?? 201 });
  });
  return { posted, fetchImpl };
}

function postReceipts(
  receipts: LaneReceipt[],
  env: Record<string, string | undefined>,
  fetchImpl?: typeof fetch,
  extraHeaders: Record<string, string> = LANE_HEADERS,
) {
  return handleRequest(
    new Request("https://ci-aggregate.test/v1/receipts", {
      method: "POST",
      headers: { "content-type": "application/json", ...extraHeaders },
      body: JSON.stringify({ receipts }),
    }),
    env,
    fetchImpl,
  );
}

describe("POST /v1/receipts", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("all-pass same SHA posts GitHub success", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await postReceipts(allPass(SHA_A), BOUND_ENV, fetchImpl);
    const body = (await res.json()) as { ok: boolean; sha: string; state: string };
    expect(res.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.sha).toBe(SHA_A);
    expect(body.state).toBe("success");
    expect(posted).toHaveLength(1);
    expect(posted[0].url).toBe(
      githubStatusUrl("ddnne/quant-platform", SHA_A),
    );
    expect(posted[0].state).toBe("success");
    expect(posted[0].context).toBe(DEFAULT_STATUS_CONTEXT);
  });

  it("one fail does not post success", async () => {
    const { posted, fetchImpl } = mockGithub();
    const receipts = allPass(SHA_A);
    receipts[0] = receipt(REQUIRED_WORKERS[0], SHA_A, "fail");
    const res = await postReceipts(receipts, BOUND_ENV, fetchImpl);
    const body = (await res.json()) as { ok: boolean; reason: string };
    expect(body.ok).toBe(false);
    expect(body.reason).toBe("lane_failed");
    expect(posted.every((p) => p.state !== "success")).toBe(true);
    expect(posted.some((p) => p.state === "failure")).toBe(true);
  });

  it("mixed SHA does not post success", async () => {
    const { posted, fetchImpl } = mockGithub();
    const receipts = allPass(SHA_A);
    receipts[4] = receipt(REQUIRED_WORKERS[4], SHA_B);
    const res = await postReceipts(receipts, BOUND_ENV, fetchImpl);
    const body = (await res.json()) as { ok: boolean; reason: string };
    expect(body.ok).toBe(false);
    expect(body.reason).toBe("sha_mismatch");
    expect(posted.every((p) => p.state !== "success")).toBe(true);
  });

  it("unbound GITHUB_STATUS_TOKEN returns 503 fail-closed", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await postReceipts(
      allPass(SHA_A),
      { CI_LANE_TOKEN: LANE_TOKEN },
      fetchImpl,
    );
    const body = (await res.json()) as { ok: boolean; reason: string };
    expect(res.status).toBe(503);
    expect(body.ok).toBe(false);
    expect(body.reason).toBe("unbound_github_status_token");
    expect(posted).toHaveLength(0);
  });

  it("unbound CI_LANE_TOKEN returns 503 fail-closed", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await postReceipts(
      allPass(SHA_A),
      { GITHUB_STATUS_TOKEN: STATUS_TOKEN },
      fetchImpl,
      LANE_HEADERS,
    );
    const body = (await res.json()) as { ok: boolean; reason: string };
    expect(res.status).toBe(503);
    expect(body.ok).toBe(false);
    expect(body.reason).toBe("unbound_ci_lane_token");
    expect(posted).toHaveLength(0);
  });

  it("wrong X-CI-Lane-Token returns 401", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await postReceipts(allPass(SHA_A), BOUND_ENV, fetchImpl, {
      "X-CI-Lane-Token": "wrong-token",
    });
    const body = (await res.json()) as { ok: boolean; reason: string };
    expect(res.status).toBe(401);
    expect(body.ok).toBe(false);
    expect(body.reason).toBe("unauthorized");
    expect(posted).toHaveLength(0);
  });

  it("authorized matching token posts GitHub success", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await postReceipts(allPass(SHA_A), BOUND_ENV, fetchImpl, LANE_HEADERS);
    const body = (await res.json()) as { ok: boolean; sha: string; state: string };
    expect(res.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.sha).toBe(SHA_A);
    expect(body.state).toBe("success");
    expect(posted).toHaveLength(1);
    expect(posted[0].state).toBe("success");
    expect(posted[0].url).toBe(githubStatusUrl("ddnne/quant-platform", SHA_A));
  });

  it("does not treat a PR comment as a success signal", async () => {
    const { posted, fetchImpl } = mockGithub();
    vi.stubGlobal("fetch", fetchImpl);
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/v1/receipts", {
        method: "POST",
        headers: { "content-type": "application/json", ...LANE_HEADERS },
        body: JSON.stringify({
          comment: "Cloudflare Workers Builds: success",
          pull_request: 1,
        }),
      }),
      BOUND_ENV,
      fetchImpl,
    );
    const body = (await res.json()) as { ok: boolean };
    expect(body.ok).toBe(false);
    expect(posted.every((p) => p.state !== "success")).toBe(true);
  });

  it("invalid JSON body is 400 and does not post GitHub", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/v1/receipts", {
        method: "POST",
        headers: { "content-type": "application/json", ...LANE_HEADERS },
        body: "{",
      }),
      BOUND_ENV,
      fetchImpl,
    );
    const body = (await res.json()) as { ok: boolean; error: string };
    expect(res.status).toBe(400);
    expect(body.ok).toBe(false);
    expect(body.error).toBe("invalid JSON body");
    expect(posted).toHaveLength(0);
  });

  it("matching query token without X-CI-Lane-Token is 401 and does not post GitHub", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await handleRequest(
      new Request(
        `https://ci-aggregate.test/v1/receipts?token=${encodeURIComponent(LANE_TOKEN)}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ receipts: allPass(SHA_A) }),
        },
      ),
      BOUND_ENV,
      fetchImpl,
    );
    const raw = await res.text();
    const body = JSON.parse(raw) as { ok: boolean; reason: string };
    expect(res.status).toBe(401);
    expect(body.ok).toBe(false);
    expect(body.reason).toBe("unauthorized");
    expect(raw).not.toContain(LANE_TOKEN);
    expect(raw).not.toMatch(/CI_LANE_TOKEN/i);
    expect(posted).toHaveLength(0);
  });
});

describe("GET /v1/receipts", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("is 405 POST required and does not post GitHub", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/v1/receipts", { method: "GET" }),
      BOUND_ENV,
      fetchImpl,
    );
    const body = (await res.json()) as { error: string };
    expect(res.status).toBe(405);
    expect(body.error).toBe("POST required");
    expect(posted).toHaveLength(0);
  });
});

describe("GET /health", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("stays unauthenticated", async () => {
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/health", { method: "GET" }),
      {},
    );
    const body = (await res.json()) as { ok: boolean; service: string };
    expect(res.status).toBe(200);
    expect(body.ok).toBe(true);
    expect(body.service).toBe("quant-platform-ci-aggregate");
  });

  it("rejects POST with 405 GET required and does not post GitHub", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/health", { method: "POST" }),
      BOUND_ENV,
      fetchImpl,
    );
    const body = (await res.json()) as { error: string };
    expect(res.status).toBe(405);
    expect(body.error).toBe("GET required");
    expect(posted).toHaveLength(0);
  });

  it("returns 404 not found for GET /nope", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/nope", { method: "GET" }),
      BOUND_ENV,
      fetchImpl,
    );
    const body = (await res.json()) as { error: string };
    expect(res.status).toBe(404);
    expect(body.error).toBe("not found");
    expect(posted).toHaveLength(0);
  });

  it("JSON is not a research API or merge-gate green", async () => {
    const { posted, fetchImpl } = mockGithub();
    const res = await handleRequest(
      new Request("https://ci-aggregate.test/health", { method: "GET" }),
      BOUND_ENV,
      fetchImpl,
    );
    const body = (await res.json()) as {
      ok: boolean;
      service: string;
      research_api: boolean;
      required_workers: string[];
      state?: string;
    };
    expect(res.status).toBe(200);
    expect(body.research_api).toBe(false);
    expect(body.required_workers).toHaveLength(REQUIRED_WORKERS.length);
    expect(body.required_workers).toEqual([...REQUIRED_WORKERS]);
    expect(body.state).not.toBe("success");
    expect(posted).toHaveLength(0);
  });
});
