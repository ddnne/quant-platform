import { describe, expect, it } from "vitest";
import { computeVersionHash, MASTER_EVENT_TYPES } from "./types";
import {
  CurrentParseError,
  payloadToMasterRecord,
  writeMasterScd2,
} from "./write";

const CURRENT_KEY = "structured/scd2/equities_master/CURRENT.json";
const WHEN = new Date("2025-04-01T00:00:00.000Z");
const AS_OF = "2025-04-01";
const UPDATED_AT = "2025-04-01T09:00:00+09:00";

function memoryBucket(): {
  bucket: R2Bucket;
  puts: {
    key: string;
    body: string;
    metadata?: Record<string, string>;
  }[];
} {
  const puts: {
    key: string;
    body: string;
    metadata?: Record<string, string>;
  }[] = [];
  const objects = new Map<string, string>();
  const bucket = {
    async get(key: string) {
      const body = objects.get(key);
      if (body === undefined) return null;
      return {
        json: async () => JSON.parse(body),
        text: async () => body,
      };
    },
    async put(
      key: string,
      value: unknown,
      options?: { customMetadata?: Record<string, string> },
    ) {
      const body = typeof value === "string" ? value : "";
      objects.set(key, body);
      puts.push({ key, body, metadata: options?.customMetadata });
      return { key, etag: `mem-${puts.length}` };
    },
  } as unknown as R2Bucket;
  return { bucket, puts };
}

function listedPayload(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    Code: "8697",
    CompanyName: "Japan Exchange Group, Inc.",
    Sector33Code: "7200",
    Sector33CodeName: "Other Financing Business",
    Sector17Code: "15",
    Sector17CodeName: "Financials (Ex Banks)",
    ScaleCategory: "TOPIX Large70",
    MarketCode: "0111",
    MarketCodeName: "Prime",
    ListingDate: "2013-01-01",
    ...overrides,
  };
}

function input(payload: Record<string, unknown>) {
  return { naturalKey: String(payload.Code ?? "8697"), payload };
}

function listedInput(code: string, name = `Name ${code}`) {
  return input(listedPayload({ Code: code, CompanyName: name }));
}

function parseCurrent(body: string): {
  schema: string;
  updated_at: string;
  count: number;
  by_code: Record<
    string,
    { local_code: string; version_hash: string; attrs: unknown; updated_at: string }
  >;
} {
  return JSON.parse(body) as {
    schema: string;
    updated_at: string;
    count: number;
    by_code: Record<
      string,
      { local_code: string; version_hash: string; attrs: unknown; updated_at: string }
    >;
  };
}

function eventPuts(
  puts: { key: string; body: string }[],
  from = 0,
): { key: string; body: string }[] {
  return puts.slice(from).filter((put) => put.key.includes("/events/"));
}

function currentPut(
  puts: { key: string; body: string; metadata?: Record<string, string> }[],
  from = 0,
) {
  const found = puts
    .slice(from)
    .filter((put) => put.key === CURRENT_KEY)
    .at(-1);
  expect(found).toBeDefined();
  return found!;
}

function storedAttrs(
  master: NonNullable<ReturnType<typeof payloadToMasterRecord>>,
) {
  return JSON.parse(JSON.stringify(master)) as Record<string, unknown>;
}

function assertNoCoverageComplete(value: unknown): void {
  expect(JSON.stringify(value)).not.toContain("COMPLETE");
}

describe("writeMasterScd2", () => {
  it("first write creates CURRENT.json with schema equities_master_scd2_current/v1", async () => {
    const { bucket, puts } = memoryBucket();
    const payload = listedPayload();
    const master = payloadToMasterRecord(payload, "8697");
    expect(master).not.toBeNull();
    const hash = await computeVersionHash(master!);

    const result = await writeMasterScd2(
      { STRUCTURED_BUCKET: bucket },
      [input(payload)],
      WHEN,
    );

    const current = currentPut(puts);
    const snap = parseCurrent(current.body);
    expect(snap.schema).toBe("equities_master_scd2_current/v1");
    expect(current.metadata?.schema).toBe("equities_master_scd2_current/v1");
    expect(snap.updated_at).toBe(UPDATED_AT);
    expect(snap.count).toBe(1);
    expect(snap.by_code["8697"]).toEqual({
      local_code: "8697",
      version_hash: hash,
      attrs: storedAttrs(master!),
      updated_at: UPDATED_AT,
    });

    const events = eventPuts(puts);
    expect(events).toHaveLength(1);
    expect(result.events_key).toBe(events[0]!.key);
    expect(result.events_key).toMatch(
      new RegExp(
        `^structured/scd2/equities_master/events/dt=${AS_OF}/scd2-.+\\.ndjson$`,
      ),
    );
    const rows = events[0]!.body
      .split("\n")
      .filter((line) => line.length > 0)
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      event_type: MASTER_EVENT_TYPES.LISTED,
      effective_date: AS_OF,
      local_code: "8697",
      prev_hash: null,
      new_hash: hash,
      attrs: storedAttrs(master!),
    });
    expect(result.inserted).toBe(1);
    expect(result.revisions).toBe(0);

    assertNoCoverageComplete(snap);
    assertNoCoverageComplete(current.metadata);
    assertNoCoverageComplete(rows);
    assertNoCoverageComplete(result);
    expect(puts.every((put) => !put.key.includes("COMPLETE"))).toBe(true);
  });

  it("unchanged attrs rewrite CURRENT but emit no extra event (events_key null)", async () => {
    const { bucket, puts } = memoryBucket();
    const payload = listedPayload();
    const env = { STRUCTURED_BUCKET: bucket };
    const first = await writeMasterScd2(env, [input(payload)], WHEN);
    expect(first.inserted).toBe(1);
    expect(first.events_key).not.toBeNull();
    const afterFirst = puts.length;
    const firstHash = parseCurrent(currentPut(puts).body).by_code["8697"]!
      .version_hash;

    const later = new Date("2025-04-02T00:00:00.000Z");
    const second = await writeMasterScd2(env, [input(payload)], later);

    expect(second.inserted).toBe(0);
    expect(second.revisions).toBe(0);
    expect(second.events_key).toBeNull();
    expect(eventPuts(puts, afterFirst)).toHaveLength(0);

    const current = currentPut(puts, afterFirst);
    const snap = parseCurrent(current.body);
    expect(snap.schema).toBe("equities_master_scd2_current/v1");
    expect(snap.by_code["8697"]!.version_hash).toBe(firstHash);
    expect(snap.by_code["8697"]!.updated_at).toBe("2025-04-02T09:00:00+09:00");
    expect(snap.count).toBe(1);

    assertNoCoverageComplete(second);
    assertNoCoverageComplete(snap);
    assertNoCoverageComplete(current.metadata);
  });

  it("changed attrs write ATTRIBUTE_CORRECT event and updated CURRENT", async () => {
    const { bucket, puts } = memoryBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const original = listedPayload();
    const first = await writeMasterScd2(env, [input(original)], WHEN);
    expect(first.inserted).toBe(1);
    const afterFirst = puts.length;
    const prevHash = parseCurrent(currentPut(puts).body).by_code["8697"]!
      .version_hash;

    const changed = listedPayload({ CompanyName: "JPX Group, Inc." });
    const master = payloadToMasterRecord(changed, "8697");
    expect(master).not.toBeNull();
    const newHash = await computeVersionHash(master!);
    expect(newHash).not.toBe(prevHash);

    const later = new Date("2025-04-02T00:00:00.000Z");
    const second = await writeMasterScd2(env, [input(changed)], later);

    const current = currentPut(puts, afterFirst);
    const snap = parseCurrent(current.body);
    expect(snap.schema).toBe("equities_master_scd2_current/v1");
    expect(snap.by_code["8697"]).toEqual({
      local_code: "8697",
      version_hash: newHash,
      attrs: storedAttrs(master!),
      updated_at: "2025-04-02T09:00:00+09:00",
    });

    const events = eventPuts(puts, afterFirst);
    expect(events).toHaveLength(1);
    expect(second.events_key).toBe(events[0]!.key);
    expect(second.events_key).toMatch(
      /^structured\/scd2\/equities_master\/events\/dt=2025-04-02\/scd2-.+\.ndjson$/,
    );
    const rows = events[0]!.body
      .split("\n")
      .filter((line) => line.length > 0)
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      event_type: MASTER_EVENT_TYPES.ATTRIBUTE_CORRECT,
      effective_date: "2025-04-02",
      local_code: "8697",
      prev_hash: prevHash,
      new_hash: newHash,
      attrs: storedAttrs(master!),
    });
    expect(second.inserted).toBe(1);
    expect(second.revisions).toBe(0);

    assertNoCoverageComplete(snap);
    assertNoCoverageComplete(current.metadata);
    assertNoCoverageComplete(rows);
    assertNoCoverageComplete(second);
  });

  it("CURRENT parse failure quarantines the body and does not write an empty snapshot", async () => {
    const { bucket, puts } = memoryBucket();
    const corrupt = "{not-json";
    await bucket.put(CURRENT_KEY, corrupt);
    const afterSeed = puts.length;

    await expect(
      writeMasterScd2(
        { STRUCTURED_BUCKET: bucket },
        [input(listedPayload())],
        WHEN,
      ),
    ).rejects.toBeInstanceOf(CurrentParseError);

    expect(puts.slice(afterSeed).some((put) => put.key === CURRENT_KEY)).toBe(
      false,
    );
    expect(currentPut(puts).body).toBe(corrupt);

    const quarantines = puts
      .slice(afterSeed)
      .filter((put) =>
        put.key.startsWith("structured/scd2/equities_master/quarantine/"),
      );
    expect(quarantines).toHaveLength(1);
    expect(quarantines[0]!.body).toBe(corrupt);
    expect(quarantines[0]!.metadata?.reason).toBe("parse_failure");
    expect(quarantines[0]!.key).not.toContain("COMPLETE");
    assertNoCoverageComplete(quarantines);
    assertNoCoverageComplete(puts.slice(afterSeed).map((put) => put.key));
  });

  it("CURRENT schema or by_code failure quarantines and leaves CURRENT in place", async () => {
    const { bucket, puts } = memoryBucket();
    const invalid = JSON.stringify({
      schema: "not-a-current-schema",
      updated_at: UPDATED_AT,
      count: 0,
    });
    await bucket.put(CURRENT_KEY, invalid);
    const afterSeed = puts.length;

    const err = await writeMasterScd2(
      { STRUCTURED_BUCKET: bucket },
      [input(listedPayload())],
      WHEN,
    ).then(
      () => null,
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(CurrentParseError);
    expect((err as CurrentParseError).quarantineKey).toMatch(
      /^structured\/scd2\/equities_master\/quarantine\/[0-9a-f]{64}\.json$/,
    );
    expect(puts.slice(afterSeed).some((put) => put.key === CURRENT_KEY)).toBe(
      false,
    );
    expect(currentPut(puts).body).toBe(invalid);
    expect(JSON.stringify(err)).not.toContain("COMPLETE");
    assertNoCoverageComplete(puts.slice(afterSeed));
  });

  it("partial page without trusted universe evidence preserves prior codes and emits no DELISTED", async () => {
    const { bucket, puts } = memoryBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    await writeMasterScd2(
      env,
      [listedInput("8697"), listedInput("7203"), listedInput("6758")],
      WHEN,
    );
    const afterFirst = puts.length;

    const later = new Date("2025-04-02T00:00:00.000Z");
    const second = await writeMasterScd2(
      env,
      [listedInput("8697"), listedInput("7203")],
      later,
    );

    const snap = parseCurrent(currentPut(puts, afterFirst).body);
    expect(snap.count).toBe(3);
    expect(Object.keys(snap.by_code).sort()).toEqual(["6758", "7203", "8697"]);
    const events = eventPuts(puts, afterFirst);
    expect(events).toHaveLength(0);
    expect(second.events_key).toBeNull();
    expect(second.inserted).toBe(0);
    assertNoCoverageComplete(snap);
    assertNoCoverageComplete(second);
  });

  it("DELISTED only with paginationExhausted and fullUniverse evidence", async () => {
    const { bucket, puts } = memoryBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    await writeMasterScd2(
      env,
      [listedInput("8697"), listedInput("7203"), listedInput("6758")],
      WHEN,
    );
    const afterFirst = puts.length;
    const prevHash = parseCurrent(currentPut(puts).body).by_code["6758"]!
      .version_hash;

    const later = new Date("2025-04-02T00:00:00.000Z");
    const exhaustedOnly = await writeMasterScd2(
      env,
      [listedInput("8697"), listedInput("7203")],
      later,
      { paginationExhausted: true, fullUniverse: false },
    );
    expect(parseCurrent(currentPut(puts, afterFirst).body).count).toBe(3);
    expect(exhaustedOnly.events_key).toBeNull();
    const afterPartial = puts.length;

    const trusted = await writeMasterScd2(
      env,
      [listedInput("8697"), listedInput("7203")],
      later,
      { paginationExhausted: true, fullUniverse: true },
    );
    const snap = parseCurrent(currentPut(puts, afterPartial).body);
    expect(snap.count).toBe(2);
    expect(snap.by_code["6758"]).toBeUndefined();
    expect(Object.keys(snap.by_code).sort()).toEqual(["7203", "8697"]);

    const events = eventPuts(puts, afterPartial);
    expect(events).toHaveLength(1);
    const rows = events[0]!.body
      .split("\n")
      .filter((line) => line.length > 0)
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      event_type: MASTER_EVENT_TYPES.DELISTED,
      effective_date: "2025-04-02",
      local_code: "6758",
      prev_hash: prevHash,
      new_hash: null,
      attrs: null,
    });
    expect(trusted.inserted).toBe(1);
    expect(trusted.events_key).toBe(events[0]!.key);
    assertNoCoverageComplete(snap);
    assertNoCoverageComplete(rows);
    assertNoCoverageComplete(trusted);
  });
});
