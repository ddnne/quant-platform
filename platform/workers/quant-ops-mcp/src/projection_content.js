/** Content verification for immutable Ops Projection payload tables. */

import {
  canonicalProjectionJson,
  projectionSha256,
} from "./projection_signature.js";

export const PROJECTED_CONTENT_TABLES = Object.freeze([
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
]);

const PROJECTED_CONTENT_TABLE_SET = new Set(PROJECTED_CONTENT_TABLES);

/** @param {Uint8Array} left @param {Uint8Array} right */
function compareBytes(left, right) {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left[index] !== right[index]) return left[index] - right[index];
  }
  return left.length - right.length;
}

/** @param {unknown[]} rows */
function canonicalRows(rows) {
  const encoder = new TextEncoder();
  return rows
    .map((row) => ({ bytes: encoder.encode(canonicalProjectionJson(row)), row }))
    .sort((left, right) => compareBytes(left.bytes, right.bytes))
    .map(({ row }) => row);
}

/** @param {unknown} value */
function isDigest(value) {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

/**
 * @param {D1Database} db
 * @param {string} generation
 * @param {string} table
 */
export async function projectedTableContent(db, generation, table) {
  if (!PROJECTED_CONTENT_TABLE_SET.has(table)) {
    throw new RangeError(`unknown Ops Projection content table: ${table}`);
  }
  const result = await db.prepare(
    `SELECT * FROM ${table} WHERE projection_generation_id=?`,
  ).bind(generation).all();
  const rows = canonicalRows(result.results || []);
  return {
    row_count: rows.length,
    content_digest: await projectionSha256({ rows }),
  };
}

/** @param {Record<string, {row_count:number,content_digest:string}>} manifest */
export async function projectedManifestDigest(manifest) {
  return projectionSha256({ tables: manifest });
}

/**
 * Verify that the signed manifest is complete and that every table used by a
 * tool still has exactly the rows the publisher sealed. The overall digest
 * binds all table digests even when one tool needs only a bounded subset.
 *
 * @param {D1Database} db
 * @param {Record<string, unknown>} envelope
 * @param {readonly string[]} requiredTables
 * @returns {Promise<{ok:boolean,reason:string|null}>}
 */
export async function verifyProjectedContent(db, envelope, requiredTables) {
  const manifestValue = envelope.content_manifest;
  const rowCountsValue = envelope.row_counts;
  if (!manifestValue || typeof manifestValue !== "object" || Array.isArray(manifestValue) ||
      !rowCountsValue || typeof rowCountsValue !== "object" || Array.isArray(rowCountsValue)) {
    return { ok: false, reason: "signed Ops Projection content manifest is missing" };
  }
  const manifest = /** @type {Record<string, unknown>} */ (manifestValue);
  const rowCounts = /** @type {Record<string, unknown>} */ (rowCountsValue);
  if (Object.keys(manifest).sort().join("\0") !== PROJECTED_CONTENT_TABLES.join("\0") ||
      Object.keys(rowCounts).sort().join("\0") !== PROJECTED_CONTENT_TABLES.join("\0")) {
    return { ok: false, reason: "signed Ops Projection content manifest membership drift" };
  }
  /** @type {Record<string, {row_count:number,content_digest:string}>} */
  const normalized = {};
  for (const table of PROJECTED_CONTENT_TABLES) {
    const raw = manifest[table];
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      return { ok: false, reason: `signed Ops Projection manifest is malformed for ${table}` };
    }
    const row = /** @type {Record<string, unknown>} */ (raw);
    if (Object.keys(row).sort().join("\0") !== "content_digest\0row_count" ||
        !Number.isInteger(row.row_count) || Number(row.row_count) < 0 ||
        !isDigest(row.content_digest) || rowCounts[table] !== row.row_count) {
      return { ok: false, reason: `signed Ops Projection manifest is malformed for ${table}` };
    }
    normalized[table] = {
      row_count: Number(row.row_count),
      content_digest: String(row.content_digest),
    };
  }
  if (await projectedManifestDigest(normalized) !== envelope.content_digest) {
    return { ok: false, reason: "signed Ops Projection content digest does not bind its manifest" };
  }
  const uniqueTables = [...new Set(requiredTables)].sort();
  if (uniqueTables.some((table) => !PROJECTED_CONTENT_TABLE_SET.has(table))) {
    return { ok: false, reason: "tool requested an unknown Ops Projection content table" };
  }
  try {
    for (const table of uniqueTables) {
      const observed = await projectedTableContent(db, String(envelope.generation_id), table);
      const expected = normalized[table];
      if (observed.row_count !== expected.row_count ||
          observed.content_digest !== expected.content_digest) {
        return { ok: false, reason: `active Ops Projection content mismatch for ${table}` };
      }
    }
  } catch {
    return { ok: false, reason: "active Ops Projection content verification failed" };
  }
  return { ok: true, reason: null };
}
