import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { callOpsTool, OPS_TOOLS } from "../src/domain.js";
import { classifyRawAcquisition, honestProjectionStatus, syncDatasetState } from "../src/domain_policy.js";
import { canonicalProjectionBytes } from "../src/projection_signature.js";
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
  new URL("../migrations/projection/0001_ops_projection.sql", import.meta.url),
  "utf8",
);
const quotaMigration = readFileSync(
  new URL("../migrations/quota/0001_remote_daily_quota.sql", import.meta.url),
  "utf8",
);

const projectionKeyPair = generateKeyPairSync("ed25519");
const projectionKeyId = "ops-projection-test-v1";
const projectionPublicJwk = projectionKeyPair.publicKey.export({ format: "jwk" });
const projectionPublicRaw = Buffer.from(String(projectionPublicJwk.x), "base64url").toString("base64");
const projectionRegistry = {
  schema_version: 1,
  keys: [{
    key_id: projectionKeyId,
    algorithm: "Ed25519",
    status: "active",
    public_key_base64: projectionPublicRaw,
  }],
};

function signedGeneration(generation, now) {
  const digest = (character) => `sha256:${character.repeat(64)}`;
  const envelope = {
    schema_version: "ops-projection-envelope/v1",
    generation_id: generation,
    content_digest: digest("1"),
    source_db_digest: digest("2"),
    generated_at: now,
    producer_commit_sha: "a".repeat(40),
    contract_digest: digest("3"),
    registry_digest: digest("4"),
    coverage_policy_version: "collection-coverage/v3",
    projection_status: "FRESH",
    source_generation: 10,
    source_snapshot_generation: now,
    source_cursor: 10,
    export_cursor: 10,
    applied_cursor: 10,
    coverage_status_digest: digest("5"),
    dataset_coverage: {},
    b0_status: "UNKNOWN",
    b0_evidence_digest: digest("6"),
    b4_status: "UNKNOWN",
    b4_evidence_digest: digest("7"),
    evidence_digests: { coverage: digest("5") },
    row_counts: { dataset_coverage: 0 },
  };
  const body = {
    schema_version: "ops-projection-signed-envelope/v1",
    algorithm: "Ed25519",
    issuer_key_id: projectionKeyId,
    envelope,
  };
  const signature = "ed25519:" + sign(
    null,
    Buffer.from(canonicalProjectionBytes(body)),
    projectionKeyPair.privateKey,
  ).toString("base64");
  return { envelope, document: { ...body, signature }, signature };
}

function opsCall(db, name, args) {
  return callOpsTool(d1(db), name, args, {
    projectionPublicKeyRegistry: projectionRegistry,
  });
}

function projectionDb() {
  const db = new DatabaseSync(":memory:");
  db.exec(projectionMigration);
  return db;
}

function seedGeneration(db, generation, { active = true, status = "FRESH" } = {}) {
  const now = new Date().toISOString();
  const signed = signedGeneration(generation, now);
  db.prepare(`INSERT INTO ops_projection_generation
    (generation_id,status,source_db_digest,content_digest,generated_at,
     producer_commit_sha,contract_digest,registry_digest,coverage_policy_version,
     sealed_at,signed_envelope_json,issuer_key_id,signature,detail_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      generation, "SEALED", signed.envelope.source_db_digest,
      signed.envelope.content_digest, now, signed.envelope.producer_commit_sha,
      signed.envelope.contract_digest, signed.envelope.registry_digest,
      signed.envelope.coverage_policy_version, now, JSON.stringify(signed.document),
      projectionKeyId, signed.signature, "{}",
    );
  if (active) {
    db.prepare(`INSERT INTO ops_projection_active
      (singleton,generation_id,activated_at) VALUES (1,?,?)
      ON CONFLICT(singleton) DO UPDATE SET
        generation_id=excluded.generation_id,activated_at=excluded.activated_at`).run(
          generation, now,
        );
  }
  db.prepare(`INSERT INTO ops_projection_metadata
    (projection_generation_id,generated_at,source_generation,source_cursor,
     export_cursor,applied_cursor,age_seconds,status,projection_version,
     refresh_attempt_at,refresh_success_at,refresh_error,detail_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      generation, now, now, 10, 10, 10, 0, status, "ops_projection/v4",
      now, status === "FRESH" ? now : null, null,
      JSON.stringify({ refresh_status: status === "FRESH" ? "success" : "failed" }),
    );
  db.prepare(`INSERT INTO ops_ready_state
    (projection_generation_id,status,snapshot_id,reason,evaluated_at)
    VALUES (?, 'NOT_READY', NULL, 'not published', ?)`).run(generation, now);
  db.prepare(`INSERT INTO ops_b0_status
    (projection_generation_id,singleton,status,policy_version,evaluated_at,
     summary_json,results_json,source_build_id)
    VALUES (?,1,'UNKNOWN','not-projected',?,'{}','[]','not-projected')`).run(generation, now);
  db.prepare(`INSERT INTO ops_sync_feed
    (projection_generation_id,feed,latest_source_change_seq,change_log_row_count,
     exported_cursor,applied_cursor,updated_at)
    VALUES (?,'jquants_records',10,1,10,10,?)`).run(generation, now);
  db.prepare(`INSERT INTO ops_storage_plane_status
    (projection_generation_id,materialized_at,payload_json) VALUES (?,?,?)`).run(
      generation, now,
      JSON.stringify({ schema: "ops_storage_plane_status/v1", counts: { facts: 12 } }),
    );
}

function insertCoverage(db, generation, dataset, status = "PARTIAL") {
  db.prepare(`INSERT INTO dataset_coverage
    (projection_generation_id,dataset,status,policy_version,collection_scope,
     history_target_start,history_target_end_rule,coverage_mode,
     expected_frequency,universe_rule,raw_retention_required,
     structured_reconciliation_required,governance_tier,observed_start,
     observed_end,row_count,source_run_id,evaluated_at,detail_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      generation, dataset, status, "collection-coverage/v3", "jsda",
      "2002-08-02", "current", "official_archive_index_reconciled",
      "official_archive_day", "official_index", 1, 1, "governed",
      "2002-08-02", "2026-08-22", 5886, 7, new Date().toISOString(), "{}",
    );
}

test("the public surface remains exactly seventeen read-only tools", () => {
  const names = OPS_TOOLS.map((tool) => tool.name);
  assert.equal(names.length, 17);
  assert.ok(names.includes("storage_plane_status"));
  for (const name of ["ingest", "publish", "delete", "sql", "query_dataset"]) {
    assert.ok(!names.includes(name));
  }
});

test("no active generation is explicit NOT_PROJECTED", async () => {
  const db = projectionDb();
  for (const [name, args] of [
    ["ops_status", {}],
    ["dataset_coverage", { dataset: "jsda_otc_bond_reference_prices" }],
    ["coverage_segments", {}],
    ["storage_plane_status", {}],
    ["sync_status", {}],
    ["latest_ready_snapshot", {}],
  ]) {
    const result = await opsCall(db, name, args);
    assert.equal(result.status, "NOT_PROJECTED", name);
    assert.equal(result.projection_generation, null, name);
    assert.equal(typeof result.reason, "string", name);
  }
  db.close();
});

test("a sealed generation cannot be read without the active pointer", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-staging", { active: false });
  insertCoverage(db, "projgen-staging", "jsda_otc_bond_reference_prices", "COMPLETE");
  const result = await opsCall(db, "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(result.status, "NOT_PROJECTED");
  db.close();
});

test("an unsigned or untrusted active generation is NOT_PROJECTED", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-untrusted");
  let result = await callOpsTool(d1(db), "ops_status", {}, {
    projectionPublicKeyRegistry: { schema_version: 1, keys: [] },
  });
  assert.equal(result.status, "NOT_PROJECTED");
  assert.equal(result.projection_generation, "projgen-untrusted");
  assert.match(result.reason, /issuer is not trusted/);
  db.prepare(`UPDATE ops_projection_generation
    SET signed_envelope_json=NULL,issuer_key_id=NULL,signature=NULL
    WHERE generation_id='projgen-untrusted'`).run();
  result = await opsCall(db, "ops_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.match(result.reason, /generation is unsigned/);
  db.close();
});

test("a tampered signed envelope is NOT_PROJECTED", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-tampered");
  const row = db.prepare(`SELECT signed_envelope_json FROM ops_projection_generation
    WHERE generation_id='projgen-tampered'`).get();
  const document = JSON.parse(row.signed_envelope_json);
  document.envelope.applied_cursor = 9;
  db.prepare(`UPDATE ops_projection_generation SET signed_envelope_json=?
    WHERE generation_id='projgen-tampered'`).run(JSON.stringify(document));
  const result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.match(result.reason, /signature is invalid/);
  db.close();
});

test("only the pointer-selected generation is visible", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-old");
  insertCoverage(db, "projgen-old", "jsda_otc_bond_reference_prices", "COMPLETE");
  seedGeneration(db, "projgen-current");
  insertCoverage(db, "projgen-current", "jsda_otc_bond_reference_prices", "PARTIAL");
  const coverage = await opsCall(db, "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(coverage.status, "PARTIAL");
  assert.equal(coverage.projection_generation, "projgen-current");
  assert.equal(coverage.coverage.policy_version, "collection-coverage/v3");
  db.close();
});

test("a missing active Coverage row never falls back to an older generation", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-old");
  insertCoverage(db, "projgen-old", "jsda_otc_bond_reference_prices", "COMPLETE");
  seedGeneration(db, "projgen-current");
  const result = await opsCall(db, "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(result.status, "NOT_PROJECTED");
  assert.equal(result.coverage, null);
  assert.equal(result.projection_generation, "projgen-current");
  assert.equal(Object.hasOwn(result, "last_known_good"), false);
  db.close();
});

test("raw status exposes one authoritative segment row and no historical attempts", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-raw");
  db.prepare(`INSERT INTO raw_retention_manifests
    (projection_generation_id,source,dataset,segment_id,run_id,manifest_key,page_count,
     row_count,raw_bytes,data_digest,completeness,created_at,reason)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      "projgen-raw", "jquants", "equities_bars_daily", "2026-08", 2, "raw/latest", 1,
      4, 40, "sha256:latest", "ACQUIRED", new Date().toISOString(),
      "latest authoritative segment receipt",
    );
  const result = await opsCall(db, "raw_retention_status", {
    dataset: "equities_bars_daily",
  });
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.totals.total_segments, 1);
  assert.equal(result.totals.acquired_segments, 1);
  assert.equal(result.attestations[0].run_id, 2);
  assert.equal(result.attestations[0].source, "jquants");
  assert.equal(result.attestations[0].acquisition_state, "EXPECTED_AND_CAPTURED");
  db.close();
});

test("raw acquisition labels remain separate from Dataset COMPLETE", () => {
  assert.equal(
    classifyRawAcquisition({ completeness: "ACQUIRED", row_count: 4, raw_bytes: 40 }),
    "EXPECTED_AND_CAPTURED",
  );
  assert.equal(
    classifyRawAcquisition({ completeness: "FAILED", row_count: 0, raw_bytes: 0 }),
    "DOWNLOAD_FAILED",
  );
});

test("sync status requires non-null equal source/export/applied cursors", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-sync");
  let result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "CURRENT");
  assert.equal(result.source_cursor, 10);
  assert.equal(result.export_cursor, 10);
  assert.equal(result.applied_cursor, 10);
  db.prepare(`UPDATE ops_sync_feed SET applied_cursor=NULL
    WHERE projection_generation_id='projgen-sync'`).run();
  result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "UNKNOWN");
  assert.equal(result.applied_cursor, null);
  assert.notEqual(result.state, "CURRENT");
  db.close();
});

test("missing source change-log evidence is NOT_PROJECTED, never zero", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-sync-unproven");
  db.prepare(`UPDATE ops_sync_feed SET change_log_row_count=NULL
    WHERE projection_generation_id='projgen-sync-unproven'`).run();
  const result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.equal(result.change_log_row_count, null);
  assert.equal(result.projection_generation, "projgen-sync-unproven");
  assert.match(result.reason, /change-log evidence is absent/);
  db.close();
});

test("aggregate tools identify missing active-generation rows", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-missing-domain-rows");
  const coverage = await opsCall(db, "coverage_gaps", {});
  assert.equal(coverage.status, "NOT_PROJECTED");
  assert.match(coverage.reason, /Coverage rows are absent/);
  const backfill = await opsCall(db, "backfill_status", {
    dataset: "equities_bars_daily",
  });
  assert.equal(backfill.status, "NOT_PROJECTED");
  assert.match(backfill.reason, /segment plans are absent/);
  const summary = await opsCall(db, "ops_status", {});
  assert.equal(summary.status, "NOT_PROJECTED");
  assert.match(summary.reason, /Coverage summary is absent/);
  db.close();
});

test("cursor policy never makes a null apply pin current", () => {
  assert.equal(
    syncDatasetState({ exported: 10, applied: null, lag: 0, changeLogRows: 1 }),
    "EXPORT_CURRENT_APPLY_UNPINNED",
  );
  assert.equal(
    syncDatasetState({ exported: 10, applied: 10, lag: 0, changeLogRows: 1 }),
    "CURRENT",
  );
});

test("NOT_READY is an explicit projected state rather than a missing default", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-not-ready");
  const result = await opsCall(db, "latest_ready_snapshot", {});
  assert.equal(result.status, "NOT_READY");
  assert.equal(result.snapshot, null);
  assert.equal(result.projection_generation, "projgen-not-ready");
  db.close();
});

test("storage_plane_status reads the publisher aggregate without ingestion tables", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-storage");
  const result = await opsCall(db, "storage_plane_status", {});
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.counts.facts, 12);
  assert.equal(result.projection_generation, "projgen-storage");
  db.close();
});

test("projection freshness is recomputed and requires refresh success", async () => {
  const db = projectionDb();
  seedGeneration(db, "projgen-fresh");
  const fresh = await opsCall(db, "projection_status", {});
  assert.equal(fresh.projection_status, "FRESH");
  assert.equal(fresh.stages.refresh_success, true);
  db.prepare(`UPDATE ops_projection_metadata
    SET detail_json='{"refresh_status":"failed"}', status='FAILED'
    WHERE projection_generation_id='projgen-fresh'`).run();
  const failed = await opsCall(db, "projection_status", {});
  assert.notEqual(failed.projection_status, "FRESH");
  assert.equal(failed.stages.refresh_success, false);
  db.close();
});

test("honestProjectionStatus rejects stored FRESH without successful refresh", () => {
  const now = Date.now();
  const result = honestProjectionStatus({
    generated_at: new Date(now).toISOString(),
    status: "FRESH",
    detail_json: '{"refresh_status":null}',
  }, now);
  assert.equal(result.status, "STALE");
});

test("quota remains isolated in its own migration and database", async () => {
  const db = new DatabaseSync(":memory:");
  db.exec(quotaMigration);
  const quota = new DurableDailyQuota(d1(db), 2);
  const principal = { subject: "human:alice", clientId: "grant-1" };
  assert.equal((await quota.charge(principal, 2, Date.parse("2026-08-25T00:00:00Z"))).used, 2);
  await assert.rejects(
    quota.charge(principal, 1, Date.parse("2026-08-25T00:01:00Z")),
    QuotaExceeded,
  );
  db.close();
});
