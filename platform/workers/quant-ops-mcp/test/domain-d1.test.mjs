import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import {
  callOpsTool,
  classifyRawAcquisition,
  JSDA_UPSTREAM_LOCATORS,
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
const quotaMigration = readFileSync(
  new URL("../migrations/0001_remote_daily_quota.sql", import.meta.url), "utf8",
);
const ingestionMigrations = [
  "0001_init.sql", "0002_watermarks.sql", "0003_change_feed.sql",
  "0004_revision_identity_v2.sql", "0005_natural_keys_v2.sql",
  "0006_raw_retention_manifests.sql", "0007_collection_coverage_v2.sql",
].map((name) => readFileSync(
  new URL(`../../ingestion-premium/migrations/${name}`, import.meta.url), "utf8",
));

test("absent Coverage projection is UNKNOWN with all JQ and JSDA gaps", async () => {
  const db = new DatabaseSync(":memory:");
  const result = await callOpsTool(d1(db), "coverage_gaps", {});
  assert.equal(result.status, "UNKNOWN");
  assert.equal(result.gaps.length, GOVERNED_DATASETS.length);
  assert.ok(result.gaps.some((row) => row.dataset === "jsda_otc_bond_reference_prices"));
  assert.ok(result.gaps.some((row) => row.dataset === "jsda_tokyo_repo_rates"));
  assert.ok(result.gaps.some((row) => row.dataset === "jsda_corporate_bond_transactions"));
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
  assert.equal(coverage.status, "PARTIAL");
  const segments = await callOpsTool(d1(db), "coverage_segments", {
    dataset: "jsda_otc_bond_reference_prices", limit: 200,
  });
  assert.equal(segments.segments.length, 1);
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
  assert.equal(raw.attestations[0].acquisition_state, "EXPECTED_AND_CAPTURED");
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

test("raw zero-row complete is empty-with-evidence not coverage complete", () => {
  assert.equal(
    classifyRawAcquisition({ completeness: "COMPLETE", row_count: 0, raw_bytes: 12 }),
    "EXPECTED_EMPTY_WITH_EVIDENCE",
  );
  assert.equal(
    JSDA_UPSTREAM_LOCATORS.jsda_otc_bond_reference_prices.includes("market.jsda.or.jp"),
    true,
  );
});
