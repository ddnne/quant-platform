/** Closed top-level MCP output schemas for the Quant Ops read surface. */

const STRING = { type: "string" };
const NULLABLE_STRING = { type: ["string", "null"] };
const INTEGER = { type: "integer" };
const NULLABLE_INTEGER = { type: ["integer", "null"] };
const BOOLEAN = { type: "boolean" };
const NULLABLE_OBJECT = { type: ["object", "null"] };
const OBJECT = { type: "object" };
const ARRAY = { type: "array", items: {} };

const GENERATION_PROPERTIES = Object.freeze({
  projection_generation: NULLABLE_STRING,
  projection_activated_at: STRING,
  projection_content_digest: { type: "string", pattern: "^sha256:[0-9a-f]{64}$" },
  projection_signature_verified: BOOLEAN,
  required_content_verified: BOOLEAN,
  projection_issuer_key_id: STRING,
});

const BASE_PROPERTIES = Object.freeze({
  plane: { type: "string", enum: ["ops_current", "research_ready"] },
  mutable: { const: false },
  status: STRING,
  reason: NULLABLE_STRING,
  ...GENERATION_PROPERTIES,
});

/** @param {Record<string, unknown>} properties */
function closedOutput(properties = {}) {
  return {
    type: "object",
    properties: { ...BASE_PROPERTIES, ...properties },
    required: ["plane", "mutable", "status", "projection_generation"],
    additionalProperties: false,
  };
}

/**
 * Nested rows are already content-addressed by the signed projection manifest.
 * Each tool nevertheless closes its top-level contract so fields cannot appear
 * silently without changing the accepted tools/list schema digest.
 */
export const OPS_OUTPUT_SCHEMAS = Object.freeze({
  ops_status: closedOutput({
    last_run: NULLABLE_OBJECT,
    coverage_status_counts: { type: ["array", "null"], items: OBJECT },
    governed_dataset_count: INTEGER,
    raw_retention: NULLABLE_OBJECT,
    alerts: ARRAY,
    research_note: STRING,
  }),
  source_inventory: closedOutput({
    inventory_count: INTEGER,
    governed_count: INTEGER,
    experimental_count: INTEGER,
    inventory: ARRAY,
  }),
  endpoint_status: closedOutput({
    dataset: STRING,
    endpoint: OBJECT,
    coverage: OBJECT,
  }),
  projection_status: closedOutput({
    projection_status: STRING,
    projection_generated_at: STRING,
    projection_source_generation: { type: ["string", "integer", "null"] },
    source_cursor: NULLABLE_INTEGER,
    export_cursor: NULLABLE_INTEGER,
    applied_cursor: NULLABLE_INTEGER,
    projection_age_seconds: NULLABLE_INTEGER,
    producer_commit_sha: STRING,
    source_db_digest: STRING,
    contract_digest: STRING,
    registry_digest: STRING,
    coverage_policy_version: STRING,
    stale: BOOLEAN,
    projection_version: STRING,
    refresh_error: NULLABLE_STRING,
    stages: OBJECT,
  }),
  collection_sla_status: closedOutput({
    dataset: STRING,
    sla: OBJECT,
    datasets: ARRAY,
  }),
  ingestion_last_run: closedOutput({ run: OBJECT }),
  dataset_coverage: closedOutput({
    dataset: STRING,
    coverage: { type: ["object", "null"] },
  }),
  coverage_gaps: closedOutput({
    governed_dataset_count: INTEGER,
    not_projected_datasets: { type: "array", items: STRING },
    gaps: ARRAY,
  }),
  coverage_segments: closedOutput({
    segments: ARRAY,
    limit: INTEGER,
  }),
  backfill_status: closedOutput({ datasets: ARRAY }),
  validation_summary: closedOutput({
    run_id: INTEGER,
    failures: ARRAY,
    dataset_count: INTEGER,
  }),
  b0_status: closedOutput({
    policy_version: STRING,
    checked_at: STRING,
    summary_json: STRING,
    results_json: STRING,
    source_build_id: STRING,
  }),
  latest_ready_snapshot: closedOutput({ snapshot: NULLABLE_OBJECT }),
  snapshot_quality: closedOutput({
    snapshot_id: STRING,
    quality: OBJECT,
  }),
  raw_retention_status: closedOutput({
    totals: NULLABLE_OBJECT,
    attestations: ARRAY,
    note: STRING,
  }),
  sync_status: closedOutput({
    feed: STRING,
    source_cursor: NULLABLE_INTEGER,
    export_cursor: NULLABLE_INTEGER,
    applied_cursor: NULLABLE_INTEGER,
    change_log_row_count: NULLABLE_INTEGER,
    lag: NULLABLE_INTEGER,
    state: STRING,
    watermarks: ARRAY,
  }),
  storage_plane_status: closedOutput({
    schema: STRING,
    generation: STRING,
    counts: OBJECT,
    hot_window: OBJECT,
    plane: STRING,
    jsda: OBJECT,
    reason: { type: ["string", "null"] },
    source_db_digest: STRING,
    materialized_at: STRING,
    research_note: STRING,
  }),
});
