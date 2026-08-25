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

function recordingEnv(): {
  env: ArtifactsPlanEnv;
  sql: string[];
  r2Puts: string[];
} {
  const sql: string[] = [];
  const r2Puts: string[] = [];
  const selectStmt = {
    bind(..._args: unknown[]) {
      return selectStmt;
    },
    first: async () => null,
    all: async () => ({ results: [], success: true, meta: {} }),
    run: async () => {
      throw new Error("unexpected D1 run");
    },
  };
  return {
    env: {
      INGESTION_RUN_TOKEN: RUN_TOKEN,
      DB: {
        prepare(query: string) {
          sql.push(query);
          if (!/^\s*SELECT\b/i.test(query)) {
            throw new Error(`unexpected D1: ${query}`);
          }
          return selectStmt;
        },
      } as unknown as D1Database,
      STRUCTURED_BUCKET: {
        async list() {
          return { objects: [], truncated: false };
        },
        async put(key: string) {
          r2Puts.push(key);
          throw new Error(`unexpected R2 put: ${key}`);
        },
      } as unknown as R2Bucket,
    },
    sql,
    r2Puts,
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

  it("GET with only matching query token and no header is 401", async () => {
    const res = await handleArtifactsJoinPlan(
      new Request(
        `https://ingestion-premium.test/v1/ops/artifacts-join-plan?datasets=markets_calendar&token=${encodeURIComponent(RUN_TOKEN)}`,
        { method: "GET" },
      ),
      planEnv(),
    );
    await assertClosedError(res, 401, "unauthorized");
  });

  it("POST with only matching query token and no header is 401", async () => {
    const res = await handleArtifactsJoinPlan(
      new Request(
        `https://ingestion-premium.test/v1/ops/artifacts-join-plan?datasets=markets_calendar&token=${encodeURIComponent(RUN_TOKEN)}`,
        { method: "POST" },
      ),
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

  it("GET with matching token does not DELETE or INSERT coverage_segments COMPLETE and does not put R2", async () => {
    const { env, sql, r2Puts } = recordingEnv();
    const res = await handleArtifactsJoinPlan(
      new Request(
        "https://ingestion-premium.test/v1/ops/artifacts-join-plan?datasets=markets_calendar",
        {
          method: "GET",
          headers: { "X-Ingestion-Token": RUN_TOKEN },
        },
      ),
      env,
    );
    expect(res.status).toBe(200);
    const json = (await res.json()) as Record<string, unknown>;
    if (Object.prototype.hasOwnProperty.call(json, "mass_research")) {
      expect(json.mass_research).toBe("NO-GO");
    }
    expect(json.mass_research).not.toBe("GO");
    expect(r2Puts).toEqual([]);
    expect(sql.some((query) => /\bDELETE\b/i.test(query))).toBe(false);
    expect(
      sql.some(
        (query) =>
          /\bINSERT\b/i.test(query) && query.includes("coverage_segments"),
      ),
    ).toBe(false);
    expect(sql.some((query) => query.includes("COMPLETE"))).toBe(false);
  });
});
