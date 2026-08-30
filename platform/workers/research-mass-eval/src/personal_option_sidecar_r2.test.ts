import { describe, expect, it } from "vitest";

import {
  PERSONAL_OPTION_SIDECAR_AUTHORITY,
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA,
  PERSONAL_OPTION_SIDECAR_PERIODS,
  PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
  PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  personalOptionSidecarInputKey,
  personalOptionSidecarObjectKey,
  personalOptionSidecarRequestDigest,
  personalOptionSidecarTerminalKey,
  type PersonalOptionSidecarInputManifest,
} from "./personal_option_sidecar_producer_contract";
import { personalOptionSidecarR2Outbound } from "./personal_option_sidecar_r2";
import { sha256Hex } from "./sha256";

type Stored = {
  bytes: Uint8Array;
  etag: string;
  customMetadata: Record<string, string>;
  checksums: R2Checksums;
};

class MemoryR2 {
  readonly values = new Map<string, Stored>();
  readonly writes: string[] = [];

  seed(key: string, value: Uint8Array | string, etag = `etag-${key}`) {
    const bytes =
      typeof value === "string" ? new TextEncoder().encode(value) : value;
    this.values.set(key, {
      bytes,
      etag,
      customMetadata: {},
      checksums: {},
    });
  }

  object(key: string, stored: Stored) {
    return {
      key,
      size: stored.bytes.byteLength,
      etag: stored.etag,
      customMetadata: stored.customMetadata,
      checksums: stored.checksums,
      arrayBuffer: async () => stored.bytes.slice().buffer,
    };
  }

  async get(key: string) {
    const stored = this.values.get(key);
    return stored ? this.object(key, stored) : null;
  }

  async head(key: string) {
    return this.get(key);
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: R2PutOptions,
  ) {
    if (
      options?.onlyIf &&
      "etagDoesNotMatch" in options.onlyIf &&
      options.onlyIf.etagDoesNotMatch === "*" &&
      this.values.has(key)
    ) {
      return null;
    }
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : ArrayBuffer.isView(value)
          ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
          : new Uint8Array(value).slice();
    const digest = options?.customMetadata?.sha256 ?? "";
    this.values.set(key, {
      bytes,
      etag: `put-${this.writes.length}`,
      customMetadata: options?.customMetadata ?? {},
      checksums: options?.sha256 ? { sha256: options.sha256 } : {},
    });
    this.writes.push(key);
    const stored = this.values.get(key)!;
    if (digest) stored.customMetadata.sha256 = digest;
    return this.object(key, stored);
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

const JOB_ID = "sidecar-r2";

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
  const mem = new MemoryR2();
  mem.seed(personalOptionSidecarInputKey(JOB_ID), inputBytes, "input");
  const headers = {
    "x-option-sidecar-job-id": JOB_ID,
    "x-option-sidecar-input-manifest-key": personalOptionSidecarInputKey(JOB_ID),
    "x-option-sidecar-input-manifest-digest": inputDigest,
  };
  return { mem, headers, inputDigest };
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
    { STRUCTURED_BUCKET: fixed.mem.asBucket() },
    key,
  );
  return { response, digest, bytes };
}

describe("option sidecar R2 capability", () => {
  it("denies outbound without the closed identity headers", async () => {
    const fixed = await fixture();
    const response = await personalOptionSidecarR2Outbound(
      new Request("http://research.r2/research/personal/option-sidecar/job=sidecar-r2/manifest.json"),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
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
  });

  it("rejects a COMPLETED terminal whose children are missing", async () => {
    const fixed = await fixture();
    const sidecars = Object.fromEntries(
      PERSONAL_OPTION_SIDECAR_PERIODS.map((period) => [
        period.period_id,
        {
          period_id: period.period_id,
          key: personalOptionSidecarObjectKey(`sha256:${"e".repeat(64)}`),
          sha256: `sha256:${"e".repeat(64)}`,
          size: 4,
        },
      ]),
    );
    const terminal = {
      ...(await identityFields(fixed)),
      status: "COMPLETED",
      sidecars,
    };
    const created = await put(fixed, personalOptionSidecarTerminalKey(JOB_ID), terminal);
    expect(created.response.status).toBe(409);
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
  });
});
