import { describe, expect, it } from "vitest";

import {
  CONTROLLED_COVERAGE_POLICY_ROWS,
  OPS_PROJECTION_D1_IDENTITIES,
} from "./controlled_pilot_registry_raw.generated";
import {
  EXACT_FOUR_COVERAGE_POLICY_DIGEST,
  EXACT_FOUR_COVERAGE_POLICY_VERSION,
  EXACT_FOUR_DATASET_IDS,
} from "./controlled_pilot_contract";
import { canonicalJson, sha256Digest } from "./controlled_pilot_json";
import { validateOpsProjectionEnvelopeClaims } from "./ops_projection_ready";

const TABLES = [
  "collection_sla_status",
  "coverage_segments",
  "dataset_coverage",
  "endpoint_inventory",
  "ingestion_run_log",
  "ingestion_validation",
  "ingestion_watermarks",
  "ops_alerts",
  "ops_b0_status",
  "ops_projection_metadata",
  "ops_ready_snapshots",
  "ops_ready_state",
  "ops_snapshot_quality",
  "ops_storage_plane_status",
  "ops_sync_feed",
  "raw_retention_manifests",
  "receipt_product_materializations",
] as const;

const digest = (character: string): string => `sha256:${character.repeat(64)}`;

async function validEnvelope(): Promise<Record<string, unknown>> {
  const contentManifest = Object.fromEntries(
    TABLES.map((table) => [table, { content_digest: digest("a"), row_count: 0 }]),
  );
  const rowCounts = Object.fromEntries(TABLES.map((table) => [table, 0]));
  const datasetCoverage = Object.fromEntries(EXACT_FOUR_DATASET_IDS.map((datasetId) => {
    const policy = CONTROLLED_COVERAGE_POLICY_ROWS[
      datasetId as keyof typeof CONTROLLED_COVERAGE_POLICY_ROWS
    ];
    return [datasetId, {
      status: "COMPLETE",
      coverage_mode: "governed",
      policy_id: policy.policy_id,
      policy_version: policy.policy_version,
      policy_digest: policy.policy_digest,
      collection_scope: "controlled",
      observed_start: "2008-05-01",
      observed_end: "2026-09-02",
    }];
  }));
  return {
    schema_version: "ops-projection-envelope/v1",
    environment: "staging",
    resource_identity: {
      environment: "staging",
      source_d1: OPS_PROJECTION_D1_IDENTITIES.staging,
      source_audit_digest: digest("b"),
      source_export_digest: digest("c"),
      source_change_seq: 11,
    },
    generation_id: "projection-11",
    content_digest: await sha256Digest(canonicalJson({ tables: contentManifest })),
    source_db_digest: digest("d"),
    generated_at: "2026-09-02T12:00:00Z",
    producer_commit_sha: "0123456789abcdef",
    contract_digest: digest("e"),
    registry_digest: digest("f"),
    coverage_policy_version: EXACT_FOUR_COVERAGE_POLICY_VERSION,
    coverage_policy_digest: EXACT_FOUR_COVERAGE_POLICY_DIGEST,
    projection_status: "FRESH",
    source_generation: 11,
    source_snapshot_generation: "snapshot-11",
    source_cursor: 11,
    export_cursor: 11,
    applied_cursor: 11,
    coverage_status_digest: digest("1"),
    dataset_coverage: datasetCoverage,
    b0_status: "PASS",
    b0_evidence_digest: digest("2"),
    b4_status: "PASS",
    b4_evidence_digest: digest("3"),
    evidence_digests: {
      raw_retention: digest("4"),
      product_materializations: digest("5"),
      validation: digest("6"),
      dependency_scope: digest("7"),
    },
    content_manifest: contentManifest,
    row_counts: rowCounts,
  };
}

describe("signed Ops Projection claim consistency", () => {
  it("accepts one internally coherent exact cursor chain", async () => {
    expect(await validateOpsProjectionEnvelopeClaims(
      await validEnvelope(),
      "staging",
      Date.parse("2026-09-02T12:00:30Z"),
    )).toBeNull();
  });

  it("rejects a resource source_change_seq that differs inside the signed envelope", async () => {
    const envelope = await validEnvelope();
    (envelope.resource_identity as Record<string, unknown>).source_change_seq = 12;
    expect(await validateOpsProjectionEnvelopeClaims(
      envelope,
      "staging",
      Date.parse("2026-09-02T12:00:30Z"),
    )).toMatch(/resource cursor/);
  });

  it("rejects a projection generated more than five minutes in the future", async () => {
    const envelope = await validEnvelope();
    envelope.generated_at = "2026-09-02T12:05:01Z";
    expect(await validateOpsProjectionEnvelopeClaims(
      envelope,
      "staging",
      Date.parse("2026-09-02T12:00:00Z"),
    )).toMatch(/stale or time-incoherent/);
  });
});
