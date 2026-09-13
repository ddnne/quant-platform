import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { vi } from "vitest";

import readyFixture from "../../../../specs/ready/controlled_pilot_ready.generated.json";
import {
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_PLAN_SET_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  controlledTraderAuthorizationKey,
} from "../../research-mass-eval/src/controlled_pilot_contract";
import {
  canonicalJson,
  isRecord,
  sha256Digest,
} from "../../research-mass-eval/src/controlled_pilot_json";
import {
  personalReceiptCandidateManifestKey,
  personalReceiptCandidatePhysicalKey,
  personalReceiptCandidateScopeKey,
} from "../../research-mass-eval/src/personal_receipt_candidate_contract";
import { PINNED_RECEIPT_REGISTRY_SCOPE } from "../src/ops_projection_policy";
import { publishAdmittedReceiptCandidate } from "../src/ready_publication";

export const NATIVE_PUBLISH_JOB_ID = "r1";
export const NATIVE_PHYSICAL_BYTES = new Uint8Array([1, 2, 3]);

export async function nativePhysicalDigest(): Promise<string> {
  return sha256Digest(NATIVE_PHYSICAL_BYTES);
}

export function nativePublishSha(character: string): string {
  return `sha256:${character.repeat(64)}`;
}

export function nativePublishChecksum(digest: string): ArrayBuffer {
  const hex = digest.slice("sha256:".length);
  return Uint8Array.from(
    Array.from({ length: 32 }, (_, index) => Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16)),
  ).buffer as ArrayBuffer;
}

export async function nativePublishSigningPair(): Promise<{ secret: string; publicKey: Uint8Array }> {
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
  const bytes = body ?? NATIVE_PHYSICAL_BYTES;
  return {
    size,
    checksums: { sha256: nativePublishChecksum(digest) },
    arrayBuffer: () => Promise.resolve(bytes.buffer.slice(0) as ArrayBuffer),
  } as unknown as R2Object & R2ObjectBody;
}

export function nativePublishCandidateBucket(
  jobId: string,
  phys: string,
  terminal: Record<string, unknown>,
  proofDigest: string,
  scopeBytes: Uint8Array,
): { bucket: R2Bucket; stored: Map<string, Uint8Array> } {
  const terminalBytes = new TextEncoder().encode(JSON.stringify(terminal));
  const objects = new Map<string, R2Object & R2ObjectBody>();
  objects.set(
    personalReceiptCandidateManifestKey(jobId),
    objectWithChecksum(nativePublishSha("t"), terminalBytes.byteLength, terminalBytes),
  );
  objects.set(
    personalReceiptCandidatePhysicalKey(phys.slice("sha256:".length)),
    objectWithChecksum(phys, NATIVE_PHYSICAL_BYTES.byteLength, NATIVE_PHYSICAL_BYTES),
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

export async function admittedNativePublication(
  jobId: string,
): Promise<{
  terminal: Record<string, unknown>;
  native: Record<string, unknown>;
  proofDigest: string;
  scopeBytes: Uint8Array;
  phys: string;
}> {
  const phys = await nativePhysicalDigest();
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
    receipt_runset_digest: nativePublishSha("e"),
    observed_through: observedThrough,
  };
  const quality = {
    kind: "receipt-candidate-snapshot-quality/v1",
    physical_digest: phys,
    profile_digest: EXACT_FOUR_PROFILE_DIGEST,
    plan_set_digest: EXACT_FOUR_PLAN_SET_DIGEST,
    dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
    receipt_runset_digest: nativePublishSha("e"),
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
    receipt_runset_digest: nativePublishSha("e"),
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
  return { terminal, native, proofDigest, scopeBytes, phys };
}

export async function mintPairedNativeReadyTrader(args: {
  jobId?: string;
  readySecret: string;
  traderSecret: string;
  readyKeyId?: string;
}): Promise<{
  jobId: string;
  snapshotId: string;
  attestationId: string;
  admittedNativeDigest: string;
  envelopeKey: string;
  envelopeBytes: Uint8Array;
  traderObjectKey: string;
  traderBytes: Uint8Array;
  physicalKey: string;
  physicalDigest: string;
  physicalBytes: Uint8Array;
  physicalSize: number;
  nativeSource: Record<string, unknown>;
  authorizationDigest: string;
}> {
  const jobId = args.jobId ?? NATIVE_PUBLISH_JOB_ID;
  const { terminal, native, proofDigest, scopeBytes, phys } = await admittedNativePublication(jobId);
  const { bucket, stored } = nativePublishCandidateBucket(
    jobId,
    phys,
    terminal,
    proofDigest,
    scopeBytes,
  );
  const minted = await publishAdmittedReceiptCandidate({
    STRUCTURED_BUCKET: bucket,
    OPS_PROJECTION_ENVIRONMENT: "staging",
    READY_ED25519_PRIVATE_KEY: args.readySecret,
    READY_ED25519_KEY_ID: args.readyKeyId ?? "ready-test",
    TRADER_ED25519_PRIVATE_KEY: args.traderSecret,
    READY_DECLARED: "false",
  } as never, { job_id: jobId, environment: "staging" });
  if (!minted.ok) throw new Error(String(minted.error));
  const envelopeBytes = stored.get(minted.envelope_key);
  const traderObjectKey = controlledTraderAuthorizationKey(jobId, minted.attestation_id);
  const traderBytes = stored.get(traderObjectKey);
  if (!envelopeBytes || !traderBytes) {
    throw new Error("native publication did not persist envelope and trader");
  }
  const envelope = JSON.parse(new TextDecoder().decode(envelopeBytes)) as Record<string, unknown>;
  const traderDoc = JSON.parse(new TextDecoder().decode(traderBytes)) as Record<string, unknown>;
  const manifest = isRecord(envelope.ready_manifest) ? envelope.ready_manifest : {};
  const source = isRecord(manifest.source) ? manifest.source : {};
  const physical = isRecord(envelope.physical) ? envelope.physical : {};
  return {
    jobId,
    snapshotId: minted.snapshot_id,
    attestationId: minted.attestation_id,
    admittedNativeDigest: String(envelope.admitted_native_digest),
    envelopeKey: minted.envelope_key,
    envelopeBytes,
    traderObjectKey,
    traderBytes,
    physicalKey: String(physical.key),
    physicalDigest: minted.immutable_db_digest,
    physicalBytes: NATIVE_PHYSICAL_BYTES,
    physicalSize: Number(physical.size),
    nativeSource: source,
    authorizationDigest: await sha256Digest(canonicalJson(traderDoc)),
  };
}
