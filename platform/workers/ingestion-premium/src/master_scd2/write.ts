/**
 * equities_master SCD2 write path (R2).
 * Diffs against CURRENT.json; writes only change events + updated snapshot.
 */

import { newRunId } from "../identity";
import { sha256HexFromString } from "../sha256";
import {
  MASTER_EVENT_TYPES,
  computeVersionHash,
  type MasterEventType,
  type MasterRecord,
} from "./types";

const CURRENT_KEY = "structured/scd2/equities_master/CURRENT.json";
const CURRENT_SCHEMA = "equities_master_scd2_current/v1" as const;

export class CurrentParseError extends Error {
  readonly quarantineKey: string | null;
  constructor(message: string, quarantineKey: string | null) {
    super(message);
    this.name = "CurrentParseError";
    this.quarantineKey = quarantineKey;
  }
}

export interface Scd2Env {
  STRUCTURED_BUCKET: R2Bucket;
}

interface CurrentEntry {
  local_code: string;
  version_hash: string;
  attrs: MasterRecord;
  updated_at: string;
}

interface CurrentSnapshot {
  schema: typeof CURRENT_SCHEMA;
  updated_at: string;
  count: number;
  by_code: Record<string, CurrentEntry>;
}

interface Scd2Event {
  event_type: MasterEventType;
  effective_date: string;
  local_code: string;
  prev_hash: string | null;
  new_hash: string | null;
  attrs: MasterRecord | null;
  run_id: string;
}

function jstDate(when: Date): string {
  const ms = when.getTime() + 9 * 60 * 60 * 1000;
  return new Date(ms).toISOString().slice(0, 10);
}

function jstIso(when: Date): string {
  const ms = when.getTime() + 9 * 60 * 60 * 1000;
  return new Date(ms).toISOString().replace(/\.(\d+)Z$/, "+09:00");
}

/** Map J-Quants listed-info style payload → MasterRecord. */
export function payloadToMasterRecord(
  payload: unknown,
  naturalKey: string,
): MasterRecord | null {
  let obj: Record<string, unknown>;
  if (typeof payload === "string") {
    try {
      obj = JSON.parse(payload) as Record<string, unknown>;
    } catch {
      return null;
    }
  } else if (payload && typeof payload === "object") {
    obj = payload as Record<string, unknown>;
  } else {
    return null;
  }
  const code = String(
    obj.Code ?? obj.code ?? obj.LocalCode ?? obj.local_code ?? naturalKey ?? "",
  ).trim();
  if (!code) return null;
  // V2 live payload uses short keys (CoName/S17/S33/Mkt/ScaleCat…). Long
  // names retained for historical or alternate surfaces.
  return {
    local_code: code,
    code_name: String(
      obj.CompanyName ??
        obj.CoName ??
        obj.company_name ??
        obj.Name ??
        obj.name ??
        "",
    ),
    sector_33_code: strOrUndef(
      obj.Sector33Code ?? obj.Sec33Code ?? obj.S33 ?? obj.sector_33_code,
    ),
    sector_33_name: strOrUndef(
      obj.Sector33CodeName ??
        obj.Sec33CodeName ??
        obj.S33Nm ??
        obj.sector_33_name,
    ),
    sector_17_code: strOrUndef(
      obj.Sector17Code ?? obj.Sec17Code ?? obj.S17 ?? obj.sector_17_code,
    ),
    sector_17_name: strOrUndef(
      obj.Sector17CodeName ??
        obj.Sec17CodeName ??
        obj.S17Nm ??
        obj.sector_17_name,
    ),
    scale_code: strOrUndef(
      obj.ScaleCategory ?? obj.ScaleCat ?? obj.scale_code,
    ),
    scale_name: strOrUndef(obj.ScaleCategoryName ?? obj.scale_name),
    listing_date: strOrUndef(
      obj.ListingDate ?? obj.ListDate ?? obj.listing_date,
    ),
    market_code: strOrUndef(
      obj.MarketCode ?? obj.MktCode ?? obj.Mkt ?? obj.market_code,
    ),
    market_name: strOrUndef(
      obj.MarketCodeName ?? obj.MktCodeName ?? obj.MktNm ?? obj.market_name,
    ),
  };
}

function strOrUndef(v: unknown): string | undefined {
  if (v === null || v === undefined || v === "") return undefined;
  return String(v);
}

function emptyCurrent(): CurrentSnapshot {
  return {
    schema: CURRENT_SCHEMA,
    updated_at: "",
    count: 0,
    by_code: {},
  };
}

function parseCurrentSnapshot(raw: string): CurrentSnapshot {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("CURRENT snapshot JSON parse failed");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("CURRENT snapshot is not an object");
  }
  const obj = parsed as Record<string, unknown>;
  if (obj.schema !== CURRENT_SCHEMA) {
    throw new Error("CURRENT snapshot schema mismatch");
  }
  if (
    !obj.by_code ||
    typeof obj.by_code !== "object" ||
    Array.isArray(obj.by_code)
  ) {
    throw new Error("CURRENT snapshot by_code missing or invalid");
  }
  return {
    schema: CURRENT_SCHEMA,
    updated_at: typeof obj.updated_at === "string" ? obj.updated_at : "",
    count:
      typeof obj.count === "number"
        ? obj.count
        : Object.keys(obj.by_code as object).length,
    by_code: obj.by_code as Record<string, CurrentEntry>,
  };
}

async function quarantineCurrent(
  bucket: R2Bucket,
  raw: string,
): Promise<string> {
  const digest = await sha256HexFromString(raw);
  const key = `structured/scd2/equities_master/quarantine/${digest}.json`;
  await bucket.put(key, raw, {
    httpMetadata: { contentType: "application/json" },
    customMetadata: {
      source_key: CURRENT_KEY,
      reason: "parse_failure",
    },
  });
  return key;
}

interface LoadedCurrent {
  snap: CurrentSnapshot;
  etag: string | null;
}

async function loadCurrent(bucket: R2Bucket): Promise<LoadedCurrent> {
  const obj = await bucket.get(CURRENT_KEY);
  if (!obj) return { snap: emptyCurrent(), etag: null };
  const raw = await obj.text();
  try {
    return { snap: parseCurrentSnapshot(raw), etag: obj.etag ?? null };
  } catch (e) {
    let quarantineKey: string | null = null;
    try {
      quarantineKey = await quarantineCurrent(bucket, raw);
    } catch {
      /* still fail closed; never replace CURRENT with an empty snapshot */
    }
    const detail = (e as Error).message || String(e);
    throw new CurrentParseError(
      `CURRENT snapshot unreadable; refusing empty replacement${
        quarantineKey ? `; quarantined ${quarantineKey}` : ""
      }: ${detail}`,
      quarantineKey,
    );
  }
}

async function putImmutable(
  bucket: R2Bucket,
  key: string,
  body: string,
  contentType: string,
  metadata: Record<string, string>,
): Promise<void> {
  const put = await bucket.put(key, body, {
    httpMetadata: { contentType },
    customMetadata: metadata,
    onlyIf: { etagDoesNotMatch: "*" },
  });
  if (put === null) {
    throw new Error(`immutable object already exists: ${key}`);
  }
}

async function putCurrentPointer(
  bucket: R2Bucket,
  body: string,
  metadata: Record<string, string>,
  etag: string | null,
): Promise<void> {
  const onlyIf = etag
    ? { etagMatches: etag }
    : { etagDoesNotMatch: "*" };
  const put = await bucket.put(CURRENT_KEY, body, {
    httpMetadata: { contentType: "application/json" },
    customMetadata: metadata,
    onlyIf,
  });
  if (put === null) {
    throw new Error("CURRENT pointer CAS failed");
  }
}

export interface MasterScd2InputRecord {
  naturalKey: string;
  payload: unknown;
}

/** Trusted full-universe evidence required before DELISTED events. */
export interface MasterScd2UniverseEvidence {
  paginationExhausted: boolean;
  fullUniverse: boolean;
}

export async function writeMasterScd2(
  env: Scd2Env,
  records: MasterScd2InputRecord[],
  when: Date,
  evidence?: MasterScd2UniverseEvidence,
): Promise<{ inserted: number; revisions: number; events_key: string | null }> {
  const runId = newRunId("scd2");
  const asOf = jstDate(when);
  const loaded = await loadCurrent(env.STRUCTURED_BUCKET);
  const prev = loaded.snap;
  const nextByCode: Record<string, CurrentEntry> = {};
  const events: Scd2Event[] = [];
  const incomingCodes = new Set<string>();

  for (const rec of records) {
    const master = payloadToMasterRecord(rec.payload, rec.naturalKey);
    if (!master) continue;
    incomingCodes.add(master.local_code);
    const hash = await computeVersionHash(master);
    const old = prev.by_code[master.local_code];
    nextByCode[master.local_code] = {
      local_code: master.local_code,
      version_hash: hash,
      attrs: master,
      updated_at: jstIso(when),
    };
    if (!old) {
      events.push({
        event_type: MASTER_EVENT_TYPES.LISTED,
        effective_date: asOf,
        local_code: master.local_code,
        prev_hash: null,
        new_hash: hash,
        attrs: master,
        run_id: runId,
      });
    } else if (old.version_hash !== hash) {
      events.push({
        event_type: MASTER_EVENT_TYPES.ATTRIBUTE_CORRECT,
        effective_date: asOf,
        local_code: master.local_code,
        prev_hash: old.version_hash,
        new_hash: hash,
        attrs: master,
        run_id: runId,
      });
    }
  }

  // Delist only with trusted pagination-exhausted / full-universe evidence.
  // Size heuristics (incoming vs previous) are not evidence.
  const prevCodes = Object.keys(prev.by_code);
  const trustedFullUniverse =
    evidence?.paginationExhausted === true && evidence?.fullUniverse === true;
  if (prevCodes.length > 0 && trustedFullUniverse) {
    for (const code of prevCodes) {
      if (!incomingCodes.has(code)) {
        const old = prev.by_code[code]!;
        events.push({
          event_type: MASTER_EVENT_TYPES.DELISTED,
          effective_date: asOf,
          local_code: code,
          prev_hash: old.version_hash,
          new_hash: null,
          attrs: null,
          run_id: runId,
        });
        // keep out of nextByCode
      }
    }
  } else {
    // Partial page: preserve previous codes not in this batch.
    for (const code of prevCodes) {
      if (!nextByCode[code]) nextByCode[code] = prev.by_code[code]!;
    }
  }

  const nextUpdatedAt = jstIso(when);
  if (prev.updated_at && nextUpdatedAt < prev.updated_at) {
    throw new Error(
      `CURRENT pointer is monotonic; refusing ${nextUpdatedAt} after ${prev.updated_at}`,
    );
  }

  const nextSnap: CurrentSnapshot = {
    schema: CURRENT_SCHEMA,
    updated_at: nextUpdatedAt,
    count: Object.keys(nextByCode).length,
    by_code: nextByCode,
  };

  const snapshotKey =
    `structured/scd2/equities_master/snapshots/dt=${asOf}/${runId}.json`;
  await putImmutable(
    env.STRUCTURED_BUCKET,
    snapshotKey,
    JSON.stringify(nextSnap),
    "application/json",
    {
      schema: nextSnap.schema,
      count: String(nextSnap.count),
      run_id: runId,
    },
  );

  let eventsKey: string | null = null;
  if (events.length > 0) {
    eventsKey =
      `structured/scd2/equities_master/events/dt=${asOf}/${runId}.ndjson`;
    const body = events.map((e) => JSON.stringify(e)).join("\n") + "\n";
    await putImmutable(
      env.STRUCTURED_BUCKET,
      eventsKey,
      body,
      "application/x-ndjson",
      {
        count: String(events.length),
        run_id: runId,
        date: asOf,
      },
    );
  }

  const pointer = {
    ...nextSnap,
    snapshot_key: snapshotKey,
    events_key: eventsKey,
  };
  await putCurrentPointer(
    env.STRUCTURED_BUCKET,
    JSON.stringify(pointer),
    {
      schema: nextSnap.schema,
      count: String(nextSnap.count),
      run_id: runId,
      snapshot_key: snapshotKey,
    },
    loaded.etag,
  );

  return { inserted: events.length, revisions: 0, events_key: eventsKey };
}
