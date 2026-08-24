import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { datasetById } from "./catalog";
import { naturalKey } from "./identity";
import {
  NATURAL_KEY_MIGRATION_ID,
  auditNaturalKeysV2,
  rebuildNaturalKeysV2,
  requireNaturalKeysV2Ready,
} from "./natural_key_migration";

const here = dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = join(here, "..", "migrations");
const INDEX_TS = join(here, "index.ts");

const LEGACY_SHORT_RATIO_KEY = '{"Date":"2025-04-01","S33":null}';
const SHORT_RATIO_PAYLOAD = {
  Date: "2025-04-01",
  S33: null,
  Ratio: 1.25,
};

interface SqliteStatement {
  sql: string;
  bind(...args: unknown[]): SqliteStatement;
  first(): Promise<Record<string, unknown> | null>;
  all(): Promise<{ results: Record<string, unknown>[]; success: true; meta: object }>;
  run(): Promise<{ success: true; meta: { changes: number; last_row_id: number } }>;
}

function sqliteD1(sqlite: DatabaseSync): { db: D1Database; batches: string[][] } {
  const batches: string[][] = [];

  function prepare(sql: string): SqliteStatement {
    let bound: unknown[] = [];
    const stmt: SqliteStatement = {
      sql,
      bind(...args: unknown[]) {
        bound = args;
        return stmt;
      },
      async first() {
        const row = sqlite.prepare(sql).get(...bound) as Record<string, unknown> | undefined;
        return row ?? null;
      },
      async all() {
        return {
          results: sqlite.prepare(sql).all(...bound) as Record<string, unknown>[],
          success: true,
          meta: {},
        };
      },
      async run() {
        const info = sqlite.prepare(sql).run(...bound);
        return {
          success: true,
          meta: {
            changes: Number(info.changes),
            last_row_id: Number(info.lastInsertRowid),
          },
        };
      },
    };
    return stmt;
  }

  const db = {
    prepare,
    async batch(statements: SqliteStatement[]) {
      batches.push(statements.map((statement) => statement.sql));
      sqlite.exec("BEGIN IMMEDIATE");
      try {
        const results = [];
        for (const statement of statements) {
          results.push(await statement.run());
        }
        sqlite.exec("COMMIT");
        return results;
      } catch (error) {
        sqlite.exec("ROLLBACK");
        throw error;
      }
    },
  };
  return { db: db as unknown as D1Database, batches };
}

function applyRebuildSchema(sqlite: DatabaseSync): void {
  for (const name of [
    "0001_init.sql",
    "0002_watermarks.sql",
    "0003_change_feed.sql",
    "0004_revision_identity_v2.sql",
    "0005_natural_keys_v2.sql",
  ]) {
    sqlite.exec(readFileSync(join(MIGRATIONS, name), "utf8"));
  }
}

function insertRecord(
  sqlite: DatabaseSync,
  row: { dataset: string; naturalKey: string; payload: Record<string, unknown> },
): void {
  const payload = JSON.stringify(row.payload);
  sqlite.prepare(
    `INSERT INTO jquants_records
     (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    "jquants",
    row.dataset,
    row.naturalKey,
    "2025-04-01T00:00:00+09:00",
    "2025-04-02T09:00:00+09:00",
    "2025-04-02T09:00:00+09:00",
    payload,
    payload,
  );
}

function migrationState(sqlite: DatabaseSync): string {
  const row = sqlite.prepare(
    "SELECT state FROM natural_key_migrations WHERE migration_id = ?",
  ).get(NATURAL_KEY_MIGRATION_ID) as { state: string } | undefined;
  if (!row) throw new Error("missing natural-key migration control row");
  return row.state;
}

describe("NATURAL_KEY_MIGRATION_ID", () => {
  it("matches the 0005 control-row identity", () => {
    expect(NATURAL_KEY_MIGRATION_ID).toBe("jquants-premium-natural-keys-v2");
  });
});

describe("naturalKey via identity", () => {
  it("hashes an incomplete short-ratio identity and keeps a complete pair", async () => {
    const spec = datasetById("markets_short_ratio");
    expect(spec).toBeDefined();
    const hashed = await naturalKey(SHORT_RATIO_PAYLOAD, spec!);
    expect(hashed.startsWith("hash:sha256:")).toBe(true);
    expect(hashed).not.toBe(LEGACY_SHORT_RATIO_KEY);
    expect(
      await naturalKey({ Date: "2025-04-01", S33: "0050", Name: "電気・ガス" }, spec!),
    ).toBe('{"Date":"2025-04-01","S33":"0050"}');
  });
});

describe("requireNaturalKeysV2Ready", () => {
  it("fails closed while PENDING and after a rejected live audit", async () => {
    const sqlite = new DatabaseSync(":memory:");
    applyRebuildSchema(sqlite);
    const { db } = sqliteD1(sqlite);
    await expect(requireNaturalKeysV2Ready(db)).rejects.toThrow(
      "natural-key migration is PENDING; READY is required",
    );

    insertRecord(sqlite, {
      dataset: "equities_bars_daily",
      naturalKey: "not-canonical",
      payload: { Code: "8697", Date: "2025-04-01", Close: 100 },
    });
    await expect(rebuildNaturalKeysV2(db)).rejects.toThrow(/live identity audit found/);
    expect(migrationState(sqlite)).toBe("REJECTED");
    await expect(requireNaturalKeysV2Ready(db)).rejects.toThrow(
      "natural-key migration is REJECTED; READY is required",
    );
  });
});

describe("rebuildNaturalKeysV2", () => {
  it("rebuilds via canonical naturalKey, swaps in one batch, and publishes READY", async () => {
    const spec = datasetById("markets_short_ratio");
    expect(spec).toBeDefined();
    const canonical = await naturalKey(SHORT_RATIO_PAYLOAD, spec!);

    const sqlite = new DatabaseSync(":memory:");
    applyRebuildSchema(sqlite);
    insertRecord(sqlite, {
      dataset: "markets_short_ratio",
      naturalKey: LEGACY_SHORT_RATIO_KEY,
      payload: SHORT_RATIO_PAYLOAD,
    });
    insertRecord(sqlite, {
      dataset: "equities_bars_daily",
      naturalKey: '{"Code":"8697","Date":"2025-04-01"}',
      payload: { Code: "8697", Date: "2025-04-01", Close: 100 },
    });
    const { db, batches } = sqliteD1(sqlite);

    const status = await rebuildNaturalKeysV2(db);
    expect(status.migrationId).toBe(NATURAL_KEY_MIGRATION_ID);
    expect(status.state).toBe("READY");
    expect(status.auditMismatches).toBe(0);
    expect(status.rowsPrimary).toBe(1);

    const stored = sqlite.prepare(
      "SELECT dataset, natural_key FROM jquants_records ORDER BY dataset",
    ).all() as { dataset: string; natural_key: string }[];
    expect(stored).toEqual([
      { dataset: "equities_bars_daily", natural_key: '{"Code":"8697","Date":"2025-04-01"}' },
      { dataset: "markets_short_ratio", natural_key: canonical },
    ]);
    expect(stored.some((row) => row.natural_key === LEGACY_SHORT_RATIO_KEY)).toBe(false);

    const swap = batches.find(
      (sqls) =>
        sqls.some((sql) => sql.includes("DELETE FROM jquants_records WHERE dataset IN")) &&
        sqls.some((sql) => sql.includes("INSERT INTO jquants_records")) &&
        sqls.some((sql) => sql.includes("state='VALIDATING'")),
    );
    expect(swap).toBeDefined();

    const audit = await auditNaturalKeysV2(db);
    expect(audit.mismatches).toBe(0);
    expect(audit.rowsChecked).toBe(2);

    await requireNaturalKeysV2Ready(db);
    const again = await rebuildNaturalKeysV2(db);
    expect(again.state).toBe("READY");
    expect(
      (sqlite.prepare(
        "SELECT natural_key FROM jquants_records WHERE dataset = ?",
      ).get("markets_short_ratio") as { natural_key: string }).natural_key,
    ).toBe(canonical);
  });
});

describe("ingestion-premium natural-key rebuild source pin", () => {
  it("gates ingest on READY and does not read payload available_at", () => {
    const src = readFileSync(INDEX_TS, "utf8");
    expect(src).toContain("await requireNaturalKeysV2Ready(env.DB)");
    expect(src).not.toContain('typeof row["available_at"]');
  });
});
