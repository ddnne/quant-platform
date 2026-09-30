/**
 * Premium structured persist: R2 bodies and bounded D1 metadata.
 * Fetch/upsert stay together in index.ts as the ingestion façade.
 */

import type { DatasetSpec } from "./catalog";
import { pickAvailableAt } from "./availability";
import { naturalKey, newRunId, pickEventTime, stableJson, toJstIso } from "./identity";
import { writeJsonlToR2 } from "./r2_structured_writer";
import {
  writeMasterScd2,
  type MasterScd2UniverseEvidence,
} from "./master_scd2/write";
import { exponentialBackoffFullJitterMs, sleepMs } from "./retry_jitter";

export type { MasterScd2UniverseEvidence };

export type PersistEnv = Pick<Cloudflare.Env, "DB" | "STRUCTURED_BUCKET"> & {
  MASTER_SCD2_ONLY?: string;
};

const RETRY_COUNT = 3;
const RETRY_BASE_DELAY_MS = 500;
const RETRY_MAX_DELAY_MS = 8_000;

/** Retry D1 prepare/batch on transient transport failures (same budget as HTTP). */
async function d1WithRetry<T>(op: () => Promise<T>): Promise<T> {
  let attempt = 0;
  while (true) {
    try {
      return await op();
    } catch (e) {
      attempt++;
      const msg = (e as Error)?.message || String(e);
      const transient =
        /network connection lost|D1_ERROR|internal error|timeout|503|502|429/i
          .test(msg);
      if (!transient || attempt > RETRY_COUNT) throw e;
      await sleepMs(
        exponentialBackoffFullJitterMs(
          attempt,
          RETRY_BASE_DELAY_MS,
          RETRY_MAX_DELAY_MS,
        ),
      );
    }
  }
}

export async function upsertWatermark(
  env: PersistEnv,
  dataset: string,
  lastEventDate: string | null,
  lastIngestedAt: string,
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO ingestion_watermarks
       (dataset, last_event_date, last_ingested_at, last_export_cursor)
     VALUES (?, ?, ?, NULL)
     ON CONFLICT(dataset) DO UPDATE SET
       last_event_date  = COALESCE(excluded.last_event_date, ingestion_watermarks.last_event_date),
       last_ingested_at = excluded.last_ingested_at`,
  ).bind(dataset, lastEventDate, lastIngestedAt).run();
}

/** Summary + cursor commit together. No history scan or per-row D1 body copy. */
async function writeSummary(
  db: D1Database,
  table: "equities_master_scd2" | "jquants_records_r2",
  dataset: string,
  identity: string,
  capturedAt: string,
  payload: string,
): Promise<void> {
  try {
    await d1WithRetry(() => db.batch([
      db.prepare(
        `INSERT OR IGNORE INTO ingestion_change_log
         (table_name, source, dataset, natural_key, event_time, available_at,
          ingested_at, payload, raw_payload, changed_at)
         VALUES (?, 'jquants', ?, ?, ?, ?, ?, ?, NULL, ?)`,
      ).bind(table, dataset, identity, capturedAt, capturedAt, capturedAt, payload, capturedAt),
      db.prepare(
        `INSERT INTO ingestion_watermarks
           (dataset, last_event_date, last_ingested_at, last_export_cursor)
         SELECT ?, NULL, ?, last_insert_rowid() WHERE changes() > 0
         ON CONFLICT(dataset) DO UPDATE SET
           last_export_cursor = MAX(COALESCE(ingestion_watermarks.last_export_cursor, 0),
                                    excluded.last_export_cursor)`,
      ).bind(dataset, capturedAt),
    ]));
  } catch {
    // Observability only. Never fabricate a cursor after failure. A duplicate
    // retry changes no rows: the prior atomic batch already saved its cursor.
  }
}

export interface UpsertSummary { inserted: number; revisions: number; }
export interface AvailableBounds { min: string | null; max: string | null; }

interface StructuredRecord {
  source: string;
  dataset: string;
  naturalKey: string;
  eventTime: string;
  availableAt: string;
  ingestedAt: string;
  payload: string;
  rawPayload: string;
}

export async function upsertRecords(
  env: PersistEnv,
  spec: DatasetSpec,
  rows: Record<string, unknown>[],
  when: Date,
  evidence?: MasterScd2UniverseEvidence,
  persistId?: string,
  bounds?: AvailableBounds,
): Promise<UpsertSummary> {
  if (rows.length === 0) return { inserted: 0, revisions: 0 };
  const ingestedAt = toJstIso(when);
  // JQ can redirect a holiday to the next business day's master. The current
  // SCD2 format dates observations at collection, so never activate it early.
  if (spec.id === "equities_master" && rows.some((row) =>
    typeof row.Date === "string" && row.Date > ingestedAt.slice(0, 10))) {
    throw new Error("future-effective master cannot update CURRENT");
  }
  const byKey = new Map<string, StructuredRecord>();
  for (const row of rows) {
    const nk = await naturalKey(row, spec);
    const ev = pickEventTime(row, spec);
    const availableAt = pickAvailableAt(row, spec.id, ingestedAt);
    const payload = stableJson(row);
    byKey.set(nk, {
      source: "jquants",
      dataset: spec.id,
      naturalKey: nk,
      eventTime: ev || availableAt,
      availableAt,
      ingestedAt,
      payload,
      rawPayload: JSON.stringify(row),
    });
  }
  const records = [...byKey.values()];
  // Measure the normalized rows being persisted, not unrelated legacy D1 rows.
  if (bounds) for (const { availableAt } of records) {
    if (bounds.min === null || availableAt < bounds.min) bounds.min = availableAt;
    if (bounds.max === null || availableAt > bounds.max) bounds.max = availableAt;
  }

  if (spec.id === "equities_master") {
    const scd2 = await writeMasterScd2(
      env,
      records.map((record) => ({
        naturalKey: record.naturalKey,
        payload: record.payload,
      })),
      when,
      evidence,
    );
    await writeSummary(
      env.DB, "equities_master_scd2", spec.id, `scd2-summary:${Date.now()}`, ingestedAt,
      JSON.stringify({
        kind: "scd2_master_summary",
        events_key: scd2.events_key,
        events: scd2.inserted,
      }),
    );
    return { inserted: scd2.inserted, revisions: scd2.revisions };
  }

  const runId = newRunId(`r2-${spec.id}`);
  const objectId = persistId && persistId.length > 0 ? persistId : runId;
  const r2Result = await writeJsonlToR2(
    env.STRUCTURED_BUCKET,
    spec.id,
    objectId,
    records.map((record) => ({
      source: record.source,
      dataset: record.dataset,
      naturalKey: record.naturalKey,
      eventTime: record.eventTime,
      availableAt: record.availableAt,
      ingestedAt: record.ingestedAt,
      payload: record.payload,
      rawPayload: record.rawPayload,
    })),
    { runDate: toJstIso(when).slice(0, 10) },
  );
  await writeSummary(
    env.DB, "jquants_records_r2", spec.id, `r2-summary:${objectId}`, ingestedAt,
    JSON.stringify({
      kind: "r2_structured_summary",
      key: r2Result.key,
      sha256: r2Result.sha256,
      count: r2Result.count,
      bytes: r2Result.bytes,
    }),
  );
  return { inserted: records.length, revisions: 0 };
}
