import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CONTROLLED_READY_RECEIPT_NATIVE_ENVELOPE_FORMAT,
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_PLAN_SET_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  controlledOpsReadyPointerKey,
  controlledPilotRequestDigest,
  controlledTraderAuthorizationKey,
} from "../../research-mass-eval/src/controlled_pilot_contract";
import { verifyReceiptNativeReadyPublication } from "../../research-mass-eval/src/receipt_native_ready_publication";
import {
  personalReceiptCandidateManifestKey,
  personalReceiptCandidateScopeKey,
} from "../../research-mass-eval/src/personal_receipt_candidate_contract";
import { PINNED_RECEIPT_REGISTRY_SCOPE } from "./ops_projection_policy";

const loadPinnedReadyKeysMock = vi.hoisted(() => vi.fn());
const loadPinnedTraderKeysMock = vi.hoisted(() => vi.fn());
vi.mock("cloudflare:workers", () => ({ WorkerEntrypoint: class {} }));
vi.mock("../../research-mass-eval/src/controlled_pilot_registries", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../research-mass-eval/src/controlled_pilot_registries")>();
  return {
    ...actual,
    loadPinnedReadyKeys: loadPinnedReadyKeysMock,
    loadPinnedTraderKeys: loadPinnedTraderKeysMock,
  };
});

import {
  canonicalJson,
  isRecord,
  sha256Digest,
} from "../../research-mass-eval/src/controlled_pilot_json";
import { verifyTraderAuthorizationBatch } from "../../research-mass-eval/src/controlled_pilot_trader_batch";
import {
  admittedNativePublication,
  nativePublishCandidateBucket,
  nativePublishSigningPair,
} from "../test_support/ready_native_publication_test_support";
import {
  providerVerifiedR2Digest,
  publishAdmittedReceiptCandidate,
} from "./ready_publication";

const sha = (character: string): string => `sha256:${character.repeat(64)}`;

function checksum(digest: string): ArrayBuffer {
  const hex = digest.slice("sha256:".length);
  return Uint8Array.from(
    Array.from({ length: 32 }, (_, index) => Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16)),
  ).buffer as ArrayBuffer;
}

async function signingSecret(): Promise<string> {
  const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
  const bytes = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary);
}

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-02T12:00:30Z"));
  loadPinnedReadyKeysMock.mockReset();
  loadPinnedReadyKeysMock.mockResolvedValue([]);
  loadPinnedTraderKeysMock.mockReset();
  loadPinnedTraderKeysMock.mockResolvedValue([]);
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
});

describe("pointer receipt-native READY publication", () => {
  const jobId = "r05-candidate-pub-1";
  const signingPair = nativePublishSigningPair;

  function candidateBucket(
    terminal: Record<string, unknown>,
    proofDigest: string,
    scopeBytes: Uint8Array,
  ): { bucket: R2Bucket; stored: Map<string, Uint8Array> } {
    return nativePublishCandidateBucket(
      jobId,
      String(terminal.compiled_scope_physical_digest),
      terminal,
      proofDigest,
      scopeBytes,
    );
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
    return admittedNativePublication(jobId);
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
    const pointerKey = controlledOpsReadyPointerKey("staging");
    const pointerAfterMint = stored.get(pointerKey);
    expect(pointerAfterMint).toBeTruthy();
    expect(JSON.parse(new TextDecoder().decode(pointerAfterMint)).envelope_key).toBe(
      minted.envelope_key,
    );
    stored.delete(pointerKey);
    const recovered = await publishAdmittedReceiptCandidate(env as never, {
      job_id: jobId,
      environment: "staging",
    });
    expect(recovered).toMatchObject({
      ok: true,
      attestation_id: minted.attestation_id,
      envelope_key: minted.envelope_key,
    });
    expect(stored.get(minted.envelope_key)).toEqual(envelopeBytes);
    expect(stored.get(authKey)).toEqual(authBytes);
    const recoveredPointer = JSON.parse(
      new TextDecoder().decode(stored.get(pointerKey)),
    ) as { envelope_key: string; published_at: string };
    expect(recoveredPointer.envelope_key).toBe(minted.envelope_key);
    const job2 = "r05-candidate-pub-2";
    const second = await admittedNativePublication(job2);
    await bucket.put(
      personalReceiptCandidateManifestKey(job2),
      new TextEncoder().encode(JSON.stringify(second.terminal)),
    );
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-02T12:40:00.500Z"));
    const newer = await publishAdmittedReceiptCandidate(env as never, {
      job_id: job2,
      environment: "staging",
    });
    expect(newer.ok).toBe(true);
    if (!newer.ok) throw new Error(String(newer.error));
    expect(JSON.parse(new TextDecoder().decode(stored.get(pointerKey))).envelope_key).toBe(
      newer.envelope_key,
    );
    vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-02T12:40:01Z"));
    const olderRetry = await publishAdmittedReceiptCandidate(env as never, {
      job_id: jobId,
      environment: "staging",
    });
    expect(olderRetry).toMatchObject({
      ok: true,
      envelope_key: minted.envelope_key,
    });
    expect(JSON.parse(new TextDecoder().decode(stored.get(pointerKey))).envelope_key).toBe(
      newer.envelope_key,
    );
    expect(stored.get(minted.envelope_key)).toEqual(envelopeBytes);
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
