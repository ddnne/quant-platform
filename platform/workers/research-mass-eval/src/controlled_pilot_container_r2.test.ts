import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import pythonTerminalFixture from "../../../../tests/fixtures/controlled_pilot_python_terminals.json";
import {
  CONTROLLED_PILOT_RUNNER_VERSION,
  controlledPilotContainerName,
} from "./controlled_pilot_contract";
import {
  CONTROLLED_JSON_TYPE,
  CONTROLLED_LEASE_CLOCK_SKEW_SECONDS,
  CONTROLLED_LEASE_MAX_BYTES,
  CONTROLLED_LEASE_STORED_MAX_BYTES,
  CONTROLLED_LEASE_TTL_SECONDS,
  CONTROLLED_TERMINAL_MAX_BYTES,
  controlledContainerR2Outbound,
  controlledPilotWriterR2Outbound,
  readBoundedBody,
  type BoundedReadTrace,
} from "./controlled_pilot_container_r2";

const THREE_BYTE_SHA256 =
  "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81";
const TRUSTED_NOW_MS = Date.parse("2026-09-02T00:00:00.000Z");

function hex(bytes: ArrayBuffer | ArrayBufferView): string {
  const view = ArrayBuffer.isView(bytes)
    ? new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    : new Uint8Array(bytes);
  return [...view].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function sha256(bytes: Uint8Array): Promise<string> {
  return `sha256:${hex(await crypto.subtle.digest("SHA-256", bytes))}`;
}

type StoredObject = {
  body: Uint8Array;
  etag: string;
  customMetadata?: Record<string, string>;
};

type BucketHooks = {
  afterLeaseGet?: () => void | Promise<void>;
  beforePut?: (key: string) => void;
  contentHashEtag?: boolean;
};

function casBucket(hooks?: BucketHooks) {
  const objects = new Map<string, StoredObject>();
  let generation = 0;
  const bucket = {
    objects,
    head: async (key: string) => {
      const stored = objects.get(key);
      if (!stored) return null;
      return {
        key,
        size: stored.body.byteLength,
        etag: stored.etag,
        httpEtag: `"${stored.etag}"`,
        customMetadata: stored.customMetadata,
      };
    },
    get: async (key: string) => {
      const stored = objects.get(key);
      if (!stored) return null;
      const snapshot = {
        key,
        size: stored.body.byteLength,
        etag: stored.etag,
        httpEtag: `"${stored.etag}"`,
        customMetadata: stored.customMetadata ? { ...stored.customMetadata } : undefined,
        arrayBuffer: async () =>
          stored.body.buffer.slice(
            stored.body.byteOffset,
            stored.body.byteOffset + stored.body.byteLength,
          ),
      };
      if (key.endsWith("/container-lease.json") && hooks?.afterLeaseGet) {
        const takeover = hooks.afterLeaseGet;
        hooks.afterLeaseGet = undefined;
        await takeover();
      }
      return snapshot;
    },
    put: async (
      key: string,
      value: ArrayBuffer | Uint8Array,
      options?: {
        onlyIf?: { etagDoesNotMatch?: string; etagMatches?: string };
        customMetadata?: Record<string, string>;
      },
    ) => {
      if (hooks?.beforePut) hooks.beforePut(key);
      const stored = objects.get(key);
      if (options?.onlyIf?.etagDoesNotMatch === "*" && stored) return null;
      if (options?.onlyIf?.etagMatches) {
        const match = options.onlyIf.etagMatches;
        if (match.includes('"') || match === "*" || /^W\//i.test(match)) {
          throw new Error("Conditional ETag should not be wrapped in quotes");
        }
        if (!stored || stored.etag !== match) return null;
      }
      const body = value instanceof Uint8Array ? value : new Uint8Array(value as ArrayBuffer);
      generation += 1;
      const etag = hooks?.contentHashEtag
        ? `ch-${await sha256(body)}`
        : `etag-${generation}`;
      objects.set(key, {
        body,
        etag,
        customMetadata: options?.customMetadata ? { ...options.customMetadata } : undefined,
      });
      return { key, etag, httpEtag: `"${etag}"`, size: body.byteLength };
    },
  };
  return bucket as typeof bucket & R2Bucket;
}

const jobId = "controlled-job-3";
const requestDigest = `sha256:${"ab".repeat(32)}`;
const identityHeaders = {
  "content-type": CONTROLLED_JSON_TYPE,
  "x-personal-job-id": jobId,
  "x-personal-request-digest": requestDigest,
  "x-personal-runner-version": CONTROLLED_PILOT_RUNNER_VERSION,
  "x-personal-job-kind": "controlled-pilot",
};

function nowSeconds(): number {
  return Date.now() / 1000;
}

function fourRecords(pad = 0) {
  return [
    { k: 1, ...(pad > 0 ? { pad: "x".repeat(pad) } : {}) },
    { k: 2 },
    { k: 3 },
    { k: 4 },
  ];
}

function completedTerminal(owner: string, token: number, pad = 0) {
  return {
    ok: true,
    identity: "controlled_pilot_v1",
    job_id: jobId,
    request_digest: requestDigest,
    execution_id: requestDigest,
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    status: "COMPLETED",
    owner_nonce: owner,
    fencing_token: token,
    automatic_promotion: false,
    live_orders_enabled: false,
    ephemeral_cleaned: true,
    papers: fourRecords(pad),
    risks: fourRecords(),
    selection: { decision: "HOLD" },
    knowledge: { kind: "knowledge" },
    generation: 1,
    max_parallel: 2,
  };
}

function failedTerminal(owner: string, token: number, error = "controlled_execution_failed") {
  return {
    ok: false,
    identity: "controlled_pilot_v1",
    job_id: jobId,
    request_digest: requestDigest,
    execution_id: requestDigest,
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    status: "FAILED",
    owner_nonce: owner,
    fencing_token: token,
    error,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
  };
}

function stageLike(status: string, owner: string, token: number, pad = 0) {
  return status === "FAILED"
    ? failedTerminal(owner, token)
    : completedTerminal(owner, token, pad);
}

function leaseDoc(
  owner: string,
  token: number,
  extras: { expires_at?: number; heartbeat_at?: number; execution_id?: string } = {},
) {
  const heartbeat = extras.heartbeat_at ?? nowSeconds();
  return {
    identity: "controlled_pilot_v1",
    job_id: jobId,
    request_digest: requestDigest,
    execution_id: extras.execution_id ?? requestDigest,
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    kind: "controlled-pilot",
    owner_nonce: owner,
    fencing_token: token,
    expires_at: extras.expires_at ?? heartbeat + CONTROLLED_LEASE_TTL_SECONDS,
    heartbeat_at: heartbeat,
    status: "CLAIMED",
  };
}

function leaseKeyOf(id = jobId): string {
  return `research/controlled_pilot/v1/jobs/${id}/container-lease.json`;
}

function terminalKeyOf(id = jobId): string {
  return `research/controlled_pilot/v1/jobs/${id}/container-terminal.json`;
}

async function outbound(
  env: { STRUCTURED_BUCKET: R2Bucket },
  key: string,
  init: RequestInit,
): Promise<Response> {
  const response = await controlledContainerR2Outbound(
    new Request(`http://research.r2/${key}`, init),
    env,
    key,
  );
  if (!response) throw new Error("router did not handle key");
  return response;
}

async function putJson(
  env: { STRUCTURED_BUCKET: R2Bucket },
  key: string,
  value: unknown,
  extra: Record<string, string> = {},
) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const digest = await sha256(bytes);
  return outbound(env, key, {
    method: "PUT",
    headers: {
      ...identityHeaders,
      "content-length": String(bytes.byteLength),
      "x-content-sha256": digest,
      ...extra,
    },
    body: bytes,
  });
}

async function getObject(
  env: { STRUCTURED_BUCKET: R2Bucket },
  key: string,
  method: "GET" | "HEAD" = "GET",
) {
  return outbound(env, key, {
    method,
    headers: identityHeaders,
  });
}

function parseLease(bucket: ReturnType<typeof casBucket>, key = leaseKeyOf()): Record<string, unknown> {
  const stored = bucket.objects.get(key);
  if (!stored) throw new Error("lease missing");
  return JSON.parse(new TextDecoder().decode(stored.body)) as Record<string, unknown>;
}

function leaseEtag(bucket: ReturnType<typeof casBucket>): string {
  return bucket.objects.get(leaseKeyOf())!.etag;
}

describe("controlled writer platform binding", () => {
  it("rejects forged controlled headers unless params and actual container id match", async () => {
    const bucket = casBucket();
    const containerName = await controlledPilotContainerName(jobId);
    const expectedContainerId = `do:${containerName}`;
    const env = {
      STRUCTURED_BUCKET: bucket,
      PERSONAL_RESEARCH_CONTAINER: {
        idFromName: (name: string) => ({
          toString: () => `do:${name}`,
        }),
      },
    };
    const key = `research/controlled_pilot/v1/jobs/${jobId}/container-stage.json`;
    const stage = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      status: "QUEUED",
    };
    const bytes = new TextEncoder().encode(JSON.stringify(stage));
    const digest = await sha256(bytes);
    const request = () => new Request(`http://research.r2/${key}`, {
      method: "PUT",
      headers: {
        ...identityHeaders,
        "content-length": String(bytes.byteLength),
        "x-content-sha256": digest,
      },
      body: bytes,
    });
    const params = { job_id: jobId, request_digest: requestDigest };

    const spoofed = await controlledPilotWriterR2Outbound(request(), env, {
      containerId: "do:unrelated-personal-container",
      className: "PersonalResearchContainer",
      params,
    });
    expect(spoofed.status).toBe(403);
    expect(bucket.objects.size).toBe(0);

    const poisonedParams = await controlledPilotWriterR2Outbound(request(), env, {
      containerId: expectedContainerId,
      className: "PersonalResearchContainer",
      params: { ...params, request_digest: `sha256:${"cd".repeat(32)}` },
    });
    expect(poisonedParams.status).toBe(403);
    expect(bucket.objects.size).toBe(0);

    const written = await controlledPilotWriterR2Outbound(request(), env, {
      containerId: expectedContainerId,
      className: "PersonalResearchContainer",
      params,
    });
    expect(written.status).toBe(201);
    expect(bucket.objects.has(key)).toBe(true);
  });
});

describe("controlled terminal atomic CAS", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(TRUSTED_NOW_MS);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("matches the stored-lease envelope formula and policy TTL", () => {
    expect(CONTROLLED_LEASE_TTL_SECONDS).toBe(1800);
    expect(CONTROLLED_LEASE_STORED_MAX_BYTES).toBe(
      CONTROLLED_LEASE_MAX_BYTES +
        Math.ceil(CONTROLLED_TERMINAL_MAX_BYTES / 3) * 4 +
        2048,
    );
  });

  it("accepts the exact Python production terminal fixture across the Worker boundary", async () => {
    const completed = pythonTerminalFixture.completed;
    const fixtureJobId = completed.job_id;
    const fixtureDigest = completed.request_digest;
    const fixtureLeaseKey = leaseKeyOf(fixtureJobId);
    const fixtureTerminalKey = terminalKeyOf(fixtureJobId);
    const fixtureHeaders = {
      "content-type": CONTROLLED_JSON_TYPE,
      "x-personal-job-id": fixtureJobId,
      "x-personal-request-digest": fixtureDigest,
      "x-personal-runner-version": completed.runner_version,
      "x-personal-job-kind": "controlled-pilot",
    };
    const heartbeat = nowSeconds();
    const lease = {
      identity: completed.identity,
      job_id: fixtureJobId,
      request_digest: fixtureDigest,
      execution_id: completed.execution_id,
      runner_version: completed.runner_version,
      kind: "controlled-pilot",
      owner_nonce: completed.owner_nonce,
      fencing_token: completed.fencing_token,
      expires_at: heartbeat + CONTROLLED_LEASE_TTL_SECONDS,
      heartbeat_at: heartbeat,
      status: "CLAIMED",
    };
    const putFixture = async (
      key: string,
      value: unknown,
      extra: Record<string, string>,
    ): Promise<Response> => {
      const bytes = new TextEncoder().encode(JSON.stringify(value));
      return outbound({ STRUCTURED_BUCKET: bucket }, key, {
        method: "PUT",
        headers: {
          ...fixtureHeaders,
          "content-length": String(bytes.byteLength),
          "x-content-sha256": await sha256(bytes),
          ...extra,
        },
        body: bytes,
      });
    };
    const bucket = casBucket();
    expect(
      (await putFixture(fixtureLeaseKey, lease, { "if-none-match": "*" }))
        .status,
    ).toBe(201);
    const published = await putFixture(fixtureTerminalKey, completed, {
      "x-personal-lease-owner": completed.owner_nonce,
      "x-personal-fencing-token": String(completed.fencing_token),
    });
    expect(published.status).toBe(201);
    const got = await outbound(
      { STRUCTURED_BUCKET: bucket },
      fixtureTerminalKey,
      { method: "GET", headers: fixtureHeaders },
    );
    expect(got.status).toBe(200);
    expect(await got.json()).toEqual(completed);
  });

  it("crash before CAS leaves CLAIMED; trusted expiry then exact token+1 takeover", async () => {
    const hooks: BucketHooks = {};
    const bucket = casBucket(hooks);
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const created = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    expect(created.status).toBe(201);

    hooks.beforePut = (key: string) => {
      if (key === leaseKey) throw new Error("crash-before-cas");
    };
    await expect(
      putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
      }),
    ).rejects.toThrow("crash-before-cas");
    expect(parseLease(bucket).status).toBe("CLAIMED");
    expect(bucket.objects.has(terminalKey)).toBe(false);
    expect((await getObject(env, terminalKey)).status).toBe(404);

    hooks.beforePut = undefined;
    const selfExpire = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", 1, { expires_at: nowSeconds() - 30, heartbeat_at: nowSeconds() - 30 }),
      { "if-match": leaseEtag(bucket) },
    );
    expect(selfExpire.status).toBe(400);
    expect(Number(parseLease(bucket).expires_at)).toBeGreaterThan(nowSeconds());

    vi.setSystemTime(TRUSTED_NOW_MS + (CONTROLLED_LEASE_TTL_SECONDS + 1) * 1000);
    const stale = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(stale.status).toBe(409);

    const takeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": leaseEtag(bucket),
    });
    expect(takeover.status).toBe(200);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-2");
    expect(parseLease(bucket).fencing_token).toBe(2);
    expect(parseLease(bucket).status).toBe("CLAIMED");

    const recovered = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-2", 2), {
      "x-personal-lease-owner": "owner-nonce-2",
      "x-personal-fencing-token": "2",
    });
    expect(recovered.status).toBe(201);
    const got = await getObject(env, terminalKey);
    expect(got.status).toBe(200);
    expect(JSON.parse(await got.text()).status).toBe("COMPLETED");
  });

  it("atomic terminal success then forbids takeover and a second different terminal", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const created = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    expect(created.status).toBe(201);
    const etag = (await created.json() as { etag: string }).etag;
    const published = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": etag,
    });
    expect(published.status).toBe(201);
    expect(parseLease(bucket).status).toBe("TERMINAL");
    expect(parseLease(bucket).heartbeat_at).toBe(nowSeconds());
    expect(bucket.objects.has(terminalKey)).toBe(false);

    const got = await getObject(env, terminalKey);
    expect(got.status).toBe(200);
    const terminalBytes = new Uint8Array(await got.arrayBuffer());
    expect(JSON.parse(new TextDecoder().decode(terminalBytes)).status).toBe("COMPLETED");
    expect(got.headers.get("content-length")).toBe(String(terminalBytes.byteLength));
    expect(got.headers.get("x-content-sha256")).toBe(await sha256(terminalBytes));

    const head = await getObject(env, terminalKey, "HEAD");
    expect(head.status).toBe(200);
    expect(head.headers.get("content-length")).toBe(String(terminalBytes.byteLength));

    const takeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": leaseEtag(bucket),
    });
    expect(takeover.status).toBe(412);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-1");
    expect(parseLease(bucket).status).toBe("TERMINAL");
  });

  it("denies an expired old owner terminal PUT; takeover uses trusted now and token+1", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    vi.setSystemTime(TRUSTED_NOW_MS + (CONTROLLED_LEASE_TTL_SECONDS + 5) * 1000);
    const denied = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(denied.status).toBe(409);
    expect(parseLease(bucket).status).toBe("CLAIMED");
    expect((await getObject(env, terminalKey)).status).toBe(404);
    const takeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": leaseEtag(bucket),
    });
    expect(takeover.status).toBe(200);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-2");
    expect(parseLease(bucket).fencing_token).toBe(2);
  });

  it("unexpired cross-owner takeover is denied even with the current ETag", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const before = bucket.objects.get(leaseKey)!.body.slice();
    const takeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": leaseEtag(bucket),
    });
    expect([409, 412]).toContain(takeover.status);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-1");
    expect(parseLease(bucket).fencing_token).toBe(1);
    expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
  });

  it("same-owner renewal preserves identity and moves heartbeat/expiry monotonically", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const original = parseLease(bucket);
    vi.setSystemTime(TRUSTED_NOW_MS + 15_000);
    const renewed = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": leaseEtag(bucket),
    });
    expect(renewed.status).toBe(200);
    const next = parseLease(bucket);
    expect(next.identity).toBe(original.identity);
    expect(next.job_id).toBe(original.job_id);
    expect(next.request_digest).toBe(original.request_digest);
    expect(next.execution_id).toBe(original.execution_id);
    expect(next.runner_version).toBe(original.runner_version);
    expect(next.kind).toBe(original.kind);
    expect(next.owner_nonce).toBe("owner-nonce-1");
    expect(next.fencing_token).toBe(1);
    expect(Number(next.heartbeat_at)).toBeGreaterThan(Number(original.heartbeat_at));
    expect(Number(next.expires_at)).toBeGreaterThanOrEqual(Number(original.expires_at));
  });

  it("illegal identity, token, heartbeat, and expiry mutations are denied", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const etag = leaseEtag(bucket);
    const original = parseLease(bucket);
    vi.setSystemTime(TRUSTED_NOW_MS + 10_000);
    const otherDigest = `sha256:${"cd".repeat(32)}`;
    const identity = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", 1, { execution_id: otherDigest }),
      { "if-match": etag },
    );
    expect(identity.status).toBe(409);
    const tokenBump = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 2), {
      "if-match": etag,
    });
    expect(tokenBump.status).toBe(409);
    const backHeartbeat = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", 1, { heartbeat_at: Number(original.heartbeat_at) }),
      { "if-match": etag },
    );
    expect(backHeartbeat.status).toBe(409);
    const backExpiry = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", 1, {
        heartbeat_at: nowSeconds(),
        expires_at: Number(original.expires_at) - 1,
      }),
      { "if-match": etag },
    );
    expect(backExpiry.status).toBe(409);
    const farFuture = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", 1, {
        heartbeat_at: nowSeconds(),
        expires_at: nowSeconds() + CONTROLLED_LEASE_TTL_SECONDS + 120,
      }),
      { "if-match": etag },
    );
    expect(farFuture.status).toBe(400);
    const mismatchedLeaseEtag = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": etag,
      "x-personal-lease-etag": "not-the-observed-etag",
    });
    expect(mismatchedLeaseEtag.status).toBe(412);
    expect(parseLease(bucket)).toEqual(original);
  });

  it("after trusted expiry, token skip/reuse is denied and exact token+1 takeover is allowed", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    vi.setSystemTime(TRUSTED_NOW_MS + (CONTROLLED_LEASE_TTL_SECONDS + 1) * 1000);
    const etag = leaseEtag(bucket);
    const reuse = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": etag,
    });
    expect(reuse.status).toBe(409);
    const skip = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 3), {
      "if-match": etag,
    });
    expect(skip.status).toBe(409);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-1");
    const takeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": etag,
    });
    expect(takeover.status).toBe(200);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-2");
    expect(parseLease(bucket).fencing_token).toBe(2);
  });

  it("same-owner post-expiry cannot reuse the stale token and must fence with token+1", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    vi.setSystemTime(TRUSTED_NOW_MS + (CONTROLLED_LEASE_TTL_SECONDS + 1) * 1000);
    const etag = leaseEtag(bucket);
    const resurrect = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": etag,
    });
    expect(resurrect.status).toBe(409);
    const reclaim = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 2), {
      "if-match": etag,
    });
    expect(reclaim.status).toBe(200);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-1");
    expect(parseLease(bucket).fencing_token).toBe(2);
  });

  it("create-only rejects caller-expired and over-TTL leases using trusted now", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const expired = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", 1, { heartbeat_at: nowSeconds() - 30, expires_at: nowSeconds() - 1 }),
      { "if-none-match": "*" },
    );
    expect(expired.status).toBe(400);
    expect(bucket.objects.has(leaseKey)).toBe(false);
    const overTtl = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", 1, {
        heartbeat_at: nowSeconds(),
        expires_at: nowSeconds() + CONTROLLED_LEASE_TTL_SECONDS + 1,
      }),
      { "if-none-match": "*" },
    );
    expect(overTtl.status).toBe(400);
    expect(bucket.objects.has(leaseKey)).toBe(false);
  });

  it("strictly rejects malformed stored CLAIMED leases without changing bytes or ETag", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const heartbeat = nowSeconds();
    const closed = leaseDoc("owner-nonce-1", 1, { heartbeat_at: heartbeat });
    const documents = [
      new TextEncoder().encode(
        JSON.stringify({ ...closed, expires_at: heartbeat - 1 }),
      ),
      new TextEncoder().encode(
        JSON.stringify({
          ...closed,
          expires_at: heartbeat + CONTROLLED_LEASE_TTL_SECONDS + 1,
        }),
      ),
      new TextEncoder().encode(
        JSON.stringify({
          ...closed,
          heartbeat_at:
            heartbeat + CONTROLLED_LEASE_CLOCK_SKEW_SECONDS + 1,
          expires_at:
            heartbeat +
            CONTROLLED_LEASE_CLOCK_SKEW_SECONDS +
            CONTROLLED_LEASE_TTL_SECONDS,
        }),
      ),
      new TextEncoder().encode(
        JSON.stringify(closed).replace(
          '"status":"CLAIMED"',
          '"status":"CLAIMED","status":"CLAIMED"',
        ),
      ),
    ];
    for (const [index, bytes] of documents.entries()) {
      resetBucket(bucket);
      const etag = `etag-malformed-claim-${index}`;
      const before = seedRaw(bucket, bytes, etag);
      const get = await getObject(env, leaseKey);
      expect(get.status).toBe(403);
      expect(get.headers.get("etag")).toBeNull();
      const head = await getObject(env, leaseKey, "HEAD");
      expect(head.status).toBe(403);
      expect(head.headers.get("etag")).toBeNull();
      const terminalGet = await getObject(env, terminalKey);
      expect([403, 404]).toContain(terminalGet.status);
      expect(terminalGet.headers.get("etag")).toBeNull();
      const terminal = await putJson(
        env,
        terminalKey,
        completedTerminal("owner-nonce-1", 1),
        {
          "x-personal-lease-owner": "owner-nonce-1",
          "x-personal-fencing-token": "1",
          "x-personal-lease-etag": etag,
        },
      );
      expect([400, 403, 409, 412]).toContain(terminal.status);
      const takeover = await putJson(
        env,
        leaseKey,
        leaseDoc("owner-nonce-2", 2),
        { "if-match": etag },
      );
      expect([400, 409, 412]).toContain(takeover.status);
      expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
      expect(bucket.objects.get(leaseKey)!.etag).toBe(etag);
    }
  });

  it("keeps an expired valid CLAIMED lease readable and permits only token+1 takeover", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const heartbeat = nowSeconds() - 60;
    const expired = leaseDoc("owner-nonce-1", 1, {
      heartbeat_at: heartbeat,
      expires_at: nowSeconds() - 1,
    });
    const bytes = new TextEncoder().encode(JSON.stringify(expired));
    const before = seedRaw(bucket, bytes, "etag-expired-claim");
    const get = await getObject(env, leaseKey);
    expect(get.status).toBe(200);
    expect(get.headers.get("etag")).toBe('"etag-expired-claim"');
    const head = await getObject(env, leaseKey, "HEAD");
    expect(head.status).toBe(200);
    expect(head.headers.get("etag")).toBe('"etag-expired-claim"');
    const staleTerminal = await putJson(
      env,
      terminalKey,
      completedTerminal("owner-nonce-1", 1),
      {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
        "x-personal-lease-etag": "etag-expired-claim",
      },
    );
    expect(staleTerminal.status).toBe(409);
    expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
    expect(bucket.objects.get(leaseKey)!.etag).toBe("etag-expired-claim");
    const takeover = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-2", 2),
      { "if-match": "etag-expired-claim" },
    );
    expect(takeover.status).toBe(200);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-2");
    expect(parseLease(bucket).fencing_token).toBe(2);
  });

  it("terminal-vs-expired-takeover from the same ETag has exactly one winner when takeover commits first", async () => {
    const hooks: BucketHooks = {};
    const bucket = casBucket(hooks);
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    vi.setSystemTime(TRUSTED_NOW_MS + (CONTROLLED_LEASE_TTL_SECONDS + 1) * 1000);
    const startEtag = leaseEtag(bucket);

    hooks.afterLeaseGet = async () => {
      const raced = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
        "if-match": startEtag,
      });
      expect(raced.status).toBe(200);
    };
    const staleTerminal = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": startEtag,
    });
    expect(staleTerminal.status).toBe(409);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-2");
    expect(parseLease(bucket).status).toBe("CLAIMED");
    expect((await getObject(env, terminalKey)).status).toBe(404);

    const winner = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-2", 2), {
      "x-personal-lease-owner": "owner-nonce-2",
      "x-personal-fencing-token": "2",
    });
    expect(winner.status).toBe(201);
    expect(parseLease(bucket).status).toBe("TERMINAL");
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-2");
  });

  it("terminal winning the same-ETag expired race freezes owner1 and rejects owner2 takeover", async () => {
    const hooks: BucketHooks = {};
    const bucket = casBucket(hooks);
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const startEtag = leaseEtag(bucket);

    hooks.afterLeaseGet = async () => {
      const published = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
        "x-personal-lease-etag": startEtag,
      });
      expect(published.status).toBe(201);
    };
    const lostTakeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": startEtag,
    });
    expect([409, 412]).toContain(lostTakeover.status);
    expect(parseLease(bucket).owner_nonce).toBe("owner-nonce-1");
    expect(parseLease(bucket).status).toBe("TERMINAL");
    const got = await getObject(env, terminalKey);
    expect(got.status).toBe(200);
    expect(JSON.parse(await got.text()).owner_nonce).toBe("owner-nonce-1");
  });

  it("content-hash ETag race still has one coherent terminal winner", async () => {
    const hooks: BucketHooks = { contentHashEtag: true };
    const bucket = casBucket(hooks);
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const startEtag = leaseEtag(bucket);
    const startBody = new TextDecoder().decode(bucket.objects.get(leaseKey)!.body);

    hooks.afterLeaseGet = async () => {
      const published = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
        "x-personal-lease-etag": startEtag,
      });
      expect(published.status).toBe(201);
    };
    const takeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": startEtag,
    });
    expect([409, 412]).toContain(takeover.status);
    const lease = parseLease(bucket);
    expect(lease.status).toBe("TERMINAL");
    expect(lease.owner_nonce).toBe("owner-nonce-1");
    expect(bucket.objects.get(leaseKey)!.etag).not.toBe(startEtag);
    expect(new TextDecoder().decode(bucket.objects.get(leaseKey)!.body)).not.toBe(startBody);
    const lateOwner2 = await putJson(env, terminalKey, stageLike("FAILED", "owner-nonce-2", 2), {
      "x-personal-lease-owner": "owner-nonce-2",
      "x-personal-fencing-token": "2",
    });
    expect(lateOwner2.status).toBe(409);
    const got = await getObject(env, terminalKey);
    const published = JSON.parse(await got.text()) as { status: string; owner_nonce: string };
    expect(published.status).toBe("COMPLETED");
    expect(published.owner_nonce).toBe("owner-nonce-1");
  });

  it("exact idempotent terminal replay returns 200 and a different terminal conflicts", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const first = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(first.status).toBe(201);
    const replay = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(replay.status).toBe(200);
    const conflict = await putJson(env, terminalKey, stageLike("FAILED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(conflict.status).toBe(409);
    const got = await getObject(env, terminalKey);
    expect(JSON.parse(await got.text()).status).toBe("COMPLETED");
    const beat = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": leaseEtag(bucket),
    });
    expect(beat.status).toBe(412);
    expect(parseLease(bucket).status).toBe("TERMINAL");
  });

  it("lease GET/HEAD returns the stored terminal envelope; logical terminal stays at 64 KiB", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const published = await putJson(
      env,
      terminalKey,
      stageLike("COMPLETED", "owner-nonce-1", 1, 20 * 1024),
      {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
      },
    );
    expect(published.status).toBe(201);
    const stored = bucket.objects.get(leaseKey)!;
    expect(stored.body.byteLength).toBeGreaterThan(CONTROLLED_LEASE_MAX_BYTES);
    expect(stored.body.byteLength).toBeLessThanOrEqual(CONTROLLED_LEASE_STORED_MAX_BYTES);

    const leaseGet = await getObject(env, leaseKey);
    expect(leaseGet.status).toBe(200);
    expect(Number(leaseGet.headers.get("content-length"))).toBe(stored.body.byteLength);
    const envelope = JSON.parse(await leaseGet.text()) as { status: string; terminal_payload_b64: string };
    expect(envelope.status).toBe("TERMINAL");
    expect(typeof envelope.terminal_payload_b64).toBe("string");
    const leaseHead = await getObject(env, leaseKey, "HEAD");
    expect(leaseHead.status).toBe(200);
    expect(Number(leaseHead.headers.get("content-length"))).toBe(stored.body.byteLength);

    const terminalGet = await getObject(env, terminalKey);
    expect(terminalGet.status).toBe(200);
    const logical = new Uint8Array(await terminalGet.arrayBuffer());
    expect(logical.byteLength).toBeLessThanOrEqual(CONTROLLED_TERMINAL_MAX_BYTES);
    expect(JSON.parse(new TextDecoder().decode(logical)).status).toBe("COMPLETED");
    const terminalHead = await getObject(env, terminalKey, "HEAD");
    expect(terminalHead.status).toBe(200);
    expect(Number(terminalHead.headers.get("content-length"))).toBe(logical.byteLength);

    bucket.objects.set(leaseKey, {
      body: new Uint8Array(CONTROLLED_LEASE_STORED_MAX_BYTES + 1),
      etag: "oversize",
    });
    expect((await getObject(env, leaseKey)).status).toBe(403);
    expect((await getObject(env, terminalKey)).status).toBe(403);
  });
});

function encodeB64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x2000;
  for (let i = 0; i < bytes.byteLength; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

async function embedTerminalLease(
  logical: Record<string, unknown>,
  leaseExtras: Record<string, unknown> = {},
): Promise<{ doc: Record<string, unknown>; bytes: Uint8Array; payload: Uint8Array }> {
  const payload = new TextEncoder().encode(JSON.stringify(logical));
  const heartbeat = nowSeconds() - 10;
  const doc = {
    identity: "controlled_pilot_v1",
    job_id: jobId,
    request_digest: requestDigest,
    execution_id: requestDigest,
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    kind: "controlled-pilot",
    owner_nonce: "owner-nonce-1",
    fencing_token: 1,
    expires_at: heartbeat + 5,
    heartbeat_at: heartbeat,
    status: "TERMINAL",
    terminal_digest: await sha256(payload),
    terminal_status: logical.status ?? "COMPLETED",
    terminal_payload_b64: encodeB64(payload),
    ...leaseExtras,
  };
  return {
    doc,
    bytes: new TextEncoder().encode(JSON.stringify(doc)),
    payload,
  };
}

function seedRaw(
  bucket: ReturnType<typeof casBucket>,
  bytes: Uint8Array,
  etag = "etag-raw-terminal",
): Uint8Array {
  const copy = bytes.slice();
  bucket.objects.set(leaseKeyOf(), { body: copy, etag });
  return copy;
}

describe("closed terminal lease validator", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(TRUSTED_NOW_MS);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function expectMalformedUnchanged(
    env: { STRUCTURED_BUCKET: R2Bucket },
    bucket: ReturnType<typeof casBucket>,
    before: Uint8Array,
    etag: string,
  ): Promise<void> {
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const get = await getObject(env, terminalKey);
    expect(get.status).toBe(403);
    expect(get.headers.get("etag")).toBeNull();
    const head = await getObject(env, terminalKey, "HEAD");
    expect(head.status).toBe(403);
    expect(head.headers.get("etag")).toBeNull();
    const leaseGet = await getObject(env, leaseKey);
    expect(leaseGet.status).toBe(403);
    expect(leaseGet.headers.get("etag")).toBeNull();
    const leaseHead = await getObject(env, leaseKey, "HEAD");
    expect(leaseHead.status).toBe(403);
    expect(leaseHead.headers.get("etag")).toBeNull();
    const replay = await putJson(env, terminalKey, completedTerminal("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(replay.status).not.toBe(200);
    expect(replay.status).not.toBe(201);
    expect([400, 403, 409, 412]).toContain(replay.status);
    expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
    expect(bucket.objects.get(leaseKey)!.etag).toBe(etag);
  }

  it("rejects the exact-field raw probe lease on GET/HEAD/lease/replay and leaves bytes", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const logical = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: "evil-runner",
      status: "COMPLETED",
      owner_nonce: "owner-nonce-1",
      fencing_token: 1,
      ok: false,
      papers: "bad",
    };
    const seeded = await embedTerminalLease(logical, {
      fencing_token: "1",
      expires_at: "not-a-time",
      heartbeat_at: null,
    });
    const before = seedRaw(bucket, seeded.bytes);
    await expectMalformedUnchanged(env, bucket, before, "etag-raw-terminal");
  });

  it("rejects string token, unsafe integer, null/string/nonfinite times, and expires<=heartbeat", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const logical = completedTerminal("owner-nonce-1", 1);
    const cases: Array<Record<string, unknown>> = [
      { fencing_token: "1" },
      { fencing_token: Number.MAX_SAFE_INTEGER + 1 },
      { heartbeat_at: null },
      { expires_at: "not-a-time" },
      { heartbeat_at: Number.NaN },
      { expires_at: Number.POSITIVE_INFINITY },
      { heartbeat_at: nowSeconds(), expires_at: nowSeconds() },
      { heartbeat_at: nowSeconds() + 1, expires_at: nowSeconds() },
      {
        heartbeat_at: nowSeconds(),
        expires_at: nowSeconds() + CONTROLLED_LEASE_TTL_SECONDS + 1,
      },
      {
        heartbeat_at:
          nowSeconds() + CONTROLLED_LEASE_CLOCK_SKEW_SECONDS + 1,
        expires_at:
          nowSeconds() + CONTROLLED_LEASE_CLOCK_SKEW_SECONDS + 2,
      },
    ];
    for (const extras of cases) {
      await resetBucket(bucket);
      const seeded = await embedTerminalLease(logical, extras);
      const before = seedRaw(bucket, seeded.bytes, "etag-time");
      await expectMalformedUnchanged(env, bucket, before, "etag-time");
    }
  });

  it("rejects duplicate-key terminal envelopes without changing bytes or ETag", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const seeded = await embedTerminalLease(
      completedTerminal("owner-nonce-1", 1),
    );
    const duplicate = new TextEncoder().encode(
      new TextDecoder().decode(seeded.bytes).replace(
        '"status":"TERMINAL"',
        '"status":"TERMINAL","status":"TERMINAL"',
      ),
    );
    const before = seedRaw(bucket, duplicate, "etag-duplicate-terminal");
    await expectMalformedUnchanged(
      env,
      bucket,
      before,
      "etag-duplicate-terminal",
    );
  });

  it("rejects missing/extra/wrong base fields on a preexisting terminal lease", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const logical = completedTerminal("owner-nonce-1", 1);
    const closed = (await embedTerminalLease(logical)).doc;
    const missing = { ...closed };
    delete missing.kind;
    const cases: Array<Record<string, unknown>> = [
      missing,
      { ...closed, extra: true },
      { ...closed, identity: "draft" },
      { ...closed, job_id: "other-job-9" },
      { ...closed, request_digest: otherDigest() },
      { ...closed, execution_id: otherDigest() },
      { ...closed, runner_version: "evil-runner" },
      { ...closed, kind: "research" },
      { ...closed, owner_nonce: "short" },
    ];
    for (const [index, doc] of cases.entries()) {
      await resetBucket(bucket);
      const bytes = new TextEncoder().encode(JSON.stringify(doc));
      const etag = `etag-base-${index}`;
      const before = seedRaw(bucket, bytes, etag);
      await expectMalformedUnchanged(env, bucket, before, etag);
    }
  });

  it("rejects logical payload runner/status/ok/owner/fence/execution/job/request mismatch", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const good = completedTerminal("owner-nonce-1", 1);
    const cases: Array<Record<string, unknown>> = [
      { ...good, runner_version: "evil-runner" },
      { ...good, status: "FAILED", ok: true },
      { ...good, ok: false },
      { ...good, owner_nonce: "other-owner-9" },
      { ...good, fencing_token: "1" },
      { ...good, fencing_token: 2 },
      { ...good, execution_id: otherDigest() },
      { ...good, job_id: "other-job-9" },
      { ...good, request_digest: otherDigest() },
      { ...good, papers: "bad" },
      { ...good, extra: true },
    ];
    for (const [index, logical] of cases.entries()) {
      await resetBucket(bucket);
      const seeded = await embedTerminalLease(logical);
      const etag = `etag-logical-${index}`;
      const before = seedRaw(bucket, seeded.bytes, etag);
      await expectMalformedUnchanged(env, bucket, before, etag);
    }
  });

  it("does not terminalize a malformed candidate from a valid CLAIMED lease", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const before = bucket.objects.get(leaseKey)!.body.slice();
    const etag = leaseEtag(bucket);
    const malformed = {
      ...completedTerminal("owner-nonce-1", 1),
      runner_version: "evil-runner",
      ok: false,
      papers: "bad",
    };
    const denied = await putJson(env, terminalKey, malformed, {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": etag,
    });
    expect(denied.status).not.toBe(201);
    expect(denied.status).not.toBe(200);
    expect([400, 403, 409]).toContain(denied.status);
    expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
    expect(parseLease(bucket).status).toBe("CLAIMED");
  });

  it("serves valid COMPLETED and FAILED terminals, observer GET/HEAD, and exact replay", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const published = await putJson(env, terminalKey, completedTerminal("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(published.status).toBe(201);
    const got = await getObject(env, terminalKey);
    expect(got.status).toBe(200);
    expect(JSON.parse(await got.text()).ok).toBe(true);
    const head = await getObject(env, terminalKey, "HEAD");
    expect(head.status).toBe(200);
    expect(head.headers.get("etag")).toBeTruthy();
    const replay = await putJson(env, terminalKey, completedTerminal("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(replay.status).toBe(200);
    const staleReplay = await putJson(env, terminalKey, completedTerminal("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": "etag-stale",
    });
    expect(staleReplay.status).toBe(200);

    const failedBucket = casBucket();
    const failedEnv = { STRUCTURED_BUCKET: failedBucket };
    expect(
      (await putJson(failedEnv, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const failed = await putJson(failedEnv, terminalKey, failedTerminal("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(failed.status).toBe(201);
    const failedGot = await getObject(failedEnv, terminalKey);
    expect(failedGot.status).toBe(200);
    expect(JSON.parse(await failedGot.text()).ok).toBe(false);
    const failedReplay = await putJson(failedEnv, terminalKey, failedTerminal("owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(failedReplay.status).toBe(200);
  });

  it("serves an expired-but-closed terminal and rejects a wrong request digest without ETag", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const seeded = await embedTerminalLease(completedTerminal("owner-nonce-1", 1), {
      heartbeat_at: nowSeconds() - 4000,
      expires_at: nowSeconds() - 4000 + CONTROLLED_LEASE_TTL_SECONDS,
    });
    const before = seedRaw(bucket, seeded.bytes, "etag-expired-closed");
    const got = await getObject(env, terminalKeyOf());
    expect(got.status).toBe(200);
    expect(got.headers.get("etag")).toBe('"etag-expired-closed"');
    expect(JSON.parse(await got.text()).status).toBe("COMPLETED");
    const head = await getObject(env, terminalKeyOf(), "HEAD");
    expect(head.status).toBe(200);
    expect(head.headers.get("etag")).toBe('"etag-expired-closed"');
    const leaseGot = await getObject(env, leaseKeyOf());
    expect(leaseGot.status).toBe(200);
    const replay = await putJson(
      env,
      terminalKeyOf(),
      completedTerminal("owner-nonce-1", 1),
      {
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
      },
    );
    expect(replay.status).toBe(200);
    expect(new Uint8Array(bucket.objects.get(leaseKeyOf())!.body)).toEqual(before);
    expect(bucket.objects.get(leaseKeyOf())!.etag).toBe("etag-expired-closed");
    const wrong = await outbound(env, terminalKeyOf(), {
      method: "GET",
      headers: { ...identityHeaders, "x-personal-request-digest": otherDigest() },
    });
    expect(wrong.status).toBe(403);
    expect(wrong.headers.get("etag")).toBeNull();
    expect(await wrong.text()).not.toContain("owner-nonce-1");
  });
});

function resetBucket(bucket: ReturnType<typeof casBucket>): void {
  bucket.objects.clear();
}

function hugeAttemptStream(
  stats: { pulled: number; cancelled: boolean },
  mode: "bytes" | "default",
): ReadableStream<Uint8Array> {
  const huge = 8 * 1024 * 1024;
  if (mode === "default") {
    return new ReadableStream<Uint8Array>({
      pull(controller) {
        stats.pulled += huge;
        controller.enqueue(new Uint8Array(huge).fill(0x78));
        controller.close();
      },
      cancel() {
        stats.cancelled = true;
      },
    });
  }
  return new ReadableStream<Uint8Array>({
    type: "bytes",
    pull(controller) {
      const byob = controller.byobRequest;
      if (byob && byob.view) {
        const n = Math.min(byob.view.byteLength, huge);
        new Uint8Array(byob.view.buffer, byob.view.byteOffset, n).fill(0x78);
        stats.pulled += n;
        byob.respond(n);
        return;
      }
      stats.pulled += huge;
      controller.enqueue(new Uint8Array(huge).fill(0x78));
      controller.close();
    },
    cancel() {
      stats.cancelled = true;
    },
  } as UnderlyingByteSource);
}


function otherDigest(): string {
  return `sha256:${"cd".repeat(32)}`;
}

function otherIdentity(digest = otherDigest()): Record<string, string> {
  return {
    ...identityHeaders,
    "x-personal-request-digest": digest,
  };
}

function revealDenied(response: Response, body: string): void {
  expect([403, 404]).toContain(response.status);
  expect(response.status).toBeLessThan(500);
  expect(response.headers.get("etag")).toBeNull();
  expect(body).not.toContain("owner-nonce-1");
  expect(body).not.toContain("fencing_token");
  expect(body).not.toContain(requestDigest);
}

describe("controlled lease etag identity and fencing attacks", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(TRUSTED_NOW_MS);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("create then same-owner renew then terminal succeeds using quoted HTTP ETags without 500", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const created = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    expect(created.status).toBe(201);
    const createdBody = await created.json() as { etag: string };
    expect(createdBody.etag).toMatch(/^"[^"]+"$/);
    expect(createdBody.etag).toBe(`"${leaseEtag(bucket)}"`);
    vi.setSystemTime(TRUSTED_NOW_MS + 15_000);
    const renewed = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": createdBody.etag,
    });
    expect(renewed.status).toBe(200);
    expect(renewed.status).not.toBe(500);
    const renewedBody = await renewed.json() as { etag: string };
    expect(renewedBody.etag).toMatch(/^"[^"]+"$/);
    const terminal = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": renewedBody.etag,
    });
    expect(terminal.status).toBe(201);
    expect(parseLease(bucket).status).toBe("TERMINAL");
  });

  it("stale quoted ETag fails renew and terminal without workerd quote 500", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const created = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    const stale = (await created.json() as { etag: string }).etag;
    vi.setSystemTime(TRUSTED_NOW_MS + 15_000);
    const renewed = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": stale,
    });
    expect(renewed.status).toBe(200);
    const staleRenew = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": stale,
    });
    expect(staleRenew.status).toBe(412);
    expect(staleRenew.status).not.toBe(500);
    const staleTerminal = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": stale,
    });
    expect(staleTerminal.status).toBe(409);
    expect(staleTerminal.status).not.toBe(500);
    expect(parseLease(bucket).status).toBe("CLAIMED");
  });

  it("denies weak, multiple, wildcard, and malformed If-Match / lease ETag values", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const raw = leaseEtag(bucket);
    const quoted = `"${raw}"`;
    vi.setSystemTime(TRUSTED_NOW_MS + 10_000);
    const good = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": quoted,
    });
    expect(good.status).toBe(200);
    const current = leaseEtag(bucket);
    const denied = [
      `W/"${current}"`,
      `"${current}", "${current}"`,
      "*",
      `"${current}`,
      `${current}"`,
      ` "${current}" `,
    ];
    for (const value of denied) {
      const response = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
        "if-match": value,
      });
      expect([400, 409, 412, 428]).toContain(response.status);
      expect(response.status).not.toBe(500);
    }
    expect(parseLease(bucket).fencing_token).toBe(1);
  });

  it("cross-digest GET/HEAD hides lease secrets and cannot forge a terminal", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const stageKey = `research/controlled_pilot/v1/jobs/${jobId}/container-stage.json`;
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const stage = {
      identity: "controlled_pilot_v1",
      job_id: jobId,
      request_digest: requestDigest,
      execution_id: requestDigest,
      runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
      status: "QUEUED",
    };
    expect((await putJson(env, stageKey, stage)).status).toBe(201);

    const attacker = otherIdentity();
    const leakGet = await outbound(env, leaseKey, { method: "GET", headers: attacker });
    const leakBody = await leakGet.text();
    revealDenied(leakGet, leakBody);
    const leakHead = await outbound(env, leaseKey, { method: "HEAD", headers: attacker });
    revealDenied(leakHead, await leakHead.text());
    const stageLeak = await outbound(env, stageKey, { method: "GET", headers: attacker });
    revealDenied(stageLeak, await stageLeak.text());

    let stolenOwner = "";
    let stolenToken = "";
    let stolenDigest = "";
    try {
      const parsed = JSON.parse(leakBody) as {
        owner_nonce?: string;
        fencing_token?: number;
        request_digest?: string;
      };
      stolenOwner = String(parsed.owner_nonce || "");
      stolenToken = String(parsed.fencing_token || "");
      stolenDigest = String(parsed.request_digest || "");
    } catch {
      stolenOwner = "";
    }
    const forgedFromLeak = await outbound(env, terminalKey, {
      method: "PUT",
      headers: {
        ...attacker,
        ...(stolenDigest ? { "x-personal-request-digest": stolenDigest } : {}),
        "content-type": CONTROLLED_JSON_TYPE,
        "x-personal-lease-owner": stolenOwner || "owner-nonce-1",
        "x-personal-fencing-token": stolenToken || "1",
        "x-content-sha256": `sha256:${"00".repeat(32)}`,
        "content-length": "2",
      },
      body: "{}",
    });
    expect(forgedFromLeak.status).not.toBe(201);
    expect(forgedFromLeak.status).toBeGreaterThanOrEqual(400);

    const stolenTerminal = await putJson(
      env,
      terminalKey,
      stageLike("COMPLETED", "owner-nonce-1", 1),
      {
        "x-personal-request-digest": otherDigest(),
        "x-personal-lease-owner": "owner-nonce-1",
        "x-personal-fencing-token": "1",
      },
    );
    expect([403, 404, 409]).toContain(stolenTerminal.status);
    expect(stolenTerminal.status).not.toBe(201);
    expect(parseLease(bucket).status).toBe("CLAIMED");

    const ownerTerminal = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
    });
    expect(ownerTerminal.status).toBe(201);
    const terminalLeak = await outbound(env, terminalKey, { method: "GET", headers: attacker });
    revealDenied(terminalLeak, await terminalLeak.text());
  });

  it("initial create requires fencing_token exactly 1", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const second = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 2), {
      "if-none-match": "*",
    });
    expect(second.status).toBe(400);
    expect(bucket.objects.has(leaseKey)).toBe(false);
    const exhausted = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-1", Number.MAX_SAFE_INTEGER),
      { "if-none-match": "*" },
    );
    expect(exhausted.status).toBe(400);
    expect(bucket.objects.has(leaseKey)).toBe(false);
    const first = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-none-match": "*",
    });
    expect(first.status).toBe(201);
    expect(parseLease(bucket).fencing_token).toBe(1);
  });

  it("seeded extra field and string fencing token cannot terminal-transition", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const terminalKey = terminalKeyOf();
    const closed = leaseDoc("owner-nonce-1", 1);
    const malformed = { ...closed, extra: true, fencing_token: "1" };
    const seededBytes = new TextEncoder().encode(JSON.stringify(malformed));
    bucket.objects.set(leaseKey, { body: seededBytes, etag: "etag-malformed" });
    const before = bucket.objects.get(leaseKey)!.body.slice();
    const denied = await putJson(env, terminalKey, stageLike("COMPLETED", "owner-nonce-1", 1), {
      "x-personal-lease-owner": "owner-nonce-1",
      "x-personal-fencing-token": "1",
      "x-personal-lease-etag": "etag-malformed",
    });
    expect(denied.status).not.toBe(201);
    expect([400, 403, 409, 412]).toContain(denied.status);
    expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
    expect(bucket.objects.get(leaseKey)!.etag).toBe("etag-malformed");
    expect(parseLease(bucket).status).toBe("CLAIMED");
    expect(parseLease(bucket).fencing_token).toBe("1");
    expect(parseLease(bucket).extra).toBe(true);
  });

  it("tampered extra fields fail closed before renew or takeover", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    expect(
      (await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), { "if-none-match": "*" })).status,
    ).toBe(201);
    const stored = parseLease(bucket);
    const etag = leaseEtag(bucket);
    bucket.objects.set(leaseKey, {
      body: new TextEncoder().encode(JSON.stringify({ ...stored, extra: true })),
      etag,
    });
    vi.setSystemTime(TRUSTED_NOW_MS + 10_000);
    const renew = await putJson(env, leaseKey, leaseDoc("owner-nonce-1", 1), {
      "if-match": etag,
    });
    expect([400, 409, 412]).toContain(renew.status);
    expect(JSON.parse(new TextDecoder().decode(bucket.objects.get(leaseKey)!.body)).extra).toBe(true);
    vi.setSystemTime(TRUSTED_NOW_MS + (CONTROLLED_LEASE_TTL_SECONDS + 1) * 1000);
    const takeover = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 2), {
      "if-match": etag,
    });
    expect([400, 409, 412]).toContain(takeover.status);
    expect(JSON.parse(new TextDecoder().decode(bucket.objects.get(leaseKey)!.body)).owner_nonce).toBe(
      "owner-nonce-1",
    );
  });

  it("exhausted MAX_SAFE fencing token cannot be taken over and does not change state", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const leaseKey = leaseKeyOf();
    const heartbeat = nowSeconds() - CONTROLLED_LEASE_TTL_SECONDS - 5;
    const exhausted = leaseDoc("owner-nonce-1", Number.MAX_SAFE_INTEGER, {
      heartbeat_at: heartbeat,
      expires_at: heartbeat + 1,
    });
    bucket.objects.set(leaseKey, {
      body: new TextEncoder().encode(JSON.stringify(exhausted)),
      etag: "etag-exhausted",
    });
    const before = bucket.objects.get(leaseKey)!.body.slice();
    const overflowToken = Number.MAX_SAFE_INTEGER + 1;
    const takeover = await putJson(
      env,
      leaseKey,
      leaseDoc("owner-nonce-2", overflowToken),
      { "if-match": "etag-exhausted" },
    );
    expect([400, 409, 412]).toContain(takeover.status);
    expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
    const reuse = await putJson(env, leaseKey, leaseDoc("owner-nonce-2", 1), {
      "if-match": "etag-exhausted",
    });
    expect(reuse.status).toBe(409);
    expect(new Uint8Array(bucket.objects.get(leaseKey)!.body)).toEqual(before);
  });
});

describe("strict bounded request reader", () => {
  const leaseKey = leaseKeyOf();

  async function leasePutFromStream(
    env: { STRUCTURED_BUCKET: R2Bucket },
    body: ReadableStream<Uint8Array>,
    extraHeaders: Record<string, string> = {},
  ): Promise<Response> {
    return outbound(env, leaseKey, {
      method: "PUT",
      headers: {
        ...identityHeaders,
        "x-content-sha256": `sha256:${THREE_BYTE_SHA256}`,
        "if-none-match": "*",
        ...extraHeaders,
      },
      body,
      duplex: "half",
    } as RequestInit);
  }

  it("does not pull an 8 MiB default-stream chunk; fail-closed and cancelled", async () => {
    const noHeaderStats = { pulled: 0, cancelled: false };
    const noHeaderTrace: BoundedReadTrace = { pulled: 0, forwarded: 0, cancelled: false };
    const noHeader = await readBoundedBody(
      new Request("http://research.r2/lease", {
        method: "PUT",
        headers: { "content-type": CONTROLLED_JSON_TYPE },
        body: hugeAttemptStream(noHeaderStats, "default"),
        duplex: "half",
      } as RequestInit),
      CONTROLLED_LEASE_MAX_BYTES,
      noHeaderTrace,
    );
    expect(noHeader).toBeInstanceOf(Response);
    expect((noHeader as Response).status).toBeGreaterThanOrEqual(400);
    expect(noHeaderStats.pulled).toBe(0);
    expect(noHeaderTrace.pulled).toBe(0);
    expect(noHeaderTrace.forwarded).toBe(0);
    expect(noHeaderStats.cancelled || noHeaderTrace.cancelled).toBe(true);

    const falseHeaderStats = { pulled: 0, cancelled: false };
    const falseHeaderTrace: BoundedReadTrace = { pulled: 0, forwarded: 0, cancelled: false };
    const falseHeader = await readBoundedBody(
      new Request("http://research.r2/lease", {
        method: "PUT",
        headers: {
          "content-type": CONTROLLED_JSON_TYPE,
          "content-length": "4",
        },
        body: hugeAttemptStream(falseHeaderStats, "default"),
        duplex: "half",
      } as RequestInit),
      CONTROLLED_LEASE_MAX_BYTES,
      falseHeaderTrace,
    );
    expect(falseHeader).toBeInstanceOf(Response);
    expect((falseHeader as Response).status).toBeGreaterThanOrEqual(400);
    expect(falseHeaderStats.pulled).toBe(0);
    expect(falseHeaderTrace.pulled).toBe(0);
    expect(falseHeaderTrace.forwarded).toBe(0);
    expect(falseHeaderStats.cancelled || falseHeaderTrace.cancelled).toBe(true);
  });

  it("BYOB 8 MiB producer never forwards the huge chunk and the lease handler is not reached", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const noHeaderStats = { pulled: 0, cancelled: false };
    const noHeader = await leasePutFromStream(env, hugeAttemptStream(noHeaderStats, "bytes"));
    expect([400, 413]).toContain(noHeader.status);
    expect(noHeaderStats.pulled).toBeLessThanOrEqual(CONTROLLED_LEASE_MAX_BYTES + 1);
    expect(noHeaderStats.pulled).toBeGreaterThan(0);
    expect(noHeaderStats.pulled).toBeLessThan(8 * 1024 * 1024);
    expect(noHeaderStats.cancelled).toBe(true);
    expect(bucket.objects.size).toBe(0);

    const falseStats = { pulled: 0, cancelled: false };
    const falseHeader = await leasePutFromStream(env, hugeAttemptStream(falseStats, "bytes"), {
      "content-length": "4",
    });
    expect([400, 413]).toContain(falseHeader.status);
    expect(falseStats.pulled).toBeLessThanOrEqual(5);
    expect(falseStats.pulled).toBeLessThan(8 * 1024 * 1024);
    expect(falseStats.cancelled).toBe(true);
    expect(bucket.objects.size).toBe(0);
  });

  it("accepts an exact 8192-byte lease PUT and rejects 8193", async () => {
    const bucket = casBucket();
    const env = { STRUCTURED_BUCKET: bucket };
    const base = leaseDoc("owner-xx", 1);
    const skeleton = new TextEncoder().encode(JSON.stringify({ ...base, owner_nonce: "" }));
    const pad = CONTROLLED_LEASE_MAX_BYTES - skeleton.byteLength;
    expect(pad).toBeGreaterThan(8);
    const exactDoc = { ...base, owner_nonce: "o".repeat(pad) };
    const exactBytes = new TextEncoder().encode(JSON.stringify(exactDoc));
    expect(exactBytes.byteLength).toBe(CONTROLLED_LEASE_MAX_BYTES);
    const exact = await outbound(env, leaseKey, {
      method: "PUT",
      headers: {
        ...identityHeaders,
        "content-length": String(exactBytes.byteLength),
        "x-content-sha256": await sha256(exactBytes),
        "if-none-match": "*",
      },
      body: exactBytes,
    });
    expect(exact.status).toBe(201);

    const over = new Uint8Array(CONTROLLED_LEASE_MAX_BYTES + 1);
    over.set(exactBytes);
    over[CONTROLLED_LEASE_MAX_BYTES] = 0x78;
    const rejected = await outbound(env, leaseKey, {
      method: "PUT",
      headers: {
        ...identityHeaders,
        "content-length": String(over.byteLength),
        "x-content-sha256": await sha256(over),
        "if-match": bucket.objects.get(leaseKey)!.etag,
      },
      body: over,
    });
    expect(rejected.status).toBe(413);

    const overStats = { pulled: 0, cancelled: false };
    const overTrace: BoundedReadTrace = { pulled: 0, forwarded: 0, cancelled: false };
    const overRead = await readBoundedBody(
      new Request("http://research.r2/lease", {
        method: "PUT",
        headers: {
          "content-type": CONTROLLED_JSON_TYPE,
          "content-length": String(CONTROLLED_LEASE_MAX_BYTES + 1),
        },
        body: new ReadableStream<Uint8Array>({
          type: "bytes",
          start(controller) {
            controller.enqueue(over.slice());
            controller.close();
          },
          cancel() {
            overStats.cancelled = true;
          },
        } as UnderlyingByteSource),
        duplex: "half",
      } as RequestInit),
      CONTROLLED_LEASE_MAX_BYTES,
      overTrace,
    );
    expect(overRead).toBeInstanceOf(Response);
    expect((overRead as Response).status).toBe(413);
    expect(overTrace.forwarded).toBe(0);
    expect(overTrace.cancelled || overStats.cancelled).toBe(true);

    const noDeclareOver = await readBoundedBody(
      new Request("http://research.r2/lease", {
        method: "PUT",
        headers: { "content-type": CONTROLLED_JSON_TYPE },
        body: over,
      }),
      CONTROLLED_LEASE_MAX_BYTES,
      overTrace,
    );
    expect(noDeclareOver).toBeInstanceOf(Response);
    expect((noDeclareOver as Response).status).toBe(413);
    expect(overTrace.forwarded).toBe(0);
    expect(overTrace.pulled).toBeLessThanOrEqual(CONTROLLED_LEASE_MAX_BYTES + 1);
  });

  it("rejects zero-length and declared-length mismatch bodies", async () => {
    const empty = await readBoundedBody(
      new Request("http://research.r2/lease", {
        method: "PUT",
        headers: {
          "content-type": CONTROLLED_JSON_TYPE,
          "content-length": "1",
        },
        body: new Uint8Array(0),
      }),
      CONTROLLED_LEASE_MAX_BYTES,
    );
    expect(empty).toBeInstanceOf(Response);
    expect((empty as Response).status).toBe(400);

    const mismatch = await readBoundedBody(
      new Request("http://research.r2/lease", {
        method: "PUT",
        headers: {
          "content-type": CONTROLLED_JSON_TYPE,
          "content-length": "4",
        },
        body: new Uint8Array([1, 2]),
      }),
      CONTROLLED_LEASE_MAX_BYTES,
    );
    expect(mismatch).toBeInstanceOf(Response);
    expect((mismatch as Response).status).toBe(400);
  });
});
