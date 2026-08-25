import { sha256HexFromBytes } from "./sha256";
import { r2DatasetSegment, r2DateSegment } from "./write_path_config";

export interface StructuredRecordLine {
  naturalKey: string;
  eventTime?: string;
  availableAt?: string;
  ingestedAt?: string;
  payload: unknown;
  rawPayload?: unknown;
  source?: string;
  dataset?: string;
}

export interface R2WriteResult {
  key: string;
  sha256: string;
  bytes: number;
  count: number;
  etag?: string;
}

function lineFor(r: StructuredRecordLine): string {
  const obj = {
    source: r.source ?? "jquants",
    dataset: r.dataset ?? "",
    natural_key: r.naturalKey,
    event_time: r.eventTime ?? null,
    available_at: r.availableAt ?? null,
    ingested_at: r.ingestedAt ?? null,
    payload: r.payload ?? null,
    raw_payload: r.rawPayload ?? null,
  };
  return JSON.stringify(obj);
}

function pickDate(records: StructuredRecordLine[], fallback: string): string {
  for (const r of records) {
    const seg = r2DateSegment(r.eventTime ?? r.availableAt ?? r.ingestedAt);
    if (seg !== "0000-01-01") return seg;
  }
  return fallback;
}

function todayUtc(): string {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export async function writeJsonlToR2(
  bucket: R2Bucket,
  dataset: string,
  runId: string,
  records: StructuredRecordLine[],
  options?: {
    runDate?: string;
    extraMetadata?: Record<string, string>;
  },
): Promise<R2WriteResult> {
  const lines: string[] = new Array(records.length);
  for (let i = 0; i < records.length; i++) {
    lines[i] = lineFor(records[i]!);
  }
  const body = records.length > 0 ? `${lines.join("\n")}\n` : "";
  const bytes = new TextEncoder().encode(body);
  const sha256 = await sha256HexFromBytes(bytes);
  const dateSeg = pickDate(records, options?.runDate ?? todayUtc());
  const key =
    `structured/jsonl/${r2DatasetSegment(dataset)}/dt=${dateSeg}/${runId}.jsonl`;

  const putResult = await bucket.put(key, body, {
    customMetadata: {
      sha256,
      count: String(records.length),
      bytes: String(bytes.byteLength),
      dataset,
      run_id: runId,
      date: dateSeg,
      schema: "jquants_records/v1",
      ...(options?.extraMetadata ?? {}),
    },
    httpMetadata: {
      contentType: "application/x-ndjson; charset=utf-8",
    },
  });

  return {
    key,
    sha256,
    bytes: bytes.byteLength,
    count: records.length,
    etag: putResult?.etag,
  };
}
