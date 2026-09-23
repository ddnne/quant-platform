import { env } from "cloudflare:workers";
import { reset } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";
import { personalResearchR2Outbound } from "../src/personal_research_r2";
import { PERSONAL_SNAPSHOT_FORMAT } from "../src/personal_snapshot_contract";
import {
  RECEIPT_CANDIDATE_FORMAT,
  parseReceiptCandidateRequest,
  personalReceiptCandidatePhysicalKey,
  personalReceiptCandidatePublicationKey,
  personalReceiptCandidateScopeKey,
  receiptCandidateRequestDigest,
} from "../src/personal_receipt_candidate_contract";
import {
  personalReceiptCandidateStatus,
  submitPersonalReceiptCandidate,
} from "../src/personal_receipt_candidate";
import type { ReadyPublicationResult } from "../../ingestion-premium/src/pilot_ready_publication_rpc";
import {
  personalJobStateKey,
  submittedStateDocument,
} from "../src/personal_job_state";
import { PERSONAL_RESEARCH_RUNNER_VERSION } from "../src/personal_research_contract";
import {
  receiptNativeManifestBodyDigest,
  receiptNativeSnapshotId,
} from "../src/ready_manifest_v2";
import { controlledTraderAuthorizationKey } from "../src/controlled_pilot_contract";
import { canonicalJson, sha256Digest } from "../src/controlled_pilot_json";
import exampleNative from "../../../../specs/ready/ready_manifest_v2.example.json";

const runtimeEnv = env as { STRUCTURED_BUCKET: R2Bucket };

const BYTES = new Uint8Array([1, 2, 3]);
const ACTUAL_HEX =
  "039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81";
const CONTENT_DIGEST = `sha256:${ACTUAL_HEX}`;
const REQUEST_DIGEST = `sha256:${"b".repeat(64)}`;
const WRONG_DIGEST = `sha256:${"c".repeat(64)}`;
const OTHER_RAW = `sha256:${"a".repeat(64)}`;
const RAW_HEX = "d".repeat(64);
const RAW_DIGEST = `sha256:${RAW_HEX}`;

type Kind = "result" | "snapshot" | "candidate";
type ProduceMode = "complete" | "short" | "overflow" | "abort";

function hex(data: ArrayBuffer | ArrayBufferView): string {
  const bytes =
    data instanceof ArrayBuffer
      ? new Uint8Array(data)
      : new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  return Array.from(bytes, (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

function objectKey(kind: Kind, jobId: string): string {
  if (kind === "result") {
    return `research/personal/jobs/job=${jobId}/result.tar.gz`;
  }
  if (kind === "candidate") {
    return `research/receipt-candidates/sha256=${RAW_HEX}.sqlite.gz`;
  }
  return `research/personal/snapshots/sha256=${RAW_HEX}.sqlite.gz`;
}

function manifestKey(kind: Kind, jobId: string): string {
  if (kind === "result") {
    return `research/personal/jobs/job=${jobId}/manifest.json`;
  }
  if (kind === "candidate") {
    return `research/receipt-candidates/job=${jobId}/manifest.json`;
  }
  return `research/personal/snapshot-builds/job=${jobId}/manifest.json`;
}

function uploadHeaders(
  kind: Kind,
  jobId: string,
  contentDigest: string,
  rawDigest = RAW_DIGEST,
  byteLength = 3,
  requestDigest = REQUEST_DIGEST,
): Record<string, string> {
  const headers: Record<string, string> = {
    "content-length": String(byteLength),
    "x-personal-job-id": jobId,
    "x-personal-request-digest": requestDigest,
    "x-content-sha256": contentDigest,
  };
  if (kind === "snapshot" || kind === "candidate") {
    headers["x-personal-raw-sha256"] = rawDigest;
  }
  return headers;
}

function completedManifest(
  kind: Kind,
  jobId: string,
  options?: {
    omitFormat?: boolean;
    extra?: Record<string, unknown>;
    requestDigest?: string;
  },
): Record<string, unknown> {
  const requestDigest = options?.requestDigest ?? REQUEST_DIGEST;
  if (kind === "result") {
    return {
      job_id: jobId,
      request_digest: requestDigest,
      status: "COMPLETED",
      result_sha256: CONTENT_DIGEST,
    };
  }
  if (kind === "candidate") {
    return {
      job_id: jobId,
      request_digest: requestDigest,
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      status: "COMPLETED",
      pending_ready: true,
      ready: false,
      go: false,
      completeness_claim: "NONE",
      controlled_live_eligibility: "FORBIDDEN",
      raw_sha256: RAW_DIGEST,
      gzip_sha256: CONTENT_DIGEST,
      snapshot_key: objectKey("candidate", jobId),
      ...(options?.omitFormat ? {} : { format: RECEIPT_CANDIDATE_FORMAT }),
      ...(options?.extra ?? {}),
    };
  }
  return {
    job_id: jobId,
    request_digest: requestDigest,
    status: "COMPLETED",
    research_state: "PERSONAL_DRAFT",
    completeness_claim: "NONE",
    controlled_live_eligibility: "FORBIDDEN",
    raw_sha256: RAW_DIGEST,
    gzip_sha256: CONTENT_DIGEST,
    snapshot_key: objectKey("snapshot", jobId),
    observed_through: "2026-09-01",
    revision_window_calendar_days: 1,
    revision_coverage: "BOUNDED_WINDOW",
  };
}

async function putWithProducer(
  kind: Kind,
  jobId: string,
  mode: ProduceMode,
  contentDigest: string,
  options?: {
    key?: string;
    rawDigest?: string;
    body?: Uint8Array;
    requestDigest?: string;
    env?: typeof runtimeEnv;
  },
): Promise<{
  response: Response;
  producer: PromiseSettledResult<void>;
}> {
  const payload = options?.body ?? BYTES;
  const stream = new FixedLengthStream(payload.byteLength);
  const producer = (async () => {
    const writer = stream.writable.getWriter();
    try {
      if (options?.body) {
        await writer.write(payload);
        await writer.close();
        return;
      }
      if (mode === "abort") {
        await writer.write(BYTES.subarray(0, 1));
        await writer.abort(new Error("test producer abort"));
        return;
      }
      if (mode === "short") {
        await writer.write(BYTES.subarray(0, 2));
        await writer.close();
        return;
      }
      if (mode === "overflow") {
        await writer.write(new Uint8Array([1, 2, 3, 4]));
        await writer.close();
        return;
      }
      await writer.write(BYTES);
      await writer.close();
    } finally {
      try {
        writer.releaseLock();
      } catch {
        /* close/abort already released the lock */
      }
    }
  })();
  const producerSettled: Promise<PromiseSettledResult<void>> = producer.then(
    () => ({ status: "fulfilled", value: undefined }),
    (reason: unknown) => ({ status: "rejected", reason }),
  );
  const response = await personalResearchR2Outbound(
    new Request(`http://research.r2/${options?.key ?? objectKey(kind, jobId)}`, {
      method: "PUT",
      headers: uploadHeaders(
        kind,
        jobId,
        contentDigest,
        options?.rawDigest,
        payload.byteLength,
        options?.requestDigest,
      ),
      body: stream.readable,
    }),
    options?.env ?? runtimeEnv,
  );
  return { response, producer: await producerSettled };
}

async function putCompletedManifest(
  kind: Kind,
  jobId: string,
  options?: {
    omitFormat?: boolean;
    extra?: Record<string, unknown>;
    requestDigest?: string;
    env?: typeof runtimeEnv;
  },
): Promise<Response> {
  const requestDigest = options?.requestDigest ?? REQUEST_DIGEST;
  const bytes = new TextEncoder().encode(
    JSON.stringify(completedManifest(kind, jobId, options)),
  );
  const digest = `sha256:${hex(await crypto.subtle.digest("SHA-256", bytes))}`;
  return personalResearchR2Outbound(
    new Request(`http://research.r2/${manifestKey(kind, jobId)}`, {
      method: "PUT",
      headers: {
        "content-length": String(bytes.byteLength),
        "x-personal-job-id": jobId,
        "x-personal-request-digest": requestDigest,
        "x-content-sha256": digest,
      },
      body: bytes,
    }),
    options?.env ?? runtimeEnv,
  );
}

describe("personalResearchR2Outbound workerd/R2 runtime", () => {
  afterEach(() => reset());

  it.each([
    { suffix: ".sqlite", contentType: "application/vnd.sqlite3" },
    { suffix: ".sqlite.gz", contentType: "application/gzip" },
  ] as const)(
    "GET and HEAD seeded snapshot $suffix",
    async ({ suffix, contentType }) => {
      const key = `research/personal/snapshots/sha256=${ACTUAL_HEX}${suffix}`;
      await runtimeEnv.STRUCTURED_BUCKET.put(key, BYTES, {
        httpMetadata: {
          contentType: "application/octet-stream",
          contentEncoding: "gzip",
        },
      });
      const get = await personalResearchR2Outbound(
        new Request(`http://research.r2/${key}`),
        runtimeEnv,
      );
      const head = await personalResearchR2Outbound(
        new Request(`http://research.r2/${key}`, { method: "HEAD" }),
        runtimeEnv,
      );
      expect(get.status).toBe(200);
      expect(get.headers.get("content-type")).toBe(contentType);
      expect(get.headers.get("content-encoding")).toBeNull();
      expect(get.headers.get("content-length")).toBe("3");
      expect(new Uint8Array(await get.arrayBuffer())).toEqual(BYTES);
      expect(head.status).toBe(200);
      expect(head.headers.get("content-type")).toBe(contentType);
      expect(head.headers.get("content-length")).toBe("3");
      expect(head.body).toBeNull();
    },
  );

  describe.each([{ kind: "result" as const }, { kind: "snapshot" as const }])(
    "$kind writer",
    ({ kind }) => {
      it("valid FixedLengthStream upload then COMPLETED manifest", async () => {
        const jobId = `r05-${kind}-ok`;
        const { response, producer } = await putWithProducer(
          kind,
          jobId,
          "complete",
          CONTENT_DIGEST,
        );
        expect(producer.status).toBe("fulfilled");
        expect(response.status).toBe(201);
        const stored = await runtimeEnv.STRUCTURED_BUCKET.get(
          objectKey(kind, jobId),
        );
        expect(stored).not.toBeNull();
        expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(BYTES);
        expect(hex(stored!.checksums.sha256!)).toBe(ACTUAL_HEX);
        expect(stored!.customMetadata?.sha256).toBe(CONTENT_DIGEST);
        if (kind === "snapshot") {
          expect(stored!.customMetadata?.raw_sha256).toBe(RAW_DIGEST);
          expect(stored!.customMetadata?.format).toBe(PERSONAL_SNAPSHOT_FORMAT);
        }
        const manifest = await putCompletedManifest(kind, jobId);
        expect(manifest.status).toBe(201);
        expect(
          await runtimeEnv.STRUCTURED_BUCKET.head(manifestKey(kind, jobId)),
        ).not.toBeNull();
      });

      it.each([
        { mode: "short" as const, digest: CONTENT_DIGEST, label: "short" },
        { mode: "overflow" as const, digest: CONTENT_DIGEST, label: "overflow" },
        { mode: "abort" as const, digest: CONTENT_DIGEST, label: "abort" },
        {
          mode: "complete" as const,
          digest: WRONG_DIGEST,
          label: "badsha",
        },
      ])(
        "failed stream $label then COMPLETED manifest 409",
        async ({ mode, digest, label }) => {
          const jobId = `r05-${kind}-${label}`;
          const { response } = await putWithProducer(
            kind,
            jobId,
            mode,
            digest,
          );
          expect(response.status).toBe(502);
          expect(await response.json()).toEqual({
            error:
              kind === "result"
                ? "result upload checksum rejected"
                : "snapshot upload checksum rejected",
          });
          expect(
            await runtimeEnv.STRUCTURED_BUCKET.head(objectKey(kind, jobId)),
          ).toBeNull();
          const manifest = await putCompletedManifest(kind, jobId);
          expect(manifest.status).toBe(409);
          expect(await manifest.json()).toEqual({
            error:
              kind === "result"
                ? "completed manifest has no matching result"
                : "completed snapshot manifest has no matching object",
          });
          expect(
            await runtimeEnv.STRUCTURED_BUCKET.head(manifestKey(kind, jobId)),
          ).toBeNull();
        },
      );
    },
  );

  it("candidate gzip then COMPLETED terminal is retrievable", async () => {
    const jobId = "r05-candidate-ok";
    const { response, producer } = await putWithProducer(
      "candidate",
      jobId,
      "complete",
      CONTENT_DIGEST,
    );
    expect(producer.status).toBe("fulfilled");
    expect(response.status).toBe(201);
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(
      objectKey("candidate", jobId),
    );
    expect(stored).not.toBeNull();
    expect(stored!.customMetadata?.format).toBe(RECEIPT_CANDIDATE_FORMAT);
    const manifest = await putCompletedManifest("candidate", jobId);
    expect(manifest.status).toBe(201);
    const get = await personalResearchR2Outbound(
      new Request(`http://research.r2/${manifestKey("candidate", jobId)}`, {
        method: "GET",
        headers: {
          "x-personal-job-id": jobId,
          "x-personal-request-digest": REQUEST_DIGEST,
          "x-personal-runner-version": PERSONAL_RESEARCH_RUNNER_VERSION,
          "x-personal-job-kind": "receipt-candidate",
        },
      }),
      runtimeEnv,
    );
    expect(get.status).toBe(200);
    expect(await get.json()).toMatchObject({
      job_id: jobId,
      status: "COMPLETED",
      format: RECEIPT_CANDIDATE_FORMAT,
      pending_ready: true,
      ready: false,
      go: false,
    });
  });

  it("candidate COMPLETED without format is refused after gzip exists", async () => {
    const jobId = "r05-candidate-noformat";
    const { response } = await putWithProducer(
      "candidate",
      jobId,
      "complete",
      CONTENT_DIGEST,
    );
    expect(response.status).toBe(201);
    const refused = await putCompletedManifest("candidate", jobId, {
      omitFormat: true,
    });
    expect(refused.status).toBe(400);
    expect(await refused.json()).toEqual({
      error: "receipt candidate manifest identity mismatch",
    });
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(manifestKey("candidate", jobId)),
    ).toBeNull();
  });

  it("binds gzip raw_sha256 to receipt-native v2 identity without making READY", async () => {
    const gzip = await putWithProducer(
      "candidate",
      "r05-candidate-native-gz",
      "complete",
      CONTENT_DIGEST,
    );
    expect(gzip.response.status).toBe(201);

    const failScope = await putCompletedManifest(
      "candidate",
      "r05-candidate-scope-fail",
      {
        extra: {
          compiled_scope_status: "FAIL",
          compiled_scope_kind: "receipt-candidate-scope-diagnostic/v1",
          compiled_scope_error: "compiled window is incomplete",
        },
      },
    );
    expect(failScope.status).toBe(201);

    expect(
      await receiptNativeSnapshotId(
        exampleNative.source as Record<string, unknown>,
      ),
    ).toBe(exampleNative.snapshot_id);
    expect(
      await receiptNativeManifestBodyDigest(
        exampleNative as Record<string, unknown>,
      ),
    ).toBe(exampleNative.manifest_digest);

    const native = await sealedNative(RAW_DIGEST);
    const passExtra = {
      compiled_scope_status: "PASS",
      compiled_scope_kind: "receipt-candidate-scope-diagnostic/v1",
      compiled_scope_physical_digest: RAW_DIGEST,
      receipt_native_manifest: native,
      receipt_native_manifest_digest: native.manifest_digest,
    };
    const created = await putCompletedManifest(
      "candidate",
      "r05-candidate-native-ok",
      { extra: passExtra },
    );
    expect(created.status).toBe(201);

    const rejectedPhysical = await putWithProducer(
      "candidate",
      "r05-candidate-phys-bad",
      "complete",
      RAW_DIGEST,
      {
        key: personalReceiptCandidatePhysicalKey(RAW_HEX),
        rawDigest: RAW_DIGEST,
      },
    );
    expect(rejectedPhysical.response.status).toBe(502);
    expect(await rejectedPhysical.response.json()).toEqual({
      error: "receipt candidate upload checksum rejected",
    });

    const physGzip = await putWithProducer(
      "candidate",
      "r05-candidate-phys-ok",
      "complete",
      CONTENT_DIGEST,
      {
        key: `research/receipt-candidates/sha256=${ACTUAL_HEX}.sqlite.gz`,
        rawDigest: CONTENT_DIGEST,
      },
    );
    expect(physGzip.response.status).toBe(201);
    const physNative = await sealedNative(CONTENT_DIGEST);
    const physicalExtra = {
      ...passExtra,
      compiled_scope_physical_digest: CONTENT_DIGEST,
      raw_sha256: CONTENT_DIGEST,
      gzip_sha256: CONTENT_DIGEST,
      snapshot_key: `research/receipt-candidates/sha256=${ACTUAL_HEX}.sqlite.gz`,
      physical_key: personalReceiptCandidatePhysicalKey(ACTUAL_HEX),
      receipt_native_manifest: physNative,
      receipt_native_manifest_digest: physNative.manifest_digest,
    };
    const missingPhysical = await putCompletedManifest(
      "candidate",
      "r05-candidate-phys-ok",
      { extra: physicalExtra },
    );
    expect(missingPhysical.status).toBe(409);
    expect(await missingPhysical.json()).toEqual({
      error:
        "completed receipt candidate manifest has no matching physical object",
    });
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        manifestKey("candidate", "r05-candidate-phys-ok"),
      ),
    ).toBeNull();
    const physSqlite = await putWithProducer(
      "candidate",
      "r05-candidate-phys-ok",
      "complete",
      CONTENT_DIGEST,
      {
        key: personalReceiptCandidatePhysicalKey(ACTUAL_HEX),
        rawDigest: CONTENT_DIGEST,
      },
    );
    expect(physSqlite.response.status).toBe(201);
    const withPhysical = await putCompletedManifest(
      "candidate",
      "r05-candidate-phys-ok",
      { extra: physicalExtra },
    );
    expect(withPhysical.status).toBe(201);

    const scopeBody = {
      format: "pit-dependency-scope-proof/v1",
      status: "PASS",
      physical_db_digest: CONTENT_DIGEST,
    };
    const scopeJson = canonicalJson(scopeBody);
    const scopeDigest = await sha256Digest(scopeJson);
    const scopeBytes = new TextEncoder().encode(scopeJson);
    const scopeNative = await sealedNative(CONTENT_DIGEST, undefined, scopeDigest);
    const scopeExtra = {
      ...physicalExtra,
      compiled_scope_proof_digest: scopeDigest,
      dependency_scope_key: personalReceiptCandidateScopeKey(
        scopeDigest.slice("sha256:".length),
      ),
      receipt_native_manifest: scopeNative,
      receipt_native_manifest_digest: scopeNative.manifest_digest,
    };
    const missingScope = await putCompletedManifest(
      "candidate",
      "r05-candidate-scope-ok",
      { extra: scopeExtra },
    );
    expect(missingScope.status).toBe(409);
    expect(await missingScope.json()).toEqual({
      error: "completed receipt candidate manifest has no matching scope object",
    });
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        manifestKey("candidate", "r05-candidate-scope-ok"),
      ),
    ).toBeNull();
    const scopePut = await putWithProducer(
      "candidate",
      "r05-candidate-scope-ok",
      "complete",
      scopeDigest,
      {
        key: personalReceiptCandidateScopeKey(scopeDigest.slice("sha256:".length)),
        rawDigest: CONTENT_DIGEST,
        body: scopeBytes,
      },
    );
    expect(scopePut.response.status).toBe(201);
    const omittedStatus = await putCompletedManifest(
      "candidate",
      "r05-candidate-scope-anon",
      {
        extra: {
          raw_sha256: CONTENT_DIGEST,
          gzip_sha256: CONTENT_DIGEST,
          snapshot_key: `research/receipt-candidates/sha256=${ACTUAL_HEX}.sqlite.gz`,
          compiled_scope_proof_digest: scopeDigest,
          dependency_scope_key: personalReceiptCandidateScopeKey(
            scopeDigest.slice("sha256:".length),
          ),
        },
      },
    );
    expect(omittedStatus.status).toBe(400);
    expect(await omittedStatus.json()).toEqual({
      error:
        "completed receipt candidate scope pointer requires compiled-scope PASS",
    });
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        manifestKey("candidate", "r05-candidate-scope-anon"),
      ),
    ).toBeNull();
    const withScope = await putCompletedManifest(
      "candidate",
      "r05-candidate-scope-ok",
      { extra: scopeExtra },
    );
    expect(withScope.status).toBe(201);

    const other = await sealedNative(OTHER_RAW);
    const swappedSnapshot = await sealedNative(RAW_DIGEST, (body) => {
      body.snapshot_id = other.snapshot_id;
    });
    const snapshotSwap = await putCompletedManifest(
      "candidate",
      "r05-candidate-native-snap",
      {
        extra: {
          ...passExtra,
          receipt_native_manifest: swappedSnapshot,
          receipt_native_manifest_digest: swappedSnapshot.manifest_digest,
        },
      },
    );
    expect(snapshotSwap.status).toBe(400);
    expect(await snapshotSwap.json()).toEqual({
      error: "receipt-native snapshot_id does not match source",
    });

    const innerMismatch = await sealedNative(RAW_DIGEST);
    innerMismatch.manifest_digest = WRONG_DIGEST;
    const inner = await putCompletedManifest(
      "candidate",
      "r05-candidate-native-inner",
      {
        extra: {
          ...passExtra,
          receipt_native_manifest: innerMismatch,
          receipt_native_manifest_digest:
            await receiptNativeManifestBodyDigest(innerMismatch),
        },
      },
    );
    expect(inner.status).toBe(400);
    expect(await inner.json()).toEqual({
      error: "receipt-native manifest_digest mismatch",
    });

    const foreign = await sealedNative(OTHER_RAW);
    const physicalSwap = await putCompletedManifest(
      "candidate",
      "r05-candidate-native-phys",
      {
        extra: {
          ...passExtra,
          receipt_native_manifest: foreign,
          receipt_native_manifest_digest: foreign.manifest_digest,
        },
      },
    );
    expect(physicalSwap.status).toBe(400);
    expect(await physicalSwap.json()).toEqual({
      error: "receipt-native physical_digest does not match gzip raw_sha256",
    });

    const withCursor = await sealedNative(RAW_DIGEST, (body) => {
      body.source_generation = "1";
    });
    const cursors = await putCompletedManifest(
      "candidate",
      "r05-candidate-native-d1",
      {
        extra: {
          ...passExtra,
          receipt_native_manifest: withCursor,
          receipt_native_manifest_digest: withCursor.manifest_digest,
        },
      },
    );
    expect(cursors.status).toBe(400);
    expect(await cursors.json()).toEqual({
      error: "receipt-native ReadyManifest forbids D1 cursor fields",
    });

    const badPlans = await sealedNative(RAW_DIGEST, (body) => {
      body.plan_ids = "exp-mdh-hold10-momentum";
    });
    const planShape = await putCompletedManifest(
      "candidate",
      "r05-candidate-native-plans",
      {
        extra: {
          ...passExtra,
          receipt_native_manifest: badPlans,
          receipt_native_manifest_digest: badPlans.manifest_digest,
        },
      },
    );
    expect(planShape.status).toBe(400);
    expect(await planShape.json()).toEqual({
      error: "ReadyManifest plan_ids is invalid",
    });
  });

  it("publishes after admitted PASS without rematerializing on retry", async () => {
    const parsed = parseReceiptCandidateRequest({
      job_id: "r05-candidate-pub",
    });
    if (!parsed.ok) throw new Error(parsed.error);
    const pubDigest = await receiptCandidateRequestDigest(parsed.value);
    let publishMode: "stall" | "reject" | "verify" = "stall";
    let publishedAt = "2026-09-02T12:00:00Z";
    let attestationId = "ready-runtime";
    const terminalPresent: boolean[] = [];
    const publishAdmittedReceiptCandidate = vi.fn(async (): Promise<ReadyPublicationResult> => {
      terminalPresent.push(
        (await runtimeEnv.STRUCTURED_BUCKET.head(
          manifestKey("candidate", "r05-candidate-pub"),
        )) !== null,
      );
      if (publishMode === "stall") {
        return await new Promise<ReadyPublicationResult>(() => {});
      }
      if (publishMode === "reject") {
        return {
          ok: false,
          status: "REJECTED",
          error: "issuer is not trusted",
          ready_declared: false,
          operational_go: false,
        };
      }
      return {
        ok: true,
        status: "VERIFIED_PILOT_READINESS",
        ready_declared: false,
        operational_go: false,
        mass_research: "NO-GO",
        automatic_promotion: false,
        live_orders_enabled: false,
        attestation_id: attestationId,
        snapshot_id: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        immutable_db_digest: CONTENT_DIGEST,
        envelope_key: `research/controlled-pilot/ready/${attestationId}.json`,
        attestation_key:
          `research/controlled-pilot/ready/${attestationId}.json.attestation.json`,
        published_at: publishedAt,
      };
    });
    const publishEnv = {
      ...runtimeEnv,
      ENVIRONMENT: "staging",
      CF_VERSION_METADATA: { id: "runtime-test" },
      PILOT_READY_PUBLICATION: { publishAdmittedReceiptCandidate },
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn() },
    };
    const gzip = await putWithProducer(
      "candidate",
      "r05-candidate-pub",
      "complete",
      CONTENT_DIGEST,
      {
        key: `research/receipt-candidates/sha256=${ACTUAL_HEX}.sqlite.gz`,
        rawDigest: CONTENT_DIGEST,
        requestDigest: pubDigest,
        env: publishEnv,
      },
    );
    expect(gzip.response.status).toBe(201);
    const sqlite = await putWithProducer(
      "candidate",
      "r05-candidate-pub",
      "complete",
      CONTENT_DIGEST,
      {
        key: personalReceiptCandidatePhysicalKey(ACTUAL_HEX),
        rawDigest: CONTENT_DIGEST,
        requestDigest: pubDigest,
        env: publishEnv,
      },
    );
    expect(sqlite.response.status).toBe(201);
    const scopeBody = {
      format: "pit-dependency-scope-proof/v1",
      status: "PASS",
      physical_db_digest: CONTENT_DIGEST,
    };
    const scopeJson = canonicalJson(scopeBody);
    const scopeDigest = await sha256Digest(scopeJson);
    const scopeBytes = new TextEncoder().encode(scopeJson);
    const scopePut = await putWithProducer(
      "candidate",
      "r05-candidate-pub",
      "complete",
      scopeDigest,
      {
        key: personalReceiptCandidateScopeKey(scopeDigest.slice("sha256:".length)),
        rawDigest: CONTENT_DIGEST,
        body: scopeBytes,
        requestDigest: pubDigest,
        env: publishEnv,
      },
    );
    expect(scopePut.response.status).toBe(201);
    expect(publishAdmittedReceiptCandidate).not.toHaveBeenCalled();
    const native = await sealedNative(CONTENT_DIGEST, undefined, scopeDigest);
    const extra = {
      compiled_scope_status: "PASS",
      compiled_scope_kind: "receipt-candidate-scope-diagnostic/v1",
      compiled_scope_physical_digest: CONTENT_DIGEST,
      raw_sha256: CONTENT_DIGEST,
      gzip_sha256: CONTENT_DIGEST,
      snapshot_key: `research/receipt-candidates/sha256=${ACTUAL_HEX}.sqlite.gz`,
      physical_key: personalReceiptCandidatePhysicalKey(ACTUAL_HEX),
      compiled_scope_proof_digest: scopeDigest,
      dependency_scope_key: personalReceiptCandidateScopeKey(
        scopeDigest.slice("sha256:".length),
      ),
      receipt_native_manifest: native,
      receipt_native_manifest_digest: native.manifest_digest,
    };
    const admitted = await putCompletedManifest("candidate", "r05-candidate-pub", {
      requestDigest: pubDigest,
      env: publishEnv,
      extra,
    });
    expect(admitted.status).toBe(201);
    expect(publishAdmittedReceiptCandidate).toHaveBeenCalledTimes(1);
    expect(publishAdmittedReceiptCandidate).toHaveBeenCalledWith({
      job_id: "r05-candidate-pub",
      environment: "staging",
    });
    expect(terminalPresent).toEqual([true]);
    const admittedTerminal = await runtimeEnv.STRUCTURED_BUCKET.get(
      manifestKey("candidate", "r05-candidate-pub"),
    );
    const admittedBytes = new Uint8Array(await admittedTerminal!.arrayBuffer());
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalReceiptCandidatePublicationKey("r05-candidate-pub"),
      ),
    ).toBeNull();
    publishMode = "reject";
    const retry = await putCompletedManifest("candidate", "r05-candidate-pub", {
      requestDigest: pubDigest,
      env: publishEnv,
      extra,
    });
    expect(retry.status).toBe(200);
    expect(publishAdmittedReceiptCandidate).toHaveBeenCalledTimes(2);
    expect(publishAdmittedReceiptCandidate).toHaveBeenNthCalledWith(2, {
      job_id: "r05-candidate-pub",
      environment: "staging",
    });
    expect(terminalPresent).toEqual([true, true]);
    expect(
      new Uint8Array(
        await (
          await runtimeEnv.STRUCTURED_BUCKET.get(
            manifestKey("candidate", "r05-candidate-pub"),
          )
        )!.arrayBuffer(),
      ),
    ).toEqual(admittedBytes);
    const beforeGet = publishAdmittedReceiptCandidate.mock.calls.length;
    const getBody = (await (
      await personalReceiptCandidateStatus(publishEnv as never, "r05-candidate-pub")
    ).json()) as Record<string, unknown>;
    expect(publishAdmittedReceiptCandidate.mock.calls.length).toBe(beforeGet);
    expect(getBody.publication).toBeUndefined();
    expect(getBody).toMatchObject({
      pending_ready: true,
      ready: false,
      job: { status: "COMPLETED" },
    });
    publishMode = "verify";
    const repaired = await submitPersonalReceiptCandidate(
      publishEnv as never,
      parsed.value,
    );
    expect(publishEnv.PERSONAL_RESEARCH_CONTAINER.getByName).not.toHaveBeenCalled();
    expect(await repaired.json()).toMatchObject({
      ok: true,
      idempotent: true,
      ready: false,
      publication: {
        historical: false,
        persisted: true,
        attempt_status: "VERIFIED_PILOT_READINESS",
      },
    });
    const observed = (await (
      await personalReceiptCandidateStatus(publishEnv as never, "r05-candidate-pub")
    ).json()) as Record<string, unknown>;
    expect(observed.publication).toMatchObject({
      historical: true,
      persisted: true,
    });
    expect(
      (observed.publication as Record<string, unknown>).attempt_status,
    ).toBeUndefined();
    const pointerObject = await runtimeEnv.STRUCTURED_BUCKET.get(
      personalReceiptCandidatePublicationKey("r05-candidate-pub"),
    );
    const pointerBytes = new Uint8Array(await pointerObject!.arrayBuffer());
    const pointer = JSON.parse(new TextDecoder().decode(pointerBytes)) as {
      attestation_id: string;
    };
    const afterPointer = publishAdmittedReceiptCandidate.mock.calls.length;
    const reconnect = await submitPersonalReceiptCandidate(
      publishEnv as never,
      parsed.value,
    );
    expect(publishAdmittedReceiptCandidate.mock.calls.length).toBe(afterPointer + 1);
    expect(await reconnect.json()).toMatchObject({
      publication: {
        historical: true,
        persisted: true,
        attempt_status: "VERIFIED_PILOT_READINESS",
      },
    });
    expect(
      new Uint8Array(
        await (
          await runtimeEnv.STRUCTURED_BUCKET.get(
            personalReceiptCandidatePublicationKey("r05-candidate-pub"),
          )
        )!.arrayBuffer(),
      ),
    ).toEqual(pointerBytes);
    await runtimeEnv.STRUCTURED_BUCKET.put(
      controlledTraderAuthorizationKey("r05-candidate-pub", pointer.attestation_id),
      new TextEncoder().encode("{}"),
    );
    const afterAuth = publishAdmittedReceiptCandidate.mock.calls.length;
    await submitPersonalReceiptCandidate(publishEnv as never, parsed.value);
    expect(publishAdmittedReceiptCandidate.mock.calls.length).toBe(afterAuth + 1);
    const afterPairedGet = publishAdmittedReceiptCandidate.mock.calls.length;
    const pairedStatus = (await (
      await personalReceiptCandidateStatus(publishEnv as never, "r05-candidate-pub")
    ).json()) as Record<string, unknown>;
    expect(publishAdmittedReceiptCandidate.mock.calls.length).toBe(afterPairedGet);
    expect(pairedStatus.publication).toMatchObject({
      historical: true,
      persisted: true,
    });
    expect(
      (pairedStatus.publication as Record<string, unknown>).attempt_status,
    ).toBeUndefined();
    // Existing Trader bytes must not suppress renewal. The pointer advances
    // through real R2 CAS, while GET stays observation-only and no build starts.
    publishedAt = "2026-09-02T14:00:00Z";
    attestationId = "ready-runtime-renewed";
    expect(await (await submitPersonalReceiptCandidate(publishEnv as never, parsed.value)).json())
      .toMatchObject({ publication: { persisted: true, pointer: { attestation_id: attestationId } } });
    publishedAt = "2026-09-02T12:00:00Z";
    attestationId = "ready-runtime";
    expect(await (await submitPersonalReceiptCandidate(publishEnv as never, parsed.value)).json())
      .toMatchObject({ publication: { persisted: false } });
    expect(await (await personalReceiptCandidateStatus(publishEnv as never, parsed.value.job_id)).json())
      .toMatchObject({ publication: { pointer: { attestation_id: "ready-runtime-renewed" } } });
    expect(publishEnv.PERSONAL_RESEARCH_CONTAINER.getByName).not.toHaveBeenCalled();
    const expiredId = "r05-candidate-expired";
    const expiredCalls = publishAdmittedReceiptCandidate.mock.calls.length;
    await runtimeEnv.STRUCTURED_BUCKET.put(
      personalJobStateKey("receipt-candidate", expiredId),
      JSON.stringify(
        submittedStateDocument({
          jobId: expiredId,
          requestDigest: pubDigest,
          kind: "receipt-candidate",
          deploymentId: "runtime-test",
          now: new Date(0),
        }),
      ),
    );
    const expired = (await (
      await personalReceiptCandidateStatus(
        publishEnv as never,
        expiredId,
        new Date("2026-09-13T00:00:00Z"),
      )
    ).json()) as Record<string, unknown>;
    expect(publishAdmittedReceiptCandidate.mock.calls.length).toBe(expiredCalls);
    expect(expired).toMatchObject({
      ok: false,
      durable: false,
      observation_only: true,
      expired: true,
      job: { status: "SUBMITTED" },
    });
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(manifestKey("candidate", expiredId)),
    ).toBeNull();
  });
});

async function sealedNative(
  physicalDigest: string,
  mutate?: (native: Record<string, unknown>) => void,
  compiledScopeProofDigest?: string,
): Promise<Record<string, unknown>> {
  const native = structuredClone(exampleNative) as Record<string, unknown>;
  const source = {
    ...(exampleNative.source as Record<string, unknown>),
    physical_digest: physicalDigest,
    ...(compiledScopeProofDigest
      ? { compiled_scope_proof_digest: compiledScopeProofDigest }
      : {}),
  };
  native.source = source;
  native.snapshot_id = await receiptNativeSnapshotId(source);
  mutate?.(native);
  native.manifest_digest = await receiptNativeManifestBodyDigest(native);
  return native;
}
