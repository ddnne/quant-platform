import { describe, expect, it } from "vitest";
import {
  handleExportChanges,
  handleExportD1,
  handleExportPaths,
  type ExportEnv,
} from "./http_export";

const EXPORT_TOKEN = "premium-test-export-token-do-not-leak";

function stubD1(): { db: D1Database; prepared: string[] } {
  const prepared: string[] = [];
  const db = {
    prepare(sql: string) {
      prepared.push(sql);
      throw new Error(`unexpected D1 prepare: ${sql}`);
    },
  } as unknown as D1Database;
  return { db, prepared };
}

function exportEnv(db: D1Database, token: string | undefined): ExportEnv {
  return { DB: db, DATA_EXPORT_TOKEN: token };
}

function exportRequest(
  path: string,
  headers: HeadersInit = {},
  method = "GET",
): Request {
  return new Request(`https://ingestion-premium.test${path}`, { method, headers });
}

async function assertClosed(
  res: Response,
  status: number,
  error: string,
  prepared: string[],
): Promise<void> {
  expect(res.status).toBe(status);
  const body = await res.text();
  expect(JSON.parse(body)).toEqual({ error });
  expect(body).not.toContain(EXPORT_TOKEN);
  expect(body).not.toContain("COMPLETE");
  expect(prepared).toEqual([]);
}

describe("handleExportD1 ignores query token", () => {
  it("GET /v1/export/d1 with only matching query token is 401 and does not dump D1", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportD1(
      exportEnv(db, EXPORT_TOKEN),
      exportRequest(`/v1/export/d1?token=${EXPORT_TOKEN}&table=jquants_records`),
    );
    await assertClosed(res, 401, "unauthorized", prepared);
  });
});

describe("handleExportChanges ignores query token", () => {
  it("GET /v1/export/changes with only matching query token is 401 and does not dump D1", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportChanges(
      exportEnv(db, EXPORT_TOKEN),
      exportRequest(`/v1/export/changes?token=${EXPORT_TOKEN}`),
    );
    await assertClosed(res, 401, "unauthorized", prepared);
  });
});

describe("handleExportPaths ignores query token", () => {
  it("GET /v1/export/d1 with only matching query token is 401 and does not dump D1", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportPaths(
      exportRequest(`/v1/export/d1?token=${EXPORT_TOKEN}&table=jquants_records`),
      exportEnv(db, EXPORT_TOKEN),
    );
    expect(res).not.toBeNull();
    await assertClosed(res!, 401, "unauthorized", prepared);
  });

  it("GET /v1/export/changes with only matching query token is 401 and does not dump D1", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportPaths(
      exportRequest(`/v1/export/changes?token=${EXPORT_TOKEN}`),
      exportEnv(db, EXPORT_TOKEN),
    );
    expect(res).not.toBeNull();
    await assertClosed(res!, 401, "unauthorized", prepared);
  });
});
