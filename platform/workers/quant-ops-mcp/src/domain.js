/** Domain-only Quant Ops reads. No SQL or storage handles cross this boundary. */

import { GOVERNED_DATASETS, GOVERNED_DATASET_SET } from "./governed.js";

const STRING = { type: "string" };
const OPTIONAL_DATASET = {
  dataset: { ...STRING, minLength: 1, maxLength: 160 },
};

/** @type {ReadonlyArray<{name:string, description:string, inputSchema:Record<string, unknown>}>} */
export const OPS_TOOLS = Object.freeze([
  tool("ops_status", "Current ingestion control-plane status; never a research-data query."),
  tool("source_inventory", "Canonical endpoint inventory with all ~31 datasets and tier classification."),
  tool("endpoint_status", "Per-endpoint status summary including governance tier, inventory status, and coverage state.", OPTIONAL_DATASET),
  tool("projection_status", "Ops projection metadata including generated_at, source_generation, age, and status."),
  tool("collection_sla_status", "Dataset SLA/freshness status with expected_after, usable_by, freshness_policy, and states.", OPTIONAL_DATASET),
  tool("ingestion_last_run", "Latest current ingestion run and bounded summary."),
  tool("dataset_coverage", "Current Coverage V2 aggregate for one governed dataset.", OPTIONAL_DATASET, ["dataset"]),
  tool("coverage_gaps", "Current governed datasets whose Coverage V2 state is not COMPLETE."),
  tool("coverage_segments", "Bounded Coverage V2 segment evidence.", {
    ...OPTIONAL_DATASET,
    status: { type: "string", enum: ["COMPLETE", "PARTIAL", "FAILED", "UNKNOWN", "STALE"] },
    limit: { type: "integer", minimum: 1, maximum: 500 },
  }),
  tool("backfill_status", "Current required-segment completion counts by dataset.", OPTIONAL_DATASET),
  tool("validation_summary", "Latest ingestion validation summary and bounded failures."),
  tool("b0_status", "Current B0 gate result when the production gate has been recorded."),
  tool("latest_ready_snapshot", "Latest published immutable READY generation metadata; no research rows."),
  tool("snapshot_quality", "Quality result attached to a published READY generation.", {
    snapshot_id: STRING,
  }),
  tool("raw_retention_status", "Raw page retention attestations linked to collection runs.", OPTIONAL_DATASET),
  tool("sync_status", "Current D1 change-feed and local-sync watermark status."),
  tool("source_inventory", "All known endpoints (governed + experimental) from the canonical inventory projection."),
  tool("endpoint_status", "One endpoint inventory row by dataset_id.", OPTIONAL_DATASET, ["dataset"]),
  tool("projection_status", "Ops projection freshness metadata (stale/missing must not look current)."),
  tool("collection_sla_status", "Dataset collection SLA / freshness policy metadata.", OPTIONAL_DATASET),
]);

/**
 * @param {string} name
 * @param {string} description
 * @param {Record<string, unknown>} properties
 * @param {string[]} required
 */
function tool(name, description, properties = {}, required = []) {
  /** @type {Record<string, unknown>} */
  const inputSchema = {
    type: "object",
    properties,
    additionalProperties: false,
  };
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

/** @param {unknown} value */
function datasetArg(value) {
  if (typeof value !== "string" || !value.trim() || value.length > 160) {
    throw new TypeError("dataset must be a non-empty string of at most 160 characters");
  }
  const dataset = value.trim();
  if (!GOVERNED_DATASET_SET.has(dataset)) {
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

/** @param {string} policy */
function _parseFreshnessWindow(policy) {
  const map = {
    "intraday_best_effort": 86400000, // 1 day
    "trading_day": 172800000, // 2 days
    "same_trading_day_am": 43200000, // 12 hours (11:30->12:30)
    "event_driven": 604800000, // 7 days
    "weekly": 1209600000, // 14 days
    "calendar_day": 86400000, // 1 day
    "archive": 31536000000, // 1 year (effectively infinite)
    "event_publication": 604800000, // 7 days
  };
  return map[policy] || 604800000; // default 7 days
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

/**
 * The result always identifies its plane. `ops_current` may change between
 * calls; `research_ready` identifies immutable publication metadata only.
 * @param {D1Database} db
 * @param {string} name
 * @param {unknown} rawArguments
 */
export async function callOpsTool(db, name, rawArguments) {
  const args = objectArgs(rawArguments);
  const known = OPS_TOOLS.some((candidate) => candidate.name === name);
  if (!known) throw new RangeError(`unknown Quant Ops Read tool: ${name}`);

  if (name === "ingestion_last_run") {
    const run = await first(db,
      "SELECT id, ran_at, source, runtime, status, detail FROM ingestion_run_log ORDER BY id DESC LIMIT 1");
    return { plane: "ops_current", mutable: true, run };
  }

  if (name === "dataset_coverage") {
    const dataset = datasetArg(args.dataset);
    const coverage = await first(db,
      `SELECT dataset, status, policy_version, collection_scope,
              history_target_start, history_target_end_rule, coverage_mode,
              expected_frequency, universe_rule, raw_retention_required,
              structured_reconciliation_required, governance_tier,
              observed_start, observed_end, row_count, source_run_id,
              evaluated_at, detail_json
         FROM dataset_coverage WHERE dataset = ? LIMIT 1`, [dataset]);
    return {
      plane: "ops_current", mutable: true, dataset,
      status: coverage ? coverage.status : "UNKNOWN",
      coverage,
      ...(coverage ? {} : { reason: "Coverage V2 projection has not been populated for this governed dataset" }),
    };
  }

  if (name === "coverage_gaps") {
    const rows = await all(db,
      `SELECT dataset, status, policy_version, collection_scope,
              history_target_start, history_target_end_rule, coverage_mode,
              expected_frequency, universe_rule, governance_tier,
              observed_start, observed_end, row_count, source_run_id, evaluated_at
         FROM dataset_coverage ORDER BY governance_tier, dataset LIMIT 500`);
    const present = new Map(rows.map((row) => [String(row.dataset), row]));
    const gaps = GOVERNED_DATASETS.flatMap((dataset) => {
      const row = present.get(dataset);
      if (!row) return [{ dataset, status: "UNKNOWN", reason: "Coverage V2 projection missing" }];
      return row.status === "COMPLETE" ? [] : [row];
    });
    return {
      plane: "ops_current", mutable: true,
      status: rows.length ? (gaps.length ? "INCOMPLETE" : "COMPLETE") : "UNKNOWN",
      governed_dataset_count: GOVERNED_DATASETS.length, gaps,
    };
  }

  if (name === "coverage_segments") {
    const clauses = [];
    const binds = [];
    if (args.dataset !== undefined) {
      clauses.push("dataset = ?");
      binds.push(datasetArg(args.dataset));
    }
    if (args.status !== undefined) {
      const allowed = new Set(["COMPLETE", "PARTIAL", "FAILED", "UNKNOWN", "STALE"]);
      if (typeof args.status !== "string" || !allowed.has(args.status)) {
        throw new TypeError("invalid coverage segment status");
      }
      clauses.push("status = ?");
      binds.push(args.status);
    }
    const where = clauses.length ? ` WHERE ${clauses.join(" AND ")}` : "";
    const limit = limitArg(args.limit);
    const segments = await all(db,
      `SELECT source, dataset, segment_id, policy_version, segment_start,
              segment_end, expected_scope, expected_items, status,
              receipt_run_id, evaluated_at, detail_json
         FROM coverage_segments${where}
        ORDER BY dataset, segment_start, segment_id LIMIT ?`,
      [...binds, limit]);
    return {
      plane: "ops_current", mutable: true,
      status: segments.length ? "AVAILABLE" : "UNKNOWN",
      ...(segments.length ? {} : { reason: "Coverage V2 segment projection is empty or unavailable" }),
      segments, limit,
    };
  }

  if (name === "backfill_status") {
    const binds = [];
    let where = "";
    if (args.dataset !== undefined) {
      where = " WHERE dataset = ?";
      binds.push(datasetArg(args.dataset));
    }
    const datasets = await all(db,
      `SELECT dataset, COUNT(*) AS required_segments,
              SUM(CASE WHEN status = 'COMPLETE' THEN 1 ELSE 0 END) AS complete_segments,
              SUM(CASE WHEN status <> 'COMPLETE' THEN 1 ELSE 0 END) AS remaining_segments
         FROM coverage_segments${where} GROUP BY dataset ORDER BY dataset`, binds);
    if (datasets.length) {
      return { plane: "ops_current", mutable: true, status: "AVAILABLE", datasets };
    }
    const requested = args.dataset === undefined ? GOVERNED_DATASETS : [datasetArg(args.dataset)];
    return {
      plane: "ops_current", mutable: true, status: "UNKNOWN",
      reason: "Coverage V2 segment projection is empty or unavailable",
      datasets: requested.map((dataset) => ({
        dataset, required_segments: null, complete_segments: null, remaining_segments: null,
      })),
    };
  }

  if (name === "validation_summary") {
    const latest = await first(db, "SELECT MAX(run_id) AS run_id FROM ingestion_validation");
    const runId = latest && latest.run_id;
    const rows = runId === null || runId === undefined ? [] : await all(db,
      "SELECT dataset, status, rows_seen, rows_inserted, rows_revisions, detail FROM ingestion_validation WHERE run_id = ? ORDER BY dataset LIMIT 500",
      [runId]);
    return {
      plane: "ops_current", mutable: true, run_id: runId ?? null,
      status: rows.length
        ? (rows.every((row) => row.status === "pass") ? "PASS" : "FAIL")
        : "UNKNOWN",
      ...(rows.length ? {} : { reason: "validation projection is empty or unavailable" }),
      failures: rows.filter((row) => row.status !== "pass"), dataset_count: rows.length,
    };
  }

  if (name === "b0_status") {
    const row = await first(db,
      `SELECT status, policy_version, evaluated_at AS checked_at,
              summary_json, source_build_id
         FROM ops_b0_status WHERE singleton = 1 LIMIT 1`);
    return row
      ? { plane: "ops_current", mutable: true, ...row }
      : { plane: "ops_current", mutable: true, status: "UNKNOWN", reason: "snapshot quality/B0 projection is unavailable" };
  }

  if (name === "latest_ready_snapshot") {
    const snapshot = await first(db,
      `SELECT snapshot_id, state, committed_at, source_run_id, change_seq,
              coverage_policy_version, quality_policy_version,
              coverage_proof_digest
         FROM ops_ready_snapshots WHERE state = 'READY'
        ORDER BY committed_at DESC LIMIT 1`);
    return snapshot
      ? { plane: "research_ready", mutable: false, snapshot }
      : { plane: "research_ready", mutable: false, snapshot: null, reason: "no published READY generation is bound to this Worker" };
  }

  if (name === "snapshot_quality") {
    const snapshotId = args.snapshot_id === undefined ? null : snapshotArg(args.snapshot_id);
    const snapshot = snapshotId
      ? await first(db, "SELECT snapshot_id FROM ops_ready_snapshots WHERE snapshot_id = ? AND state = 'READY' LIMIT 1", [snapshotId])
      : await first(db, "SELECT snapshot_id FROM ops_ready_snapshots WHERE state = 'READY' ORDER BY committed_at DESC LIMIT 1");
    const quality = snapshot ? await first(db,
      `SELECT snapshot_id, status, policy_version, evaluated_at, summary_json
         FROM ops_snapshot_quality WHERE snapshot_id = ? LIMIT 1`, [snapshot.snapshot_id]) : null;
    return {
      plane: "research_ready", mutable: false,
      snapshot_id: snapshot?.snapshot_id ?? null, quality,
      ...((snapshot && quality) ? {} : { reason: "verified READY quality projection is unavailable" }),
    };
  }

  if (name === "raw_retention_status") {
    const binds = [];
    let where = "";
    if (args.dataset !== undefined) {
      where = " WHERE dataset = ?";
      binds.push(datasetArg(args.dataset));
    }
    const rows = await all(db,
      `SELECT dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
              data_digest, completeness, created_at
         FROM raw_retention_manifests${where}
        ORDER BY run_id DESC, dataset LIMIT 500`, binds);
    return { plane: "ops_current", mutable: true, attestations: rows };
  }

  if (name === "source_inventory") {
    const inventory = await all(db,
      `SELECT dataset_id, display_name, source, governance_tier, inventory_status,
              collection_window, expected_frequency, coverage_segment_granularity,
              research_eligible, enabled, sla
         FROM endpoint_inventory ORDER BY source, governance_tier, dataset_id LIMIT 500`);
    return {
      plane: "ops_current", mutable: true,
      inventory_count: inventory.length,
      governed_count: inventory.filter((e) => e.governance_tier === "governed").length,
      experimental_count: inventory.filter((e) => e.governance_tier === "experimental").length,
      inventory,
    };
  }

  if (name === "endpoint_status") {
    const dataset = datasetArg(args.dataset);
    const endpoint = await first(db,
      `SELECT dataset_id, display_name, source, governance_tier, inventory_status,
              collection_window, expected_frequency, coverage_segment_granularity,
              research_eligible, enabled, sla, historical_start
         FROM endpoint_inventory WHERE dataset_id = ? LIMIT 1`, [dataset]);
    const coverage = await first(db,
      `SELECT dataset, status, policy_version, collection_scope,
              observed_start, observed_end, row_count, source_run_id, evaluated_at
         FROM dataset_coverage WHERE dataset = ? LIMIT 1`, [dataset]);
    return {
      plane: "ops_current", mutable: true, dataset,
      endpoint: endpoint || { dataset, status: "UNKNOWN", reason: "Endpoint not found in inventory" },
      coverage: coverage || { dataset, status: "UNKNOWN", reason: "Coverage V2 projection not populated" },
    };
  }

  if (name === "projection_status") {
    const metadata = await first(db,
      `SELECT generated_at, source_generation, age, status, projection_version
         FROM ops_projection_metadata ORDER BY generated_at DESC LIMIT 1`);
    return {
      plane: "ops_current", mutable: true,
      status: metadata ? metadata.status : "UNAVAILABLE",
      ...(metadata || { reason: "Projection metadata not available" }),
    };
  }

  if (name === "collection_sla_status") {
    const dataset = datasetArg(args.dataset);
    const sla = await first(db,
      `SELECT dataset_id, expected_after, usable_by, freshness_policy, timezone,
              current_state, state_reason, state_since, last_event_date, last_checked_at
         FROM collection_sla_status WHERE dataset_id = ? LIMIT 1`, [dataset]);
    const coverage = await first(db,
      `SELECT status, observed_end, evaluated_at FROM dataset_coverage WHERE dataset = ? LIMIT 1`, [dataset]);
    return {
      plane: "ops_current", mutable: true, dataset,
      sla: sla || { dataset, status: "UNKNOWN", reason: "SLA status not configured" },
      coverage_status: coverage?.status || "UNKNOWN",
      fresh: coverage && sla && sla.freshness_policy
        ? coverage.observed_end && sla.last_checked_at
          ? new Date(coverage.observed_end) >= new Date(Date.now() - _parseFreshnessWindow(sla.freshness_policy))
          : false
        : null,
    };
  }

  if (name === "sync_status") {
    const marks = await all(db,
      "SELECT dataset, last_event_date, last_ingested_at, last_export_cursor FROM ingestion_watermarks ORDER BY dataset LIMIT 500");
    const change = await first(db, "SELECT MAX(change_seq) AS latest_change_seq FROM ingestion_change_log");
    return { plane: "ops_current", mutable: true, watermarks: marks, latest_change_seq: change?.latest_change_seq ?? null };
  }

  if (name === "source_inventory") {
    const rows = await all(db,
      `SELECT dataset, source, endpoint, tier, inventory_status, enabled, entitlement,
              collection_window, history_target, research_eligible, sla_json, reason
         FROM source_inventory ORDER BY tier, dataset LIMIT 500`);
    if (!rows.length) {
      return {
        plane: "ops_current", mutable: true, status: "UNKNOWN",
        reason: "source_inventory projection missing; run publish_ops_projection",
        total_known_endpoints: GOVERNED_DATASETS.length,
        datasets: GOVERNED_DATASETS.map((dataset) => ({
          dataset, inventory_status: "UNKNOWN", tier: "governed",
        })),
      };
    }
    const status_counts = {};
    for (const row of rows) {
      const key = String(row.inventory_status || "UNKNOWN");
      status_counts[key] = (status_counts[key] || 0) + 1;
    }
    return {
      plane: "ops_current", mutable: true, status: "AVAILABLE",
      total_known_endpoints: rows.length, status_counts, datasets: rows,
    };
  }

  if (name === "endpoint_status") {
    const dataset = datasetArg(args.dataset);
    const row = await first(db,
      `SELECT dataset, source, endpoint, tier, inventory_status, enabled, entitlement,
              collection_window, history_target, research_eligible, sla_json, reason
         FROM source_inventory WHERE dataset = ? LIMIT 1`, [dataset]);
    return row
      ? { plane: "ops_current", mutable: true, endpoint: row }
      : {
        plane: "ops_current", mutable: true, endpoint: null,
        reason: "endpoint not present in source_inventory projection",
        dataset,
      };
  }

  if (name === "projection_status") {
    const row = await first(db,
      `SELECT projection_status, projection_generated_at, projection_source_generation,
              projection_age_seconds, stale, reason
         FROM ops_projection_meta WHERE singleton = 1 LIMIT 1`);
    if (!row) {
      return {
        plane: "ops_current", mutable: true,
        projection_status: "MISSING", stale: true,
        reason: "projection metadata missing; publisher has not applied a generation",
      };
    }
    return { plane: "ops_current", mutable: true, ...row };
  }

  if (name === "collection_sla_status") {
    const binds = [];
    let where = "";
    if (args.dataset !== undefined) {
      where = " WHERE dataset = ?";
      binds.push(datasetArg(args.dataset));
    }
    const rows = await all(db,
      `SELECT dataset, inventory_status, collection_window, sla_json
         FROM source_inventory${where} ORDER BY dataset LIMIT 500`, binds);
    return {
      plane: "ops_current", mutable: true,
      status: rows.length ? "AVAILABLE" : "UNKNOWN",
      datasets: rows,
      ...(rows.length ? {} : { reason: "source_inventory/SLA projection empty" }),
    };
  }

  const [lastRun, coverage, raw] = await Promise.all([
    first(db, "SELECT id, ran_at, source, runtime, status FROM ingestion_run_log ORDER BY id DESC LIMIT 1"),
    all(db, "SELECT status, COUNT(*) AS count FROM dataset_coverage GROUP BY status ORDER BY status"),
    first(db, "SELECT COUNT(*) AS manifests, SUM(CASE WHEN completeness = 'COMPLETE' THEN 1 ELSE 0 END) AS complete FROM raw_retention_manifests"),
  ]);
  return {
    plane: "ops_current", mutable: true, last_run: lastRun,
    coverage_status: coverage.length ? "AVAILABLE" : "UNKNOWN",
    coverage_status_counts: coverage,
    governed_dataset_count: GOVERNED_DATASETS.length,
    raw_retention: raw || { manifests: 0, complete: 0 },
    research_note: "Current Ops status is not evidence that a research READY snapshot contains the same state.",
  };
}
