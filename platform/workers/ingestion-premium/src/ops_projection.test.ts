import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  dispatchOpsTool,
  OPS_TOOLS,
} from "../../quant-ops-mcp/src/domain.js";
import { verifyProjectionGenerationWithSpki } from "../../quant-ops-mcp/src/projection_signature.js";
import {
  OpsProjectionPublishError,
  PROJECTED_CONTENT_TABLES,
  digest,
  manifestFromRows,
  publishOpsProjection,
  type OpsProjectionEnv,
} from "./ops_projection";
import {
  trustedComplete,
  verifySignedReceiptEnvelope,
  type ClosedObjectStores,
} from "./ops_projection_policy";

const here = dirname(fileURLToPath(import.meta.url));
const ingestionMigrations = join(here, "../migrations");
const projectionMigrations = join(here, "../../quant-ops-mcp/migrations/projection");

function applySqlDir(db: DatabaseSync, directory: string, through?: string): void {
  const files = readdirSync(directory)
    .filter((name) => name.endsWith(".sql"))
    .sort();
  for (const name of files) {
    if (through && name > through) break;
    db.exec(readFileSync(join(directory, name), "utf8"));
  }
}

function b64(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64");
}

async function sha256Prefixed(bytes: Uint8Array): Promise<string> {
  const raw = await crypto.subtle.digest("SHA-256", bytes);
  return "sha256:" + Array.from(new Uint8Array(raw), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function exactJqTrustedComplete(
  objects: Awaited<ReturnType<typeof seedGovernedObjects>>,
  envelope: Record<string, unknown>,
  registry: Parameters<typeof trustedComplete>[7],
  stores: ClosedObjectStores | null | undefined,
): Promise<boolean> {
  return trustedComplete(
    {
      status: "COMPLETE",
      source: "jquants",
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      segment_start: "2026-08-01",
      segment_end: "2026-08-31",
      policy_version: "collection-coverage/v3",
      receipt_run_id: 1,
    },
    [{
      source: "jquants",
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      segment_start: "2026-08-01",
      segment_end: "2026-08-31",
      status: "SUCCESS",
      run_id: 1,
      pagination_exhausted: 1,
      structured_row_count: 2,
      raw_row_count: 2,
      raw_page_count: 1,
      digests_json: JSON.stringify(envelope),
    }],
    [{
      source: "jquants",
      run_id: 1,
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      operation_id: "op-1",
      row_count: 2,
      raw_row_count: 2,
      artifact_key: "artifact.jsonl",
      manifest_key: "manifest.json",
      raw_manifest_key: "raw.json",
      artifact_digest: objects.structured,
      manifest_digest: objects.manifestDigest,
      raw_manifest_digest: objects.rawDigest,
      byte_count: objects.artifactBytes,
    }],
    [{
      run_id: 1,
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      environment: "production",
      state: "RECEIPT_COMMITTED",
      operation_id: "op-1",
      source: "jquants",
      receipt_digest: "sha256:" + "ee".repeat(32),
      request_digest: "sha256:" + "cc".repeat(32),
      structured_digest: objects.structured,
      raw_manifest_digest: objects.rawDigest,
    }],
    [{
      operation_id: "op-1",
      state: "FINALIZED",
      environment: "production",
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      source: "jquants",
      receipt_digest: "sha256:" + "ee".repeat(32),
    }],
    new Map([["op-1", 2]]),
    "production",
    registry,
    stores,
  );
}

async function seedGovernedObjects() {
  const artifact = new TextEncoder().encode('{"nk":"k1"}\n{"nk":"k2"}\n');
  const manifest = new TextEncoder().encode('{"format":"product-manifest/v1"}');
  const rawManifest = new TextEncoder().encode('{"format":"jquants-raw-manifest/v1"}');
  const structuredBucket = wrapR2();
  const authorityBucket = wrapR2();
  const rawBucket = wrapR2();
  await structuredBucket.put("artifact.jsonl", artifact, { onlyIf: { etagDoesNotMatch: "*" } });
  await authorityBucket.put("manifest.json", manifest, { onlyIf: { etagDoesNotMatch: "*" } });
  await rawBucket.put("raw.json", rawManifest, { onlyIf: { etagDoesNotMatch: "*" } });
  const stores = {
    structured: structuredBucket,
    authority: authorityBucket,
    raw: rawBucket,
  };
  return {
    bucket: structuredBucket,
    stores,
    artifact,
    structured: await sha256Prefixed(artifact),
    manifestDigest: await sha256Prefixed(manifest),
    rawDigest: "sha256:" + "aa".repeat(32),
    rawFileDigest: await sha256Prefixed(rawManifest),
    artifactBytes: artifact.byteLength,
    manifestBytes: manifest.byteLength,
    rawBytes: rawManifest.byteLength,
  };
}

async function keyPair(): Promise<{ pkcs8: string; spki: string }> {
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, [
    "sign",
    "verify",
  ]);
  return {
    pkcs8: b64(new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey))),
    spki: b64(new Uint8Array(await crypto.subtle.exportKey("spki", pair.publicKey))),
  };
}

function coerce(value: unknown): unknown {
  if (typeof value === "bigint") return Number(value);
  return value;
}

function wrapSqlite(
  db: DatabaseSync,
  hooks: { beforeRun?: (sql: string) => void } = {},
): D1Database {
  const prepare = (sql: string) => {
    const bound: unknown[] = [];
    const stmt = {
      bind(...args: unknown[]) {
        bound.push(...args);
        return stmt;
      },
      async all() {
        const rows = db.prepare(sql).all(...bound) as Record<string, unknown>[];
        return {
          results: rows.map((row) =>
            Object.fromEntries(
              Object.entries(row).map(([key, value]) => [key, coerce(value)]),
            ),
          ),
          success: true,
          meta: {},
        };
      },
      async first() {
        const row = db.prepare(sql).get(...bound) as Record<string, unknown> | undefined;
        if (!row) return null;
        return Object.fromEntries(
          Object.entries(row).map(([key, value]) => [key, coerce(value)]),
        );
      },
      async run() {
        hooks.beforeRun?.(sql);
        const result = db.prepare(sql).run(...bound);
        return { success: true, meta: { changes: Number(result.changes) } };
      },
    };
    return stmt;
  };
  const database = {
    prepare,
    batch: async (statements: { run: () => Promise<unknown> }[]) =>
      Promise.all(statements.map((statement) => statement.run())),
    withSession: () => database,
  };
  return database as unknown as D1Database;
}

function seedBase(db: DatabaseSync, cursor = 12): void {
  db.prepare(
    `INSERT INTO ingestion_change_log(
       table_name,source,dataset,natural_key,event_time,available_at,ingested_at,payload,changed_at
     ) VALUES ('jquants_daily_bars','jquants','equities_bars','1301','2026-08-01','2026-08-01','2026-08-01','{}','2026-08-01T00:00:00Z')`,
  ).run();
  db.prepare("UPDATE ingestion_change_log SET change_seq=?").run(cursor);
  db.prepare(
    `INSERT INTO ingestion_run_log(id,ran_at,source,runtime,status,detail)
     VALUES (1,'2026-08-01T00:00:00Z','jquants','cloud','ok',NULL)`,
  ).run();
  db.exec(`
    CREATE TABLE IF NOT EXISTS snapshot_quality_results (
      build_id TEXT NOT NULL,
      policy_version TEXT NOT NULL,
      status TEXT NOT NULL,
      evaluated_at TEXT NOT NULL,
      summary_json TEXT NOT NULL,
      results_json TEXT NOT NULL
    );
  `);
  db.prepare(
    `INSERT INTO snapshot_quality_results(
       build_id,policy_version,status,evaluated_at,summary_json,results_json
     ) VALUES (
       'b0-build-1','collection-coverage/v3','PASS','2026-08-01T00:00:00Z','{}',
       ?
     )`,
  ).run(JSON.stringify([{ check_id: "B4", status: "PASS" }]));
}

function insertSegment(
  db: DatabaseSync,
  args: { segment: string; status: string; start: string; end: string },
): void {
  db.prepare(
    `INSERT INTO coverage_segments(
       source,dataset,segment_id,policy_version,segment_start,segment_end,expected_scope,
       expected_items,status,receipt_run_id,evaluated_at,detail_json
     ) VALUES ('jquants','equities_bars_daily',?,?,?,?, 'day',1,?,1,'2026-08-01T00:00:00Z','{}')`,
  ).run(args.segment, "collection-coverage/v3", args.start, args.end, args.status);
}

function insertReceipt(
  db: DatabaseSync,
  args: {
    segment: string;
    status: string;
    exhausted?: number;
    observed?: number;
    rawRows?: number;
    digests?: string;
  },
): void {
  db.prepare(
    `INSERT INTO collection_receipts(
       source,dataset,segment_id,segment_start,segment_end,expected_scope,expected_items,
       observed_items,raw_page_count,raw_row_count,structured_row_count,pagination_exhausted,
       digests_json,run_id,status,error,checked_at
     ) VALUES (
       'jquants','equities_bars_daily',?,'2026-08-01','2026-08-31','day',1,
       ?,1,?,?,?, ?,1,? ,NULL,'2026-08-01T00:00:00Z'
     )`,
  ).run(
    args.segment,
    args.observed ?? 2,
    args.rawRows ?? 2,
    args.observed ?? 2,
    args.exhausted ?? 1,
    args.digests ?? '{"artifact_digest":"sha256:aa","manifest_digest":"sha256:bb"}',
    args.status,
  );
}

function wrapR2(hooks: { onPut?: (key: string) => void } = {}): R2Bucket {
  const store = new Map<string, Uint8Array>();
  const toBytes = (value: unknown): Uint8Array => {
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    return new TextEncoder().encode(String(value));
  };
  return {
    async head(key: string) {
      return store.has(key) ? { key } : null;
    },
    async get(key: string) {
      const body = store.get(key);
      if (body === undefined) return null;
      return {
        text: async () => new TextDecoder().decode(body),
        arrayBuffer: async () => body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength),
      };
    },
    async put(
      key: string,
      value: unknown,
      options?: { onlyIf?: { etagDoesNotMatch?: string } },
    ) {
      hooks.onPut?.(key);
      if (options?.onlyIf?.etagDoesNotMatch === "*" && store.has(key)) {
        return null;
      }
      store.set(key, toBytes(value));
      return { key };
    },
  } as unknown as R2Bucket;
}

async function envFor(
  source: DatabaseSync,
  target: DatabaseSync,
  keys: { pkcs8: string; spki: string },
  hooks?: {
    beforeRun?: (sql: string) => void;
    r2?: boolean;
    version?: { id: string; tag?: string };
    r2OnPut?: (key: string) => void;
    bucket?: R2Bucket;
    receiptRegistry?: OpsProjectionEnv["RECEIPT_VERIFY_REGISTRY"];
  },
): Promise<OpsProjectionEnv> {
  return {
    DB: wrapSqlite(source),
    OPS_PROJECTION_DB: wrapSqlite(target, hooks),
    STRUCTURED_BUCKET:
      hooks?.r2 === false ? undefined : hooks?.bucket ?? wrapR2({ onPut: hooks?.r2OnPut }),
    RAW_BUCKET: hooks?.r2 === false ? undefined : (hooks as { stores?: { raw?: R2Bucket } })?.stores?.raw ?? wrapR2(),
    AUTHORITY_EVIDENCE_BUCKET: hooks?.r2 === false ? undefined : (hooks as { stores?: { authority?: R2Bucket } })?.stores?.authority ?? wrapR2(),
    OPS_PROJECTION_SIGNING_PKCS8_B64: keys.pkcs8,
    OPS_PROJECTION_VERIFY_SPKI_B64: keys.spki,
    OPS_PROJECTION_SIGNING_KEY_ID: "ops-projection-cloud-test-v1",
    OPS_PROJECTION_ENVIRONMENT: "production",
    CF_VERSION_METADATA: hooks?.version ?? {
      id: "10000000-0000-4000-8000-000000000001",
      tag: "a".repeat(40),
    },
    RECEIPT_VERIFY_REGISTRY: hooks?.receiptRegistry,
  };
}

describe("ops projection cloud publisher", () => {
  it("publishes from real 0001-0010 source schema onto the dedicated projection migration", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    insertSegment(source, {
      segment: "2026-08",
      status: "COMPLETE",
      start: "2026-08-01",
      end: "2026-08-31",
    });
    insertReceipt(source, { segment: "2026-08", status: "SUCCESS" });
    source.prepare(
      `INSERT INTO raw_retention_manifests(
         dataset,run_id,manifest_key,page_count,row_count,raw_bytes,data_digest,completeness,created_at
       ) VALUES ('equities_bars',1,'raw/equities_bars/1/manifest.json',1,2,10,'sha256:cc','ACQUIRED','2026-08-01T00:00:00Z')`,
    ).run();
    const keys = await keyPair();
    const prepared: string[] = [];
    const env = await envFor(source, target, keys, {
      beforeRun(sql) {
        prepared.push(sql);
      },
    });
    const original = env.DB.prepare.bind(env.DB);
    const sourceSql: string[] = [];
    env.DB.prepare = ((sql: string) => {
      sourceSql.push(sql);
      return original(sql);
    }) as D1Database["prepare"];
    const result = await publishOpsProjection(env);
    expect(result.status).toBe("published");
    expect(sourceSql.join("\n")).not.toMatch(
      /jquants_records|jquants_daily_bars|jsda_otc_bond/,
    );
    expect(sourceSql.some((sql) => /FROM raw_retention_manifests/.test(sql))).toBe(true);
    expect(
      sourceSql.some(
        (sql) =>
          /FROM raw_retention_manifests/.test(sql) &&
          /\bsource\b|\bsegment_id\b|\breason\b/.test(sql),
      ),
    ).toBe(false);
    const generation = result.generation_id;
    const stored: Record<string, Record<string, unknown>[]> = {};
    for (const table of PROJECTED_CONTENT_TABLES) {
      stored[table] = target
        .prepare(`SELECT * FROM ${table} WHERE projection_generation_id=?`)
        .all(generation) as Record<string, unknown>[];
    }
    const sealed = target
      .prepare(
        "SELECT status, content_digest, signed_envelope_json FROM ops_projection_generation WHERE generation_id=?",
      )
      .get(generation) as {
      status: string;
      content_digest: string;
      signed_envelope_json: string;
    };
    expect(sealed.status).toBe("SEALED");
    expect(sealed.content_digest).toBe(await digest({ tables: await manifestFromRows(stored) }));
    const envelope = JSON.parse(sealed.signed_envelope_json).envelope as {
      generation_id: string;
      content_digest: string;
      row_counts: Record<string, number>;
      projection_status: string;
      source_cursor: number | null;
      export_cursor: number | null;
      applied_cursor: number | null;
      producer_commit_sha: string;
    };
    expect(envelope.generation_id).toBe(generation);
    expect(envelope.content_digest).toBe(sealed.content_digest);
    expect(envelope.projection_status).toBe("FRESH");
    expect(envelope.source_cursor).toBe(12);
    expect(envelope.export_cursor).toBe(12);
    expect(envelope.applied_cursor).toBe(12);
    expect(envelope.producer_commit_sha).toBe("a".repeat(40));
    expect(envelope.producer_commit_sha).not.toBe(
      "10000000-0000-4000-8000-000000000001",
    );
    expect(envelope.source_generation).toBe(12);
    expect(envelope.source_generation).toBe(envelope.source_cursor);
    expect(stored.endpoint_inventory.length).toBeGreaterThan(0);
    expect(stored.collection_sla_status.length).toBe(stored.endpoint_inventory.length);
    expect(stored.ops_sync_feed[0].feed).toBe("jquants_records");
    expect(stored.ops_projection_metadata[0].source_generation).toBe(12);
    expect(envelope.row_counts.receipt_product_materializations).toBe(0);
    const coverage = stored.coverage_segments[0];
    expect(coverage.status).toBe("UNKNOWN");
    const dataset = stored.dataset_coverage[0];
    expect(dataset.status).toBe("UNKNOWN");
    const raw = stored.raw_retention_manifests[0];
    expect(raw.source).toBe("UNKNOWN");
    expect(raw.segment_id).toBe("dataset");
    expect(raw.reason).toBeNull();
    expect(JSON.parse(String(stored.ops_storage_plane_status[0].payload_json)).jsda.phase).toBe(
      "NOT_PROJECTED",
    );
  });


  it("does not claim FRESH or SEALED without an R2 export and target apply", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const keys = await keyPair();
    await expect(
      publishOpsProjection(await envFor(source, target, keys, { r2: false })),
    ).rejects.toThrow(/R2 export bucket is required/);
    expect(
      target.prepare("SELECT generation_id FROM ops_projection_generation").get(),
    ).toBeUndefined();
  });

  it("fails closed before R2 or D1 mutation when provenance is missing", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const keys = await keyPair();
    await expect(
      publishOpsProjection(
        await envFor(source, target, keys, { version: { id: "10000000-0000-4000-8000-000000000001" } }),
      ),
    ).rejects.toThrow(/provenance is missing|clean merged Git SHA/);
    expect(
      target.prepare("SELECT generation_id FROM ops_projection_generation").get(),
    ).toBeUndefined();
  });

  it("never treats a Cloudflare version UUID as the Git SHA", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const keys = await keyPair();
    await expect(
      publishOpsProjection(
        await envFor(source, target, keys, {
          version: { id: "a".repeat(40), tag: "a".repeat(40) },
        }),
      ),
    ).rejects.toThrow(/Cloudflare version UUID is invalid|not a Git SHA/);
  });

  it("aggregates every required segment and never promotes COMPLETE+PARTIAL to COMPLETE", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    insertSegment(source, {
      segment: "2026-08",
      status: "COMPLETE",
      start: "2026-08-01",
      end: "2026-08-31",
    });
    insertSegment(source, {
      segment: "2026-09",
      status: "PARTIAL",
      start: "2026-09-01",
      end: "2026-09-30",
    });
    insertReceipt(source, { segment: "2026-08", status: "SUCCESS" });
    const keys = await keyPair();
    await publishOpsProjection(await envFor(source, target, keys));
    const dataset = target.prepare("SELECT status FROM dataset_coverage").get() as {
      status: string;
    };
    expect(dataset.status).not.toBe("COMPLETE");
    const statuses = target
      .prepare("SELECT segment_id, status FROM coverage_segments ORDER BY segment_id")
      .all() as { segment_id: string; status: string }[];
    expect(statuses.map((row) => row.status)).toEqual(["UNKNOWN", "PARTIAL"]);
  });

  it("no-ops unchanged evidence, republishes changed evidence, and rejects cursor regression", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source, 20);
    insertSegment(source, {
      segment: "2026-08",
      status: "PARTIAL",
      start: "2026-08-01",
      end: "2026-08-31",
    });
    const keys = await keyPair();
    const env = await envFor(source, target, keys);
    const first = await publishOpsProjection(env);
    expect(first.status).toBe("published");
    expect(await publishOpsProjection(env)).toEqual({
      status: "noop",
      generation_id: first.generation_id,
      source_evidence_digest: first.source_evidence_digest,
    });
    source.prepare("UPDATE ingestion_run_log SET status='failed' WHERE id=1").run();
    const second = await publishOpsProjection(await envFor(source, target, keys));
    expect(second.status).toBe("published");
    expect(second.generation_id).not.toBe(first.generation_id);
    source.exec("DELETE FROM ingestion_change_log");
    source.prepare(
      `INSERT INTO ingestion_change_log(
         table_name,source,dataset,natural_key,event_time,available_at,ingested_at,payload,changed_at
       ) VALUES ('jquants_daily_bars','jquants','equities_bars','1301','2026-08-01','2026-08-01','2026-08-01','{}','2026-08-01T00:00:00Z')`,
    ).run();
    source.prepare("UPDATE ingestion_change_log SET change_seq=3").run();
    await expect(publishOpsProjection(await envFor(source, target, keys))).rejects.toThrow(
      /cursor would regress/,
    );
  });

  it("reuses orphan OPEN and leaves the prior active pointer when seal fails", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source, 4);
    insertSegment(source, {
      segment: "2026-08",
      status: "PARTIAL",
      start: "2026-08-01",
      end: "2026-08-31",
    });
    const keys = await keyPair();
    const first = await publishOpsProjection(await envFor(source, target, keys));
    source.prepare("UPDATE ingestion_run_log SET detail='changed' WHERE id=1").run();
    let failSeal = true;
    await expect(
      publishOpsProjection(
        await envFor(source, target, keys, {
          beforeRun(sql) {
            if (failSeal && /status='SEALED'/.test(sql)) throw new Error("injected seal failure");
          },
        }),
      ),
    ).rejects.toBeInstanceOf(OpsProjectionPublishError);
    const open = target
      .prepare(
        "SELECT generation_id, status, generated_at FROM ops_projection_generation WHERE status='OPEN'",
      )
      .get() as { generation_id: string; generated_at: string };
    expect(open.generation_id).not.toBe(first.generation_id);
    expect(
      (target.prepare("SELECT generation_id FROM ops_projection_active").get() as { generation_id: string })
        .generation_id,
    ).toBe(first.generation_id);
    failSeal = false;
    const retried = await publishOpsProjection(await envFor(source, target, keys));
    expect(retried.generation_id).toBe(open.generation_id);
    expect(
      (target.prepare("SELECT generated_at FROM ops_projection_generation WHERE generation_id=?").get(open.generation_id) as { generated_at: string }).generated_at,
    ).toBe(open.generated_at);
  });

  it("fails closed on cap overflow and placeholder verify keys", async () => {
    const source = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    for (let index = 0; index < 10_002; index += 1) {
      source
        .prepare(
          `INSERT INTO ingestion_run_log(ran_at,source,runtime,status,detail)
           VALUES ('2026-08-01T00:00:00Z','jquants','cloud','ok',NULL)`,
        )
        .run();
    }
    const target = new DatabaseSync(":memory:");
    applySqlDir(target, projectionMigrations);
    const keys = await keyPair();
    await expect(publishOpsProjection(await envFor(source, target, keys))).rejects.toThrow(
      /exceeds metadata cap/,
    );
    const emptySource = new DatabaseSync(":memory:");
    applySqlDir(emptySource, ingestionMigrations, "0010_raw_acquisition_status.sql");
    const emptyTarget = new DatabaseSync(":memory:");
    applySqlDir(emptyTarget, projectionMigrations);
    await expect(
      publishOpsProjection({
        ...(await envFor(emptySource, emptyTarget, keys)),
        OPS_PROJECTION_VERIFY_SPKI_B64: "A".repeat(44),
      }),
    ).rejects.toThrow(/unprovisioned/);
  });

  it("publishes a generation that all 17 MCP tools can read", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    insertSegment(source, {
      segment: "2026-08",
      status: "PARTIAL",
      start: "2026-08-01",
      end: "2026-08-31",
    });
    const keys = await keyPair();
    const env = await envFor(source, target, keys);
    const published = await publishOpsProjection(env);
    expect(published.status).toBe("published");
    const db = wrapSqlite(target);
    const verify = (generation: Record<string, unknown>) =>
      verifyProjectionGenerationWithSpki(
        generation,
        keys.spki,
        "ops-projection-cloud-test-v1",
        "production",
      );
    expect(OPS_TOOLS).toHaveLength(17);
    const digestId = `sha256:${"ab".repeat(32)}`;
    const calls: Array<[string, Record<string, unknown>]> = [
      ["ops_status", {}],
      ["source_inventory", {}],
      ["endpoint_status", { dataset: "equities_bars_daily" }],
      ["projection_status", {}],
      ["collection_sla_status", {}],
      ["ingestion_last_run", {}],
      ["dataset_coverage", { dataset: "equities_bars_daily" }],
      ["coverage_gaps", {}],
      ["coverage_segments", {}],
      ["backfill_status", {}],
      ["validation_summary", {}],
      ["b0_status", {}],
      ["latest_ready_snapshot", {}],
      ["snapshot_quality", { snapshot_id: digestId }],
      ["raw_retention_status", {}],
      ["sync_status", {}],
      ["storage_plane_status", {}],
    ];
    for (const [name, args] of calls) {
      const result = await dispatchOpsTool(db, name, args, verify) as {
        status: string;
        reason?: string;
      };
      expect(typeof result.status).toBe("string");
      expect(result.status).not.toBe("");
    }
  });

  it("uses atomic create-only R2 and applies only verified readback bytes", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const keys = await keyPair();
    const puts: string[] = [];
    const env = await envFor(source, target, keys, {
      r2OnPut: (key) => puts.push(key),
    });
    const result = await publishOpsProjection(env);
    expect(result.status).toBe("published");
    expect(puts).toHaveLength(1);
    const generation = result.generation_id;
    const stored = env.STRUCTURED_BUCKET as unknown as {
      get: (key: string) => Promise<{ text: () => Promise<string> } | null>;
    };
    const object = await stored.get(
      `ops-projection/production/${generation}/export.json`,
    );
    expect(object).not.toBeNull();
    const exportDoc = JSON.parse(await object!.text()) as {
      tables: Record<string, Record<string, unknown>[]>;
    };
    const d1Rows = target
      .prepare(
        "SELECT * FROM ops_projection_metadata WHERE projection_generation_id=?",
      )
      .get(generation) as Record<string, unknown>;
    expect(d1Rows.status).toBe(exportDoc.tables.ops_projection_metadata[0].status);
    expect(d1Rows.source_cursor).toBe(
      exportDoc.tables.ops_projection_metadata[0].source_cursor,
    );
    expect(d1Rows.export_cursor).toBe(d1Rows.applied_cursor);
  });

  it("rejects an existing export object with a different digest", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const keys = await keyPair();
    const bucket = wrapR2();
    const env = await envFor(source, target, keys, { bucket });
    const published = await publishOpsProjection(env);
    await bucket.put(
      `ops-projection/production/${published.generation_id}/export.json`,
      JSON.stringify({ kind: "forged" }),
    );
    const retryTarget = new DatabaseSync(":memory:");
    applySqlDir(retryTarget, projectionMigrations);
    await expect(
      publishOpsProjection(await envFor(source, retryTarget, keys, { bucket })),
    ).rejects.toThrow(/exists with a different digest|equal-length different bytes/);
  });

  it("rejects equal-length semantically equivalent different export bytes", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const keys = await keyPair();
    const bucket = wrapR2();
    const env = await envFor(source, target, keys, { bucket });
    const published = await publishOpsProjection(env);
    const key = `ops-projection/production/${published.generation_id}/export.json`;
    const object = await bucket.get(key);
    const original = new Uint8Array(await object!.arrayBuffer());
    const text = new TextDecoder().decode(original);
    const spaced = text.replace(/":"/g, '": "');
    const mutated = new TextEncoder().encode(
      spaced.length === original.byteLength
        ? spaced
        : text.replace("ops-projection-export/v1", "ops-projection-export/V1"),
    );
    expect(mutated.byteLength).toBe(original.byteLength);
    expect(Buffer.from(mutated).equals(Buffer.from(original))).toBe(false);
    await bucket.put(key, mutated);
    const retryTarget = new DatabaseSync(":memory:");
    applySqlDir(retryTarget, projectionMigrations);
    await expect(
      publishOpsProjection(await envFor(source, retryTarget, keys, { bucket })),
    ).rejects.toThrow(/equal-length different bytes/);
  });

  it("produces a new generation when data is unchanged but the worker version changes", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source, 20);
    const keys = await keyPair();
    const first = await publishOpsProjection(await envFor(source, target, keys));
    expect(first.status).toBe("published");
    const second = await publishOpsProjection(
      await envFor(source, target, keys, {
        version: { id: "20000000-0000-4000-8000-000000000002", tag: "a".repeat(40) },
      }),
    );
    expect(second.status).toBe("published");
    expect(second.generation_id).not.toBe(first.generation_id);
    expect(second.source_evidence_digest).toBe(first.source_evidence_digest);
  });

  it("accepts exact Coverage V3 receipt chains including JSDA and rejects V2", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations);
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const keys = await keyPair();
    const digestJson = JSON.stringify({
      artifact_digest: "sha256:" + "aa".repeat(32),
      manifest_digest: "sha256:" + "bb".repeat(32),
      structured_digest: "sha256:" + "cc".repeat(32),
      raw_manifest_digest: "sha256:" + "dd".repeat(32),
    });
    source.prepare(
      `INSERT INTO coverage_segments(
         source,dataset,segment_id,policy_version,segment_start,segment_end,expected_scope,
         expected_items,status,receipt_run_id,evaluated_at,detail_json
       ) VALUES
         ('jquants','equities_bars_daily','2026-08','collection-coverage/v3','2026-08-01','2026-08-31','day',1,'COMPLETE',1,'2026-08-01T00:00:00Z','{}'),
         ('jsda','jsda_otc_bond_reference_prices','2026-08-01','collection-coverage/v3','2026-08-01','2026-08-01','official_archive_index_day',1,'COMPLETE',1,'2026-08-01T00:00:00Z','{}'),
         ('jquants','equities_master','2026-08','collection-coverage/v2','2026-08-01','2026-08-31','day',1,'COMPLETE',1,'2026-08-01T00:00:00Z','{}')`,
    ).run();
    source.prepare(
      `INSERT INTO collection_receipts(
         source,dataset,segment_id,segment_start,segment_end,expected_scope,expected_items,
         observed_items,raw_page_count,raw_row_count,structured_row_count,pagination_exhausted,
         digests_json,run_id,status,error,checked_at
       ) VALUES
         ('jquants','equities_bars_daily','2026-08','2026-08-01','2026-08-31','day',1,2,1,2,2,1,?,1,'SUCCESS',NULL,'2026-08-01T00:00:00Z'),
         ('jsda','jsda_otc_bond_reference_prices','2026-08-01','2026-08-01','2026-08-01','official_archive_index_day',1,2,1,2,2,1,?,1,'SUCCESS',NULL,'2026-08-01T00:00:00Z')`,
    ).run(digestJson, digestJson);
    const result = await publishOpsProjection(await envFor(source, target, keys));
    expect(result.status).toBe("published");
    const rows = target
      .prepare(
        "SELECT source, dataset, policy_version, status FROM coverage_segments ORDER BY dataset",
      )
      .all() as { source: string; dataset: string; policy_version: string; status: string }[];
    const byDataset = Object.fromEntries(rows.map((row) => [row.dataset, row]));
    expect(byDataset.equities_bars_daily.status).toBe("UNKNOWN");
    expect(byDataset.equities_master.status).toBe("UNKNOWN");
    expect(byDataset.equities_master.policy_version).toBe("collection-coverage/v2");
    expect(byDataset.jsda_otc_bond_reference_prices.source).toBe("jsda");
    expect(byDataset.jsda_otc_bond_reference_prices.status).toBe("UNKNOWN");
    const envelope = JSON.parse(
      (target.prepare(
        "SELECT signed_envelope_json FROM ops_projection_generation WHERE generation_id=?",
      ).get(result.generation_id) as { signed_envelope_json: string }).signed_envelope_json,
    ).envelope as { coverage_policy_version: string; dataset_coverage: Record<string, { status: string }> };
    expect(envelope.coverage_policy_version).not.toBe("collection-coverage/v3");
    expect(envelope.dataset_coverage.equities_bars_daily.status).not.toBe("COMPLETE");
    const inventory = target
      .prepare("SELECT dataset_id FROM endpoint_inventory")
      .all() as { dataset_id: string }[];
    expect(inventory.some((row) => row.dataset_id === "jsda_otc_bond_reference_prices")).toBe(
      true,
    );
  });

  it("fails closed when B0/B4 evidence is missing", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations, "0010_raw_acquisition_status.sql");
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    source.exec("DELETE FROM snapshot_quality_results");
    const keys = await keyPair();
    const missing = await publishOpsProjection(await envFor(source, target, keys));
    expect(missing.status).toBe("published");
    const missingEnvelope = JSON.parse(
      (target.prepare(
        "SELECT signed_envelope_json FROM ops_projection_generation WHERE generation_id=?",
      ).get(missing.generation_id) as { signed_envelope_json: string }).signed_envelope_json,
    ).envelope as { b0_status: string; b4_status: string };
    expect(missingEnvelope.b0_status).toBe("UNKNOWN");
    expect(missingEnvelope.b4_status).toBe("UNKNOWN");
  });

  it("projects authoritative B0/B4 PASS into the sealed envelope", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations);
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    insertSegment(source, {
      segment: "2026-08",
      status: "PARTIAL",
      start: "2026-08-01",
      end: "2026-08-31",
    });
    const keys = await keyPair();
    const result = await publishOpsProjection(await envFor(source, target, keys));
    const sealed = JSON.parse(
      (target.prepare(
        "SELECT signed_envelope_json FROM ops_projection_generation WHERE generation_id=?",
      ).get(result.generation_id) as { signed_envelope_json: string }).signed_envelope_json,
    ).envelope as { b0_status: string; b4_status: string; source_cursor: number; generation_id: string };
    expect(sealed.b0_status).toBe("PASS");
    expect(sealed.b4_status).toBe("PASS");
    expect(sealed.generation_id).toBe(result.generation_id);
    const row = target.prepare("SELECT status FROM ops_b0_status").get() as { status: string };
    expect(row.status).toBe("PASS");
  });

  it("verifies authentic signed JQ/JSDA receipts and rejects tamper plus V2", async () => {
    const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
    const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
    const registry = {
      authority_status: "ACTIVE",
      environment: "production",
      authority_instance_digest: "sha256:" + "11".repeat(32),
      keys: [
        {
          key_id: "receipt-test-v1",
          algorithm: "Ed25519",
          public_key_base64: b64(raw),
          status: "active",
          environment: "production",
        },
      ],
    };
    const signClaims = async (claims: Record<string, unknown>) => {
      const body = JSON.stringify(claims);
      const signature = new Uint8Array(
        await crypto.subtle.sign("Ed25519", pair.privateKey, new TextEncoder().encode(body)),
      );
      const digest = "sha256:" + Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))),
        (byte) => byte.toString(16).padStart(2, "0"),
      ).join("");
      return {
        issuer_key_id: "receipt-test-v1",
        environment: "production",
        authority_instance_digest: registry.authority_instance_digest,
        signed_body_b64: b64(new TextEncoder().encode(body)),
        signature: `ed25519:${b64(signature)}`,
        body_digest: digest,
        structured_digest: claims.structured_digest,
        raw_manifest_digest: claims.raw_manifest_digest,
        extra_digests: claims.extra_digests,
      };
    };
    const objects = await seedGovernedObjects();
    const jqClaims = {
      source: "jquants",
      contract_id: "jquants_premium_core",
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      segment_start: "2026-08-01",
      segment_end: "2026-08-31",
      environment: "production",
      coverage_policy_version: "collection-coverage/v3",
      run_id: 1,
      raw_page_count: 1,
      raw_count: 2,
      checked_at: "2026-08-01T00:00:00Z",
      structured_digest: objects.structured,
      raw_manifest_digest: objects.rawDigest,
      artifact_byte_count: objects.artifactBytes,
      manifest_byte_count: objects.manifestBytes,
      raw_manifest_byte_count: objects.rawBytes,
      pagination_exhausted: true,
      discovery_exhausted: true,
      structured_count: 2,
      receipt_issue_digest: "sha256:" + "cc".repeat(32),
      source_request_digest: "sha256:" + "ff".repeat(32),
      artifact_key: "artifact.jsonl",
      manifest_key: "manifest.json",
      raw_manifest_key: "raw.json",
      extra_digests: {
        product_artifact_digest: objects.structured,
        product_manifest_digest: objects.manifestDigest,
        acquisition_collection_manifest_file_digest: objects.rawFileDigest,
      },
    };
    const jsdaClaims = {
      ...jqClaims,
      source: "jsda",
      dataset: "jsda_otc_bond_reference_prices",
      segment_id: "2026-08-01",
    };
    const jqEnvelope = await signClaims(jqClaims);
    const jsdaEnvelope = await signClaims(jsdaClaims);
    expect(await verifySignedReceiptEnvelope(jqEnvelope, registry, "production")).not.toBeNull();
    expect(await verifySignedReceiptEnvelope(jsdaEnvelope, registry, "production")).not.toBeNull();
    const tampered = { ...jqEnvelope, body_digest: "sha256:" + "ff".repeat(32) };
    expect(await verifySignedReceiptEnvelope(tampered, registry, "production")).toBeNull();
    const complete = await trustedComplete(
      {
        status: "COMPLETE",
        source: "jquants",
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        segment_start: "2026-08-01",
        segment_end: "2026-08-31",
        expected_scope: "day",
        expected_items: 1,
        policy_version: "collection-coverage/v3",
        receipt_run_id: 1,
      },
      [
        {
          source: "jquants",
          dataset: "equities_bars_daily",
          segment_id: "2026-08",
          segment_start: "2026-08-01",
          segment_end: "2026-08-31",
          expected_scope: "day",
          expected_items: 1,
          status: "SUCCESS",
          run_id: 1,
          pagination_exhausted: 1,
          structured_row_count: 2,
          raw_row_count: 2,
          raw_page_count: 1,
          checked_at: "2026-08-01T00:00:00Z",
          digests_json: JSON.stringify(jqEnvelope),
        },
      ],
      [
        {
          source: "jquants",
          run_id: 1,
          dataset: "equities_bars_daily",
          segment_id: "2026-08",
          operation_id: "op-1",
          row_count: 2,
          raw_row_count: 2,
          artifact_key: "artifact.jsonl",
          manifest_key: "manifest.json",
          raw_manifest_key: "raw.json",
          artifact_digest: objects.structured,
          manifest_digest: objects.manifestDigest,
          raw_manifest_digest: objects.rawDigest,
          byte_count: objects.artifactBytes,
        },
      ],
      [
        {
          run_id: 1,
          dataset: "equities_bars_daily",
          segment_id: "2026-08",
          environment: "production",
          state: "RECEIPT_COMMITTED",
          operation_id: "op-1",
          source: "jquants",
          receipt_digest: "sha256:" + "ee".repeat(32),
          request_digest: "sha256:" + "cc".repeat(32),
          structured_digest: objects.structured,
          raw_manifest_digest: objects.rawDigest,
        },
      ],
      [
        {
          operation_id: "op-1",
          state: "FINALIZED",
          environment: "production",
          dataset: "equities_bars_daily",
          segment_id: "2026-08",
          source: "jquants",
          receipt_digest: "sha256:" + "ee".repeat(32),
        },
      ],
      new Map([["op-1", 2]]),
      "production",
      registry,
      objects.stores,
    );
    expect(complete).toBe(true);
    expect(await trustedComplete(
      {
        status: "COMPLETE",
        source: "jquants",
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        segment_start: "2026-08-01",
        segment_end: "2026-08-31",
        policy_version: "collection-coverage/v3",
        receipt_run_id: 1,
      },
      [],
      [],
      [],
      [],
      new Map(),
      "production",
      registry,
      objects.stores,
    )).toBe(false);
    const v2 = await trustedComplete(
      {
        status: "COMPLETE",
        source: "jquants",
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        policy_version: "collection-coverage/v2",
        receipt_run_id: 1,
      },
      [],
      [],
      [],
      [],
      new Map(),
      "production",
      registry,
    );
    expect(v2).toBe(false);
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      objects.stores,
    )).toBe(true);
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      {
        structured: objects.stores.raw,
        authority: objects.stores.structured,
        raw: objects.stores.authority,
      },
    )).toBe(false);
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      { ...objects.stores, structured: wrapR2() },
    )).toBe(false);
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      { ...objects.stores, authority: wrapR2() },
    )).toBe(false);
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      { ...objects.stores, raw: wrapR2() },
    )).toBe(false);
    const wrongStructured = wrapR2();
    await wrongStructured.put(
      "artifact.jsonl",
      new TextEncoder().encode("wrong-artifact\n"),
    );
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      { ...objects.stores, structured: wrongStructured },
    )).toBe(false);
    const wrongAuthority = wrapR2();
    await wrongAuthority.put(
      "manifest.json",
      new TextEncoder().encode("wrong-manifest\n"),
    );
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      { ...objects.stores, authority: wrongAuthority },
    )).toBe(false);
    const wrongRaw = wrapR2();
    await wrongRaw.put("raw.json", new TextEncoder().encode("wrong-raw\n"));
    expect(await exactJqTrustedComplete(
      objects,
      jqEnvelope,
      registry,
      { ...objects.stores, raw: wrongRaw },
    )).toBe(false);
    expect(objects.rawDigest).not.toBe(objects.rawFileDigest);
    const swapped = await signClaims({
      ...jqClaims,
      extra_digests: {
        ...jqClaims.extra_digests,
        acquisition_collection_manifest_file_digest: objects.rawDigest,
      },
    });
    expect(await exactJqTrustedComplete(
      objects,
      swapped,
      registry,
      objects.stores,
    )).toBe(false);
  });

  it("projects authentic ACTIVE-pinned signed JQ COMPLETE and keeps JSDA UNKNOWN without evidence", async () => {
    const source = new DatabaseSync(":memory:");
    const target = new DatabaseSync(":memory:");
    applySqlDir(source, ingestionMigrations);
    applySqlDir(target, projectionMigrations);
    seedBase(source);
    const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
    const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
    const registry = {
      authority_status: "ACTIVE" as const,
      environment: "production",
      authority_instance_digest: "sha256:" + "11".repeat(32),
      keys: [
        {
          key_id: "receipt-test-v1",
          algorithm: "Ed25519",
          public_key_base64: b64(raw),
          status: "active",
          environment: "production",
          not_before: "2026-01-01T00:00:00Z",
          not_after: "2027-01-01T00:00:00Z",
          revoked_at: null,
        },
      ],
    };
    const objects = await seedGovernedObjects();
    const claims = {
      source: "jquants",
      contract_id: "jquants_premium_core",
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      segment_start: "2026-08-01",
      segment_end: "2026-08-31",
      environment: "production",
      coverage_policy_version: "collection-coverage/v3",
      run_id: 1,
      raw_page_count: 1,
      raw_count: 2,
      checked_at: "2026-08-01T00:00:00Z",
      structured_digest: objects.structured,
      raw_manifest_digest: objects.rawDigest,
      artifact_byte_count: objects.artifactBytes,
      manifest_byte_count: objects.manifestBytes,
      raw_manifest_byte_count: objects.rawBytes,
      pagination_exhausted: true,
      discovery_exhausted: true,
      structured_count: 2,
      receipt_issue_digest: "sha256:" + "cc".repeat(32),
      source_request_digest: "sha256:" + "ff".repeat(32),
      artifact_key: "artifact.jsonl",
      manifest_key: "manifest.json",
      raw_manifest_key: "raw.json",
      extra_digests: {
        product_artifact_digest: objects.structured,
        product_manifest_digest: objects.manifestDigest,
        acquisition_collection_manifest_file_digest: objects.rawFileDigest,
      },
    };
    const body = JSON.stringify(claims);
    const signature = new Uint8Array(
      await crypto.subtle.sign("Ed25519", pair.privateKey, new TextEncoder().encode(body)),
    );
    const bodyDigest = "sha256:" + Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))),
      (byte) => byte.toString(16).padStart(2, "0"),
    ).join("");
    const envelope = {
      issuer_key_id: "receipt-test-v1",
      environment: "production",
      authority_instance_digest: registry.authority_instance_digest,
      signed_body_b64: b64(new TextEncoder().encode(body)),
      signature: `ed25519:${b64(signature)}`,
      body_digest: bodyDigest,
      structured_digest: claims.structured_digest,
      raw_manifest_digest: claims.raw_manifest_digest,
      extra_digests: claims.extra_digests,
    };
    source.prepare(
      `INSERT INTO coverage_segments(
         source,dataset,segment_id,policy_version,segment_start,segment_end,expected_scope,
         expected_items,status,receipt_run_id,evaluated_at,detail_json
       ) VALUES
         ('jquants','equities_bars_daily','2026-08','collection-coverage/v3','2026-08-01','2026-08-31','day',1,'COMPLETE',1,'2026-08-01T00:00:00Z','{}'),
         ('jsda','jsda_otc_bond_reference_prices','2026-08-01','collection-coverage/v3','2026-08-01','2026-08-01','official_archive_index_day',1,'COMPLETE',1,'2026-08-01T00:00:00Z','{}')`,
    ).run();
    source.prepare(
      `INSERT INTO receipt_authority_operations(
         operation_id,request_digest,run_id,environment,source,contract_id,dataset,segment_id,
         segment_start,segment_end,state,checked_at,updated_at,raw_manifest_digest
       ) VALUES (
         'op-1','sha256:' || ?,1,'production','jquants','jquants_premium_core','equities_bars_daily','2026-08',
         '2026-08-01','2026-08-31','COLLECTING','2026-08-01T00:00:00Z','2026-08-01T00:00:00Z',
         ?
       )`,
    ).run("cc".repeat(32), objects.rawDigest);
    source.prepare(
      `INSERT INTO receipt_authority_structured_rows(
         operation_id,natural_key,source,dataset,event_time,available_at,ingested_at,payload,raw_payload,row_digest
       ) VALUES
         ('op-1','k1','jquants','equities_bars_daily','2026-08-01','2026-08-01','2026-08-01T00:00:00Z','{}','{}','sha256:' || ?),
         ('op-1','k2','jquants','equities_bars_daily','2026-08-02','2026-08-02','2026-08-01T00:00:00Z','{}','{}','sha256:' || ?)`,
    ).run("11".repeat(32), "22".repeat(32));
    source.prepare(
      `INSERT INTO receipt_product_materializations(
         operation_id,run_id,source,dataset,segment_id,artifact_key,artifact_digest,artifact_body,
         row_count,byte_count,manifest_key,manifest_digest,raw_manifest_key,raw_manifest_digest,
         raw_page_count,raw_row_count,raw_bytes,committed_at
       ) VALUES (
         'op-1',1,'jquants','equities_bars_daily','2026-08','artifact.jsonl',?,'',
         2,?, 'manifest.json',?,'raw.json',?,
         1,2,2,'2026-08-01T00:00:00Z'
       )`,
    ).run(objects.structured, objects.artifactBytes, objects.manifestDigest, objects.rawDigest);
    source.prepare(
      `UPDATE receipt_authority_operations
          SET state='STRUCTURED_COMMITTED',
              structured_manifest_key='manifest.json',
              structured_digest=?
        WHERE operation_id='op-1'`,
    ).run(objects.structured);
    source.prepare(
      `INSERT INTO collection_receipts(
         source,dataset,segment_id,segment_start,segment_end,expected_scope,expected_items,
         observed_items,raw_page_count,raw_row_count,structured_row_count,pagination_exhausted,
         digests_json,run_id,status,error,checked_at
       ) VALUES (
         'jquants','equities_bars_daily','2026-08','2026-08-01','2026-08-31','day',1,
         2,1,2,2,1,?,1,'SUCCESS',NULL,'2026-08-01T00:00:00Z'
       )`,
    ).run(JSON.stringify(envelope));
    source.prepare(
      `UPDATE receipt_authority_operations
          SET state='RECEIPT_COMMITTED', receipt_digest='sha256:' || ?
        WHERE operation_id='op-1'`,
    ).run("ee".repeat(32));
    source.prepare(
      `INSERT INTO receipt_authority_requests(
         operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,state,
         receipt_digest,created_at,updated_at
       ) VALUES (
         'op-1',?,'production','jquants','jquants_premium_core','equities_bars_daily','2026-08','FINALIZED',
         'sha256:' || ?,'2026-08-01T00:00:00Z','2026-08-01T00:00:00Z'
       )`,
    ).run("ab".repeat(32), "ee".repeat(32));
    const keys = await keyPair();
    const env = await envFor(source, target, keys, { receiptRegistry: registry, bucket: objects.stores.structured, stores: objects.stores } as never);
    expect(await env.STRUCTURED_BUCKET!.get("artifact.jsonl")).toBeTruthy();
    expect(await env.AUTHORITY_EVIDENCE_BUCKET!.get("manifest.json")).toBeTruthy();
    expect(await env.RAW_BUCKET!.get("raw.json")).toBeTruthy();
    expect(await trustedComplete(
      {
        status: "COMPLETE",
        source: "jquants",
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        segment_start: "2026-08-01",
        segment_end: "2026-08-31",
        policy_version: "collection-coverage/v3",
        receipt_run_id: 1,
      },
      [{
        source: "jquants", dataset: "equities_bars_daily", segment_id: "2026-08",
        segment_start: "2026-08-01", segment_end: "2026-08-31",
        status: "SUCCESS", run_id: 1, pagination_exhausted: 1,
        structured_row_count: 2, raw_row_count: 2, raw_page_count: 1,
        digests_json: JSON.stringify(envelope),
      }],
      [{
        source: "jquants", run_id: 1, dataset: "equities_bars_daily", segment_id: "2026-08",
        operation_id: "op-1", row_count: 2, raw_row_count: 2,
        artifact_key: "artifact.jsonl", manifest_key: "manifest.json", raw_manifest_key: "raw.json",
        artifact_digest: objects.structured, manifest_digest: objects.manifestDigest,
        raw_manifest_digest: objects.rawDigest, byte_count: objects.artifactBytes,
      }],
      [{
        run_id: 1, dataset: "equities_bars_daily", segment_id: "2026-08", environment: "production",
        state: "RECEIPT_COMMITTED", operation_id: "op-1", source: "jquants",
        receipt_digest: "sha256:" + "ee".repeat(32), request_digest: "sha256:" + "cc".repeat(32),
        structured_digest: objects.structured, raw_manifest_digest: objects.rawDigest,
      }],
      [{
        operation_id: "op-1", state: "FINALIZED", environment: "production",
        dataset: "equities_bars_daily", segment_id: "2026-08", source: "jquants",
        receipt_digest: "sha256:" + "ee".repeat(32),
      }],
      new Map([["op-1", 2]]),
      "production",
      registry,
      { structured: env.STRUCTURED_BUCKET, authority: env.AUTHORITY_EVIDENCE_BUCKET, raw: env.RAW_BUCKET },
    )).toBe(true);
    const result = await publishOpsProjection(env);
    expect(result.status).toBe("published");
    const rows = target
      .prepare("SELECT dataset, status FROM coverage_segments ORDER BY dataset")
      .all() as { dataset: string; status: string }[];
    const byDataset = Object.fromEntries(rows.map((row) => [row.dataset, row.status]));
    expect(byDataset.equities_bars_daily).toBe("COMPLETE");
    expect(byDataset.jsda_otc_bond_reference_prices).toBe("UNKNOWN");
    const envelopeRow = JSON.parse(
      (target.prepare(
        "SELECT signed_envelope_json FROM ops_projection_generation WHERE generation_id=?",
      ).get(result.generation_id) as { signed_envelope_json: string }).signed_envelope_json,
    ).envelope as {
      dataset_coverage: Record<string, { status: string }>;
      coverage_policy_version: string;
    };
    expect(envelopeRow.dataset_coverage.equities_bars_daily.status).toBe("COMPLETE");
    expect(envelopeRow.dataset_coverage.jsda_otc_bond_reference_prices.status).toBe("UNKNOWN");
    expect(envelopeRow.coverage_policy_version).toBe("collection-coverage/v3");
  });

  it("rejects signed one-day/run-7 claims presented as whole-month/run-99 COMPLETE", async () => {
    const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
    const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
    const registry = {
      authority_status: "ACTIVE" as const,
      environment: "production",
      authority_instance_digest: "sha256:" + "11".repeat(32),
      keys: [{
        key_id: "receipt-test-v1",
        algorithm: "Ed25519",
        public_key_base64: b64(raw),
        status: "active",
        environment: "production",
      }],
    };
    const claims = {
      source: "jquants",
      contract_id: "jquants_premium_core",
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
      segment_start: "2026-08-07",
      segment_end: "2026-08-07",
      environment: "production",
      coverage_policy_version: "collection-coverage/v3",
      run_id: 7,
      raw_page_count: 1,
      raw_count: 2,
      checked_at: "2026-08-01T00:00:00Z",
      structured_digest: "sha256:" + "aa".repeat(32),
      raw_manifest_digest: "sha256:" + "bb".repeat(32),
      pagination_exhausted: true,
      discovery_exhausted: true,
      structured_count: 2,
      receipt_issue_digest: "sha256:" + "cc".repeat(32),
      source_request_digest: "sha256:" + "ff".repeat(32),
      extra_digests: {
        product_artifact_digest: "sha256:" + "aa".repeat(32),
        product_manifest_digest: "sha256:" + "dd".repeat(32),
      },
    };
    const body = JSON.stringify(claims);
    const signature = new Uint8Array(
      await crypto.subtle.sign("Ed25519", pair.privateKey, new TextEncoder().encode(body)),
    );
    const bodyDigest = "sha256:" + Array.from(
      new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(body))),
      (byte) => byte.toString(16).padStart(2, "0"),
    ).join("");
    const envelope = {
      issuer_key_id: "receipt-test-v1",
      environment: "production",
      authority_instance_digest: registry.authority_instance_digest,
      signed_body_b64: b64(new TextEncoder().encode(body)),
      signature: `ed25519:${b64(signature)}`,
      body_digest: bodyDigest,
      structured_digest: claims.structured_digest,
      raw_manifest_digest: claims.raw_manifest_digest,
      extra_digests: claims.extra_digests,
    };
    const complete = await trustedComplete(
      {
        status: "COMPLETE",
        source: "jquants",
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        segment_start: "2026-08-01",
        segment_end: "2026-08-31",
        expected_scope: "day",
        expected_items: 1,
        policy_version: "collection-coverage/v3",
        receipt_run_id: 99,
      },
      [{
        source: "jquants",
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        segment_start: "2026-08-01",
        segment_end: "2026-08-31",
        expected_scope: "day",
        expected_items: 1,
        status: "SUCCESS",
        run_id: 99,
        pagination_exhausted: 1,
        structured_row_count: 2,
        raw_row_count: 2,
        raw_page_count: 1,
        checked_at: "2026-08-01T00:00:00Z",
        digests_json: JSON.stringify(envelope),
      }],
      [{
        source: "jquants",
        run_id: 99,
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        operation_id: "op-1",
        row_count: 2,
        raw_row_count: 2,
        artifact_digest: "sha256:" + "aa".repeat(32),
        manifest_digest: "sha256:" + "dd".repeat(32),
        raw_manifest_digest: "sha256:" + "bb".repeat(32),
      }],
      [{
        run_id: 99,
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        environment: "production",
        state: "RECEIPT_COMMITTED",
        operation_id: "op-1",
        source: "jquants",
        receipt_digest: "sha256:" + "ee".repeat(32),
        request_digest: "sha256:" + "cc".repeat(32),
        structured_digest: "sha256:" + "aa".repeat(32),
        raw_manifest_digest: "sha256:" + "bb".repeat(32),
      }],
      [{
        operation_id: "op-1",
        state: "FINALIZED",
        environment: "production",
        dataset: "equities_bars_daily",
        segment_id: "2026-08",
        source: "jquants",
        receipt_digest: "sha256:" + "ee".repeat(32),
      }],
      new Map([["op-1", 2]]),
      "production",
      registry,
    );
    expect(complete).toBe(false);
  });
});
