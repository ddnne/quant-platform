/** Application-level contract-v2 natural-key rebuild for D1.
 *
 * D1 cannot reproduce the canonical SHA-256 fallback in portable SQL.  This
 * module therefore parses the stored source payload and calls the very same
 * `naturalKey` function used by live ingestion.  It fills private staging
 * tables page by page, derives one current row plus zero-or-more revisions per
 * canonical identity, and swaps all affected live rows in one D1 batch.
 */

import { PREMIUM_CORE_DATASETS, datasetById } from "./catalog";
import { naturalKey } from "./identity";

export const NATURAL_KEY_MIGRATION_ID = "jquants-premium-natural-keys-v2";
const PAGE_SIZE = 500;
// These are the contract-v2 identities that replaced the former global field
// sweep. Rebuilding unaffected high-volume bars/options would add risk without
// changing a key; the final audit still checks every Premium-core dataset.
const MIGRATED_DATASET_IDS = [
  "equities_investor_types",
  "fins_dividend",
  "fins_earnings_date",
  "markets_margin_alert",
  "markets_short_ratio",
  "markets_short_sale_report",
  "edinet_major_shareholders",
  "edinet_cross_shareholdings",
  "edinet_large_volume_shareholders",
] as const;
const AUDIT_DATASET_IDS = PREMIUM_CORE_DATASETS.map((spec) => spec.id);

export type NaturalKeyMigrationState =
  | "PENDING"
  | "BUILDING"
  | "VALIDATING"
  | "READY"
  | "REJECTED";

export interface NaturalKeyMigrationStatus {
  migrationId: string;
  state: NaturalKeyMigrationState;
  contractSchemaVersion: number;
  rowsPrimary: number;
  rowsRevisions: number;
  rowsChanges: number;
  auditMismatches: number | null;
  detail: string | null;
}

export interface NaturalKeyAudit {
  rowsChecked: number;
  mismatches: number;
  examples: { table: string; dataset: string; stored: string; canonical: string }[];
}

interface StoredVersion {
  __rowid: number;
  source: string;
  dataset: string;
  natural_key: string;
  event_time: string;
  available_at: string;
  ingested_at: string;
  payload: string;
  raw_payload: string | null;
}

interface StoredChange extends StoredVersion {
  change_seq: number;
  table_name: string;
  changed_at: string;
}

function migrationRow(row: Record<string, unknown>): NaturalKeyMigrationStatus {
  return {
    migrationId: String(row.migration_id),
    state: row.state as NaturalKeyMigrationState,
    contractSchemaVersion: Number(row.contract_schema_version),
    rowsPrimary: Number(row.rows_primary),
    rowsRevisions: Number(row.rows_revisions),
    rowsChanges: Number(row.rows_changes),
    auditMismatches: row.audit_mismatches === null ? null : Number(row.audit_mismatches),
    detail: row.detail === null ? null : String(row.detail),
  };
}

export async function naturalKeyMigrationStatus(
  db: D1Database,
): Promise<NaturalKeyMigrationStatus> {
  const row = await db.prepare(
    `SELECT migration_id, state, contract_schema_version, rows_primary,
            rows_revisions, rows_changes, audit_mismatches, detail
     FROM natural_key_migrations WHERE migration_id = ?`,
  ).bind(NATURAL_KEY_MIGRATION_ID).first();
  if (!row) {
    throw new Error("natural-key migration schema is not installed (apply 0005)");
  }
  return migrationRow(row);
}

/** Hard read/write gate used by ingestion and structured exports. */
export async function requireNaturalKeysV2Ready(db: D1Database): Promise<void> {
  const status = await naturalKeyMigrationStatus(db);
  if (status.state !== "READY") {
    throw new Error(`natural-key migration is ${status.state}; READY is required`);
  }
}

function payloadObject(payload: unknown): Record<string, unknown> {
  if (typeof payload !== "string") throw new Error("stored payload is not JSON text");
  const parsed: unknown = JSON.parse(payload);
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("stored payload is not a JSON object");
  }
  return parsed as Record<string, unknown>;
}

function inClause(ids: readonly string[]): string {
  return ids.map(() => "?").join(", ");
}

async function canonicalFor(row: Pick<StoredVersion, "dataset" | "payload">): Promise<string> {
  const spec = datasetById(row.dataset);
  if (!spec) throw new Error(`dataset is outside Premium core: ${row.dataset}`);
  return naturalKey(payloadObject(row.payload), spec);
}

async function insertVersionPage(
  db: D1Database,
  rows: StoredVersion[],
  origin: "primary" | "revision",
): Promise<void> {
  // Eleven fields per row and D1's 100-bind cap => at most nine rows.
  const statements: D1PreparedStatement[] = [];
  for (let offset = 0; offset < rows.length; offset += 9) {
    const chunk = rows.slice(offset, offset + 9);
    const values: unknown[] = [];
    for (const row of chunk) {
      values.push(
        row.source, row.dataset, row.natural_key, await canonicalFor(row),
        row.event_time, row.available_at, row.ingested_at, row.payload,
        row.raw_payload, origin, row.__rowid,
      );
    }
    statements.push(db.prepare(
      `INSERT INTO jquants_records_nk_v2_versions_stage
       (source, dataset, original_natural_key, natural_key, event_time,
        available_at, ingested_at, payload, raw_payload, origin, origin_rowid)
       VALUES ${chunk.map(() => "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").join(", ")}`,
    ).bind(...values));
  }
  if (statements.length > 0) await db.batch(statements);
}

async function insertChangePage(db: D1Database, rows: StoredChange[]): Promise<void> {
  // Eleven fields per row and D1's 100-bind cap => at most nine rows.
  const statements: D1PreparedStatement[] = [];
  for (let offset = 0; offset < rows.length; offset += 9) {
    const chunk = rows.slice(offset, offset + 9);
    const values: unknown[] = [];
    for (const row of chunk) {
      values.push(
        row.change_seq, row.table_name, row.source, row.dataset,
        await canonicalFor(row), row.event_time, row.available_at,
        row.ingested_at, row.payload, row.raw_payload, row.changed_at,
      );
    }
    statements.push(db.prepare(
      `INSERT INTO ingestion_change_log_nk_v2_stage
       (change_seq, table_name, source, dataset, natural_key, event_time,
        available_at, ingested_at, payload, raw_payload, changed_at)
       VALUES ${chunk.map(() => "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").join(", ")}`,
    ).bind(...values));
  }
  if (statements.length > 0) await db.batch(statements);
}

async function stageVersions(db: D1Database, table: string): Promise<void> {
  const origin = table === "jquants_records" ? "primary" : "revision";
  let cursor = 0;
  while (true) {
    const result = await db.prepare(
      `SELECT rowid AS __rowid, source, dataset, natural_key, event_time,
              available_at, ingested_at, payload, raw_payload
       FROM ${table}
       WHERE rowid > ? AND dataset IN (${inClause(MIGRATED_DATASET_IDS)})
       ORDER BY rowid LIMIT ?`,
    ).bind(cursor, ...MIGRATED_DATASET_IDS, PAGE_SIZE).all();
    const rows = (result.results ?? []) as unknown as StoredVersion[];
    if (rows.length === 0) return;
    await insertVersionPage(db, rows, origin);
    cursor = Number(rows[rows.length - 1].__rowid);
  }
}

async function stageChanges(db: D1Database): Promise<void> {
  let cursor = 0;
  while (true) {
    const result = await db.prepare(
      `SELECT rowid AS __rowid, change_seq, table_name, source, dataset,
              natural_key, event_time, available_at, ingested_at, payload,
              raw_payload, changed_at
       FROM ingestion_change_log
       WHERE rowid > ? AND dataset IN (${inClause(MIGRATED_DATASET_IDS)})
       ORDER BY rowid LIMIT ?`,
    ).bind(cursor, ...MIGRATED_DATASET_IDS, PAGE_SIZE).all();
    const rows = (result.results ?? []) as unknown as StoredChange[];
    if (rows.length === 0) return;
    await insertChangePage(db, rows);
    cursor = Number(rows[rows.length - 1].__rowid);
  }
}

async function derivePrimaryAndRevisions(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare("DELETE FROM jquants_records_nk_v2_primary_stage"),
    db.prepare("DELETE FROM jquants_records_nk_v2_revisions_stage"),
  ]);
  const ranked = `
    WITH deduplicated AS (
      SELECT source, dataset, natural_key, event_time, available_at,
             ingested_at, payload, raw_payload,
             MAX(CASE origin WHEN 'primary' THEN 1 ELSE 0 END) AS primary_rank,
             MAX(origin_rowid) AS origin_rowid
      FROM jquants_records_nk_v2_versions_stage
      GROUP BY source, dataset, natural_key, event_time, available_at,
               ingested_at, payload, raw_payload
    ), ranked AS (
      SELECT source, dataset, natural_key, event_time, available_at,
             ingested_at, payload, raw_payload,
             ROW_NUMBER() OVER (
               PARTITION BY source, dataset, natural_key
               ORDER BY julianday(ingested_at) DESC, ingested_at DESC,
                        julianday(available_at) DESC, available_at DESC,
                        primary_rank DESC, origin_rowid DESC
             ) AS version_rank
      FROM deduplicated
    )`;
  await db.batch([
    db.prepare(
      `${ranked}
       INSERT INTO jquants_records_nk_v2_primary_stage
       SELECT source, dataset, natural_key, event_time, available_at,
              ingested_at, payload, raw_payload
       FROM ranked WHERE version_rank = 1`,
    ),
    db.prepare(
      `${ranked}
       INSERT OR IGNORE INTO jquants_records_nk_v2_revisions_stage
       SELECT source, dataset, natural_key, event_time, available_at,
              ingested_at, payload, raw_payload
       FROM ranked WHERE version_rank > 1`,
    ),
  ]);
}

async function tableCount(db: D1Database, table: string): Promise<number> {
  const row = await db.prepare(`SELECT COUNT(*) AS n FROM ${table}`).first();
  return Number(row?.n ?? 0);
}

async function auditTable(
  db: D1Database,
  table: string,
  wherePremiumCore: boolean,
): Promise<NaturalKeyAudit> {
  let cursor = 0;
  let rowsChecked = 0;
  let mismatches = 0;
  const examples: NaturalKeyAudit["examples"] = [];
  while (true) {
    const filter = wherePremiumCore ? `AND dataset IN (${inClause(AUDIT_DATASET_IDS)})` : "";
    const result = await db.prepare(
      `SELECT rowid AS __rowid, dataset, natural_key, payload FROM ${table}
       WHERE rowid > ? ${filter} ORDER BY rowid LIMIT ?`,
    ).bind(
      cursor,
      ...(wherePremiumCore ? AUDIT_DATASET_IDS : []),
      PAGE_SIZE,
    ).all();
    const rows = (result.results ?? []) as Record<string, unknown>[];
    if (rows.length === 0) break;
    for (const row of rows) {
      rowsChecked++;
      let canonical: string;
      try {
        canonical = await canonicalFor({
          dataset: String(row.dataset), payload: String(row.payload),
        });
      } catch (error) {
        canonical = `<invalid payload: ${(error as Error).message}>`;
      }
      const stored = String(row.natural_key);
      if (stored !== canonical) {
        mismatches++;
        if (examples.length < 10) {
          examples.push({ table, dataset: String(row.dataset), stored, canonical });
        }
      }
    }
    cursor = Number(rows[rows.length - 1].__rowid);
  }
  return { rowsChecked, mismatches, examples };
}

async function auditTables(
  db: D1Database,
  tables: { name: string; filter: boolean }[],
): Promise<NaturalKeyAudit> {
  const combined: NaturalKeyAudit = { rowsChecked: 0, mismatches: 0, examples: [] };
  for (const table of tables) {
    const audit = await auditTable(db, table.name, table.filter);
    combined.rowsChecked += audit.rowsChecked;
    combined.mismatches += audit.mismatches;
    combined.examples.push(...audit.examples.slice(0, 10 - combined.examples.length));
  }
  return combined;
}

/** Recompute every Premium-core identity and atomically publish the rebuild. */
export async function rebuildNaturalKeysV2(db: D1Database): Promise<NaturalKeyMigrationStatus> {
  const existing = await naturalKeyMigrationStatus(db);
  if (existing.state === "READY") return existing;
  const lockToken = crypto.randomUUID();
  const locked = await db.prepare(
    `UPDATE natural_key_migrations
     SET state='BUILDING', lock_token=?, started_at=datetime('now'),
         completed_at=NULL, audit_mismatches=NULL, detail='building canonical staging tables'
     WHERE migration_id=? AND state IN ('PENDING','REJECTED')`,
  ).bind(lockToken, NATURAL_KEY_MIGRATION_ID).run();
  if (Number(locked.meta?.changes ?? 0) !== 1) {
    const status = await naturalKeyMigrationStatus(db);
    throw new Error(`natural-key migration cannot start while ${status.state}`);
  }

  let liveSwapStarted = false;
  try {
    await db.batch([
      db.prepare("DELETE FROM jquants_records_nk_v2_versions_stage"),
      db.prepare("DELETE FROM jquants_records_nk_v2_primary_stage"),
      db.prepare("DELETE FROM jquants_records_nk_v2_revisions_stage"),
      db.prepare("DELETE FROM ingestion_change_log_nk_v2_stage"),
    ]);
    await stageVersions(db, "jquants_records");
    await stageVersions(db, "jquants_records_revisions");
    await stageChanges(db);
    await derivePrimaryAndRevisions(db);

    const stageAudit = await auditTables(db, [
      { name: "jquants_records_nk_v2_primary_stage", filter: false },
      { name: "jquants_records_nk_v2_revisions_stage", filter: false },
      { name: "ingestion_change_log_nk_v2_stage", filter: false },
    ]);
    if (stageAudit.mismatches !== 0) {
      throw new Error(`staging identity audit found ${stageAudit.mismatches} mismatch(es)`);
    }

    const [rowsPrimary, rowsRevisions, rowsChanges] = await Promise.all([
      tableCount(db, "jquants_records_nk_v2_primary_stage"),
      tableCount(db, "jquants_records_nk_v2_revisions_stage"),
      tableCount(db, "ingestion_change_log_nk_v2_stage"),
    ]);
    const placeholders = inClause(MIGRATED_DATASET_IDS);
    liveSwapStarted = true;
    // D1 batch is transactional: readers see either all legacy rows or the
    // complete canonical replacement, never a partially replaced dataset.
    await db.batch([
      db.prepare(`DELETE FROM jquants_records WHERE dataset IN (${placeholders})`)
        .bind(...MIGRATED_DATASET_IDS),
      db.prepare(`DELETE FROM jquants_records_revisions WHERE dataset IN (${placeholders})`)
        .bind(...MIGRATED_DATASET_IDS),
      db.prepare(`DELETE FROM ingestion_change_log WHERE dataset IN (${placeholders})`)
        .bind(...MIGRATED_DATASET_IDS),
      db.prepare(
        `INSERT INTO jquants_records
         SELECT source, dataset, natural_key, event_time, available_at,
                ingested_at, payload, raw_payload
         FROM jquants_records_nk_v2_primary_stage`,
      ),
      db.prepare(
        `INSERT INTO jquants_records_revisions
         SELECT source, dataset, natural_key, event_time, available_at,
                ingested_at, payload, raw_payload
         FROM jquants_records_nk_v2_revisions_stage`,
      ),
      db.prepare(
        `INSERT OR IGNORE INTO ingestion_change_log
         (change_seq, table_name, source, dataset, natural_key, event_time,
          available_at, ingested_at, payload, raw_payload, changed_at)
         SELECT change_seq, table_name, source, dataset, natural_key,
                event_time, available_at, ingested_at, payload, raw_payload,
                changed_at
         FROM ingestion_change_log_nk_v2_stage ORDER BY change_seq`,
      ),
      db.prepare(
        `UPDATE natural_key_migrations
         SET state='VALIDATING', rows_primary=?, rows_revisions=?,
             rows_changes=?, detail='atomic replacement complete; auditing live rows'
         WHERE migration_id=? AND lock_token=? AND state='BUILDING'`,
      ).bind(
        rowsPrimary, rowsRevisions, rowsChanges,
        NATURAL_KEY_MIGRATION_ID, lockToken,
      ),
    ]);

    const liveAudit = await auditTables(db, [
      { name: "jquants_records", filter: true },
      { name: "jquants_records_revisions", filter: true },
      { name: "ingestion_change_log", filter: true },
    ]);
    const state: NaturalKeyMigrationState = liveAudit.mismatches === 0 ? "READY" : "REJECTED";
    await db.prepare(
      `UPDATE natural_key_migrations
       SET state=?, completed_at=datetime('now'), audit_mismatches=?, detail=?,
           lock_token=NULL
       WHERE migration_id=? AND lock_token=? AND state='VALIDATING'`,
    ).bind(
      state,
      liveAudit.mismatches,
      liveAudit.mismatches === 0
        ? `canonical identity audit passed (${liveAudit.rowsChecked} rows)`
        : JSON.stringify(liveAudit.examples).slice(0, 4000),
      NATURAL_KEY_MIGRATION_ID,
      lockToken,
    ).run();
    if (liveAudit.mismatches !== 0) {
      throw new Error(`live identity audit found ${liveAudit.mismatches} mismatch(es)`);
    }
    return naturalKeyMigrationStatus(db);
  } catch (error) {
    await db.prepare(
      `UPDATE natural_key_migrations
       SET state='REJECTED', completed_at=datetime('now'), detail=?, lock_token=NULL
       WHERE migration_id=? AND lock_token=?`,
    ).bind(
      `${liveSwapStarted ? "post-swap" : "pre-swap"} failure: ${(error as Error).message}`
        .slice(0, 4000),
      NATURAL_KEY_MIGRATION_ID,
      lockToken,
    ).run();
    throw error;
  }
}

/** Full post-migration audit: stored key == canonical key(payload). */
export async function auditNaturalKeysV2(db: D1Database): Promise<NaturalKeyAudit> {
  return auditTables(db, [
    { name: "jquants_records", filter: true },
    { name: "jquants_records_revisions", filter: true },
    { name: "ingestion_change_log", filter: true },
  ]);
}
