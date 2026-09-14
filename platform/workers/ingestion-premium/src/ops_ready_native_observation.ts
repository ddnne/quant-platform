/** Observe known R2 READY pointer/envelope for Ops. Pointer is discovery, not authority. */

import { CREATE_ONLY_COMPARE_MAX_BYTES } from "../../research-mass-eval/src/http";
import {
  loadPinnedReadyKeys,
  loadPinnedTraderKeys,
} from "../../research-mass-eval/src/controlled_pilot_registries";
import { verifyReceiptNativeReadyPublication } from "../../research-mass-eval/src/receipt_native_ready_publication";
import {
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  controlledOpsReadyPointerKey,
  controlledPilotRequestDigest,
  controlledReadyKey,
  controlledTraderAuthorizationKey,
  parseOpsReadyPointer,
  type ControlledPilotRequest,
} from "../../research-mass-eval/src/controlled_pilot_contract";
import {
  verifyTraderAuthorizationBatch,
  type TraderReadyBind,
} from "../../research-mass-eval/src/controlled_pilot_trader_batch";
import {
  canonicalJson,
  isRecord,
  parseCanonicalUtc,
  sha256Digest,
} from "../../research-mass-eval/src/controlled_pilot_json";

export type NativeReadyObservation = {
  eligibility: "READY" | "NOT_READY";
  reason: string;
  envelope_digest: string | null;
  trader_authorization_digest: string | null;
  attestation_id: string | null;
  snapshot_id: string | null;
  published_at: string | null;
  physical_digest: string | null;
  ready_key_id: string | null;
  snapshot: {
    snapshot_id: string;
    state: "READY";
    committed_at: string;
    source_run_id: null;
    change_seq: null;
    coverage_policy_version: string;
    quality_policy_version: string;
    coverage_proof_digest: string;
    manifest_json: string;
  } | null;
};

export function nativeReadyEvidenceFingerprint(observation: NativeReadyObservation): {
  eligibility: NativeReadyObservation["eligibility"];
  reason: string;
  envelope_digest: string | null;
  trader_authorization_digest: string | null;
  attestation_id: string | null;
  snapshot_id: string | null;
  published_at: string | null;
  physical_digest: string | null;
  ready_key_id: string | null;
} {
  return {
    eligibility: observation.eligibility,
    reason: observation.reason,
    envelope_digest: observation.envelope_digest,
    trader_authorization_digest: observation.trader_authorization_digest,
    attestation_id: observation.attestation_id,
    snapshot_id: observation.snapshot_id,
    published_at: observation.published_at,
    physical_digest: observation.physical_digest,
    ready_key_id: observation.ready_key_id,
  };
}

async function readBoundedJson(
  object: { size: number; arrayBuffer(): Promise<ArrayBuffer> },
  maximum: number,
): Promise<Record<string, unknown> | null> {
  if (!Number.isSafeInteger(object.size) || object.size < 1 || object.size > maximum) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(
      new TextDecoder().decode(await object.arrayBuffer()),
    );
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function observeNativeReadyForOps(
  bucket: R2Bucket | undefined,
  environment: string,
  clock: { now(): number } = { now: () => Date.now() },
): Promise<NativeReadyObservation> {
  const ineligible = (
    reason: string,
    fields: Partial<NativeReadyObservation> = {},
  ): NativeReadyObservation => ({
    eligibility: "NOT_READY",
    reason,
    envelope_digest: null,
    trader_authorization_digest: null,
    attestation_id: null,
    snapshot_id: null,
    published_at: null,
    physical_digest: null,
    ready_key_id: null,
    snapshot: null,
    ...fields,
  });
  if (!bucket) return ineligible("native READY pointer is absent");
  if (environment !== "production" && environment !== "staging") {
    return ineligible("native READY environment is invalid");
  }
  const pointerObject = await bucket.get(controlledOpsReadyPointerKey(environment));
  if (!pointerObject) return ineligible("native READY pointer is absent");
  const pointer = parseOpsReadyPointer(
    await readBoundedJson(pointerObject, CREATE_ONLY_COMPARE_MAX_BYTES),
  );
  if (!pointer || pointer.environment !== environment) {
    return ineligible("native READY pointer is not usable");
  }
  const envelopeObject = await bucket.get(pointer.envelope_key);
  if (!envelopeObject) return ineligible("native READY envelope is absent");
  const document = await readBoundedJson(envelopeObject, CREATE_ONLY_COMPARE_MAX_BYTES);
  if (!document) return ineligible("native READY envelope is not JSON");
  const attestation = isRecord(document.attestation) ? document.attestation : null;
  const manifest = isRecord(document.ready_manifest) ? document.ready_manifest : null;
  const physical = isRecord(document.physical) ? document.physical : null;
  const envelopeFields = {
    envelope_digest: await sha256Digest(canonicalJson(document)),
    attestation_id:
      typeof attestation?.attestation_id === "string" ? attestation.attestation_id : null,
    snapshot_id: typeof attestation?.snapshot_id === "string" ? attestation.snapshot_id : null,
    published_at: typeof manifest?.published_at === "string" ? manifest.published_at : null,
    physical_digest: typeof physical?.digest === "string" ? physical.digest : null,
    ready_key_id: typeof attestation?.key_id === "string" ? attestation.key_id : null,
  };
  if (!envelopeFields.snapshot_id) {
    return ineligible("native READY envelope snapshot_id is missing", envelopeFields);
  }
  const verified = await verifyReceiptNativeReadyPublication(
    document,
    envelopeFields.snapshot_id,
    environment,
    clock,
  );
  if (!verified.ok) return ineligible(verified.error, envelopeFields);
  const pub = verified.publication;
  if (
    pointer.envelope_digest !== envelopeFields.envelope_digest ||
    pointer.attestation_id !== pub.attestation_id ||
    pointer.snapshot_id !== pub.snapshot_id ||
    pointer.identity !== pub.identity ||
    pointer.environment !== pub.environment ||
    pointer.envelope_key !== controlledReadyKey(pub.attestation_id) ||
    envelopeFields.published_at === null ||
    parseCanonicalUtc(pointer.published_at) !== parseCanonicalUtc(envelopeFields.published_at)
  ) {
    return ineligible(
      "native READY pointer does not bind the verified envelope",
      envelopeFields,
    );
  }
  const activeReady = (await loadPinnedReadyKeys(environment)).filter(
    (key) => key.status === "active",
  );
  if (activeReady.length !== 1 || activeReady[0]!.key_id !== envelopeFields.ready_key_id) {
    return ineligible("READY issuer is not the currently active key", envelopeFields);
  }
  const physicalHead = await bucket.head(pub.physical.key);
  if (
    !physicalHead ||
    !Number.isSafeInteger(physicalHead.size) ||
    physicalHead.size !== pub.physical.size
  ) {
    return ineligible("physical snapshot metadata is unavailable", envelopeFields);
  }
  const request: ControlledPilotRequest = {
    idempotency_key: pub.job_id,
    ready_attestation_id: pub.attestation_id,
    snapshot_id: pub.snapshot_id,
  };
  const ready: TraderReadyBind = {
    environment: pub.environment,
    ready_manifest_digest: pub.ready_manifest_digest,
    snapshot_id: pub.snapshot_id,
    immutable_db_digest: pub.immutable_db_digest,
    physical: { key: pub.physical.key, size: pub.physical.size },
    profile_digest: EXACT_FOUR_PROFILE_DIGEST,
    dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
    resolved_universe_digest: String(attestation?.resolved_universe_digest || ""),
  };
  const traderObject = await bucket.get(
    controlledTraderAuthorizationKey(request.idempotency_key, request.ready_attestation_id),
  );
  const traderDocument = traderObject
    ? await readBoundedJson(traderObject, CREATE_ONLY_COMPARE_MAX_BYTES)
    : null;
  if (!traderDocument) {
    return ineligible("current trader authorization is absent", envelopeFields);
  }
  const activeTrader = (await loadPinnedTraderKeys(environment)).filter(
    (key) => key.status === "active",
  );
  const authorized = await verifyTraderAuthorizationBatch(
    traderDocument,
    request,
    ready,
    await controlledPilotRequestDigest(request),
    activeTrader,
    clock,
  );
  if (!authorized.ok) return ineligible(authorized.error, envelopeFields);
  return {
    eligibility: "READY",
    reason: "verified receipt-native READY envelope",
    ...envelopeFields,
    trader_authorization_digest: await sha256Digest(canonicalJson(traderDocument)),
    snapshot: {
      snapshot_id: pub.snapshot_id,
      state: "READY",
      committed_at: envelopeFields.published_at,
      source_run_id: null,
      change_seq: null,
      coverage_policy_version: String(attestation?.coverage_policy_version || ""),
      quality_policy_version: "receipt-candidate-snapshot-quality/v1",
      coverage_proof_digest: String(attestation?.coverage_proof_digest || ""),
      manifest_json: canonicalJson(manifest),
    },
  };
}
