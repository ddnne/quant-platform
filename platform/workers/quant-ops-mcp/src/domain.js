/** Domain-only Quant Ops reads. No SQL or storage handles cross this boundary. */

import { GOVERNED_DATASETS, GOVERNED_DATASET_SET } from "./governed.js";

/** Official JSDA product/index locators. Overlay when inventory SLA omits them. */
export const JSDA_UPSTREAM_LOCATORS = Object.freeze({
  jsda_otc_bond_reference_prices:
    "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html",
  jsda_tokyo_repo_rates: "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/index.html",
  jsda_corporate_bond_transactions:
    "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/",
});

const STRING = { type: "string" };
const OPTIONAL_DATASET = {
  dataset: { ...STRING, minLength: 1, maxLength: 160 },
};

/** @type {ReadonlyArray<{name:string, description:string, inputSchema:Record<string, unknown>}>} */
export const OPS_TOOLS = Object.freeze([
  tool("ops_status", "Current ingestion control-plane status; never a research-data query."),
  tool("source_inventory", "Canonical endpoint inventory with all ~31 datasets and tier classification."),
  tool("endpoint_status", "Per-endpoint status summary including governance tier, inventory status, and coverage state.", OPTIONAL_DATASET, ["dataset"]),
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
  tool(
    "storage_plane_status",
    "D1 light-path / hot-window / surplus-stage proof for CF-native P0. Counts only; no research rows.",
  ),
]);
/**
 * @param {string} name
 * @param {string} description
 * @param {Record<string, unknown>} properties
 * @param {string[]} required
 */
function parseSla(raw) {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) return { ...raw };
  if (typeof raw !== "string" || !raw.trim()) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function overlayInventoryRow(row) {
  const sla = parseSla(row.sla);
  const loc = JSDA_UPSTREAM_LOCATORS[row.dataset_id];
  if (loc && !sla.upstream_locator) sla.upstream_locator = loc;
  return { ...row, sla };
}

/** Raw acquisition ≠ dataset Coverage COMPLETE. */
export function classifyRawAcquisition(row) {
  const completeness = String(row?.completeness || "");
  const rows = Number(row?.row_count ?? 0);
  const bytes = Number(row?.raw_bytes ?? 0);
  if (completeness === "FAILED") return "DOWNLOAD_FAILED";
  if (completeness !== "COMPLETE") return "UNVERIFIED";
  if (rows > 0) return "EXPECTED_AND_CAPTURED";
  if (bytes > 0) return "EXPECTED_EMPTY_WITH_EVIDENCE";
  return "SOURCE_NOT_PUBLISHED";
}

/**
 * CURRENT requires a local applied cursor. Export lag 0 with applied_cursor null
 * is EXPORT_CURRENT_APPLY_UNPINNED, never CURRENT.
 */
export function syncDatasetState({ exported, applied, lag, changeLogRows }) {
  if (exported == null) {
    return changeLogRows === 0 ? "CHANGE_LOG_EMPTY" : "EXPORT_CURSOR_NULL";
  }
  if (applied == null) {
    if (lag === 0) return "EXPORT_CURRENT_APPLY_UNPINNED";
    if (lag != null && lag > 0) return "LAGGING_APPLY_UNPINNED";
    return "APPLY_UNPINNED";
  }
  if (lag === 0 && Number(applied) === Number(exported)) return "CURRENT";
  if (lag != null && lag > 0) return "LAGGING";
  return "UNKNOWN";
}

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

/** @param {unknown} value @param {{governedOnly?: boolean}} options */
function datasetArg(value, options = {}) {
  if (typeof value !== "string" || !value.trim() || value.length > 160) {
    throw new TypeError("dataset must be a non-empty string of at most 160 characters");
  }
  const dataset = value.trim();
  const governedOnly = options.governedOnly !== false;
  // Inventory/SLA tools may address experimental endpoints; coverage tools stay governed-only.
  if (governedOnly && !GOVERNED_DATASET_SET.has(dataset)) {
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

/** @param {D1Database} db */
async function activeProjectionGeneration(db) {
  const row = await first(db,
    "SELECT generation_id, activated_at FROM ops_projection_active WHERE singleton = 1");
  return row;
}

/**
 * Prefer active generation rows; if generation column missing or null-only legacy,
 * fall back to unfiltered (caller must still surface DEGRADED_MIXED when mixed).
 * @param {D1Database} db
 * @param {string} table
 * @param {string} selectSql without WHERE
 * @param {unknown[]} binds
 */
async function allForActiveGeneration(db, table, selectSql, binds = []) {
  const active = await activeProjectionGeneration(db);
  if (!active?.generation_id) {
    return { rows: await all(db, selectSql, binds), active: null, mixed: false };
  }
  const gen = String(active.generation_id);
  // Inject generation filter before ORDER BY / LIMIT if present.
  let sql = selectSql;
  if (/\bWHERE\b/i.test(sql)) {
    sql = sql.replace(/\bWHERE\b/i, `WHERE projection_generation_id = ? AND `);
    binds = [gen, ...binds];
  } else if (/\bORDER BY\b/i.test(sql)) {
    sql = sql.replace(/\bORDER BY\b/i, `WHERE projection_generation_id = ? ORDER BY `);
    binds = [gen, ...binds];
  } else if (/\bLIMIT\b/i.test(sql)) {
    sql = sql.replace(/\bLIMIT\b/i, `WHERE projection_generation_id = ? LIMIT `);
    binds = [gen, ...binds];
  } else {
    sql = `${sql} WHERE projection_generation_id = ?`;
    binds = [...binds, gen];
  }
  try {
    const rows = await all(db, sql, binds);
    // Detect mixed gens if unfiltered has other gens
    const other = await first(db,
      `SELECT COUNT(*) AS n FROM ${table} WHERE projection_generation_id IS NOT NULL AND projection_generation_id != ?`,
      [gen]);
    const mixed = Number(other?.n || 0) > 0;
    return { rows, active, mixed };
  } catch (error) {
    // Column may not exist yet pre-migration — fall back.
    if (/no such column|projection_generation_id/i.test(String(error))) {
      return { rows: await all(db, selectSql, binds.slice(active ? 1 : 0)), active, mixed: false };
    }
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
    const active = await activeProjectionGeneration(db);
    let coverage = null;
    if (active?.generation_id) {
      coverage = await first(db,
        `SELECT dataset, status, policy_version, collection_scope,
                history_target_start, history_target_end_rule, coverage_mode,
                expected_frequency, universe_rule, raw_retention_required,
                structured_reconciliation_required, governance_tier,
                observed_start, observed_end, row_count, source_run_id,
                evaluated_at, detail_json, projection_generation_id
           FROM dataset_coverage
          WHERE dataset = ? AND projection_generation_id = ? LIMIT 1`,
        [dataset, active.generation_id]);
      if (!coverage) {
        const lkg = await first(db,
          `SELECT dataset, status, policy_version, collection_scope,
                  history_target_start, history_target_end_rule, coverage_mode,
                  expected_frequency, universe_rule, raw_retention_required,
                  structured_reconciliation_required, governance_tier,
                  observed_start, observed_end, row_count, source_run_id,
                  evaluated_at, detail_json
             FROM dataset_coverage WHERE dataset = ? LIMIT 1`, [dataset]);
        return {
          plane: "ops_current", mutable: true, dataset,
          status: "UNKNOWN",
          active_generation: active.generation_id,
          coverage: null,
          last_known_good: lkg || null,
          reason: lkg
            ? "active generation missing dataset; last-known-good is not current COMPLETE"
            : "Coverage V2 projection has not been populated for this governed dataset",
        };
      }
    } else {
      coverage = await first(db,
        `SELECT dataset, status, policy_version, collection_scope,
                history_target_start, history_target_end_rule, coverage_mode,
                expected_frequency, universe_rule, raw_retention_required,
                structured_reconciliation_required, governance_tier,
                observed_start, observed_end, row_count, source_run_id,
                evaluated_at, detail_json
           FROM dataset_coverage WHERE dataset = ? LIMIT 1`, [dataset]);
    }
    return {
      plane: "ops_current", mutable: true, dataset,
      status: coverage ? coverage.status : "UNKNOWN",
      active_generation: active?.generation_id ?? null,
      coverage,
      ...(coverage ? {} : { reason: "Coverage V2 projection has not been populated for this governed dataset" }),
    };
  }

  if (name === "coverage_gaps") {
    const active = await activeProjectionGeneration(db);
    const binds = [];
    let genClause = "";
    if (active?.generation_id) {
      genClause = " WHERE projection_generation_id = ?";
      binds.push(active.generation_id);
    }
    const rows = await all(db,
      `SELECT dataset, status, policy_version, collection_scope,
              history_target_start, history_target_end_rule, coverage_mode,
              expected_frequency, universe_rule, governance_tier,
              observed_start, observed_end, row_count, source_run_id, evaluated_at
         FROM dataset_coverage${genClause} ORDER BY governance_tier, dataset LIMIT 500`,
      binds);
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
    // Always return one row per governed dataset (26). Never drop JSDA rows.
    const binds = [];
    let where = "";
    if (args.dataset !== undefined) {
      where = " WHERE dataset = ?";
      binds.push(datasetArg(args.dataset));
    }
    const grouped = await all(db,
      `SELECT dataset, COUNT(*) AS required_segments,
              SUM(CASE WHEN status = 'COMPLETE' THEN 1 ELSE 0 END) AS complete_segments,
              SUM(CASE WHEN status <> 'COMPLETE' THEN 1 ELSE 0 END) AS remaining_segments
         FROM coverage_segments${where} GROUP BY dataset ORDER BY dataset`, binds);
    const byDataset = new Map(grouped.map((row) => [String(row.dataset), row]));
    const requested = args.dataset === undefined
      ? GOVERNED_DATASETS
      : [datasetArg(args.dataset)];
    const datasets = requested.map((dataset) => {
      const row = byDataset.get(dataset);
      if (!row) {
        const state = String(dataset).startsWith("jsda_")
          ? "DISCOVERY_INCOMPLETE"
          : "PLANNING_MISSING";
        return {
          dataset,
          required_segments: 0,
          complete_segments: 0,
          remaining_segments: 0,
          state,
        };
      }
      const required = Number(row.required_segments || 0);
      const complete = Number(row.complete_segments || 0);
      let state = "PARTIAL";
      if (required > 0 && complete === required) state = "COVERAGE_COMPLETE";
      else if (required === 0) {
        state = String(dataset).startsWith("jsda_")
          ? "DISCOVERY_INCOMPLETE"
          : "PLANNING_MISSING";
      } else if (complete === 0) state = "DISCOVERY_INCOMPLETE";
      return {
        dataset,
        required_segments: required,
        complete_segments: complete,
        remaining_segments: Number(row.remaining_segments || 0),
        state,
      };
    });
    return {
      plane: "ops_current",
      mutable: true,
      status: datasets.some((d) => d.required_segments > 0) ? "AVAILABLE" : "UNKNOWN",
      governed_dataset_count: GOVERNED_DATASETS.length,
      datasets,
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
    const totals = await first(db,
      `SELECT COUNT(*) AS total,
              SUM(CASE WHEN completeness = 'COMPLETE' THEN 1 ELSE 0 END) AS complete,
              SUM(CASE WHEN completeness IS NULL OR completeness != 'COMPLETE' THEN 1 ELSE 0 END) AS incomplete,
              SUM(CASE WHEN IFNULL(row_count, 0) = 0 OR IFNULL(raw_bytes, 0) = 0 THEN 1 ELSE 0 END) AS zero_byte_or_zero_row,
              SUM(CASE WHEN completeness = 'FAILED' THEN 1 ELSE 0 END) AS failed
         FROM raw_retention_manifests${where}`, binds);
    const unresolvedPred = "completeness IS NULL OR completeness != 'COMPLETE'";
    const oldestWhere = where ? `${where} AND (${unresolvedPred})` : ` WHERE ${unresolvedPred}`;
    const oldest = await first(db,
      `SELECT dataset, run_id, created_at, completeness, row_count, raw_bytes
         FROM raw_retention_manifests${oldestWhere}
        ORDER BY created_at ASC LIMIT 1`, binds);
    const rows = await all(db,
      `SELECT dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
              data_digest, completeness, created_at
         FROM raw_retention_manifests${where}
        ORDER BY run_id DESC, dataset LIMIT 500`, binds);
    return {
      plane: "ops_current",
      mutable: true,
      totals: {
        total: Number(totals?.total || 0),
        complete: Number(totals?.complete || 0),
        incomplete: Number(totals?.incomplete || 0),
        zero_byte_or_zero_row: Number(totals?.zero_byte_or_zero_row || 0),
        failed: Number(totals?.failed || 0),
      },
      oldest_unresolved: oldest || null,
      attestations: (rows || []).map((row) => ({
        ...row,
        acquisition_state: classifyRawAcquisition(row),
      })),
      note: "raw acquisition COMPLETE is not dataset Coverage COMPLETE",
    };
  }

  if (name === "source_inventory") {
    const inventory = await all(db,
      `SELECT dataset_id, display_name, source, governance_tier, inventory_status,
              collection_window, expected_frequency, coverage_segment_granularity,
              research_eligible, enabled, sla
         FROM endpoint_inventory ORDER BY source, governance_tier, dataset_id LIMIT 500`);
    const overlaid = (inventory || []).map(overlayInventoryRow);
    return {
      plane: "ops_current", mutable: true,
      inventory_count: overlaid.length,
      governed_count: overlaid.filter((e) => e.governance_tier === "governed").length,
      experimental_count: overlaid.filter((e) => e.governance_tier === "experimental").length,
      inventory: overlaid,
    };
  }

  if (name === "endpoint_status") {
    const dataset = datasetArg(args.dataset, { governedOnly: false });
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
    const active = await activeProjectionGeneration(db);
    const metadata = await first(db,
      `SELECT generated_at, source_generation, age_seconds, status, projection_version, detail_json,
              projection_generation_id
         FROM ops_projection_metadata ORDER BY generated_at DESC LIMIT 1`);
    if (!metadata) {
      return {
        plane: "ops_current", mutable: true,
        projection_status: "MISSING", stale: true,
        reason: "projection metadata missing; run scripts/publish_ops_projection.py",
      };
    }
    // Recompute age from request time (never trust stored age=0 forever).
    let age = null;
    try {
      const genAt = Date.parse(String(metadata.generated_at));
      if (!Number.isNaN(genAt)) age = Math.max(0, Math.floor((Date.now() - genAt) / 1000));
    } catch {
      age = Number(metadata.age_seconds ?? 0);
    }
    let status = metadata.status || "UNKNOWN";
    if (age == null && String(metadata.generated_at || "")) status = "UNKNOWN";
    if (status === "FRESH" && age != null && age > 86400) status = "STALE";
    if (status === "FRESH" && age == null) status = "UNKNOWN";
    // Mixed generation detection across coverage table
    const gens = await all(db,
      `SELECT DISTINCT projection_generation_id AS g FROM dataset_coverage
        WHERE projection_generation_id IS NOT NULL LIMIT 20`);
    if (gens.length > 1) status = "DEGRADED_MIXED_GENERATION";
    const stale = status === "STALE" || status === "DEGRADED_MIXED_GENERATION";
    const refreshSuccess = status === "FRESH" && !stale;
    return {
      plane: "ops_current", mutable: true,
      projection_status: status,
      projection_generated_at: metadata.generated_at,
      projection_source_generation: metadata.source_generation,
      projection_age_seconds: age,
      active_generation: active?.generation_id ?? metadata.projection_generation_id ?? null,
      activated_at: active?.activated_at ?? null,
      distinct_projection_generations: gens.map((r) => r.g),
      stale,
      projection_version: metadata.projection_version,
      last_known_good: stale ? {
        generated_at: metadata.generated_at,
        source_generation: metadata.source_generation,
        not_fresh: true,
      } : null,
      stages: {
        refresh_attempt: true,
        refresh_success: refreshSuccess,
        projection_generated: Boolean(metadata.generated_at),
        d1_applied: Boolean(active?.generation_id),
        mcp_visible: true,
      },
    };
  }

  if (name === "collection_sla_status") {
    const projMeta = await first(db,
      `SELECT generated_at, status FROM ops_projection_metadata ORDER BY generated_at DESC LIMIT 1`);
    let projectionStale = true;
    if (projMeta?.generated_at) {
      const genAt = Date.parse(String(projMeta.generated_at));
      const age = Number.isNaN(genAt) ? null : Math.max(0, Math.floor((Date.now() - genAt) / 1000));
      const st = String(projMeta.status || "");
      projectionStale = st !== "FRESH" || (age != null && age > 86400);
    }
    const projectFromInventory = async (datasetFilter) => {
      const binds = [];
      let where = "";
      if (datasetFilter) {
        where = " WHERE dataset_id = ?";
        binds.push(datasetFilter);
      }
      const inv = await all(db,
        `SELECT dataset_id, sla FROM endpoint_inventory${where} ORDER BY dataset_id LIMIT 500`,
        binds);
      const marks = await all(db,
        "SELECT dataset, last_event_date FROM ingestion_watermarks LIMIT 500");
      const markMap = new Map((marks || []).map((m) => [String(m.dataset), m.last_event_date ?? null]));
      return (inv || []).map((row) => {
        const sla = parseSla(row.sla);
        const loc = JSDA_UPSTREAM_LOCATORS[row.dataset_id];
        if (loc && !sla.upstream_locator) sla.upstream_locator = loc;
        let current_state = "UNKNOWN";
        let state_reason = "sla_table_empty_projected_from_inventory";
        if (projectionStale) {
          current_state = "PROJECTION_STALE";
          state_reason = "ops_projection_stale";
        } else if (row.dataset_id === "equities_bars_daily_am") {
          current_state = "NOT_PUBLISHED";
          state_reason = "am_publication_not_proven_for_session";
        }
        return {
          dataset_id: row.dataset_id,
          expected_after: sla.expected_after ?? null,
          usable_by: sla.usable_by ?? null,
          freshness_policy: sla.freshness_policy ?? null,
          timezone: sla.timezone || "Asia/Tokyo",
          upstream_locator: sla.upstream_locator ?? null,
          current_state,
          state_reason,
          last_event_date: markMap.get(row.dataset_id) ?? null,
          last_checked_at: new Date().toISOString(),
        };
      });
    };
    if (args.dataset !== undefined) {
      const dataset = datasetArg(args.dataset, { governedOnly: false });
      const sla = await first(db,
        `SELECT dataset_id, expected_after, usable_by, freshness_policy, timezone,
                current_state, state_reason, state_since, last_event_date, last_checked_at
           FROM collection_sla_status WHERE dataset_id = ? LIMIT 1`, [dataset]);
      if (sla) {
        return { plane: "ops_current", mutable: true, dataset, sla };
      }
      const projected = await projectFromInventory(dataset);
      return {
        plane: "ops_current", mutable: true, dataset,
        sla: projected[0] || { dataset, current_state: "UNKNOWN", reason: "SLA status not projected" },
        source: "inventory_projection",
      };
    }
    const rows = await all(db,
      `SELECT dataset_id, expected_after, usable_by, freshness_policy, timezone,
              current_state, state_reason, state_since, last_event_date, last_checked_at
         FROM collection_sla_status ORDER BY dataset_id LIMIT 500`);
    if (rows.length) {
      return {
        plane: "ops_current", mutable: true,
        status: "AVAILABLE",
        datasets: rows,
      };
    }
    const projected = await projectFromInventory();
    return {
      plane: "ops_current", mutable: true,
      status: projected.length ? "PROJECTED_FROM_INVENTORY" : "UNKNOWN",
      datasets: projected,
      ...(projected.length ? {} : { reason: "collection_sla_status projection empty" }),
    };
  }

  if (name === "sync_status") {
    const marks = await all(db,
      "SELECT dataset, last_event_date, last_ingested_at, last_export_cursor FROM ingestion_watermarks ORDER BY dataset LIMIT 500");
    const change = await first(db, "SELECT MAX(change_seq) AS latest_change_seq FROM ingestion_change_log");
    const changeCount = await first(db, "SELECT COUNT(*) AS n FROM ingestion_change_log");
    const latest = change?.latest_change_seq == null ? null : Number(change.latest_change_seq);
    const changeLogRows = changeCount?.n == null ? 0 : Number(changeCount.n);
    const pin = await first(db,
      "SELECT last_applied_change_seq FROM ops_applied_pins WHERE feed = ? LIMIT 1",
      ["jquants_records"]);
    const appliedFeedRaw = pin?.last_applied_change_seq;
    const appliedFeed =
      appliedFeedRaw == null || appliedFeedRaw === ""
        ? null
        : Number(appliedFeedRaw);
    const appliedFeedCursor = Number.isNaN(appliedFeed) ? null : appliedFeed;
    // Per-dataset export cursor + lag vs latest change_seq (null cursor = not synced).
    // applied_cursor stays null until local apply pin is projected — do not
    // pretend D1 watermark equals local research apply.
    const datasets = (marks || []).map((row) => {
      const cursorRaw = row.last_export_cursor;
      const exported = cursorRaw == null || cursorRaw === "" ? null : Number(cursorRaw);
      const lag =
        latest == null || exported == null || Number.isNaN(exported)
          ? null
          : Math.max(0, latest - exported);
      const applied = null;
      const state = syncDatasetState({
        exported: Number.isNaN(exported) ? null : exported,
        applied,
        lag,
        changeLogRows,
      });
      return {
        dataset: row.dataset,
        last_event_date: row.last_event_date ?? null,
        last_ingested_at: row.last_ingested_at ?? null,
        source_cursor: latest,
        exported_cursor: Number.isNaN(exported) ? null : exported,
        applied_cursor: applied,
        ready_pinned_cursor: null,
        lag,
        state,
      };
    });
    const null_cursors = datasets.filter((d) => d.exported_cursor == null).length;
    return {
      plane: "ops_current",
      mutable: true,
      // latest_change_seq kept as stable alias; latest_source_change_seq is the explicit name.
      latest_change_seq: latest,
      latest_source_change_seq: latest,
      change_log_row_count: changeLogRows,
      bootstrapped: changeLogRows > 0 && null_cursors === 0,
      applied_feed_cursor: appliedFeedCursor,
      watermarks: marks,
      datasets,
      null_export_cursor_count: null_cursors,
      research_note:
        "Cloudflare ingestion progress ≠ local research apply. " +
        "Null export cursors are honest when change_log is empty or watermark not advanced; " +
        "applied_cursor is null until local sync pin is projected. Do not treat null as COMPLETE.",
    };
  }

  // GLM_PATCH_OK skeleton + schema-corrected live tables (jquants_records SoT).
  // Fact counts are plane-local; JSDA COMPLETE is receipt-owned (coverage ledger).
  if (name === "storage_plane_status") {
    const hotCutoff = "2026-07-01";
    const n = async (sql, binds = []) => {
      const row = await first(db, sql, binds);
      const v = row?.n ?? row?.c ?? 0;
      return Number(v) || 0;
    };
    const [
      jquantsTotal,
      barsHot,
      barsCold,
      masterHot,
      changeLogRows,
      completeSegs,
      otcRows,
      corpRows,
      tokyoRepoRows,
      legacyBars,
      legacyListed,
      legacyCal,
      stagePrimary,
      stageRev,
      stageVer,
      stageChg,
      ingestionChangeLog,
      jsdaCovRows,
    ] = await Promise.all([
      n("SELECT COUNT(*) AS n FROM jquants_records"),
      n(
        "SELECT COUNT(*) AS n FROM jquants_records WHERE dataset = 'equities_bars_daily' AND substr(event_time,1,10) >= ?",
        [hotCutoff],
      ),
      n(
        "SELECT COUNT(*) AS n FROM jquants_records WHERE dataset = 'equities_bars_daily' AND substr(event_time,1,10) < ?",
        [hotCutoff],
      ),
      n(
        "SELECT COUNT(*) AS n FROM jquants_records WHERE dataset = 'equities_master' AND substr(event_time,1,10) >= ?",
        [hotCutoff],
      ),
      n("SELECT COUNT(*) AS n FROM ingestion_change_log"),
      n("SELECT COUNT(*) AS n FROM coverage_segments WHERE status = 'COMPLETE'"),
      n("SELECT COUNT(*) AS n FROM jsda_otc_bond_reference_prices"),
      n("SELECT COUNT(*) AS n FROM jsda_corporate_bond_transactions"),
      n("SELECT COUNT(*) AS n FROM jsda_repo_rates"),
      n("SELECT COUNT(*) AS n FROM jquants_daily_bars"),
      n("SELECT COUNT(*) AS n FROM jquants_listed_info"),
      n("SELECT COUNT(*) AS n FROM jquants_market_calendar"),
      n("SELECT COUNT(*) AS n FROM jquants_records_nk_v2_primary_stage"),
      n("SELECT COUNT(*) AS n FROM jquants_records_nk_v2_revisions_stage"),
      n("SELECT COUNT(*) AS n FROM jquants_records_nk_v2_versions_stage"),
      n("SELECT COUNT(*) AS n FROM ingestion_change_log_nk_v2_stage"),
      n("SELECT COUNT(*) AS n FROM ingestion_change_log"),
      all(
        db,
        "SELECT dataset, status, row_count, observed_start, observed_end FROM dataset_coverage WHERE dataset LIKE 'jsda_%' ORDER BY dataset",
      ).catch(() => []),
    ]);
    const emptyLegacy =
      legacyBars === 0 && legacyListed === 0 && legacyCal === 0;
    const coldCleared = barsCold === 0;
    const jsdaCoverage = {};
    for (const row of jsdaCovRows || []) {
      if (!row?.dataset) continue;
      jsdaCoverage[row.dataset] = {
        status: row.status,
        coverage_row_count: Number(row.row_count) || 0,
        observed_start: row.observed_start ?? null,
        observed_end: row.observed_end ?? null,
      };
    }
    const factByDataset = {
      jsda_otc_bond_reference_prices: otcRows,
      jsda_corporate_bond_transactions: corpRows,
      jsda_tokyo_repo_rates: tokyoRepoRows,
    };
    const factTableByDataset = {
      jsda_otc_bond_reference_prices: "jsda_otc_bond_reference_prices",
      jsda_corporate_bond_transactions: "jsda_corporate_bond_transactions",
      jsda_tokyo_repo_rates: "jsda_repo_rates",
    };
    const divergence = [];
    for (const [ds, factN] of Object.entries(factByDataset)) {
      const cov = jsdaCoverage[ds] || {};
      const status = cov.status;
      const covN = Number(cov.coverage_row_count) || 0;
      if (status === "COMPLETE" && factN === 0 && covN > 0) {
        divergence.push({
          dataset: ds,
          fact_table: factTableByDataset[ds],
          coverage_status: status,
          coverage_row_count: covN,
          fact_rows: factN,
          kind: "COMPLETE_WITHOUT_LOCAL_FACTS",
          note:
            "Receipt/coverage COMPLETE projected without this plane holding fact rows. " +
            "Not automatic data loss — check local research DB / R2 structured SoT.",
        });
      } else if (
        status === "COMPLETE" &&
        factN > 0 &&
        covN > 0 &&
        factN !== covN
      ) {
        divergence.push({
          dataset: ds,
          fact_table: factTableByDataset[ds],
          coverage_status: status,
          coverage_row_count: covN,
          fact_rows: factN,
          kind: "FACT_VS_COVERAGE_COUNT_MISMATCH",
          note:
            "Plane fact count differs from coverage ledger row_count " +
            "(often hot-tip D1 vs full local history).",
        });
      }
    }
    return {
      plane: "ops_current",
      mutable: true,
      hot_cutoff: hotCutoff,
      d1_approx_via_counts: {
        jquants_records_total: jquantsTotal,
        bars_hot: barsHot,
        bars_cold_before_hot_cutoff: barsCold,
        master_hot: masterHot,
        change_log_rows: changeLogRows,
        ingestion_change_log_rows: ingestionChangeLog,
      },
      complete_segments: completeSegs,
      jsda: {
        otc_rows: otcRows,
        corporate_rows: corpRows,
        tokyo_repo_rows: tokyoRepoRows,
        fact_table_map: {
          jsda_otc_bond_reference_prices: "jsda_otc_bond_reference_prices",
          jsda_corporate_bond_transactions: "jsda_corporate_bond_transactions",
          jsda_tokyo_repo_rates: "jsda_repo_rates",
        },
        coverage: jsdaCoverage,
        coverage_vs_fact_divergence: divergence,
        definition:
          "tokyo_repo_rows = COUNT(jsda_repo_rates) on this plane only. " +
          "dataset COMPLETE for jsda_tokyo_repo_rates is owned by signed " +
          "collection_receipts + coverage_segments (segment jsda-era-timeseries), " +
          "not by D1 fact backfill. ops projection publishes coverage ledgers; " +
          "full JSDA history lives on local research DB / R2 structured SoT.",
      },
      empty_legacy_tables: {
        jquants_daily_bars: legacyBars === 0,
        jquants_listed_info: legacyListed === 0,
        jquants_market_calendar: legacyCal === 0,
        all_empty: emptyLegacy,
      },
      stage_table_counts: {
        jquants_records_nk_v2_primary_stage: stagePrimary,
        jquants_records_nk_v2_revisions_stage: stageRev,
        jquants_records_nk_v2_versions_stage: stageVer,
        ingestion_change_log_nk_v2_stage: stageChg,
      },
      p0_claims: {
        bars_cold_cleared: coldCleared ? "CONFIRMED" : "RESIDUAL_COLD",
        legacy_empty: emptyLegacy ? "CONFIRMED_EMPTY" : "NOT_EMPTY",
        high_volume_write_path_code: "R2_ONLY_DEFAULT_IN_write_path_config",
        master_new_writes: "SCD2_R2_PATH_IN_master_scd2",
        mass_research: "NO-GO",
        ready: null,
        honesty_note:
          "Counts-only ops proof. Not READY. Not full Parquet materialization. " +
          "Does not claim all historical COMPLETE. JSDA COMPLETE is receipt-owned; " +
          "fact counts are plane-local (D1 may show tokyo_repo_rows=0 while coverage COMPLETE).",
      },
      research_note:
        "storage_plane_status is control-plane proof only; never treat as Mass or READY.",
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
