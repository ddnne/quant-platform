import { describe, expect, it } from "vitest";
import {
  handleExportChanges,
  handleExportD1,
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
): Request {
  return new Request(`https://ingestion-premium.test${path}`, { headers });
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

describe("handleExportD1 fail-closed args", () => {
  it("unbound DATA_EXPORT_TOKEN is 401 even when X-Ingestion-Token is sent", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportD1(
      exportEnv(db, undefined),
      exportRequest("/v1/export/d1", { "X-Ingestion-Token": EXPORT_TOKEN }),
    );
    await assertClosed(res, 401, "unauthorized", prepared);
  });

  it("bound token with table=not_a_table is 400 and does not prepare", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportD1(
      exportEnv(db, EXPORT_TOKEN),
      exportRequest("/v1/export/d1?table=not_a_table", {
        "X-Ingestion-Token": EXPORT_TOKEN,
      }),
    );
    await assertClosed(res, 400, "table not exportable", prepared);
  });

  it("bound token with limit=0 or 1001 is 400 and does not prepare", async () => {
    for (const limit of [0, 1001]) {
      const { db, prepared } = stubD1();
      const res = await handleExportD1(
        exportEnv(db, EXPORT_TOKEN),
        exportRequest(`/v1/export/d1?limit=${limit}`, {
          "X-Ingestion-Token": EXPORT_TOKEN,
        }),
      );
      await assertClosed(
        res,
        400,
        "limit must be an integer between 1 and 1000",
        prepared,
      );
    }
  });
});

describe("handleExportChanges fail-closed args", () => {
  it("unbound DATA_EXPORT_TOKEN is 401 even when X-Ingestion-Token is sent", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportChanges(
      exportEnv(db, undefined),
      exportRequest("/v1/export/changes", {
        "X-Ingestion-Token": EXPORT_TOKEN,
      }),
    );
    await assertClosed(res, 401, "unauthorized", prepared);
  });

  it("bound token with after_seq=-1 is 400 and does not prepare", async () => {
    const { db, prepared } = stubD1();
    const res = await handleExportChanges(
      exportEnv(db, EXPORT_TOKEN),
      exportRequest("/v1/export/changes?after_seq=-1", {
        "X-Ingestion-Token": EXPORT_TOKEN,
      }),
    );
    await assertClosed(
      res,
      400,
      "after_seq must be a non-negative safe integer",
      prepared,
    );
  });
});
