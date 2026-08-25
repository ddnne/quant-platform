/**
 * Premium structured persist: D1 record upsert and watermark writes.
 * Fetch/upsert stay together in index.ts as the ingestion façade.
 */

import type { DatasetSpec } from "./catalog";
import { pickAvailableAt } from "./availability";
import { naturalKey, newRunId, pickEventTime, stableJson, toJstIso } from "./identity";
import { isR2Only, wantsSummaryChangeLog } from "./write_path_config";
import { writeJsonlToR2 } from "./r2_structured_writer";
import {
  writeMasterScd2,
  type MasterScd2UniverseEvidence,
} from "./master_scd2/write";
import { exponentialBackoffFullJitterMs, sleepMs } from "./retry_jitter";

export type { MasterScd2UniverseEvidence };

export interface PersistEnv {
  DB: D1Database;
  STRUCTURED_BUCKET: R2Bucket;
  MASTER_SCD2_ONLY?: string;
  ALLOW_D1_STRUCTURED_DATASETS?: string;
}

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
     VALUES (
       ?,
       ?,
       ?,
       (SELECT MAX(change_seq) FROM ingestion_change_log WHERE dataset = ?)
     )
     ON CONFLICT(dataset) DO UPDATE SET
       last_event_date  = COALESCE(excluded.last_event_date, ingestion_watermarks.last_event_date),
       last_ingested_at = excluded.last_ingested_at,
       last_export_cursor = COALESCE(
         (SELECT MAX(change_seq) FROM ingestion_change_log WHERE dataset = excluded.dataset),
         ingestion_watermarks.last_export_cursor
       )`,
  ).bind(dataset, lastEventDate, lastIngestedAt, dataset).run();
}

export interface UpsertSummary { inserted: number; revisions: number; }

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

function recordBinds(records: StructuredRecord[]): unknown[] {
  return records.flatMap((record) => [
    record.source,
    record.dataset,
    record.naturalKey,
    record.eventTime,
    record.availableAt,
    record.ingestedAt,
    record.payload,
    record.rawPayload,
  ]);
}

export async function upsertRecords(
  env: PersistEnv,
  spec: DatasetSpec,
  rows: Record<string, unknown>[],
  when: Date,
  evidence?: MasterScd2UniverseEvidence,
): Promise<UpsertSummary> {
  if (rows.length === 0) return { inserted: 0, revisions: 0 };
  const ingestedAt = toJstIso(when);
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

  if (isR2Only(spec.id, env)) {
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
      if (wantsSummaryChangeLog(spec.id)) {
        const summaryPayload = JSON.stringify({
          kind: "scd2_master_summary",
          events_key: scd2.events_key,
          events: scd2.inserted,
        });
        try {
          await d1WithRetry(() =>
            env.DB.prepare(
              `INSERT OR IGNORE INTO ingestion_change_log
               (table_name, source, dataset, natural_key, event_time, available_at,
                ingested_at, payload, raw_payload, changed_at)
               VALUES ('equities_master_scd2', 'jquants', ?, ?, ?, ?, ?, ?, NULL, ?)`,
            ).bind(
              spec.id,
              `scd2-summary:${Date.now()}`,
              toJstIso(when),
              toJstIso(when),
              toJstIso(when),
              summaryPayload,
              toJstIso(when),
            ).run(),
          );
        } catch {
          /* observability only */
        }
      }
      return { inserted: scd2.inserted, revisions: scd2.revisions };
    }

    const runId = newRunId(`r2-${spec.id}`);
    const r2Result = await writeJsonlToR2(
      env.STRUCTURED_BUCKET,
      spec.id,
      runId,
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
    if (wantsSummaryChangeLog(spec.id)) {
      const summaryPayload = JSON.stringify({
        kind: "r2_structured_summary",
        key: r2Result.key,
        sha256: r2Result.sha256,
        count: r2Result.count,
        bytes: r2Result.bytes,
      });
      try {
        await d1WithRetry(() =>
          env.DB.prepare(
            `INSERT OR IGNORE INTO ingestion_change_log
             (table_name, source, dataset, natural_key, event_time, available_at,
              ingested_at, payload, raw_payload, changed_at)
             VALUES ('jquants_records_r2', 'jquants', ?, ?, ?, ?, ?, ?, NULL, ?)`,
          ).bind(
            spec.id,
            `r2-summary:${runId}`,
            toJstIso(when),
            toJstIso(when),
            toJstIso(when),
            summaryPayload,
            toJstIso(when),
          ).run(),
        );
      } catch {
        // Summary change_log is observability-only; never fail the ingest.
      }
    }
    return { inserted: records.length, revisions: 0 };
  }

  const CHUNK = Math.floor(100 / 8); // D1 max 100 binds; 8 fields/row → 12 rows.
  const large = records.length > 200;
  const D1_BATCH_STMTS = large ? 48 : 3;
  let inserted = 0;
  let revisions = 0;
  type Stmt = ReturnType<D1Database["prepare"]>;
  let pending: { stmt: Stmt; archive: boolean }[] = [];

  const flush = async (): Promise<void> => {
    if (pending.length === 0) return;
    const batch = pending;
    pending = [];
    const results = await d1WithRetry(() =>
      env.DB.batch(batch.map((entry) => entry.stmt)),
    );
    batch.forEach((entry, index) => {
      if (entry.archive) {
        revisions += (results[index]?.meta?.changes ?? 0) as number;
      }
    });
  };

  for (let i = 0; i < records.length; i += CHUNK) {
    const chunk = records.slice(i, i + CHUNK);
    const placeholders = chunk.map(() => "(?, ?, ?, ?, ?, ?, ?, ?)").join(", ");
    const binds = recordBinds(chunk);

    const upsertSql =
      `INSERT INTO jquants_records
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       VALUES ${placeholders}
       ON CONFLICT(source, dataset, natural_key) DO UPDATE SET
         event_time = CASE
           WHEN jquants_records.payload IS excluded.payload THEN jquants_records.event_time
           ELSE excluded.event_time END,
         available_at = CASE
           WHEN jquants_records.payload IS excluded.payload
             THEN CASE
               WHEN julianday(jquants_records.available_at)
                    <= julianday(excluded.available_at)
                 THEN jquants_records.available_at
               ELSE excluded.available_at END
           ELSE CASE
             WHEN julianday(excluded.available_at)
                  >= julianday(excluded.ingested_at)
               THEN excluded.available_at
             ELSE excluded.ingested_at END END,
         ingested_at = excluded.ingested_at,
         payload = CASE
           WHEN jquants_records.payload IS excluded.payload THEN jquants_records.payload
           ELSE excluded.payload END,
         raw_payload = CASE
           WHEN jquants_records.payload IS excluded.payload THEN jquants_records.raw_payload
           ELSE excluded.raw_payload END`;

    const archiveSql =
      `WITH incoming
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       AS (VALUES ${placeholders})
       INSERT OR IGNORE INTO jquants_records_revisions
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       SELECT current.source, current.dataset, current.natural_key,
              current.event_time, current.available_at, current.ingested_at,
              current.payload, current.raw_payload
       FROM jquants_records AS current
       JOIN incoming
         ON current.source = incoming.source
        AND current.dataset = incoming.dataset
        AND current.natural_key = incoming.natural_key
       WHERE current.payload IS NOT incoming.payload`;

    // Change feed before primary upsert so it sees the displaced current row.
    const changeSql =
      `WITH incoming
       (source, dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)
       AS (VALUES ${placeholders})
       INSERT OR IGNORE INTO ingestion_change_log
       (table_name, source, dataset, natural_key, event_time, available_at,
        ingested_at, payload, raw_payload, changed_at)
       SELECT 'jquants_records', incoming.source, incoming.dataset,
              incoming.natural_key, incoming.event_time,
              CASE WHEN current.natural_key IS NOT NULL
                         AND current.payload IS NOT incoming.payload
                   THEN CASE
                     WHEN julianday(incoming.available_at)
                          >= julianday(incoming.ingested_at)
                       THEN incoming.available_at
                     ELSE incoming.ingested_at END
                   ELSE incoming.available_at END,
              incoming.ingested_at, incoming.payload, incoming.raw_payload,
              incoming.ingested_at
       FROM incoming
       LEFT JOIN jquants_records AS current
         ON current.source = incoming.source
        AND current.dataset = incoming.dataset
        AND current.natural_key = incoming.natural_key
       WHERE current.natural_key IS NULL
          OR current.payload IS NOT incoming.payload`;

    if (large) {
      pending.push(
        { stmt: env.DB.prepare(archiveSql).bind(...binds), archive: true },
        { stmt: env.DB.prepare(changeSql).bind(...binds), archive: false },
        { stmt: env.DB.prepare(upsertSql).bind(...binds), archive: false },
      );
      if (pending.length >= D1_BATCH_STMTS) await flush();
      continue;
    }

    const existing = await d1WithRetry(() =>
      env.DB.prepare(
        `SELECT natural_key FROM jquants_records
         WHERE source = ? AND dataset = ?
           AND natural_key IN (${chunk.map(() => "?").join(", ")})`,
      ).bind("jquants", spec.id, ...chunk.map((record) => record.naturalKey)).all(),
    );
    inserted += chunk.length - (existing.results?.length ?? 0);
    const batch = await d1WithRetry(() =>
      env.DB.batch([
        env.DB.prepare(archiveSql).bind(...binds),
        env.DB.prepare(changeSql).bind(...binds),
        env.DB.prepare(upsertSql).bind(...binds),
      ]),
    );
    revisions += (batch[0]?.meta?.changes ?? 0) as number;
  }

  await flush();
  if (large) {
    inserted = records.length; // existence SELECT skipped to keep RTT low
  }

  return { inserted, revisions };
}
