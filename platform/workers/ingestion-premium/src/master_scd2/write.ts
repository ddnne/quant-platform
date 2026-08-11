/**
 * equities_master SCD2 write path (R2).
 * Diffs against CURRENT.json; writes only change events + updated snapshot.
 */

import {
  MASTER_EVENT_TYPES,
  computeVersionHash,
  type MasterEventType,
  type MasterRecord,
} from "./types";

const CURRENT_KEY = "structured/scd2/equities_master/CURRENT.json";

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
  schema: "equities_master_scd2_current/v1";
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
  return {
    local_code: code,
    code_name: String(obj.CompanyName ?? obj.company_name ?? obj.Name ?? obj.name ?? ""),
    sector_33_code: strOrUndef(obj.Sector33Code ?? obj.sector_33_code),
    sector_33_name: strOrUndef(obj.Sector33CodeName ?? obj.sector_33_name),
    sector_17_code: strOrUndef(obj.Sector17Code ?? obj.sector_17_code),
    sector_17_name: strOrUndef(obj.Sector17CodeName ?? obj.sector_17_name),
    scale_code: strOrUndef(obj.ScaleCategory ?? obj.scale_code),
    scale_name: strOrUndef(obj.ScaleCategoryName ?? obj.scale_name),
    listing_date: strOrUndef(obj.ListingDate ?? obj.listing_date),
    market_code: strOrUndef(obj.MarketCode ?? obj.market_code),
    market_name: strOrUndef(obj.MarketCodeName ?? obj.market_name),
  };
}

function strOrUndef(v: unknown): string | undefined {
  if (v === null || v === undefined || v === "") return undefined;
  return String(v);
}

async function loadCurrent(bucket: R2Bucket): Promise<CurrentSnapshot> {
  const obj = await bucket.get(CURRENT_KEY);
  if (!obj) {
    return {
      schema: "equities_master_scd2_current/v1",
      updated_at: "",
      count: 0,
      by_code: {},
    };
  }
  try {
    const parsed = (await obj.json()) as CurrentSnapshot;
    if (!parsed.by_code) parsed.by_code = {};
    return parsed;
  } catch {
    return {
      schema: "equities_master_scd2_current/v1",
      updated_at: "",
      count: 0,
      by_code: {},
    };
  }
}

export interface MasterScd2InputRecord {
  naturalKey: string;
  payload: unknown;
}

export async function writeMasterScd2(
  env: Scd2Env,
  records: MasterScd2InputRecord[],
  when: Date,
): Promise<{ inserted: number; revisions: number; events_key: string | null }> {
  const runId = `scd2-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const asOf = jstDate(when);
  const prev = await loadCurrent(env.STRUCTURED_BUCKET);
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

  // Delistings: only when we have a full-universe snapshot (many codes).
  // Avoid false delists on partial pages: require incoming >= 50% of previous.
  const prevCodes = Object.keys(prev.by_code);
  if (
    prevCodes.length > 0 &&
    incomingCodes.size >= Math.max(100, Math.floor(prevCodes.length * 0.5))
  ) {
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

  const nextSnap: CurrentSnapshot = {
    schema: "equities_master_scd2_current/v1",
    updated_at: jstIso(when),
    count: Object.keys(nextByCode).length,
    by_code: nextByCode,
  };

  await env.STRUCTURED_BUCKET.put(
    CURRENT_KEY,
    JSON.stringify(nextSnap),
    {
      httpMetadata: { contentType: "application/json" },
      customMetadata: {
        schema: nextSnap.schema,
        count: String(nextSnap.count),
        run_id: runId,
      },
    },
  );

  let eventsKey: string | null = null;
  if (events.length > 0) {
    eventsKey =
      `structured/scd2/equities_master/events/dt=${asOf}/${runId}.ndjson`;
    const body = events.map((e) => JSON.stringify(e)).join("\n") + "\n";
    await env.STRUCTURED_BUCKET.put(eventsKey, body, {
      httpMetadata: { contentType: "application/x-ndjson" },
      customMetadata: {
        count: String(events.length),
        run_id: runId,
        date: asOf,
      },
    });
  }

  return { inserted: events.length, revisions: 0, events_key: eventsKey };
}
