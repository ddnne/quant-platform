import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import readyFixture from "../../../../specs/ready/controlled_pilot_ready.generated.json";
import {
  CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT,
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_PLAN_SET_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  controlledPhysicalSnapshotKey,
  controlledPilotRequestDigest,
  controlledReadyKey,
  controlledTraderAuthorizationKey,
} from "../../research-mass-eval/src/controlled_pilot_contract";
import { verifyReceiptNativeReadyPublication } from "../../research-mass-eval/src/receipt_native_ready_publication";
import {
  personalReceiptCandidateManifestKey,
  personalReceiptCandidatePhysicalKey,
  personalReceiptCandidateScopeKey,
} from "../../research-mass-eval/src/personal_receipt_candidate_contract";
import { PINNED_RECEIPT_REGISTRY_SCOPE } from "./ops_projection_policy";

const projectionMock = vi.hoisted(() => vi.fn());
const loadPinnedReadyKeysMock = vi.hoisted(() => vi.fn());
const loadPinnedTraderKeysMock = vi.hoisted(() => vi.fn());
vi.mock("cloudflare:workers", () => ({ WorkerEntrypoint: class {} }));
vi.mock("../../research-mass-eval/src/ops_projection_ready", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../research-mass-eval/src/ops_projection_ready")>();
  return { ...actual, verifyOpsProjectionReady: projectionMock };
});
vi.mock("../../research-mass-eval/src/controlled_pilot_registries", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../research-mass-eval/src/controlled_pilot_registries")>();
  return {
    ...actual,
    loadPinnedReadyKeys: loadPinnedReadyKeysMock,
    loadPinnedTraderKeys: loadPinnedTraderKeysMock,
  };
});

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  canonicalJson,
  isRecord,
  sha256Digest,
} from "../../research-mass-eval/src/controlled_pilot_json";
import { verifyTraderAuthorizationBatch } from "../../research-mass-eval/src/controlled_pilot_trader_batch";
import {
  providerVerifiedR2Digest,
  publishAdmittedReceiptCandidate,
  publishPilotReady,
  type ReadyPublicationCandidate,
} from "./ready_publication";

const sha = (character: string): string => `sha256:${character.repeat(64)}`;

function checksum(digest: string): ArrayBuffer {
  const hex = digest.slice("sha256:".length);
  return Uint8Array.from(
    Array.from({ length: 32 }, (_, index) => Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16)),
  ).buffer as ArrayBuffer;
}

function candidate(): ReadyPublicationCandidate {
  const fixture = structuredClone(readyFixture) as Record<string, unknown>;
  return {
    environment: "staging",
    snapshot_id: String((fixture.ready_manifest as Record<string, unknown>).snapshot_id),
    physical: fixture.physical as ReadyPublicationCandidate["physical"],
    ready_manifest: fixture.ready_manifest as Record<string, unknown>,
    dependency_scope_evidence: fixture.dependency_scope_evidence as Record<string, unknown>,
    signed_projection_document: fixture.signed_projection_document as Record<string, unknown>,
  };
}

async function signingSecret(): Promise<string> {
  const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
  const bytes = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary);
}

function storedObject(bytes: Uint8Array): R2ObjectBody {
  return {
    size: bytes.byteLength,
    arrayBuffer: () => Promise.resolve(bytes.buffer.slice(0) as ArrayBuffer),
  } as unknown as R2ObjectBody;
}

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-02T12:00:30Z"));
  loadPinnedReadyKeysMock.mockReset();
  loadPinnedReadyKeysMock.mockResolvedValue([]);
  loadPinnedTraderKeysMock.mockReset();
  loadPinnedTraderKeysMock.mockResolvedValue([]);
  projectionMock.mockReset();
  projectionMock.mockResolvedValue({
    ok: true,
    value: {
      document_digest: sha("d"),
      issuer_key_id: "ops-projection-test",
      envelope: {},
      session_scope: readyFixture.controlled_session_scope,
    },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("READY publication physical R2 trust boundary", () => {
  it("accepts only the provider SHA-256 checksum", () => {
    const digest = sha("a");
    expect(providerVerifiedR2Digest({ checksums: { sha256: checksum(digest) } } as R2Object)).toBe(digest);
    expect(providerVerifiedR2Digest({ customMetadata: { sha256: digest } } as unknown as R2Object)).toBeNull();
    expect(providerVerifiedR2Digest({ checksums: {} } as R2Object)).toBeNull();
  });

  it("rejects a missing provider checksum without reading the snapshot body", async () => {
    const input = candidate();
    let gets = 0;
    const bucket = {
      head: vi.fn(async () => ({
        size: input.physical.size,
        customMetadata: { sha256: input.physical.digest },
        checksums: {},
      })),
      get: vi.fn(async () => {
        gets += 1;
        throw new Error("snapshot body must not be read");
      }),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const result = await publishPilotReady({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, input);
    expect(result).toMatchObject({ ok: false, status: "REJECTED" });
    expect(gets).toBe(0);
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("rejects a physical object not bound by the signed dependency scope", async () => {
    const input = candidate();
    projectionMock.mockResolvedValueOnce({
      ok: true,
      value: {
        document_digest: sha("d"),
        issuer_key_id: "ops-projection-test",
        envelope: {},
        session_scope: {
          ...readyFixture.controlled_session_scope,
          physical_db_digest: sha("b"),
        },
      },
    });
    const bucket = {
      head: vi.fn(),
      get: vi.fn(),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const result = await publishPilotReady({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, input);
    expect(result).toMatchObject({
      ok: false,
      status: "REJECTED",
      error: "signed Ops Projection physical snapshot digest mismatch",
    });
    expect(bucket.head).not.toHaveBeenCalled();
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("publishes the envelope at the consumer key with create-only writes", async () => {
    const input = candidate();
    const objects = new Map<string, Uint8Array>();
    const putOptions: unknown[] = [];
    const physicalKey = input.physical.key;
    const bucket = {
      head: vi.fn(async (key: string) => key === physicalKey ? ({
        size: input.physical.size,
        checksums: { sha256: checksum(input.physical.digest) },
      }) : null),
      get: vi.fn(async (key: string) => {
        if (key === physicalKey) throw new Error("snapshot body must not be read");
        const bytes = objects.get(key);
        return bytes ? storedObject(bytes) : null;
      }),
      put: vi.fn(async (key: string, value: Uint8Array, options: unknown) => {
        putOptions.push(options);
        objects.set(key, new Uint8Array(value));
        return {} as R2Object;
      }),
    } as unknown as R2Bucket;
    const result = await publishPilotReady({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, input);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.attestation_id).toMatch(/^ready-[0-9a-f]{64}$/);
    expect(result.envelope_key).toBe(controlledReadyKey(result.attestation_id));
    const stored = JSON.parse(new TextDecoder().decode(objects.get(result.envelope_key)));
    expect(stored.format).toBe("controlled-pilot-ready-envelope/v1");
    expect(stored.controlled_session_scope).toEqual(readyFixture.controlled_session_scope);
    expect(bucket.get).not.toHaveBeenCalledWith(physicalKey);
    expect(putOptions).toHaveLength(2);
    for (const options of putOptions as Array<{ onlyIf?: { etagDoesNotMatch?: string } }>) {
      expect(options.onlyIf?.etagDoesNotMatch).toBe("*");
    }
  });

  it("uses the full authority resource digest so distinct snapshots cannot collide", async () => {
    const first = candidate();
    const second = candidate();
    second.physical = {
      ...second.physical,
      digest: sha("b"),
      key: controlledPhysicalSnapshotKey(sha("b")),
    };
    const publish = async (input: ReadyPublicationCandidate) => {
      projectionMock.mockResolvedValueOnce({
        ok: true,
        value: {
          document_digest: sha("d"),
          issuer_key_id: "ops-projection-test",
          envelope: {},
          session_scope: {
            ...readyFixture.controlled_session_scope,
            physical_db_digest: input.physical.digest,
          },
        },
      });
      const objects = new Map<string, Uint8Array>();
      const bucket = {
        head: vi.fn(async () => ({
          size: input.physical.size,
          checksums: { sha256: checksum(input.physical.digest) },
        })),
        get: vi.fn(async (key: string) => {
          const bytes = objects.get(key);
          return bytes ? storedObject(bytes) : null;
        }),
        put: vi.fn(async (key: string, value: Uint8Array) => {
          objects.set(key, new Uint8Array(value));
          return {} as R2Object;
        }),
      } as unknown as R2Bucket;
      return publishPilotReady({
        STRUCTURED_BUCKET: bucket,
        OPS_PROJECTION_ENVIRONMENT: "staging",
        READY_ED25519_PRIVATE_KEY: await signingSecret(),
        READY_ED25519_KEY_ID: "ready-test",
        READY_DECLARED: "false",
      } as never, input);
    };
    const left = await publish(first);
    const right = await publish(second);
    expect(left.ok).toBe(true);
    expect(right.ok).toBe(true);
    if (!left.ok || !right.ok) return;
    expect(left.attestation_id).toMatch(/^ready-[0-9a-f]{64}$/);
    expect(right.attestation_id).toMatch(/^ready-[0-9a-f]{64}$/);
    expect(left.attestation_id).not.toBe(right.attestation_id);
  });

  it("rejects a conflicting immutable READY envelope", async () => {
    const input = candidate();
    const conflicting = new TextEncoder().encode('{"different":true}');
    const bucket = {
      head: vi.fn(async () => ({
        size: input.physical.size,
        checksums: { sha256: checksum(input.physical.digest) },
      })),
      get: vi.fn(async (key: string) =>
        key.endsWith(".attestation.json") ? null : storedObject(conflicting)),
      put: vi.fn(async (key: string) =>
        key.endsWith(".attestation.json") ? ({} as R2Object) : null),
    } as unknown as R2Bucket;
    const result = await publishPilotReady({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, input);
    expect(result).toMatchObject({ ok: false, status: "REJECTED" });
  });

  it("resumes byte-identically after a crash between attestation and envelope", async () => {
    const input = candidate();
    const objects = new Map<string, Uint8Array>();
    let crashOnce = true;
    const bucket = {
      head: vi.fn(async () => ({
        size: input.physical.size,
        checksums: { sha256: checksum(input.physical.digest) },
      })),
      get: vi.fn(async (key: string) => {
        const bytes = objects.get(key);
        return bytes ? storedObject(bytes) : null;
      }),
      put: vi.fn(async (key: string, value: Uint8Array) => {
        if (!key.endsWith(".attestation.json") && crashOnce) {
          crashOnce = false;
          throw new Error("simulated crash");
        }
        objects.set(key, new Uint8Array(value));
        return {} as R2Object;
      }),
    } as unknown as R2Bucket;
    const env = {
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never;
    await expect(publishPilotReady(env, input)).rejects.toThrow("simulated crash");
    expect([...objects.keys()]).toHaveLength(1);
    const retry = await publishPilotReady(env, input);
    expect(retry.ok).toBe(true);
    if (!retry.ok) return;
    expect(objects.has(retry.envelope_key)).toBe(true);
    expect(objects.has(retry.attestation_key)).toBe(true);
  });

  it("rejects when OPS_PROJECTION_ENVIRONMENT is missing or mismatches the candidate", async () => {
    const input = candidate();
    const secret = await signingSecret();
    for (const environmentFields of [
      {},
      { OPS_PROJECTION_ENVIRONMENT: "production" },
    ] as const) {
      const bucket = {
        head: vi.fn(),
        get: vi.fn(),
        put: vi.fn(),
      } as unknown as R2Bucket;
      projectionMock.mockClear();
      const result = await publishPilotReady({
        STRUCTURED_BUCKET: bucket,
        READY_ED25519_PRIVATE_KEY: secret,
        READY_ED25519_KEY_ID: "ready-test",
        READY_DECLARED: "false",
        ...environmentFields,
      } as never, input);
      expect(result).toMatchObject({
        ok: false,
        status: "REJECTED",
        error: "READY environment does not match OPS_PROJECTION_ENVIRONMENT",
      });
      expect(projectionMock).not.toHaveBeenCalled();
      expect(bucket.head).not.toHaveBeenCalled();
      expect(bucket.get).not.toHaveBeenCalled();
      expect(bucket.put).not.toHaveBeenCalled();
    }
  });

  it("leaves receipt-native v2 PENDING before attestation when a signing key is configured", async () => {
    const example = JSON.parse(
      readFileSync(
        fileURLToPath(
          new URL(
            "../../../../specs/ready/ready_manifest_v2.example.json",
            import.meta.url,
          ),
        ),
        "utf8",
      ),
    ) as Record<string, unknown>;
    const unsigned = { ...example };
    delete unsigned.manifest_digest;
    expect(await sha256Digest(canonicalJson(unsigned))).toBe(example.manifest_digest);
    const input = candidate();
    input.ready_manifest = example;
    const bucket = {
      head: vi.fn(),
      get: vi.fn(),
      put: vi.fn(),
    } as unknown as R2Bucket;
    const result = await publishPilotReady({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, input);
    expect(result).toMatchObject({
      ok: false,
      status: "PENDING",
      error: "receipt-native ready-manifest/v2 is not supported for attestation",
      ready_declared: false,
      operational_go: false,
    });
    expect(projectionMock).not.toHaveBeenCalled();
    expect(bucket.put).not.toHaveBeenCalled();
    const malformed = { ...unsigned, feature_generation: 1 };
    const malformedDigest = await sha256Digest(canonicalJson(malformed));
    const malformedResult = await publishPilotReady({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, {
      ...input,
      ready_manifest: { ...malformed, manifest_digest: malformedDigest },
    });
    expect(malformedResult).toMatchObject({ ok: false, status: "REJECTED" });
    expect(String(malformedResult.error)).toMatch(/feature_generation/);
    const cursorPayload = {
      ...input.ready_manifest,
      source_generation: "1",
    };
    const rejected = await publishPilotReady({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, { ...input, ready_manifest: cursorPayload });
    expect(rejected).toMatchObject({ ok: false, status: "REJECTED" });
    expect(String(rejected.error)).toMatch(/cursor|closed/);
  });
});

describe("pointer receipt-native READY publication", () => {
  const jobId = "r05-candidate-pub-1";
  const phys = sha("1");

  async function signingPair(): Promise<{ secret: string; publicKey: Uint8Array }> {
    const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
    const priv = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
    const pub = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
    let binary = "";
    for (const value of priv) binary += String.fromCharCode(value);
    return { secret: btoa(binary), publicKey: pub };
  }

  function objectWithChecksum(
    digest: string,
    size: number,
    body?: Uint8Array,
  ): R2Object & R2ObjectBody {
    const bytes = body ?? new Uint8Array([1, 2, 3]);
    return {
      size,
      checksums: { sha256: checksum(digest) },
      arrayBuffer: () => Promise.resolve(bytes.buffer.slice(0) as ArrayBuffer),
    } as unknown as R2Object & R2ObjectBody;
  }

  function candidateBucket(
    terminal: Record<string, unknown>,
    proofDigest: string,
    scopeBytes: Uint8Array,
  ): { bucket: R2Bucket; stored: Map<string, Uint8Array> } {
    const terminalBytes = new TextEncoder().encode(JSON.stringify(terminal));
    const objects = new Map<string, R2Object & R2ObjectBody>();
    objects.set(
      personalReceiptCandidateManifestKey(jobId),
      objectWithChecksum(sha("t"), terminalBytes.byteLength, terminalBytes),
    );
    objects.set(
      personalReceiptCandidatePhysicalKey(phys.slice("sha256:".length)),
      objectWithChecksum(phys, 3),
    );
    objects.set(
      personalReceiptCandidateScopeKey(proofDigest.slice("sha256:".length)),
      objectWithChecksum(proofDigest, scopeBytes.byteLength, scopeBytes),
    );
    const stored = new Map<string, Uint8Array>();
    const bucket = {
      head: vi.fn(async (key: string) => objects.get(key) ?? null),
      get: vi.fn(async (key: string) => {
        const putBody = stored.get(key);
        if (putBody) {
          return {
            size: putBody.byteLength,
            arrayBuffer: () => Promise.resolve(putBody.buffer.slice(0) as ArrayBuffer),
          } as unknown as R2ObjectBody;
        }
        return objects.get(key) ?? null;
      }),
      put: vi.fn(async (key: string, value: ArrayBuffer | Uint8Array) => {
        const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
        stored.set(key, bytes);
        return { key, size: bytes.byteLength } as R2Object;
      }),
    } as unknown as R2Bucket;
    return { bucket, stored };
  }

  async function sealNative(
    terminal: Record<string, unknown>,
    native: Record<string, unknown>,
  ): Promise<void> {
    delete native.manifest_digest;
    native.manifest_digest = await sha256Digest(canonicalJson(native));
    terminal.receipt_native_manifest = native;
    terminal.receipt_native_manifest_digest = native.manifest_digest;
  }

  async function sealQuality(
    terminal: Record<string, unknown>,
    native: Record<string, unknown>,
    quality: Record<string, unknown>,
  ): Promise<void> {
    const proofContext = {
      physical_digest: quality.physical_digest,
      profile_digest: quality.profile_digest,
      plan_set_digest: quality.plan_set_digest,
      dependency_closure_digest: quality.dependency_closure_digest,
      receipt_runset_digest: quality.receipt_runset_digest,
      period_start: quality.period_start,
      period_end: quality.period_end,
      observation_policy: quality.observation_policy,
      observed_through: quality.observed_through,
    };
    const b0 = await sha256Digest(canonicalJson({ ...proofContext, b0: quality.b0 }));
    const b4 = await sha256Digest(canonicalJson({ ...proofContext, b4: quality.b4 }));
    const qualityDigest = await sha256Digest(canonicalJson(quality));
    terminal.snapshot_quality = quality;
    terminal.snapshot_quality_digest = qualityDigest;
    terminal.snapshot_b0_status = quality.b0_status;
    terminal.b0_proof_digest = b0;
    terminal.b4_proof_digest = b4;
    terminal.validation_proof_digest = qualityDigest;
    native.b0_proof_digest = b0;
    native.b4_proof_digest = b4;
    native.validation_proof_digest = qualityDigest;
    await sealNative(terminal, native);
  }

  async function stagingPublish(bucket: R2Bucket) {
    return publishAdmittedReceiptCandidate({
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: await signingSecret(),
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as never, { job_id: jobId, environment: "staging" });
  }

  async function admittedNative(): Promise<{
    terminal: Record<string, unknown>;
    native: Record<string, unknown>;
    proofDigest: string;
    scopeBytes: Uint8Array;
  }> {
    const example = JSON.parse(
      readFileSync(
        fileURLToPath(
          new URL("../../../../specs/ready/ready_manifest_v2.example.json", import.meta.url),
        ),
        "utf8",
      ),
    ) as Record<string, unknown>;
    const fixture = structuredClone(readyFixture) as Record<string, unknown>;
    const unsignedScope = {
      ...(fixture.dependency_scope_evidence as Record<string, unknown>),
    };
    delete unsignedScope.proof_digest;
    unsignedScope.physical_db_digest = phys;
    const proofDigest = await sha256Digest(canonicalJson(unsignedScope));
    const scopeBytes = new TextEncoder().encode(canonicalJson(unsignedScope));
    const observedThrough = "2026-08-25T00:00:00+00:00";
    const source = {
      ...(example.source as Record<string, unknown>),
      environment: "staging",
      authority_instance_digest:
        PINNED_RECEIPT_REGISTRY_SCOPE.staging.authority_instance_digest,
      physical_digest: phys,
      compiled_scope_proof_digest: proofDigest,
      receipt_runset_digest: sha("e"),
      observed_through: observedThrough,
    };
    const quality = {
      kind: "receipt-candidate-snapshot-quality/v1",
      physical_digest: phys,
      profile_digest: EXACT_FOUR_PROFILE_DIGEST,
      plan_set_digest: EXACT_FOUR_PLAN_SET_DIGEST,
      dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
      receipt_runset_digest: sha("e"),
      observation_policy: "max_verified_claims_checked_at",
      observed_through: observedThrough,
      period_start: unsignedScope.period_start,
      period_end: unsignedScope.period_end,
      b0: [
        { name: "B0_master", ok: true, value: 4000, gate: 3000, detail: "master issuers=4000 gate>=3000" },
        { name: "B0_bars_issuers", ok: true, value: 4100, gate: 3000, detail: "bar issuers=4100 gate>=3000" },
        { name: "B0_bars_latest_day", ok: true, value: 4200, gate: 3000, detail: "latest day rows=4200 gate>=3000" },
      ],
      b4: [
        {
          check_id: "B4",
          dataset: "equities_bars_daily",
          status: "pass",
          detail: "all trading days covered",
          metrics: {
            bar_dates: 1,
            trading_days_in_window: 1,
            gap_rate: 0,
            missing_day_count: 0,
            missing_days_sample: [],
          },
        },
      ],
      c8: [
        {
          check_id: "C8",
          dataset: "equities_bars_daily",
          status: "pass",
          detail: "0 day(s) since latest event_time",
          metrics: {
            latest_event_time: unsignedScope.period_end,
            reference: unsignedScope.period_end,
            max_days: 7,
            days_lag: 0,
          },
        },
        {
          check_id: "C8",
          dataset: "indices_bars_daily_topix",
          status: "pass",
          detail: "0 day(s) since latest event_time",
          metrics: {
            latest_event_time: unsignedScope.period_end,
            reference: unsignedScope.period_end,
            max_days: 7,
            days_lag: 0,
          },
        },
        {
          check_id: "C8",
          dataset: "markets_calendar",
          status: "pass",
          detail: "0 day(s) since latest event_time",
          metrics: {
            latest_event_time: unsignedScope.period_end,
            reference: unsignedScope.period_end,
            max_days: 7,
            days_lag: 0,
          },
        },
      ],
      b0_status: "PASS",
      b4_status: "PASS",
      c8_status: "PASS",
    };
    const proofContext = {
      physical_digest: phys,
      profile_digest: EXACT_FOUR_PROFILE_DIGEST,
      plan_set_digest: EXACT_FOUR_PLAN_SET_DIGEST,
      dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
      receipt_runset_digest: sha("e"),
      period_start: unsignedScope.period_start,
      period_end: unsignedScope.period_end,
      observation_policy: "max_verified_claims_checked_at",
      observed_through: observedThrough,
    };
    const b0 = await sha256Digest(canonicalJson({ ...proofContext, b0: quality.b0 }));
    const b4 = await sha256Digest(canonicalJson({ ...proofContext, b4: quality.b4 }));
    const qualityDigest = await sha256Digest(canonicalJson(quality));
    const coverage = await sha256Digest(canonicalJson({
      kind: "coverage-proof",
      physical: phys,
      datasets: unsignedScope.dataset_ids ?? [],
    }));
    const raw = await sha256Digest(canonicalJson({ kind: "raw-proof", physical: phys }));
    const receipt = await sha256Digest(canonicalJson({ kind: "receipt-proof", physical: phys }));
    const native: Record<string, unknown> = { ...example, source };
    native.b0_proof_digest = b0;
    native.b4_proof_digest = b4;
    native.validation_proof_digest = qualityDigest;
    native.coverage_proof_digest = coverage;
    native.raw_proof_digest = raw;
    native.receipt_proof_digest = receipt;
    native.resolved_universe_digest = unsignedScope.resolved_universe_digest;
    native.feature_generation = (readyFixture.ready_manifest as Record<string, unknown>).feature_generation;
    native.catalog_generation = (readyFixture.ready_manifest as Record<string, unknown>).catalog_generation;
    native.pit_contract_digests = { dependency_scope: proofDigest };
    native.snapshot_id = await sha256Digest(canonicalJson({ source }));
    delete native.manifest_digest;
    native.manifest_digest = await sha256Digest(canonicalJson(native));
    const terminal = {
      format: "receipt-candidate/v1",
      job_id: jobId,
      status: "COMPLETED",
      compiled_scope_status: "PASS",
      compiled_scope_physical_digest: phys,
      compiled_scope_proof_digest: proofDigest,
      raw_sha256: phys,
      physical_key: personalReceiptCandidatePhysicalKey(phys.slice("sha256:".length)),
      dependency_scope_key: personalReceiptCandidateScopeKey(proofDigest.slice("sha256:".length)),
      receipt_native_manifest: native,
      receipt_native_manifest_digest: native.manifest_digest,
      snapshot_quality_kind: "receipt-candidate-snapshot-quality/v1",
      snapshot_quality_digest: qualityDigest,
      snapshot_quality: quality,
      snapshot_b0_status: "PASS",
      snapshot_b4_status: "PASS",
      snapshot_c8_status: "PASS",
      b0_proof_digest: b0,
      b4_proof_digest: b4,
      validation_proof_digest: qualityDigest,
    };
    return { terminal, native, proofDigest, scopeBytes };
  }

  it("signs a pointer-admitted native candidate and the Cloud verifier accepts it", async () => {
    const { terminal, native, proofDigest, scopeBytes } = await admittedNative();
    const { bucket, stored } = candidateBucket(terminal, proofDigest, scopeBytes);
    const pair = await signingPair();
    const traderPair = await signingPair();
    loadPinnedReadyKeysMock.mockResolvedValue([
      {
        key_id: "ready-test",
        public_key: pair.publicKey,
        algorithm: "Ed25519",
        status: "active",
        not_before: "2020-01-01T00:00:00Z",
        not_after: "2099-01-01T00:00:00Z",
        revoked_at: null,
        environment: "staging",
      },
    ]);
    const env = {
      STRUCTURED_BUCKET: bucket,
      OPS_PROJECTION_ENVIRONMENT: "staging",
      READY_ED25519_PRIVATE_KEY: pair.secret,
      READY_ED25519_KEY_ID: "ready-test",
      READY_DECLARED: "false",
    } as Record<string, unknown>;
    const first = await publishAdmittedReceiptCandidate(env as never, {
      job_id: jobId,
      environment: "staging",
    });
    expect(first).toMatchObject({
      ok: false,
      status: "PENDING",
      error: "TRADER_ED25519_PRIVATE_KEY unprovisioned",
    });
    const envelopeKey = [...stored.keys()].find(
      (key) => key.includes("/v1/ready/") && key.endsWith(".json") && !key.includes(".attestation."),
    );
    expect(envelopeKey).toBeTruthy();
    const envelopeBytes = stored.get(envelopeKey!);
    expect(envelopeBytes).toBeTruthy();
    const envelope = JSON.parse(new TextDecoder().decode(envelopeBytes)) as Record<string, unknown>;
    expect(envelope.format).toBe(CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT);
    const verified = await verifyReceiptNativeReadyPublication(
      envelope,
      String(native.snapshot_id),
      "staging",
    );
    if (!verified.ok) throw new Error(verified.error);
    const firstPublishedAt = isRecord(envelope.attestation)
      ? envelope.attestation.verified_at
      : null;
    const firstAttestationBytes = stored.get(`${envelopeKey}.attestation.json`);
    const traderKey = {
      key_id: "trader-test",
      public_key: traderPair.publicKey,
      algorithm: "Ed25519" as const,
      status: "active" as const,
      not_before: "2026-09-02T12:10:00Z",
      not_after: "2099-01-01T00:00:00Z",
      revoked_at: null,
      environment: "staging",
    };
    loadPinnedTraderKeysMock.mockResolvedValue([traderKey]);
    env.TRADER_ED25519_PRIVATE_KEY = traderPair.secret;
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-02T12:20:00Z"));
    const minted = await publishAdmittedReceiptCandidate(env as never, {
      job_id: jobId,
      environment: "staging",
    });
    expect(minted).toMatchObject({
      ok: true,
      status: "VERIFIED_PILOT_READINESS",
      ready_declared: false,
      operational_go: false,
      mass_research: "NO-GO",
    });
    if (!minted.ok) throw new Error(String(minted.error));
    expect(stored.get(minted.envelope_key)).toEqual(envelopeBytes);
    const authKey = controlledTraderAuthorizationKey(jobId, minted.attestation_id);
    const authBytes = stored.get(authKey);
    expect(authBytes).toBeTruthy();
    const traderDoc = JSON.parse(new TextDecoder().decode(authBytes)) as Record<string, unknown>;
    expect(traderDoc.issued_at).toBe("2026-09-02T12:20:00Z");
    expect(traderDoc.issued_at).not.toBe(firstPublishedAt);
    expect(traderDoc.expires_at).toBe(
      isRecord(envelope.attestation) ? envelope.attestation.expires_at : null,
    );
    const traderRequest = {
      idempotency_key: jobId,
      ready_attestation_id: minted.attestation_id,
      snapshot_id: String(native.snapshot_id),
    };
    const authorized = await verifyTraderAuthorizationBatch(
      traderDoc,
      traderRequest,
      {
        environment: "staging",
        ready_manifest_digest: String(
          isRecord(envelope.attestation) ? envelope.attestation.ready_manifest_digest : "",
        ),
        snapshot_id: String(native.snapshot_id),
        immutable_db_digest: String(isRecord(envelope.physical) ? envelope.physical.digest : ""),
        physical: {
          key: String(isRecord(envelope.physical) ? envelope.physical.key : ""),
          size: Number(isRecord(envelope.physical) ? envelope.physical.size : 0),
        },
        profile_digest: EXACT_FOUR_PROFILE_DIGEST,
        dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
        resolved_universe_digest: String(
          isRecord(envelope.attestation) ? envelope.attestation.resolved_universe_digest : "",
        ),
      },
      await controlledPilotRequestDigest(traderRequest),
      [traderKey],
    );
    expect(authorized.ok).toBe(true);
    stored.delete(`${envelopeKey}.attestation.json`);
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-02T12:40:00Z"));
    const retry = await publishAdmittedReceiptCandidate(env as never, {
      job_id: jobId,
      environment: "staging",
    });
    expect(retry).toMatchObject({
      ok: true,
      attestation_id: minted.attestation_id,
      envelope_key: minted.envelope_key,
    });
    expect(stored.get(minted.envelope_key)).toEqual(envelopeBytes);
    expect(stored.get(authKey)).toEqual(authBytes);
    expect(stored.get(`${envelopeKey}.attestation.json`)).toEqual(firstAttestationBytes);
  });

  it("rejects outer PASS labels when B0 measure rows are not ok", async () => {
    const { terminal, proofDigest, scopeBytes } = await admittedNative();
    const quality = {
      ...(terminal.snapshot_quality as Record<string, unknown>),
    };
    const b0 = [...(quality.b0 as Array<Record<string, unknown>>)].slice(0, 2);
    quality.b0 = b0;
    quality.b0_status = "PASS";
    const native = terminal.receipt_native_manifest as Record<string, unknown>;
    await sealQuality(terminal, native, quality);
    const { bucket } = candidateBucket(terminal, proofDigest, scopeBytes);
    const result = await stagingPublish(bucket);
    expect(result).toMatchObject({ ok: false, status: "REJECTED" });
    expect(String(result.error)).toMatch(/B0 measures are incomplete/);
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("rejects production source published under staging", async () => {
    const { terminal, proofDigest, scopeBytes, native } = await admittedNative();
    const source = {
      ...(native.source as Record<string, unknown>),
      environment: "production",
      authority_instance_digest:
        PINNED_RECEIPT_REGISTRY_SCOPE.production.authority_instance_digest,
    };
    native.source = source;
    native.snapshot_id = await sha256Digest(canonicalJson({ source }));
    delete native.manifest_digest;
    native.manifest_digest = await sha256Digest(canonicalJson(native));
    await sealNative(terminal, native);
    const { bucket } = candidateBucket(terminal, proofDigest, scopeBytes);
    const result = await stagingPublish(bucket);
    expect(result).toMatchObject({ ok: false, status: "REJECTED" });
    expect(String(result.error)).toMatch(/source environment/);
  });

  it("does not publish diagnostic MISSING generation pins as READY", async () => {
    const { terminal, native, proofDigest, scopeBytes } = await admittedNative();
    native.feature_generation = "MISSING";
    await sealNative(terminal, native);
    const { bucket } = candidateBucket(terminal, proofDigest, scopeBytes);
    const result = await stagingPublish(bucket);
    expect(result).toMatchObject({ ok: false, status: "PENDING" });
    expect(String(result.error)).toMatch(/feature_generation/);
    expect(bucket.put).not.toHaveBeenCalled();
  });

  it("rejects a coherent quality and scope period that is not the contract window", async () => {
    const { terminal, native, proofDigest, scopeBytes } = await admittedNative();
    const quality = {
      ...(terminal.snapshot_quality as Record<string, unknown>),
    };
    quality.period_end = quality.period_start;
    const unsigned = JSON.parse(new TextDecoder().decode(scopeBytes)) as Record<string, unknown>;
    unsigned.period_end = quality.period_start;
    const shortenedProof = await sha256Digest(canonicalJson(unsigned));
    const shortenedScope = new TextEncoder().encode(canonicalJson(unsigned));
    native.source = {
      ...(native.source as Record<string, unknown>),
      compiled_scope_proof_digest: shortenedProof,
    };
    native.pit_contract_digests = { dependency_scope: shortenedProof };
    native.snapshot_id = await sha256Digest(canonicalJson({ source: native.source }));
    terminal.compiled_scope_proof_digest = shortenedProof;
    terminal.dependency_scope_key = personalReceiptCandidateScopeKey(
      shortenedProof.slice("sha256:".length),
    );
    await sealQuality(terminal, native, quality);
    const { bucket } = candidateBucket(terminal, shortenedProof, shortenedScope);
    const result = await stagingPublish(bucket);
    expect(result).toMatchObject({ ok: false, status: "REJECTED" });
    expect(String(result.error)).toMatch(/canonical exact-four/);
    expect(bucket.put).not.toHaveBeenCalled();
    expect(proofDigest).not.toBe(shortenedProof);
  });
});
