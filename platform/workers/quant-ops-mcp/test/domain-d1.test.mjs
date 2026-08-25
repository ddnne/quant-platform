import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import {
  callOpsTool,
  classifyRawAcquisition,
  honestProjectionStatus,
  JSDA_UPSTREAM_LOCATORS,
  OPS_TOOLS,
  syncDatasetState,
} from "../src/domain.js";
import { GOVERNED_DATASETS } from "../src/governed.js";
import { DurableDailyQuota, QuotaExceeded } from "../src/quota.js";

function d1(db) {
  return {
    prepare(sql) {
      return {
        bind(...values) {
          const statement = db.prepare(sql);
          return {
            async all() { return { results: statement.all(...values) }; },
            async first() { return statement.get(...values) || null; },
            async run() { statement.run(...values); return { results: [] }; },
          };
        },
      };
    },
  };
}

const projectionMigration = readFileSync(
  new URL("../migrations/0002_ops_projection.sql", import.meta.url), "utf8",
);
const inventoryMigration = readFileSync(
  new URL("../migrations/0003_endpoint_inventory_sla.sql", import.meta.url), "utf8",
);
const generationMigration = readFileSync(
  new URL("../migrations/0004_projection_generation.sql", import.meta.url), "utf8",
);
const appliedPinsMigration = readFileSync(
  new URL("../migrations/0007_ops_applied_pins.sql", import.meta.url), "utf8",
);
const quotaMigration = readFileSync(
  new URL("../migrations/0001_remote_daily_quota.sql", import.meta.url), "utf8",
);
const ingestionMigrations = [
  "0001_init.sql", "0002_watermarks.sql", "0003_change_feed.sql",
  "0004_revision_identity_v2.sql", "0005_natural_keys_v2.sql",
  "0006_raw_retention_manifests.sql", "0007_collection_coverage_v2.sql",
  "0010_raw_acquisition_status.sql",
].map((name) => readFileSync(
  new URL(`../../ingestion-premium/migrations/${name}`, import.meta.url), "utf8",
));

test("coverage tool descriptions report stored policy_version not frozen Coverage V2", () => {
  const byName = Object.fromEntries(OPS_TOOLS.map((tool) => [tool.name, tool.description]));
  for (const name of ["dataset_coverage", "coverage_gaps", "coverage_segments"]) {
    assert.match(byName[name], /Coverage projection \(policy_version as stored on the generation\)/);
    assert.doesNotMatch(byName[name], /Coverage V2/);
  }
});

test("absent Coverage projection is UNKNOWN with all JQ and JSDA gaps", async () => {
  const db = new DatabaseSync(":memory:");
  const result = await callOpsTool(d1(db), "coverage_gaps", {});
  assert.equal(result.status, "UNKNOWN");
  assert.equal(result.gaps.length, GOVERNED_DATASETS.length);
  assert.ok(result.gaps.some((row) => row.dataset === "jsda_otc_bond_reference_prices"));
  assert.ok(result.gaps.some((row) => row.dataset === "jsda_tokyo_repo_rates"));
  assert.ok(result.gaps.some((row) => row.dataset === "jsda_corporate_bond_transactions"));
  assert.ok(result.gaps.every((row) =>
    row.reason === "Coverage projection has not been populated"));
  const coverage = await callOpsTool(d1(db), "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(coverage.status, "UNKNOWN");
  assert.equal(coverage.reason, "Coverage projection has not been populated");
  assert.doesNotMatch(coverage.reason, /Coverage V2/);
  const segments = await callOpsTool(d1(db), "coverage_segments", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(segments.status, "UNKNOWN");
  assert.equal(segments.reason, "Coverage projection has not been populated");
  const endpoint = await callOpsTool(d1(db), "endpoint_status", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(endpoint.coverage.status, "UNKNOWN");
  assert.equal(endpoint.coverage.reason, "Coverage projection has not been populated");
  db.close();
});

test("real projection schema exposes bounded JSDA Coverage and READY metadata", async () => {
  const db = new DatabaseSync(":memory:");
  db.exec(projectionMigration);
  db.prepare(`INSERT INTO dataset_coverage
    (dataset,status,policy_version,collection_scope,history_target_start,
     history_target_end_rule,coverage_mode,expected_frequency,universe_rule,
     raw_retention_required,structured_reconciliation_required,governance_tier,
     observed_start,observed_end,row_count,source_run_id,evaluated_at,detail_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      "jsda_otc_bond_reference_prices", "PARTIAL", "collection-coverage/v2",
      "jsda", "2002-08-02", "current", "official_archive_index_reconciled",
      "official_archive_day", "official_index", 1, 1, "governed",
      "2002-08-02", "2002-08-02", 1, 7, "2026-08-11T00:00:00Z", "{}",
    );
  db.prepare(`INSERT INTO coverage_segments
    (source,dataset,segment_id,policy_version,segment_start,segment_end,
     expected_scope,expected_items,status,receipt_run_id,evaluated_at,detail_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      "jsda", "jsda_otc_bond_reference_prices", "2002-08", "collection-coverage/v2",
      "2002-08-02", "2002-08-30", "{}", 1, "PARTIAL", 7,
      "2026-08-11T00:00:00Z", "{}",
    );
  const snapshotId = "sha256:" + "a".repeat(64);
  db.prepare(`INSERT INTO ops_ready_snapshots
    VALUES (?,?,?,?,?,?,?,?)`).run(
      snapshotId, "READY", "2026-08-11T00:00:00Z", 7, 42,
      "collection-coverage/v2", "b0+coverage/v2", "sha256:" + "b".repeat(64),
    );
  db.prepare(`INSERT INTO ops_snapshot_quality VALUES (?,?,?,?,?)`).run(
    snapshotId, "PASS", "b0+coverage/v2", "2026-08-11T00:00:00Z", "{}",
  );
  db.prepare(`INSERT INTO ops_b0_status VALUES (?,?,?,?,?,?)`).run(
    1, "PASS", "b0+coverage/v2", "2026-08-11T00:00:00Z", "{}", "build-1",
  );

  const coverage = await callOpsTool(d1(db), "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(coverage.status, "UNKNOWN");
  assert.equal(coverage.coverage, null);
  assert.equal(coverage.last_known_good.status, "PARTIAL");
  // Live projection remains collection-coverage/v2 (STALE). Do not pretend V3 is published.
  assert.equal(coverage.last_known_good.policy_version, "collection-coverage/v2");
  assert.match(coverage.reason, /policy_version collection-coverage\/v2/);
  assert.doesNotMatch(coverage.reason, /Coverage V2/);
  const segments = await callOpsTool(d1(db), "coverage_segments", {
    dataset: "jsda_otc_bond_reference_prices", limit: 200,
  });
  assert.equal(segments.segments.length, 1);
  assert.equal(segments.segments[0].policy_version, "collection-coverage/v2");
  const quality = await callOpsTool(d1(db), "snapshot_quality", { snapshot_id: snapshotId });
  assert.equal(quality.quality.status, "PASS");
  const b0 = await callOpsTool(d1(db), "b0_status", {});
  assert.equal(b0.status, "PASS");
  db.close();
});

test("durable quota migration enforces the conditional upsert on real SQLite", async () => {
  const db = new DatabaseSync(":memory:");
  db.exec(quotaMigration);
  const quota = new DurableDailyQuota(d1(db), 2);
  const principal = { subject: "human:alice", clientId: "grant-1" };
  assert.equal((await quota.charge(principal, 2, Date.parse("2026-08-11T12:00:00Z"))).used, 2);
  await assert.rejects(
    quota.charge(principal, 1, Date.parse("2026-08-11T12:01:00Z")),
    QuotaExceeded,
  );
  db.close();
});

test("Ops queries run against the complete ingestion D1 migration sequence", async () => {
  const db = new DatabaseSync(":memory:");
  for (const migration of ingestionMigrations) db.exec(migration);
  db.exec(projectionMigration);
  db.exec(quotaMigration);
  db.prepare(`INSERT INTO ingestion_run_log
    (ran_at,source,runtime,status,detail) VALUES (?,?,?,?,?)`).run(
      "2026-08-11T00:00:00Z", "jquants", "worker", "pass", "{}",
    );
  const runId = Number(db.prepare("SELECT MAX(id) AS id FROM ingestion_run_log").get().id);
  db.prepare(`INSERT INTO ingestion_validation
    (run_id,dataset,started_at,finished_at,status,rows_seen,rows_inserted,
     rows_revisions,available_at_min,available_at_max,detail)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)`).run(
      runId, "equities_bars_daily", "2026-08-11T00:00:00Z",
      "2026-08-11T00:01:00Z", "pass", 1, 1, 0,
      "2026-08-10T06:30:00Z", "2026-08-10T06:30:00Z", "{}",
    );
  db.prepare(`INSERT INTO ingestion_watermarks
    (dataset,last_event_date,last_ingested_at,last_export_cursor)
    VALUES (?,?,?,?)`).run(
      "equities_bars_daily", "2026-08-10", "2026-08-11T00:00:00Z", 7,
    );
  db.prepare(`INSERT INTO raw_retention_manifests
    (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,data_digest,
     completeness,created_at) VALUES (?,?,?,?,?,?,?,?,?)`).run(
      "equities_bars_daily", runId, "raw/jq/manifest.json", 1, 1, 10,
      "sha256:test", "COMPLETE", "2026-08-11T00:00:00Z",
    );

  const validation = await callOpsTool(d1(db), "validation_summary", {});
  assert.equal(validation.status, "PASS");
  const raw = await callOpsTool(d1(db), "raw_retention_status", {
    dataset: "equities_bars_daily",
  });
  assert.equal(raw.attestations.length, 1);
  const sync = await callOpsTool(d1(db), "sync_status", {});
  assert.equal(sync.watermarks.length, 1);
  assert.equal(sync.latest_change_seq, null);
  assert.equal(raw.totals.total, 1);
  assert.equal(raw.totals.acquired, 1);
  assert.equal(raw.totals.complete, undefined);
  assert.equal(raw.attestations[0].acquisition_state, "EXPECTED_AND_CAPTURED");
  assert.equal(raw.attestations[0].completeness, "COMPLETE");
  assert.match(raw.note, /not dataset Coverage COMPLETE/);
  const ops = await callOpsTool(d1(db), "ops_status", {});
  assert.equal(ops.raw_retention.manifests, 1);
  assert.equal(ops.raw_retention.acquired, 1);
  assert.equal(ops.raw_retention.complete, undefined);
  db.close();
});

test("applied_feed_cursor is null until ops_applied_pins has a non-null seq", async () => {
  const db = new DatabaseSync(":memory:");
  const sync = await callOpsTool(d1(db), "sync_status", {});
  assert.equal(sync.applied_feed_cursor, null);
  db.close();
});

test("applied_cursor null is never CURRENT even when export lag is 0", () => {
  assert.equal(
    syncDatasetState({ exported: 10, applied: null, lag: 0, changeLogRows: 1 }),
    "EXPORT_CURRENT_APPLY_UNPINNED",
  );
  assert.equal(
    syncDatasetState({ exported: 10, applied: 10, lag: 0, changeLogRows: 1 }),
    "CURRENT",
  );
});

function seedSyncPlane(db, { exported, latest, applied }) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS ingestion_watermarks (
      dataset TEXT PRIMARY KEY,
      last_event_date TEXT,
      last_ingested_at TEXT NOT NULL,
      last_export_cursor INTEGER
    );
    CREATE TABLE IF NOT EXISTS ingestion_change_log (
      change_seq INTEGER PRIMARY KEY AUTOINCREMENT,
      table_name TEXT NOT NULL,
      source TEXT NOT NULL,
      dataset TEXT NOT NULL,
      natural_key TEXT NOT NULL,
      event_time TEXT NOT NULL,
      available_at TEXT NOT NULL,
      ingested_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      raw_payload TEXT,
      changed_at TEXT NOT NULL
    );
  `);
  db.exec(appliedPinsMigration);
  db.prepare(`INSERT INTO ingestion_watermarks
    (dataset, last_event_date, last_ingested_at, last_export_cursor)
    VALUES (?,?,?,?)`).run(
      "equities_bars_daily", "2026-08-10", "2026-08-11T00:00:00Z", exported,
    );
  db.prepare(`INSERT INTO ingestion_change_log
    (change_seq, table_name, source, dataset, natural_key, event_time,
     available_at, ingested_at, payload, changed_at)
    VALUES (?,?,?,?,?,?,?,?,?,?)`).run(
      latest, "jquants_records", "jquants", "equities_bars_daily", "nk",
      "2026-08-10", "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z", "{}",
      "2026-08-11T00:00:00Z",
    );
  db.prepare(`INSERT INTO ops_applied_pins
    (feed, last_applied_change_seq, updated_at, projected_at, projection_generation_id)
    VALUES (?,?,?,?,?)`).run(
      "jquants_records", applied, "2026-08-12T00:00:00Z", "2026-08-12T00:00:00Z", null,
    );
}

test("matching applied pin with export lag 0 is CURRENT", async () => {
  const db = new DatabaseSync(":memory:");
  seedSyncPlane(db, { exported: 10, latest: 10, applied: 10 });
  const sync = await callOpsTool(d1(db), "sync_status", {});
  assert.equal(sync.applied_feed_cursor, 10);
  assert.equal(sync.datasets.length, 1);
  assert.equal(sync.datasets[0].applied_cursor, 10);
  assert.equal(sync.datasets[0].exported_cursor, 10);
  assert.equal(sync.datasets[0].lag, 0);
  assert.equal(sync.datasets[0].state, "CURRENT");
  db.close();
});

test("applied pin with export lag greater than 0 is not CURRENT", async () => {
  const db = new DatabaseSync(":memory:");
  seedSyncPlane(db, { exported: 10, latest: 20, applied: 10 });
  const sync = await callOpsTool(d1(db), "sync_status", {});
  assert.equal(sync.applied_feed_cursor, 10);
  assert.equal(sync.datasets[0].applied_cursor, 10);
  assert.equal(sync.datasets[0].lag, 10);
  assert.notEqual(sync.datasets[0].state, "CURRENT");
  assert.equal(sync.datasets[0].state, "LAGGING");
  db.close();
});

test("ops_applied_pins NULL seq is unpinned not CURRENT", async () => {
  const db = new DatabaseSync(":memory:");
  seedSyncPlane(db, { exported: 10, latest: 10, applied: null });
  const sync = await callOpsTool(d1(db), "sync_status", {});
  assert.equal(sync.applied_feed_cursor, null);
  assert.equal(sync.datasets[0].applied_cursor, null);
  assert.equal(sync.datasets[0].lag, 0);
  assert.equal(sync.datasets[0].state, "EXPORT_CURRENT_APPLY_UNPINNED");
  db.close();
});

function insertCoverageRow(db, dataset, status, generationId = null) {
  const columns = [
    "dataset", "status", "policy_version", "collection_scope",
    "history_target_start", "history_target_end_rule", "coverage_mode",
    "expected_frequency", "universe_rule", "raw_retention_required",
    "structured_reconciliation_required", "governance_tier",
    "observed_start", "observed_end", "row_count", "source_run_id",
    "evaluated_at", "detail_json",
  ];
  const values = [
    dataset, status, "collection-coverage/v2", "jsda", "2002-08-02", "current",
    "official_archive_index_reconciled", "official_archive_day", "official_index",
    1, 1, "governed", "2002-08-02", "2002-08-02", 1, 7, "2026-08-11T00:00:00Z", "{}",
  ];
  if (generationId != null) {
    columns.push("projection_generation_id");
    values.push(generationId);
  }
  const placeholders = columns.map(() => "?").join(",");
  db.prepare(
    `INSERT INTO dataset_coverage (${columns.join(",")}) VALUES (${placeholders})`,
  ).run(...values);
}

test("COMPLETE coverage without active generation is UNKNOWN not COMPLETE", async () => {
  const db = new DatabaseSync(":memory:");
  db.exec(projectionMigration);
  insertCoverageRow(db, "jsda_otc_bond_reference_prices", "COMPLETE");
  const coverage = await callOpsTool(d1(db), "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(coverage.status, "UNKNOWN");
  assert.equal(coverage.coverage, null);
  assert.equal(coverage.last_known_good.status, "COMPLETE");
  assert.equal(coverage.last_known_good.policy_version, "collection-coverage/v2");
  assert.match(coverage.reason, /last-known-good is not current COMPLETE/);
  assert.match(coverage.reason, /policy_version collection-coverage\/v2/);
  assert.doesNotMatch(coverage.reason, /Coverage V2/);

  const gaps = await callOpsTool(d1(db), "coverage_gaps", {});
  assert.equal(gaps.status, "UNKNOWN");
  assert.equal(gaps.gaps.length, GOVERNED_DATASETS.length);
  assert.ok(gaps.gaps.every((row) => row.status !== "COMPLETE"));
  const otc = gaps.gaps.find((row) => row.dataset === "jsda_otc_bond_reference_prices");
  assert.equal(otc.status, "UNKNOWN");
  assert.equal(otc.reason, "Coverage projection has not been populated");

  const endpoint = await callOpsTool(d1(db), "endpoint_status", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(endpoint.coverage.status, "UNKNOWN");
  assert.equal(endpoint.coverage.last_known_good.status, "COMPLETE");
  assert.equal(endpoint.coverage.last_known_good.policy_version, "collection-coverage/v2");
  assert.match(endpoint.coverage.reason, /policy_version collection-coverage\/v2/);
  db.close();
});

test("active generation COMPLETE is current coverage COMPLETE", async () => {
  const db = new DatabaseSync(":memory:");
  db.exec(projectionMigration);
  db.exec(inventoryMigration);
  db.exec(generationMigration);
  const gen = "projgen-active";
  db.prepare(`INSERT INTO ops_projection_generation
    (generation_id, status, generated_at, detail_json) VALUES (?,?,?,?)`).run(
      gen, "ACTIVE", "2026-08-11T00:00:00Z", "{}",
    );
  db.prepare(`INSERT INTO ops_projection_active
    (singleton, generation_id, activated_at) VALUES (?,?,?)`).run(
      1, gen, "2026-08-11T00:00:00Z",
    );
  insertCoverageRow(db, "jsda_otc_bond_reference_prices", "COMPLETE", gen);
  const coverage = await callOpsTool(d1(db), "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(coverage.status, "COMPLETE");
  assert.equal(coverage.coverage.status, "COMPLETE");
  assert.equal(coverage.coverage.policy_version, "collection-coverage/v2");
  assert.equal(coverage.active_generation, gen);

  const endpoint = await callOpsTool(d1(db), "endpoint_status", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(endpoint.coverage.status, "COMPLETE");
  db.close();
});

test("raw zero-row complete is empty-with-evidence not coverage complete", () => {
  assert.equal(
    classifyRawAcquisition({ completeness: "COMPLETE", row_count: 0, raw_bytes: 12 }),
    "EXPECTED_EMPTY_WITH_EVIDENCE",
  );
  assert.equal(
    classifyRawAcquisition({ completeness: "ACQUIRED", row_count: 0, raw_bytes: 12 }),
    "EXPECTED_EMPTY_WITH_EVIDENCE",
  );
  assert.equal(
    JSDA_UPSTREAM_LOCATORS.jsda_otc_bond_reference_prices.includes("market.jsda.or.jp"),
    true,
  );
});

test("raw ACQUIRED is captured like legacy COMPLETE and is not Coverage COMPLETE", async () => {
  assert.equal(
    classifyRawAcquisition({ completeness: "ACQUIRED", row_count: 4, raw_bytes: 40 }),
    "EXPECTED_AND_CAPTURED",
  );
  assert.equal(
    classifyRawAcquisition({ completeness: "ACQUIRED", row_count: 0, raw_bytes: 0 }),
    "SOURCE_NOT_PUBLISHED",
  );
  assert.equal(
    classifyRawAcquisition({ completeness: "COMPLETE", row_count: 2, raw_bytes: 8 }),
    "EXPECTED_AND_CAPTURED",
  );
  assert.equal(
    classifyRawAcquisition({ completeness: "FAILED", row_count: 0, raw_bytes: 0 }),
    "DOWNLOAD_FAILED",
  );
  assert.equal(
    classifyRawAcquisition({ completeness: "PENDING", row_count: 1, raw_bytes: 8 }),
    "UNVERIFIED",
  );

  const db = new DatabaseSync(":memory:");
  for (const migration of ingestionMigrations) db.exec(migration);
  db.prepare(`INSERT INTO ingestion_run_log
    (ran_at,source,runtime,status,detail) VALUES (?,?,?,?,?)`).run(
      "2026-08-23T00:00:00Z", "jquants", "worker", "pass", "{}",
    );
  const insert = db.prepare(`INSERT INTO raw_retention_manifests
    (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,data_digest,
     completeness,created_at) VALUES (?,?,?,?,?,?,?,?,?)`);
  insert.run(
    "equities_bars_daily", 1, "raw/a.json", 1, 4, 20,
    "sha256:a", "ACQUIRED", "2026-08-23T00:00:00Z",
  );
  insert.run(
    "equities_bars_daily", 2, "raw/b.json", 1, 0, 12,
    "sha256:b", "COMPLETE", "2026-08-21T00:00:00Z",
  );
  insert.run(
    "equities_bars_daily", 3, "raw/c.json", 1, 0, 0,
    "sha256:c", "FAILED", "2026-08-20T00:00:00Z",
  );

  const raw = await callOpsTool(d1(db), "raw_retention_status", {
    dataset: "equities_bars_daily",
  });
  assert.equal(raw.totals.total, 3);
  assert.equal(raw.totals.acquired, 2);
  assert.equal(raw.totals.failed, 1);
  assert.equal(raw.totals.incomplete, 1);
  assert.equal(raw.totals.complete, undefined);
  assert.doesNotMatch(JSON.stringify(raw.totals), /Coverage COMPLETE/);
  assert.match(raw.note, /not dataset Coverage COMPLETE/);
  assert.doesNotMatch(raw.note, /Coverage COMPLETE is/);
  const byRun = Object.fromEntries(
    raw.attestations.map((row) => [Number(row.run_id), row]),
  );
  assert.equal(byRun[1].acquisition_state, "EXPECTED_AND_CAPTURED");
  assert.equal(byRun[1].completeness, "ACQUIRED");
  assert.equal(byRun[2].acquisition_state, "EXPECTED_EMPTY_WITH_EVIDENCE");
  assert.equal(byRun[2].completeness, "COMPLETE");
  assert.equal(byRun[3].acquisition_state, "DOWNLOAD_FAILED");
  assert.equal(Number(raw.oldest_unresolved.run_id), 3);
  assert.equal(raw.oldest_unresolved.completeness, "FAILED");

  const ops = await callOpsTool(d1(db), "ops_status", {});
  assert.equal(ops.raw_retention.manifests, 3);
  assert.equal(ops.raw_retention.acquired, 2);
  assert.equal(ops.raw_retention.complete, undefined);
  assert.doesNotMatch(JSON.stringify(ops.raw_retention), /Coverage COMPLETE/);
  db.close();
});

test("honestProjectionStatus: FRESH requires refresh_status success", () => {
  const now = Date.parse("2026-08-21T13:00:00Z");
  const recent = "2026-08-21T12:30:49.152421+00:00";
  const skipped = honestProjectionStatus({
    generated_at: recent,
    status: "FRESH",
    detail_json: '{"refresh_status":null}',
  }, now);
  assert.equal(skipped.status, "STALE");
  assert.equal(skipped.refreshAttempt, false);
  assert.equal(skipped.refreshOk, false);

  const failed = honestProjectionStatus({
    generated_at: recent,
    status: "FRESH",
    detail_json: '{"refresh_status":"failed"}',
  }, now);
  assert.equal(failed.status, "DEGRADED_REFRESH_FAILED");
  assert.equal(failed.refreshAttempt, true);
  assert.equal(failed.refreshOk, false);

  const ok = honestProjectionStatus({
    generated_at: recent,
    status: "FRESH",
    detail_json: '{"refresh_status":"success"}',
  }, now);
  assert.equal(ok.status, "FRESH");
  assert.equal(ok.refreshOk, true);

  const aged = honestProjectionStatus({
    generated_at: "2026-08-21T12:30:49.152421+00:00",
    status: "FRESH",
    detail_json: '{"refresh_status":"success"}',
  }, Date.parse("2026-08-23T14:00:00Z"));
  assert.equal(aged.status, "STALE");
  assert.equal(aged.refreshOk, true);
});

async function seedProjectionMeta(db, { generatedAt, status, detail, gen }) {
  db.exec(projectionMigration);
  db.exec(inventoryMigration);
  db.exec(generationMigration);
  db.prepare(`INSERT INTO ops_projection_metadata
    (generated_at, source_generation, age_seconds, status, projection_version,
     detail_json, projection_generation_id)
    VALUES (?,?,?,?,?,?,?)`).run(
    generatedAt, generatedAt, 0, status, "ops_projection/v3", detail, gen,
  );
  db.prepare(`INSERT INTO ops_projection_generation
    (generation_id, status, generated_at, detail_json) VALUES (?,?,?,?)`).run(
    gen, "ACTIVE", generatedAt, "{}",
  );
  db.prepare(`INSERT INTO ops_projection_active
    (singleton, generation_id, activated_at) VALUES (?,?,?)`).run(
    1, gen, generatedAt,
  );
}

test("projection_status does not report FRESH when refresh_success is false", async () => {
  const db = new DatabaseSync(":memory:");
  const generatedAt = new Date().toISOString();
  await seedProjectionMeta(db, {
    generatedAt,
    status: "FRESH",
    detail: JSON.stringify({ refresh_status: null }),
    gen: "projgen-ef18b4f86ee946048161d25e2a30a2a8",
  });
  const result = await callOpsTool(d1(db), "projection_status", {});
  assert.equal(result.projection_status, "STALE");
  assert.equal(result.stale, true);
  assert.equal(result.stages.refresh_attempt, false);
  assert.equal(result.stages.refresh_success, false);
  assert.equal(result.last_known_good.not_fresh, true);
  db.close();
});

test("live stored FRESH + null refresh_status + age>86400 never CURRENT/FRESH", async () => {
  const db = new DatabaseSync(":memory:");
  await seedProjectionMeta(db, {
    generatedAt: "2026-08-21T12:30:49.152421+00:00",
    status: "FRESH",
    detail: JSON.stringify({ refresh_status: null }),
    gen: "projgen-ef18b4f86ee946048161d25e2a30a2a8",
  });
  const result = await callOpsTool(d1(db), "projection_status", {});
  assert.equal(result.projection_status, "STALE");
  assert.notEqual(result.projection_status, "FRESH");
  assert.equal(result.stale, true);
  assert.equal(result.stages.refresh_success, false);
  assert.equal(result.last_known_good.not_fresh, true);
  db.close();
});

test("projection_status FRESH only when refresh_status is success and age is fresh", async () => {
  const db = new DatabaseSync(":memory:");
  const generatedAt = new Date().toISOString();
  await seedProjectionMeta(db, {
    generatedAt,
    status: "FRESH",
    detail: JSON.stringify({ refresh_status: "success" }),
    gen: "projgen-success",
  });
  const result = await callOpsTool(d1(db), "projection_status", {});
  assert.equal(result.projection_status, "FRESH");
  assert.equal(result.stale, false);
  assert.equal(result.stages.refresh_attempt, true);
  assert.equal(result.stages.refresh_success, true);
  db.close();
});
