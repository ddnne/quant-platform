import { describe, expect, it } from "vitest";
import {
  handleArtifactsJoinPlan,
  type ArtifactsPlanEnv,
} from "./ops_artifacts_plan";

const RUN_TOKEN = "premium-test-run-token-do-not-leak";

function stubD1(): D1Database {
  const stmt = {
    bind: (..._args: unknown[]) => stmt,
    first: async () => ({ n: 0, mn: null, mx: null }),
    all: async () => ({ results: [], success: true, meta: {} }),
    run: async () => ({ success: true, meta: {} }),
  };
  return { prepare: (_sql: string) => stmt } as unknown as D1Database;
}

function stubR2(): R2Bucket {
  return {
    async list() {
      return { objects: [], truncated: false };
    },
  } as unknown as R2Bucket;
}

function rejectingD1(): D1Database {
  return {
    prepare() {
      throw new Error("live D1 must not be called");
    },
  } as unknown as D1Database;
}

function rejectingR2(): R2Bucket {
  return {
    async list() {
      throw new Error("live R2 must not be called");
    },
  } as unknown as R2Bucket;
}

function planEnv(overrides: Partial<ArtifactsPlanEnv> = {}): ArtifactsPlanEnv {
  return {
    STRUCTURED_BUCKET: rejectingR2(),
    DB: rejectingD1(),
    INGESTION_RUN_TOKEN: RUN_TOKEN,
    ...overrides,
  };
}

function planRequest(path: string, headers: Record<string, string> = {}): Request {
  return new Request(`https://ingestion-premium.test${path}`, { headers });
}

async function assertClosedError(
  res: Response,
  status: number,
  error: string,
): Promise<void> {
  expect(res.status).toBe(status);
  const body = await res.text();
  expect(JSON.parse(body)).toEqual({ error });
  expect(body).not.toContain(RUN_TOKEN);
  expect(body).not.toContain("Mass");
  expect(body).not.toContain("READY");
  expect(body).not.toContain("COMPLETE");
  expect(body).not.toMatch(/"mass_research"\s*:\s*"GO"/);
}

describe("artifacts-join-plan token fail-closed", () => {
  it("rejects unbound INGESTION_RUN_TOKEN with 401 even when a header is sent", async () => {
    const res = await handleArtifactsJoinPlan(
      planRequest("/v1/ops/artifacts-join-plan?datasets=markets_calendar", {
        "X-Ingestion-Token": RUN_TOKEN,
      }),
      planEnv({ INGESTION_RUN_TOKEN: undefined }),
    );
    await assertClosedError(res, 401, "unauthorized");
  });

  it("rejects a missing token with 401", async () => {
    const res = await handleArtifactsJoinPlan(
      planRequest("/v1/ops/artifacts-join-plan?datasets=markets_calendar"),
      planEnv(),
    );
    await assertClosedError(res, 401, "unauthorized");
  });

  it("rejects a wrong token with 401", async () => {
    const res = await handleArtifactsJoinPlan(
      planRequest("/v1/ops/artifacts-join-plan?datasets=markets_calendar", {
        "X-Ingestion-Token": "wrong-token",
      }),
      planEnv(),
    );
    await assertClosedError(res, 401, "unauthorized");
  });

  it("rejects a missing datasets query with 400", async () => {
    const res = await handleArtifactsJoinPlan(
      planRequest("/v1/ops/artifacts-join-plan", {
        "X-Ingestion-Token": RUN_TOKEN,
      }),
      planEnv(),
    );
    await assertClosedError(res, 400, "datasets required (comma-separated)");
  });
});

describe("artifacts-join-plan read-only join", () => {
  it("authorized mock path is NO-GO and does not include mass_research GO", async () => {
    const res = await handleArtifactsJoinPlan(
      planRequest("/v1/ops/artifacts-join-plan?datasets=markets_calendar", {
        "X-Ingestion-Token": RUN_TOKEN,
      }),
      planEnv({ STRUCTURED_BUCKET: stubR2(), DB: stubD1() }),
    );
    expect(res.status).toBe(200);
    const json = (await res.json()) as Record<string, unknown>;
    expect(json.schema).toBe("artifacts-join-plan/v1");
    expect(json.mass_research).toBe("NO-GO");
    expect(json.mass_research).not.toBe("GO");
    expect(Object.keys(json)).not.toContain("GO");
    expect(Object.values(json)).not.toContain("GO");
    expect(JSON.stringify(json)).not.toMatch(/"mass_research"\s*:\s*"GO"/);
    expect(json).not.toHaveProperty("READY");
    expect(json).not.toHaveProperty("COMPLETE");
  });
});
