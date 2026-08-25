/** Quant Ops read-model dispatch. Every query is bound to one active generation. */

import { GOVERNED_DATASETS, GOVERNED_DATASET_SET } from "./governed.js";
import {
  classifyRawAcquisition,
  honestProjectionStatus,
  overlayInventoryRow,
  syncDatasetState,
} from "./domain_policy.js";
import { verifyProjectionGeneration } from "./projection_signature.js";

const STRING = { type: "string" };
const OPTIONAL_DATASET = {
  dataset: { ...STRING, minLength: 1, maxLength: 160 },
};

/** @type {ReadonlyArray<{name:string, description:string, inputSchema:Record<string, unknown>}>} */
export const OPS_TOOLS = Object.freeze([
  tool("ops_status", "Active immutable Ops projection summary; never a research-data query."),
  tool("source_inventory", "Active canonical endpoint inventory and governance tier."),
  tool("endpoint_status", "Active endpoint inventory and Coverage status.", OPTIONAL_DATASET, ["dataset"]),
  tool("projection_status", "Active projection generation, freshness, and cursor metadata."),
  tool("collection_sla_status", "Publisher-materialized active dataset SLA status.", OPTIONAL_DATASET),
  tool("ingestion_last_run", "Latest run in the active immutable projection generation."),
  tool("dataset_coverage", "Active Coverage projection (policy_version as stored on the generation) for one governed dataset.", OPTIONAL_DATASET, ["dataset"]),
  tool("coverage_gaps", "Active governed datasets whose Coverage projection (policy_version as stored on the generation) is not COMPLETE."),
  tool("coverage_segments", "Bounded active Coverage projection (policy_version as stored on the generation) segment evidence.", {
    ...OPTIONAL_DATASET,
    status: { type: "string", enum: ["COMPLETE", "PARTIAL", "FAILED", "UNKNOWN", "STALE"] },
    limit: { type: "integer", minimum: 1, maximum: 500 },
  }),
  tool("backfill_status", "Active required-segment completion counts by dataset.", OPTIONAL_DATASET),
  tool("validation_summary", "Latest validation run in the active projection."),
  tool("b0_status", "Active B0 gate evidence, including explicit UNKNOWN."),
  tool("latest_ready_snapshot", "Active profile/plan/closure-bound immutable READY publication state."),
  tool("snapshot_quality", "Quality result attached to an active READY snapshot.", { snapshot_id: STRING }),
  tool("raw_retention_status", "Latest authoritative raw evidence per source segment.", OPTIONAL_DATASET),
  tool("sync_status", "Active source/export/applied cursor projection."),
  tool("storage_plane_status", "Publisher-materialized storage aggregate; never scans ingestion facts."),
]);

/** @param {string} name @param {string} description @param {Record<string, unknown>} properties @param {string[]} required */
function tool(name, description, properties = {}, required = []) {
  /** @type {Record<string, unknown>} */
  const inputSchema = { type: "object", properties, additionalProperties: false };
  if (required.length) inputSchema.required = required;
  return { name, description, inputSchema };
}

/** @param {unknown} value */
function objectArgs(value) {
  if (value === undefined || value === null) return {};
  if (typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("tool arguments must be an object");
  }
  return /** @type {Record<string, unknown>} */ (value);
}

/** @param {unknown} value @param {{governedOnly?: boolean}} options */
function datasetArg(value, options = {}) {
  if (typeof value !== "string" || !value.trim() || value.length > 160) {
    throw new TypeError("dataset must be a non-empty string of at most 160 characters");
  }
  const dataset = value.trim();
  if (options.governedOnly !== false && !GOVERNED_DATASET_SET.has(dataset)) {
    throw new RangeError("dataset is not in the governed Ops catalog");
  }
  return dataset;
}

/** @param {unknown} value */
function snapshotArg(value) {
  if (typeof value !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new TypeError("snapshot_id must be a sha256 content identifier");
  }
  return value;
}

/** @param {unknown} value */
function limitArg(value) {
  const result = value === undefined ? 200 : Number(value);
  if (!Number.isInteger(result) || result < 1 || result > 500) {
    throw new TypeError("limit must be an integer between 1 and 500");
  }
  return result;
}

/** @param {D1Database} db @param {string} sql @param {unknown[]} binds */
async function all(db, sql, binds = []) {
  try {
    const result = await db.prepare(sql).bind(...binds).all();
    return result.results || [];
  } catch (error) {
    if (/no such table/i.test(String(error))) return [];
    throw error;
  }
}

/** @param {D1Database} db @param {string} sql @param {unknown[]} binds */
async function first(db, sql, binds = []) {
  try {
    return await db.prepare(sql).bind(...binds).first();
  } catch (error) {
    if (/no such table/i.test(String(error))) return null;
    throw error;
  }
}

/** @param {D1Database} db */
async function activeProjectionGeneration(db) {
  try {
    return await first(db, `
      SELECT a.generation_id, a.activated_at, g.source_db_digest,g.content_digest,
             g.producer_commit_sha, g.contract_digest, g.registry_digest,
             g.coverage_policy_version,g.signed_envelope_json,g.issuer_key_id,
             g.signature
        FROM ops_projection_active a
        JOIN ops_projection_generation g
          ON g.generation_id=a.generation_id AND g.status='SEALED'
       WHERE a.singleton=1
       LIMIT 1`);
  } catch (error) {
    if (/no such column/i.test(String(error))) return null;
    throw error;
  }
}

/** @param {Record<string, unknown> | null} active @param {string} reason @param {string} plane */
function notProjected(active, reason, plane = "ops_current") {
  return {
    plane,
    mutable: false,
    status: "NOT_PROJECTED",
    projection_generation: active?.generation_id ?? null,
    reason,
  };
}

/** @param {Record<string, unknown>} active */
function generationFields(active) {
  return {
    projection_generation: active.generation_id,
    projection_activated_at: active.activated_at,
    projection_content_digest: active.content_digest,
    projection_signature_verified: true,
    projection_issuer_key_id: active.issuer_key_id,
  };
}

/** @param {unknown} value */
function parseJson(value) {
  if (typeof value !== "string" || !value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

/**
 * @param {D1Database} db
 * @param {string} name
 * @param {unknown} rawArguments
 * @param {{projectionPublicKeyRegistry?:unknown}} options
 */
export async function callOpsTool(db, name, rawArguments, options = {}) {
  const args = objectArgs(rawArguments);
  if (!OPS_TOOLS.some((candidate) => candidate.name === name)) {
    throw new RangeError(`unknown Quant Ops Read tool: ${name}`);
  }
  const active = await activeProjectionGeneration(db);
  if (!active) {
    return notProjected(null, "active Ops Projection generation is unavailable", name.startsWith("snapshot") || name === "latest_ready_snapshot" ? "research_ready" : "ops_current");
  }
  const verified = await verifyProjectionGeneration(
    active,
    options.projectionPublicKeyRegistry,
  );
  if (!verified.ok) {
    return notProjected(
      active,
      verified.reason || "active Ops Projection signature is unverifiable",
      name.startsWith("snapshot") || name === "latest_ready_snapshot"
        ? "research_ready"
        : "ops_current",
    );
  }
  const generation = String(active.generation_id);

  if (name === "ingestion_last_run") {
    const run = await first(db, `
      SELECT id,ran_at,source,runtime,status,detail
        FROM ingestion_run_log
       WHERE projection_generation_id=?
       ORDER BY id DESC LIMIT 1`, [generation]);
    return run
      ? { plane: "ops_current", mutable: false, status: "AVAILABLE", ...generationFields(active), run }
      : notProjected(active, "ingestion run was not included in the active generation");
  }

  if (name === "dataset_coverage") {
    const dataset = datasetArg(args.dataset);
    const coverage = await first(db, `
      SELECT dataset,status,policy_version,collection_scope,
             history_target_start,history_target_end_rule,coverage_mode,
             expected_frequency,universe_rule,raw_retention_required,
             structured_reconciliation_required,governance_tier,
             observed_start,observed_end,row_count,source_run_id,
             evaluated_at,detail_json
        FROM dataset_coverage
       WHERE projection_generation_id=? AND dataset=? LIMIT 1`,
    [generation, dataset]);
    return coverage
      ? { plane: "ops_current", mutable: false, status: coverage.status, ...generationFields(active), dataset, coverage }
      : { ...notProjected(active, "dataset Coverage row is absent from the active generation"), dataset, coverage: null };
  }

  if (name === "coverage_gaps") {
    const rows = await all(db, `
      SELECT dataset,status,policy_version,collection_scope,
             history_target_start,history_target_end_rule,coverage_mode,
             expected_frequency,universe_rule,governance_tier,
             observed_start,observed_end,row_count,source_run_id,evaluated_at
        FROM dataset_coverage
       WHERE projection_generation_id=?
       ORDER BY governance_tier,dataset LIMIT 500`, [generation]);
    const present = new Map(rows.map((row) => [String(row.dataset), row]));
    const gaps = [];
    const notProjectedDatasets = [];
    for (const dataset of GOVERNED_DATASETS) {
      const row = present.get(dataset);
      if (!row) {
        notProjectedDatasets.push(dataset);
        gaps.push({ dataset, status: "NOT_PROJECTED", reason: "Coverage row absent from active generation" });
      } else if (row.status !== "COMPLETE") {
        gaps.push(row);
      }
    }
    const status = notProjectedDatasets.length
      ? "NOT_PROJECTED"
      : gaps.length ? "INCOMPLETE" : "COMPLETE";
    return {
      plane: "ops_current", mutable: false, status, ...generationFields(active),
      governed_dataset_count: GOVERNED_DATASETS.length,
      not_projected_datasets: notProjectedDatasets,
      gaps,
      reason: notProjectedDatasets.length
        ? "one or more governed Coverage rows are absent from the active generation"
        : null,
    };
  }

  if (name === "coverage_segments") {
    const clauses = ["projection_generation_id=?"];
    const binds = [generation];
    if (args.dataset !== undefined) {
      clauses.push("dataset=?");
      binds.push(datasetArg(args.dataset));
    }
    if (args.status !== undefined) {
      const allowed = new Set(["COMPLETE", "PARTIAL", "FAILED", "UNKNOWN", "STALE"]);
      if (typeof args.status !== "string" || !allowed.has(args.status)) {
        throw new TypeError("invalid coverage segment status");
      }
      clauses.push("status=?");
      binds.push(args.status);
    }
    const limit = limitArg(args.limit);
    const segments = await all(db, `
      SELECT source,dataset,segment_id,policy_version,segment_start,segment_end,
             expected_scope,expected_items,status,receipt_run_id,evaluated_at,detail_json
        FROM coverage_segments
       WHERE ${clauses.join(" AND ")}
       ORDER BY dataset,segment_start,segment_id LIMIT ?`, [...binds, limit]);
    return segments.length
      ? { plane: "ops_current", mutable: false, status: "AVAILABLE", ...generationFields(active), segments, limit }
      : { ...notProjected(active, "no matching Coverage segments are projected"), segments: [], limit };
  }

  if (name === "backfill_status") {
    const requested = args.dataset === undefined
      ? GOVERNED_DATASETS
      : [datasetArg(args.dataset)];
    const rows = await all(db, `
      SELECT dataset,COUNT(*) AS required_segments,
             SUM(CASE WHEN status='COMPLETE' THEN 1 ELSE 0 END) AS complete_segments,
             SUM(CASE WHEN status<>'COMPLETE' THEN 1 ELSE 0 END) AS remaining_segments
        FROM coverage_segments
       WHERE projection_generation_id=?
       GROUP BY dataset ORDER BY dataset`, [generation]);
    const byDataset = new Map(rows.map((row) => [String(row.dataset), row]));
    const datasets = requested.map((dataset) => {
      const row = byDataset.get(dataset);
      if (!row) {
        return {
          dataset,
          status: "NOT_PROJECTED",
          required_segments: null,
          complete_segments: null,
          remaining_segments: null,
          reason: "segment plan absent from active generation",
        };
      }
      const required = Number(row.required_segments);
      const complete = Number(row.complete_segments);
      return {
        dataset,
        status: required > 0 && complete === required ? "COVERAGE_COMPLETE" : "PARTIAL",
        required_segments: required,
        complete_segments: complete,
        remaining_segments: Number(row.remaining_segments),
      };
    });
    return {
      plane: "ops_current", mutable: false,
      status: datasets.some((row) => row.status === "NOT_PROJECTED") ? "NOT_PROJECTED" : "AVAILABLE",
      ...generationFields(active), datasets,
      reason: datasets.some((row) => row.status === "NOT_PROJECTED")
        ? "one or more segment plans are absent from the active generation"
        : null,
    };
  }

  if (name === "validation_summary") {
    const latest = await first(db, `
      SELECT MAX(run_id) AS run_id FROM ingestion_validation
       WHERE projection_generation_id=?`, [generation]);
    if (latest?.run_id === null || latest?.run_id === undefined) {
      return notProjected(active, "validation rows are absent from the active generation");
    }
    const rows = await all(db, `
      SELECT dataset,status,rows_seen,rows_inserted,rows_revisions,detail
        FROM ingestion_validation
       WHERE projection_generation_id=? AND run_id=?
       ORDER BY dataset LIMIT 500`, [generation, latest.run_id]);
    if (!rows.length) return notProjected(active, "validation rows are absent from the active generation");
    return {
      plane: "ops_current", mutable: false,
      status: rows.every((row) => row.status === "pass") ? "PASS" : "FAIL",
      ...generationFields(active), run_id: latest.run_id,
      failures: rows.filter((row) => row.status !== "pass"),
      dataset_count: rows.length,
    };
  }

  if (name === "b0_status") {
    const row = await first(db, `
      SELECT status,policy_version,evaluated_at AS checked_at,summary_json,
             results_json,source_build_id
        FROM ops_b0_status
       WHERE projection_generation_id=? AND singleton=1 LIMIT 1`, [generation]);
    return row
      ? { plane: "ops_current", mutable: false, ...generationFields(active), ...row }
      : notProjected(active, "B0 row is absent from the active generation");
  }

  if (name === "latest_ready_snapshot") {
    const state = await first(db, `
      SELECT status,snapshot_id,reason,evaluated_at
        FROM ops_ready_state WHERE projection_generation_id=? LIMIT 1`, [generation]);
    if (!state) return notProjected(active, "READY publication state is absent", "research_ready");
    if (state.status !== "READY") {
      return {
        plane: "research_ready", mutable: false, ...generationFields(active),
        status: state.status, snapshot: null, reason: state.reason,
      };
    }
    const snapshot = await first(db, `
      SELECT snapshot_id,state,committed_at,source_run_id,change_seq,
             coverage_policy_version,quality_policy_version,
             coverage_proof_digest,manifest_json
        FROM ops_ready_snapshots
       WHERE projection_generation_id=? AND snapshot_id=? AND state='READY' LIMIT 1`,
    [generation, state.snapshot_id]);
    return snapshot
      ? { plane: "research_ready", mutable: false, status: "READY", ...generationFields(active), snapshot }
      : notProjected(active, "READY state points to a missing snapshot row", "research_ready");
  }

  if (name === "snapshot_quality") {
    let snapshotId = args.snapshot_id === undefined ? null : snapshotArg(args.snapshot_id);
    if (!snapshotId) {
      const state = await first(db, `
        SELECT snapshot_id FROM ops_ready_state
         WHERE projection_generation_id=? AND status='READY' LIMIT 1`, [generation]);
      snapshotId = state?.snapshot_id ? String(state.snapshot_id) : null;
    }
    if (!snapshotId) return notProjected(active, "no active READY snapshot is available", "research_ready");
    const quality = await first(db, `
      SELECT snapshot_id,status,policy_version,evaluated_at,summary_json
        FROM ops_snapshot_quality
       WHERE projection_generation_id=? AND snapshot_id=? LIMIT 1`,
    [generation, snapshotId]);
    return quality
      ? { plane: "research_ready", mutable: false, status: quality.status, ...generationFields(active), snapshot_id: snapshotId, quality }
      : notProjected(active, "quality row is absent for the active READY snapshot", "research_ready");
  }

  if (name === "raw_retention_status") {
    const binds = [generation];
    let filter = "";
    if (args.dataset !== undefined) {
      filter = " AND dataset=?";
      binds.push(datasetArg(args.dataset));
    }
    const rows = await all(db, `
      SELECT source,dataset,segment_id,run_id,manifest_key,page_count,row_count,raw_bytes,
             data_digest,completeness,created_at,reason
        FROM raw_retention_manifests
       WHERE projection_generation_id=?${filter}
       ORDER BY dataset,segment_id LIMIT 500`, binds);
    if (!rows.length) {
      return { ...notProjected(active, "authoritative raw segment evidence is absent"), totals: null, attestations: [] };
    }
    const captured = new Set(["ACQUIRED", "COMPLETE"]);
    const totals = {
      total_segments: rows.length,
      acquired_segments: rows.filter((row) => captured.has(String(row.completeness))).length,
      failed_segments: rows.filter((row) => row.completeness === "FAILED").length,
      not_captured_segments: rows.filter((row) => !captured.has(String(row.completeness))).length,
    };
    return {
      plane: "ops_current", mutable: false, status: "AVAILABLE", ...generationFields(active),
      totals,
      attestations: rows.map((row) => ({ ...row, acquisition_state: classifyRawAcquisition(row) })),
      note: "one latest authoritative row per source segment; superseded failed attempts are audit-only upstream",
    };
  }

  if (name === "source_inventory") {
    const inventory = await all(db, `
      SELECT dataset_id,display_name,source,governance_tier,inventory_status,
             upstream_locator,collection_window,expected_frequency,
             coverage_segment_granularity,research_eligible,enabled,sla,
             historical_start,available_at_json
        FROM endpoint_inventory
       WHERE projection_generation_id=?
       ORDER BY source,governance_tier,dataset_id LIMIT 500`, [generation]);
    if (!inventory.length) return notProjected(active, "endpoint inventory is absent from the active generation");
    const overlaid = inventory.map(overlayInventoryRow);
    return {
      plane: "ops_current", mutable: false, status: "AVAILABLE", ...generationFields(active),
      inventory_count: overlaid.length,
      governed_count: overlaid.filter((row) => row.governance_tier === "governed").length,
      experimental_count: overlaid.filter((row) => row.governance_tier === "experimental").length,
      inventory: overlaid,
    };
  }

  if (name === "endpoint_status") {
    const dataset = datasetArg(args.dataset, { governedOnly: false });
    const endpoint = await first(db, `
      SELECT dataset_id,display_name,source,governance_tier,inventory_status,
             upstream_locator,collection_window,expected_frequency,
             coverage_segment_granularity,research_eligible,enabled,sla,
             historical_start,available_at_json
        FROM endpoint_inventory
       WHERE projection_generation_id=? AND dataset_id=? LIMIT 1`, [generation, dataset]);
    if (!endpoint) return { ...notProjected(active, "endpoint is absent from active inventory"), dataset };
    const coverage = await first(db, `
      SELECT dataset,status,policy_version,collection_scope,observed_start,
             observed_end,row_count,source_run_id,evaluated_at
        FROM dataset_coverage
       WHERE projection_generation_id=? AND dataset=? LIMIT 1`, [generation, dataset]);
    return {
      plane: "ops_current", mutable: false,
      status: coverage ? "AVAILABLE" : "NOT_PROJECTED",
      ...generationFields(active), dataset, endpoint: overlayInventoryRow(endpoint),
      reason: coverage ? null : "Coverage row is absent from active generation",
      coverage: coverage || {
        dataset, status: "NOT_PROJECTED",
        reason: "Coverage row is absent from active generation",
      },
    };
  }

  if (name === "projection_status") {
    const metadata = await first(db, `
      SELECT generated_at,source_generation,source_cursor,export_cursor,
             applied_cursor,age_seconds,status,projection_version,
             refresh_attempt_at,refresh_success_at,refresh_error,detail_json
        FROM ops_projection_metadata
       WHERE projection_generation_id=? LIMIT 1`, [generation]);
    if (!metadata) return notProjected(active, "projection metadata is absent from the active generation");
    const honest = honestProjectionStatus(metadata);
    const status = honest.status;
    const stale = status !== "FRESH";
    return {
      plane: "ops_current", mutable: false, status,
      projection_status: status,
      projection_generated_at: metadata.generated_at,
      projection_source_generation: metadata.source_generation,
      source_cursor: metadata.source_cursor,
      export_cursor: metadata.export_cursor,
      applied_cursor: metadata.applied_cursor,
      projection_age_seconds: honest.age,
      ...generationFields(active),
      producer_commit_sha: active.producer_commit_sha,
      source_db_digest: active.source_db_digest,
      contract_digest: active.contract_digest,
      registry_digest: active.registry_digest,
      coverage_policy_version: active.coverage_policy_version,
      stale,
      projection_version: metadata.projection_version,
      refresh_error: metadata.refresh_error,
      stages: {
        refresh_attempt: honest.refreshAttempt,
        refresh_success: status === "FRESH" && honest.refreshOk,
        projection_generated: true,
        d1_applied: true,
        mcp_visible: true,
      },
    };
  }

  if (name === "collection_sla_status") {
    const binds = [generation];
    let filter = "";
    if (args.dataset !== undefined) {
      filter = " AND dataset_id=?";
      binds.push(datasetArg(args.dataset, { governedOnly: false }));
    }
    const rows = await all(db, `
      SELECT dataset_id,expected_after,usable_by,freshness_policy,timezone,
             current_state,state_reason,state_since,last_event_date,last_checked_at
        FROM collection_sla_status
       WHERE projection_generation_id=?${filter}
       ORDER BY dataset_id LIMIT 500`, binds);
    if (!rows.length) return notProjected(active, "SLA rows are absent from the active generation");
    if (args.dataset !== undefined) {
      return {
        plane: "ops_current", mutable: false, status: "AVAILABLE",
        ...generationFields(active), dataset: rows[0].dataset_id, sla: rows[0],
      };
    }
    return { plane: "ops_current", mutable: false, status: "AVAILABLE", ...generationFields(active), datasets: rows };
  }

  if (name === "sync_status") {
    const feed = await first(db, `
      SELECT feed,latest_source_change_seq,change_log_row_count,exported_cursor,
             applied_cursor,updated_at
        FROM ops_sync_feed
       WHERE projection_generation_id=? AND feed='jquants_records' LIMIT 1`, [generation]);
    if (!feed) return notProjected(active, "sync feed row is absent from the active generation");
    const marks = await all(db, `
      SELECT dataset,last_event_date,last_ingested_at,last_export_cursor
        FROM ingestion_watermarks
       WHERE projection_generation_id=? ORDER BY dataset LIMIT 500`, [generation]);
    const source = feed.latest_source_change_seq == null ? null : Number(feed.latest_source_change_seq);
    const exported = feed.exported_cursor == null ? null : Number(feed.exported_cursor);
    const applied = feed.applied_cursor == null ? null : Number(feed.applied_cursor);
    const changeLogRows = feed.change_log_row_count == null
      ? null
      : Number(feed.change_log_row_count);
    if (changeLogRows === null) {
      return {
        ...notProjected(active, "source change-log evidence is absent from the active generation"),
        source_cursor: source,
        export_cursor: exported,
        applied_cursor: applied,
        change_log_row_count: null,
        watermarks: marks,
      };
    }
    const lag = source == null || exported == null ? null : Math.max(0, source - exported);
    const state = syncDatasetState({
      exported,
      applied,
      lag,
      changeLogRows,
    });
    return {
      plane: "ops_current", mutable: false,
      status: state === "CURRENT" ? "CURRENT" : "UNKNOWN",
      ...generationFields(active),
      feed: feed.feed,
      source_cursor: source,
      export_cursor: exported,
      applied_cursor: applied,
      change_log_row_count: changeLogRows,
      lag,
      state,
      watermarks: marks,
      reason: state === "CURRENT" ? null : "source/export/applied cursors are not all current and equal",
    };
  }

  if (name === "storage_plane_status") {
    const row = await first(db, `
      SELECT materialized_at,payload_json
        FROM ops_storage_plane_status
       WHERE projection_generation_id=? LIMIT 1`, [generation]);
    if (!row) return notProjected(active, "storage aggregate is absent from the active generation");
    const payload = parseJson(row.payload_json);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return notProjected(active, "storage aggregate payload is invalid JSON");
    }
    return {
      ...payload,
      plane: "ops_current",
      mutable: false,
      status: "AVAILABLE",
      ...generationFields(active),
      materialized_at: row.materialized_at,
      research_note: "publisher-materialized control-plane proof only; never READY or Mass authority",
    };
  }

  // ops_status
  const [lastRun, coverage, rawRows, alerts] = await Promise.all([
    first(db, `SELECT id,ran_at,source,runtime,status FROM ingestion_run_log WHERE projection_generation_id=? ORDER BY id DESC LIMIT 1`, [generation]),
    all(db, `SELECT status,COUNT(*) AS count FROM dataset_coverage WHERE projection_generation_id=? GROUP BY status ORDER BY status`, [generation]),
    all(db, `SELECT completeness FROM raw_retention_manifests WHERE projection_generation_id=?`, [generation]),
    all(db, `SELECT alert_key,severity,status,reason,observed_at FROM ops_alerts WHERE projection_generation_id=? ORDER BY severity,alert_key LIMIT 100`, [generation]),
  ]);
  const captured = rawRows.length
    ? rawRows.filter((row) => row.completeness === "ACQUIRED" || row.completeness === "COMPLETE").length
    : null;
  return {
    plane: "ops_current", mutable: false,
    status: coverage.length ? "AVAILABLE" : "NOT_PROJECTED",
    ...generationFields(active),
    last_run: lastRun,
    coverage_status_counts: coverage.length ? coverage : null,
    governed_dataset_count: GOVERNED_DATASETS.length,
    raw_retention: rawRows.length
      ? { authoritative_segments: rawRows.length, acquired_segments: captured }
      : null,
    alerts,
    reason: coverage.length ? null : "Coverage summary is absent from the active generation",
    research_note: "Active Ops projection is not a research READY snapshot.",
  };
}
