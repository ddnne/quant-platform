import { describe, expect, it } from "vitest";
import { handlePruneChangelog, type PruneEnv } from "./ops_prune_changelog";

const RUN_TOKEN = "premium-test-run-token-do-not-leak";
const PRUNE_URL = "https://ingestion-premium.test/v1/ops/prune-changelog";

function touchingD1(): { db: D1Database; sql: string[] } {
  const sql: string[] = [];
  const db = {
    prepare(query: string) {
      sql.push(query);
      throw new Error(`unexpected D1: ${query}`);
    },
  } as unknown as D1Database;
  return { db, sql };
}

function pruneEnv(token: string | undefined, db: D1Database): PruneEnv {
  return { DB: db, INGESTION_RUN_TOKEN: token };
}

function pruneRequest(headers: HeadersInit = {}): Request {
  return new Request(PRUNE_URL, { method: "POST", headers });
}

function assertUnauthorized401(res: Response, body: string): void {
  expect(res.status).toBe(401);
  expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
  expect(body).not.toContain(RUN_TOKEN);
  expect(body).not.toMatch(/INGESTION_RUN_TOKEN/i);
  expect(body).not.toContain("COMPLETE");
  expect(body).not.toContain("READY");
}

describe("premium changelog prune auth", () => {
  it("rejects unbound INGESTION_RUN_TOKEN even when a header is sent", async () => {
    const { db, sql } = touchingD1();
    const res = await handlePruneChangelog(
      pruneRequest({ "X-Ingestion-Token": RUN_TOKEN }),
      pruneEnv(undefined, db),
    );
    const body = await res.text();
    assertUnauthorized401(res, body);
    expect(sql).toEqual([]);
  });

  it("rejects a missing token", async () => {
    const { db, sql } = touchingD1();
    const res = await handlePruneChangelog(
      pruneRequest(),
      pruneEnv(RUN_TOKEN, db),
    );
    const body = await res.text();
    assertUnauthorized401(res, body);
    expect(sql).toEqual([]);
  });

  it("rejects a wrong token", async () => {
    const { db, sql } = touchingD1();
    const res = await handlePruneChangelog(
      pruneRequest({ "X-Ingestion-Token": "wrong-token" }),
      pruneEnv(RUN_TOKEN, db),
    );
    const body = await res.text();
    assertUnauthorized401(res, body);
    expect(sql).toEqual([]);
  });
});
