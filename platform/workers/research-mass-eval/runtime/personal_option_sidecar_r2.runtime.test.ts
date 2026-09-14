import { env } from "cloudflare:workers";
import { reset } from "cloudflare:test";
import { afterEach, describe, expect, it } from "vitest";

import {
  PERSONAL_OPTION_SIDECAR_AUTHORITY,
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_DATASET,
  PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA,
  PERSONAL_OPTION_SIDECAR_OBJECT_SCHEMA,
  PERSONAL_OPTION_SIDECAR_PERIODS,
  PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
  PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  PERSONAL_OPTION_SIDECAR_SOURCE_VERSION,
  personalOptionSidecarInputKey,
  personalOptionSidecarObjectKey,
  personalOptionSidecarRequestDigest,
  personalOptionSidecarTerminalKey,
  type PersonalOptionSidecarInputManifest,
} from "../src/personal_option_sidecar_producer_contract";
import { personalOptionSidecarR2Outbound } from "../src/personal_option_sidecar_r2";
import { sha256Hex } from "../src/sha256";

const runtimeEnv = env as { STRUCTURED_BUCKET: R2Bucket };
const JOB_ID = "sidecar-r2";

async function seed(key: string, bytes: Uint8Array) {
  const stored = await runtimeEnv.STRUCTURED_BUCKET.put(key, bytes);
  if (!stored) throw new Error(`seed failed: ${key}`);
  return stored;
}

function emptyPeriod(
  period: (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number],
) {
  return {
    period_id: period.period_id,
    year: period.year,
    raw_start: period.raw_start,
    period_start: period.period_start,
    period_end: period.period_end,
    warmup_sessions: period.warmup_sessions,
    evaluation_sessions: period.evaluation_sessions,
    warmup_dates: [],
    evaluation_dates: [],
    calendar_digest: `sha256:${"c".repeat(64)}`,
    raw_input_digest: `sha256:${"d".repeat(64)}`,
    calendar: [],
    options: [],
  };
}

async function identityFields(fixed: Awaited<ReturnType<typeof fixture>>) {
  return {
    schema_version: PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA,
    kind: PERSONAL_OPTION_SIDECAR_KIND,
    job_id: JOB_ID,
    runner_version: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
    input_manifest_digest: fixed.inputDigest,
    input_manifest_key: personalOptionSidecarInputKey(JOB_ID),
    request_digest: await personalOptionSidecarRequestDigest(
      { job_id: JOB_ID },
      fixed.inputDigest,
    ),
    producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
    cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
    ...PERSONAL_OPTION_SIDECAR_AUTHORITY,
  };
}

async function fixture() {
  const input = {
    schema_version: PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA,
    producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
    job_id: JOB_ID,
    cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
    runner_version: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
    dataset: "derivatives_bars_daily_options_225",
    source_version: "research-options-225-vol-series/v1.3",
    duplicate_resolution: {
      natural_key: ["Date", "Code"],
      compare: ["ingested_at", "object_key", "line_index"],
      winner: "lexicographic_max",
    },
    session_calendar: {
      dataset: "markets_calendar",
    },
    periods: Object.fromEntries(
      PERSONAL_OPTION_SIDECAR_PERIODS.map((period) => [
        period.period_id,
        emptyPeriod(period),
      ]),
    ),
  } as unknown as PersonalOptionSidecarInputManifest;
  const inputBytes = new TextEncoder().encode(JSON.stringify(input));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  await seed(personalOptionSidecarInputKey(JOB_ID), inputBytes);
  const headers = {
    "x-option-sidecar-job-id": JOB_ID,
    "x-option-sidecar-input-manifest-key": personalOptionSidecarInputKey(JOB_ID),
    "x-option-sidecar-input-manifest-digest": inputDigest,
  };
  return { headers, inputDigest };
}

function validChild(
  period: (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number],
  locked: { raw_input_digest: string; calendar_digest: string },
) {
  return {
    schema_version: PERSONAL_OPTION_SIDECAR_OBJECT_SCHEMA,
    period_id: period.period_id,
    year: period.year,
    period_start: period.period_start,
    period_end: period.period_end,
    opt225_regime: {
      source: {
        dataset: PERSONAL_OPTION_SIDECAR_DATASET,
        version: PERSONAL_OPTION_SIDECAR_SOURCE_VERSION,
        raw_input_digest: locked.raw_input_digest,
        calendar_digest: locked.calendar_digest,
      },
    },
  };
}

async function put(
  fixed: Awaited<ReturnType<typeof fixture>>,
  key: string,
  document: unknown,
) {
  const bytes = new TextEncoder().encode(JSON.stringify(document));
  const digest = `sha256:${await sha256Hex(bytes)}`;
  const response = await personalOptionSidecarR2Outbound(
    new Request(`http://research.r2/${key}`, {
      method: "PUT",
      headers: {
        ...fixed.headers,
        "content-length": String(bytes.byteLength),
        "x-content-sha256": digest,
      },
      body: bytes,
    }),
    runtimeEnv,
    key,
  );
  return { response, digest, bytes };
}

async function seedChild(document: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(document));
  const digest = `sha256:${await sha256Hex(bytes)}`;
  const key = personalOptionSidecarObjectKey(digest);
  await seed(key, bytes);
  return { bytes, digest, key };
}

async function seedValidChildren() {
  const sidecars: Record<string, Record<string, unknown>> = {};
  for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
    const locked = emptyPeriod(period);
    const seeded = await seedChild(validChild(period, locked));
    sidecars[period.period_id] = {
      period_id: period.period_id,
      year: period.year,
      period_start: period.period_start,
      period_end: period.period_end,
      key: seeded.key,
      sha256: seeded.digest,
      size: seeded.bytes.byteLength,
      raw_input_digest: locked.raw_input_digest,
      calendar_digest: locked.calendar_digest,
    };
  }
  return { sidecars };
}

async function completedTerminal(
  fixed: Awaited<ReturnType<typeof fixture>>,
  sidecars: Record<string, Record<string, unknown>>,
) {
  return {
    ...(await identityFields(fixed)),
    status: "COMPLETED" as const,
    sidecars,
  };
}

describe("option sidecar R2 capability", () => {
  afterEach(() => reset());

  it("denies outbound without the closed identity headers", async () => {
    const response = await personalOptionSidecarR2Outbound(
      new Request("http://research.r2/research/personal/option-sidecar/job=sidecar-r2/manifest.json"),
      runtimeEnv,
      personalOptionSidecarTerminalKey(JOB_ID),
    );
    expect(response.status).toBe(403);
  });

  it("rejects a child write after the terminal and requires children first", async () => {
    const fixed = await fixture();
    const timeout = {
      ...(await identityFields(fixed)),
      status: "FAILED",
      error: "timeout",
    };
    expect(
      (await put(fixed, personalOptionSidecarTerminalKey(JOB_ID), timeout)).response
        .status,
    ).toBe(201);
    const child = { schema_version: "personal-n225-option-sidecar/v1", period_id: "y2021_full" };
    const childBytes = new TextEncoder().encode(JSON.stringify(child));
    const childDigest = `sha256:${await sha256Hex(childBytes)}`;
    const late = await put(
      fixed,
      personalOptionSidecarObjectKey(childDigest),
      child,
    );
    expect(late.response.status).toBe(409);
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalOptionSidecarObjectKey(childDigest),
      ),
    ).toBeNull();
  });

  it("rejects a COMPLETED terminal whose children are missing", async () => {
    const fixed = await fixture();
    const { sidecars } = await seedValidChildren();
    const missingKey = sidecars.y2021_full!.key as string;
    await runtimeEnv.STRUCTURED_BUCKET.delete(missingKey);
    expect(await runtimeEnv.STRUCTURED_BUCKET.head(missingKey)).toBeNull();
    const created = await put(
      fixed,
      personalOptionSidecarTerminalKey(JOB_ID),
      await completedTerminal(fixed, sidecars),
    );
    expect(created.response.status).toBe(409);
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalOptionSidecarTerminalKey(JOB_ID),
      ),
    ).toBeNull();
  });

  it("rejects a forged terminal whose request digest does not match the locked input", async () => {
    const fixed = await fixture();
    const forged = {
      ...(await identityFields(fixed)),
      status: "FAILED",
      request_digest: `sha256:${"e".repeat(64)}`,
      error: "forged",
    };
    expect(
      (await put(fixed, personalOptionSidecarTerminalKey(JOB_ID), forged)).response.status,
    ).toBe(400);
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalOptionSidecarTerminalKey(JOB_ID),
      ),
    ).toBeNull();
  });

  it("publishes a COMPLETE terminal when three distinct valid children exist", async () => {
    const fixed = await fixture();
    const sidecars: Record<string, Record<string, unknown>> = {};
    for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
      const locked = emptyPeriod(period);
      const child = validChild(period, locked);
      const key = personalOptionSidecarObjectKey(
        `sha256:${await sha256Hex(new TextEncoder().encode(JSON.stringify(child)))}`,
      );
      const written = await put(fixed, key, child);
      expect(written.response.status).toBe(201);
      const storedChild = await runtimeEnv.STRUCTURED_BUCKET.get(key);
      expect(storedChild).not.toBeNull();
      expect(new Uint8Array(await storedChild!.arrayBuffer())).toEqual(written.bytes);
      sidecars[period.period_id] = {
        period_id: period.period_id,
        year: period.year,
        period_start: period.period_start,
        period_end: period.period_end,
        key,
        sha256: written.digest,
        size: written.bytes.byteLength,
        raw_input_digest: locked.raw_input_digest,
        calendar_digest: locked.calendar_digest,
      };
    }
    const created = await put(
      fixed,
      personalOptionSidecarTerminalKey(JOB_ID),
      await completedTerminal(fixed, sidecars),
    );
    expect(created.response.status).toBe(201);
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(
      personalOptionSidecarTerminalKey(JOB_ID),
    );
    expect(stored).not.toBeNull();
    expect(stored!.size).toBe(created.bytes.byteLength);
    expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(created.bytes);
    for (const period of PERSONAL_OPTION_SIDECAR_PERIODS) {
      const row = sidecars[period.period_id]!;
      const child = await runtimeEnv.STRUCTURED_BUCKET.head(row.key as string);
      expect(child).not.toBeNull();
      expect(child!.size).toBe(row.size);
    }
  });

  it("rejects a forged COMPLETE terminal that reuses one valid child under all three periods", async () => {
    const fixed = await fixture();
    const { sidecars } = await seedValidChildren();
    const first = sidecars.y2021_full!;
    const reused = Object.fromEntries(
      PERSONAL_OPTION_SIDECAR_PERIODS.map((period) => [
        period.period_id,
        {
          ...sidecars[period.period_id],
          key: first.key,
          sha256: first.sha256,
          size: first.size,
        },
      ]),
    );
    const created = await put(
      fixed,
      personalOptionSidecarTerminalKey(JOB_ID),
      await completedTerminal(fixed, reused),
    );
    expect(created.response.status).toBe(409);
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalOptionSidecarTerminalKey(JOB_ID),
      ),
    ).toBeNull();
  });

  it("rejects an arbitrary JSON child whose HEAD digest and size would otherwise match", async () => {
    const fixed = await fixture();
    const { sidecars } = await seedValidChildren();
    const period = PERSONAL_OPTION_SIDECAR_PERIODS[1]!;
    const junk = { hello: "world", period_id: period.period_id };
    const junkPut = await seedChild(junk);
    const forged = {
      ...sidecars,
      [period.period_id]: {
        ...sidecars[period.period_id],
        key: junkPut.key,
        sha256: junkPut.digest,
        size: junkPut.bytes.byteLength,
      },
    };
    const created = await put(
      fixed,
      personalOptionSidecarTerminalKey(JOB_ID),
      await completedTerminal(fixed, forged),
    );
    expect(created.response.status).toBe(409);
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalOptionSidecarTerminalKey(JOB_ID),
      ),
    ).toBeNull();
  });

  it("rejects a syntactically valid child whose period identity does not match the lock", async () => {
    const fixed = await fixture();
    const { sidecars } = await seedValidChildren();
    const period = PERSONAL_OPTION_SIDECAR_PERIODS[0]!;
    const mismatched = {
      ...validChild(period, emptyPeriod(period)),
      period_id: "y2023_full",
    };
    const childPut = await seedChild(mismatched);
    const forged = {
      ...sidecars,
      [period.period_id]: {
        ...sidecars[period.period_id],
        key: childPut.key,
        sha256: childPut.digest,
        size: childPut.bytes.byteLength,
      },
    };
    const created = await put(
      fixed,
      personalOptionSidecarTerminalKey(JOB_ID),
      await completedTerminal(fixed, forged),
    );
    expect(created.response.status).toBe(409);
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalOptionSidecarTerminalKey(JOB_ID),
      ),
    ).toBeNull();
  });

  it("revalidates children when accepting an idempotent existing COMPLETE terminal", async () => {
    const fixed = await fixture();
    const { sidecars } = await seedValidChildren();
    const terminal = await completedTerminal(fixed, sidecars);
    expect(
      (await put(fixed, personalOptionSidecarTerminalKey(JOB_ID), terminal)).response
        .status,
    ).toBe(201);
    expect(
      (await put(fixed, personalOptionSidecarTerminalKey(JOB_ID), terminal)).response
        .status,
    ).toBe(200);
    const firstKey = sidecars.y2021_full!.key as string;
    await seed(firstKey, new TextEncoder().encode(JSON.stringify({ overwritten: true })));
    expect(
      (await put(fixed, personalOptionSidecarTerminalKey(JOB_ID), terminal)).response
        .status,
    ).toBe(409);
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(
      personalOptionSidecarTerminalKey(JOB_ID),
    );
    expect(stored).not.toBeNull();
    expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(
      new TextEncoder().encode(JSON.stringify(terminal)),
    );
  });
});
