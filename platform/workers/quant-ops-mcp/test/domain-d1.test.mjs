import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { callOpsTool, OPS_TOOLS } from "../src/domain.js";
import { classifyRawAcquisition, honestProjectionStatus, syncDatasetState } from "../src/domain_policy.js";
import {
  PROJECTED_CONTENT_TABLES,
  projectedManifestDigest,
  projectedTableContent,
} from "../src/projection_content.js";
import { canonicalProjectionBytes, projectionSha256 } from "../src/projection_signature.js";
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

function signedGeneration(generation, now, contentManifest, contentDigest) {
  const digest = (character) => `sha256:${character.repeat(64)}`;
  const envelope = {
    schema_version: "ops-projection-envelope/v1",
    generation_id: generation,
    content_digest: contentDigest,
    source_db_digest: digest("2"),
    generated_at: now,
    producer_commit_sha: "a".repeat(40),
    contract_digest: digest("3"),
    registry_digest: digest("4"),
    coverage_policy_version: "collection-coverage/v3",
    coverage_policy_digest: digest("8"),
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
    content_manifest: contentManifest,
    row_counts: Object.fromEntries(
      Object.entries(contentManifest).map(([table, row]) => [table, row.row_count]),
    ),
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

async function seedGeneration(
  db,
  generation,
  {
    active = true,
    status = "FRESH",
    populate = null,
    sync = {},
    signing = true,
    afterManifest = null,
    documentTransform = null,
    contentDigestOverride = null,
  } = {},
) {
  const now = new Date().toISOString();
  db.prepare(`INSERT INTO ops_projection_generation
    (generation_id,status,source_db_digest,content_digest,generated_at,
     producer_commit_sha,contract_digest,registry_digest,coverage_policy_version,
     sealed_at,signed_envelope_json,issuer_key_id,signature,detail_json)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      generation, "OPEN", `sha256:${"0".repeat(64)}`,
      `sha256:${"0".repeat(64)}`, now, "a".repeat(40),
      `sha256:${"0".repeat(64)}`, `sha256:${"0".repeat(64)}`,
      "collection-coverage/v3", null, null, null, null, "{}",
    );
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
    VALUES (?,'jquants_records',?,?,?,?,?)`).run(
      generation,
      sync.source === undefined ? 10 : sync.source,
      sync.changeLogRows === undefined ? 1 : sync.changeLogRows,
      sync.exported === undefined ? 10 : sync.exported,
      sync.applied === undefined ? 10 : sync.applied,
      now,
    );
  db.prepare(`INSERT INTO ops_storage_plane_status
    (projection_generation_id,materialized_at,payload_json) VALUES (?,?,?)`).run(
      generation, now,
      JSON.stringify({ schema: "ops_storage_plane_status/v1", counts: { facts: 12 } }),
    );
  if (populate) populate(db, generation, now);

  const contentManifest = {};
  for (const table of PROJECTED_CONTENT_TABLES) {
    contentManifest[table] = await projectedTableContent(d1(db), generation, table);
  }
  const contentDigest = await projectedManifestDigest(contentManifest);
  if (afterManifest) afterManifest(db, generation, now);
  const signed = signedGeneration(
    generation,
    now,
    contentManifest,
    contentDigestOverride || contentDigest,
  );
  const storedDocument = documentTransform
    ? documentTransform(structuredClone(signed.document))
    : signed.document;
  db.prepare(`UPDATE ops_projection_generation
    SET source_db_digest=?,content_digest=?,producer_commit_sha=?,contract_digest=?,
        registry_digest=?,coverage_policy_version=?,signed_envelope_json=?,
        issuer_key_id=?,signature=?
    WHERE generation_id=? AND status='OPEN'`).run(
      signed.envelope.source_db_digest, signed.envelope.content_digest,
      signed.envelope.producer_commit_sha, signed.envelope.contract_digest,
      signed.envelope.registry_digest, signed.envelope.coverage_policy_version,
      signing ? JSON.stringify(storedDocument) : null,
      signing ? projectionKeyId : null,
      signing ? signed.signature : null,
      generation,
    );
  db.prepare(`UPDATE ops_projection_generation SET status='SEALED',sealed_at=?
    WHERE generation_id=? AND status='OPEN'`).run(now, generation);
  if (active) {
    db.prepare(`INSERT INTO ops_projection_active
      (singleton,generation_id,activated_at) VALUES (1,?,?)
      ON CONFLICT(singleton) DO UPDATE SET
        generation_id=excluded.generation_id,activated_at=excluded.activated_at`).run(
          generation, now,
        );
  }
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

test("content hashing matches Python for D1 numbers and non-ASCII text", async () => {
  const digest = await projectionSha256({
    rows: [{
      projection_generation_id: "g",
      dataset_id: "日本株",
      research_eligible: 1,
      enabled: 0,
      weight: 1,
      note: "東京",
    }],
  });
  assert.equal(
    digest,
    "sha256:76195ac60aedf9a62db147dd1c8914282617553423c5d0fb918627447aac7d61",
  );
});

test("all seventeen tool results stay inside their closed output schema", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-output-contract");
  const argsByName = {
    endpoint_status: { dataset: "equities_bars_daily" },
    dataset_coverage: { dataset: "equities_bars_daily" },
  };
  for (const tool of OPS_TOOLS) {
    const value = await opsCall(db, tool.name, argsByName[tool.name] || {});
    const allowed = new Set(Object.keys(tool.outputSchema.properties));
    assert.deepEqual(
      Object.keys(value).filter((key) => !allowed.has(key)),
      [],
      tool.name,
    );
    for (const required of tool.outputSchema.required) {
      assert.ok(Object.hasOwn(value, required), `${tool.name}.${required}`);
    }
  }
  db.close();
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
  await seedGeneration(db, "projgen-staging", {
    active: false,
    populate: (target, generation) => insertCoverage(
      target, generation, "jsda_otc_bond_reference_prices", "COMPLETE",
    ),
  });
  const result = await opsCall(db, "dataset_coverage", {
    dataset: "jsda_otc_bond_reference_prices",
  });
  assert.equal(result.status, "NOT_PROJECTED");
  db.close();
});

test("an unsigned or untrusted active generation is NOT_PROJECTED", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-untrusted");
  let result = await callOpsTool(d1(db), "ops_status", {}, {
    projectionPublicKeyRegistry: { schema_version: 1, keys: [] },
  });
  assert.equal(result.status, "NOT_PROJECTED");
  assert.equal(result.projection_generation, "projgen-untrusted");
  assert.match(result.reason, /issuer is not trusted/);
  await seedGeneration(db, "projgen-unsigned", { signing: false });
  result = await opsCall(db, "ops_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.match(result.reason, /generation is unsigned/);
  db.close();
});

test("a tampered signed envelope is NOT_PROJECTED", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-tampered", {
    documentTransform(document) {
      document.envelope.applied_cursor = 9;
      return document;
    },
  });
  const result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.match(result.reason, /signature is invalid/);
  db.close();
});

test("signature-valid manifest with the wrong overall digest is NOT_PROJECTED", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-manifest-unbound", {
    contentDigestOverride: `sha256:${"e".repeat(64)}`,
  });
  const result = await opsCall(db, "storage_plane_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.equal(result.projection_signature_verified, true);
  assert.equal(result.projection_content_verified, false);
  assert.match(result.reason, /content digest does not bind its manifest/);
  db.close();
});

test("signature-valid payload tampering is detected by table rehash", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-content-tampered", {
    afterManifest(target, generation) {
      target.prepare(`UPDATE ops_storage_plane_status
        SET payload_json='{"counts":{"facts":999}}'
        WHERE projection_generation_id=?`).run(generation);
    },
  });
  const result = await opsCall(db, "storage_plane_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.equal(result.projection_signature_verified, true);
  assert.equal(result.projection_content_verified, false);
  assert.match(result.reason, /content mismatch for ops_storage_plane_status/);
  db.close();
});

test("OPEN publication seals pointer-last and freezes every payload table", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-frozen");
  const generation = db.prepare(`SELECT status,sealed_at,signed_envelope_json
    FROM ops_projection_generation WHERE generation_id='projgen-frozen'`).get();
  assert.equal(generation.status, "SEALED");
  assert.equal(typeof generation.sealed_at, "string");
  const envelope = JSON.parse(generation.signed_envelope_json).envelope;
  assert.equal(
    envelope.content_manifest.ops_projection_metadata.row_count,
    1,
    "metadata participates in the non-recursive content manifest",
  );
  assert.deepEqual(
    Object.keys(envelope.content_manifest).sort(),
    [...PROJECTED_CONTENT_TABLES],
  );
  const triggers = new Set(
    db.prepare(`SELECT name FROM sqlite_master WHERE type='trigger'`).all()
      .map((row) => row.name),
  );
  for (const table of PROJECTED_CONTENT_TABLES) {
    for (const operation of ["insert", "update", "delete"]) {
      assert.ok(triggers.has(`${table}_open_${operation}`), `${table} ${operation}`);
    }
    assert.throws(
      () => db.prepare(`INSERT INTO ${table} (projection_generation_id) VALUES (?)`)
        .run("projgen-frozen"),
      /require an OPEN projection generation/,
      `${table} sealed insert`,
    );
  }
  assert.throws(
    () => db.prepare(`UPDATE ops_storage_plane_status SET payload_json='{}'
      WHERE projection_generation_id='projgen-frozen'`).run(),
    /immutable after projection seal/,
  );
  assert.throws(
    () => db.prepare(`DELETE FROM ops_storage_plane_status
      WHERE projection_generation_id='projgen-frozen'`).run(),
    /immutable after projection seal/,
  );
  assert.throws(
    () => db.prepare(`UPDATE ops_projection_generation SET content_digest=?
      WHERE generation_id='projgen-frozen'`).run(`sha256:${"f".repeat(64)}`),
    /sealed Ops Projection generation is immutable/,
  );
  db.close();
});

test("only the pointer-selected generation is visible", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-old", {
    populate: (target, generation) => insertCoverage(
      target, generation, "jsda_otc_bond_reference_prices", "COMPLETE",
    ),
  });
  await seedGeneration(db, "projgen-current", {
    populate: (target, generation) => insertCoverage(
      target, generation, "jsda_otc_bond_reference_prices", "PARTIAL",
    ),
  });
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
  await seedGeneration(db, "projgen-old", {
    populate: (target, generation) => insertCoverage(
      target, generation, "jsda_otc_bond_reference_prices", "COMPLETE",
    ),
  });
  await seedGeneration(db, "projgen-current");
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
  await seedGeneration(db, "projgen-raw", {
    populate(target, generation, now) {
      target.prepare(`INSERT INTO raw_retention_manifests
        (projection_generation_id,source,dataset,segment_id,run_id,manifest_key,page_count,
         row_count,raw_bytes,data_digest,completeness,created_at,reason)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
          generation, "jquants", "equities_bars_daily", "2026-08", 2, "raw/latest", 1,
          4, 40, "sha256:latest", "ACQUIRED", now,
          "latest authoritative segment receipt",
        );
    },
  });
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
  await seedGeneration(db, "projgen-sync");
  let result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "CURRENT");
  assert.equal(result.source_cursor, 10);
  assert.equal(result.export_cursor, 10);
  assert.equal(result.applied_cursor, 10);
  await seedGeneration(db, "projgen-sync-unpinned", {
    sync: { applied: null },
  });
  result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "UNKNOWN");
  assert.equal(result.applied_cursor, null);
  assert.notEqual(result.state, "CURRENT");
  db.close();
});

test("missing source change-log evidence is NOT_PROJECTED, never zero", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-sync-unproven", {
    sync: { changeLogRows: null },
  });
  const result = await opsCall(db, "sync_status", {});
  assert.equal(result.status, "NOT_PROJECTED");
  assert.equal(result.change_log_row_count, null);
  assert.equal(result.projection_generation, "projgen-sync-unproven");
  assert.match(result.reason, /change-log evidence is absent/);
  db.close();
});

test("aggregate tools identify missing active-generation rows", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-missing-domain-rows");
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
  await seedGeneration(db, "projgen-not-ready");
  const result = await opsCall(db, "latest_ready_snapshot", {});
  assert.equal(result.status, "NOT_READY");
  assert.equal(result.snapshot, null);
  assert.equal(result.projection_generation, "projgen-not-ready");
  db.close();
});

test("storage_plane_status reads the publisher aggregate without ingestion tables", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-storage");
  const result = await opsCall(db, "storage_plane_status", {});
  assert.equal(result.status, "AVAILABLE");
  assert.equal(result.counts.facts, 12);
  assert.equal(result.projection_generation, "projgen-storage");
  assert.equal(result.projection_signature_verified, true);
  assert.equal(result.projection_content_verified, true);
  db.close();
});

test("projection freshness is recomputed and requires refresh success", async () => {
  const db = projectionDb();
  await seedGeneration(db, "projgen-fresh");
  const fresh = await opsCall(db, "projection_status", {});
  assert.equal(fresh.projection_status, "FRESH");
  assert.equal(fresh.stages.refresh_success, true);
  await seedGeneration(db, "projgen-failed", { status: "FAILED" });
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
