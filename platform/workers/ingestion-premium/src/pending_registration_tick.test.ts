import { createHash, randomUUID } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  PENDING_REGISTRATION_KEY,
  runPendingRegistrationTick,
  type PendingRegistrationOutput,
} from "./pending_registration_tick";

class MemoryObject {
  constructor(
    readonly body: string,
    readonly etag: string,
  ) {}
  get size(): number {
    return new TextEncoder().encode(this.body).byteLength;
  }
  async text(): Promise<string> {
    return this.body;
  }
}

class MemoryBucket {
  private objects = new Map<string, MemoryObject>();

  async get(key: string): Promise<MemoryObject | null> {
    return this.objects.get(key) ?? null;
  }

  async put(
    key: string,
    value: string,
    options?: { onlyIf?: { etagMatches?: string } },
  ): Promise<MemoryObject | null> {
    const current = this.objects.get(key);
    const expected = options?.onlyIf?.etagMatches;
    if (expected !== undefined && current?.etag !== expected) return null;
    const etag = createHash("sha256").update(value).digest("hex");
    const stored = new MemoryObject(value, etag);
    this.objects.set(key, stored);
    return stored;
  }
}

function requestedDoc(overrides: Record<string, unknown> = {}) {
  return {
    schema: "receipt-pending-registration/v1",
    environment: "staging",
    state: "requested",
    attempts: 0,
    lease: null,
    last: null,
    ...overrides,
  };
}

const POLICY = {
  environment: "staging" as const,
  operationMode: "PENDING" as const,
  readyDeclared: "false",
};

const OUTPUT: PendingRegistrationOutput = {
  registration: {
    key_id: "receipt-staging-aaaaaaaaaaaaaaaa",
    public_key_base64: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    registration_digest: `sha256:${"b".repeat(64)}`,
    authority_status: "PENDING",
  },
  caller_worker_version_id: "10000000-0000-4000-8000-000000000003",
  caller_worker_version_tag: `rp-s-c-${"1".repeat(40)}`,
};

describe("pending registration control tick", () => {
  it("absent or idle does not call registration", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    let calls = 0;
    expect(
      await runPendingRegistrationTick(bucket, async () => {
        calls += 1;
        return OUTPUT;
      }, POLICY),
    ).toEqual({ status: "idle", called: false, reason: "absent" });
    await (bucket as unknown as MemoryBucket).put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify(requestedDoc({ state: "idle" })),
    );
    expect(
      await runPendingRegistrationTick(bucket, async () => {
        calls += 1;
        return OUTPUT;
      }, POLICY),
    ).toEqual({ status: "idle", called: false, reason: "idle" });
    expect(calls).toBe(0);
  });

  it("invalid control and ACTIVE/READY policy have no side effects", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    let calls = 0;
    const register = async () => {
      calls += 1;
      return OUTPUT;
    };
    await (bucket as unknown as MemoryBucket).put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify(requestedDoc({ extra: true })),
    );
    expect(await runPendingRegistrationTick(bucket, register, POLICY))
      .toEqual({ status: "stop", called: false, reason: "invalid" });
    await (bucket as unknown as MemoryBucket).put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify(requestedDoc()),
    );
    expect(
      await runPendingRegistrationTick(bucket, register, {
        ...POLICY,
        operationMode: "ACTIVE",
      }),
    ).toEqual({ status: "stop", called: false, reason: "policy" });
    expect(
      await runPendingRegistrationTick(bucket, register, {
        ...POLICY,
        readyDeclared: "true",
      }),
    ).toEqual({ status: "stop", called: false, reason: "policy" });
    expect(calls).toBe(0);
  });

  it("requested dispatches once then is idempotent", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    let calls = 0;
    const register = async () => {
      calls += 1;
      return OUTPUT;
    };
    await (bucket as unknown as MemoryBucket).put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify(requestedDoc()),
    );
    expect(await runPendingRegistrationTick(bucket, register, POLICY))
      .toEqual({ status: "pass", called: true, reason: "ok" });
    expect(await runPendingRegistrationTick(bucket, register, POLICY))
      .toEqual({ status: "idle", called: false, reason: "completed" });
    await (bucket as unknown as MemoryBucket).put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify({
        ...requestedDoc(),
        last: JSON.parse(
          await (await bucket.get(PENDING_REGISTRATION_KEY))!.text(),
        ).last,
      }),
    );
    expect(await runPendingRegistrationTick(bucket, register, POLICY))
      .toEqual({ status: "idle", called: false, reason: "idempotent" });
    expect(calls).toBe(1);
    const stored = JSON.parse(
      await (await bucket.get(PENDING_REGISTRATION_KEY))!.text(),
    );
    expect(stored.state).toBe("completed");
    expect(stored.last).toMatchObject({
      status: "pass",
      key_id: OUTPUT.registration.key_id,
      public_key_base64: OUTPUT.registration.public_key_base64,
      authority_status: "PENDING",
    });
    expect(stored.last.private_key).toBeUndefined();
  });

  it("failed dispatch retries then stops at the attempt bound", async () => {
    const bucket = new MemoryBucket() as unknown as R2Bucket;
    let calls = 0;
    const boom = async () => {
      calls += 1;
      throw new Error(`forced ${randomUUID()}`);
    };
    await (bucket as unknown as MemoryBucket).put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify(requestedDoc()),
    );
    expect(await runPendingRegistrationTick(bucket, boom, POLICY))
      .toEqual({ status: "fail", called: true, reason: "registration_failed" });
    expect(await runPendingRegistrationTick(bucket, boom, POLICY))
      .toEqual({ status: "fail", called: true, reason: "registration_failed" });
    expect(await runPendingRegistrationTick(bucket, boom, POLICY))
      .toEqual({ status: "fail", called: true, reason: "registration_failed" });
    expect(await runPendingRegistrationTick(bucket, boom, POLICY))
      .toEqual({ status: "stop", called: false, reason: "exhausted" });
    expect(calls).toBe(3);
  });
});
