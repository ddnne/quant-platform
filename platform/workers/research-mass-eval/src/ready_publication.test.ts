import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import readyFixture from "../../../../specs/ready/controlled_pilot_ready.generated.json";
import { controlledPhysicalSnapshotKey, controlledReadyKey } from "./controlled_pilot_contract";

const projectionMock = vi.hoisted(() => vi.fn());
vi.mock("cloudflare:workers", () => ({ WorkerEntrypoint: class {} }));
vi.mock("./ops_projection_ready", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./ops_projection_ready")>();
  return { ...actual, verifyOpsProjectionReady: projectionMock };
});

import {
  providerVerifiedR2Digest,
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
});
