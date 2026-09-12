import {
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  isPersonalResearchJobId,
  isPersonalResearchSnapshotKey,
  personalResearchManifestKey,
  personalResearchResultKey,
  type PersonalContainerKind,
} from "./personal_research_contract";
import {
  PERSONAL_SNAPSHOT_FORMAT,
  isPersonalSnapshotManifestKey,
  personalSnapshotManifestKey,
  personalSnapshotObjectKey,
} from "./personal_snapshot_contract";
import {
  RECEIPT_CANDIDATE_FORMAT,
  isReceiptCandidateManifestKey,
  isReceiptCandidateObjectKey,
  personalReceiptCandidateManifestKey,
  personalReceiptCandidateObjectKey,
} from "./personal_receipt_candidate_contract";
import {
  isPersonalIndexOverlayFamilyCohort,
  personalIndexOverlayFamilyRunnerVersion,
  personalIndexOverlayFamilyTerminalManifestKey,
  personalIndexOverlayFamilyTerminalSchema,
  type PersonalIndexVolOverlay2023CohortId,
} from "./personal_index_vol_overlay_2023_contract";
import {
  PERSONAL_SVI_2023_COHORT_ID,
  PERSONAL_SVI_2023_RUNNER_VERSION,
  personalSviTerminalManifestKey,
} from "./personal_svi_2023_contract";
import {
  isPersonalSviOutboundRequest,
  personalSviR2Outbound,
} from "./personal_svi_r2";
import {
  isPersonalIndexVolOverlayOutboundRequest,
  personalIndexVolOverlayR2Outbound,
} from "./personal_index_vol_overlay_r2";
import {
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
  personalVolAmPmPanelBuildTerminalKey,
} from "./personal_vol_am_pm_panel_writer_contract";
import {
  isPersonalVolAmPmPanelOutboundRequest,
  personalVolAmPmPanelR2Outbound,
} from "./personal_vol_am_pm_panel_r2";
import {
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  personalOptionSidecarTerminalKey,
} from "./personal_option_sidecar_producer_contract";
import {
  isPersonalOptionSidecarOutboundRequest,
  personalOptionSidecarR2Outbound,
} from "./personal_option_sidecar_r2";
import {
  isPersonalAcquisitionCacheOutboundRequest,
  personalAcquisitionCacheR2Outbound,
} from "./personal_acquisition_cache_r2";
import { sha256Hex } from "./sha256";
import { CONTROLLED_PILOT_KEY_PREFIX } from "./controlled_pilot_contract";

const RESULT_MAX_BYTES = 512 * 1024 * 1024;
const MANIFEST_MAX_BYTES = 64 * 1024;
// Gzip PUT is compressed transport, not expanded sqlite.
const SNAPSHOT_GZIP_MAX_BYTES = PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES;
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const SHA_HEX_RE = /^[0-9a-f]{64}$/;

type R2Env = { STRUCTURED_BUCKET: R2Bucket };

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function contentLength(request: Request, maximum: number): number | null {
  const raw = request.headers.get("content-length");
  if (!raw || !/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) return null;
  return value;
}

function outputIdentity(
  request: Request,
): { jobId: string; requestDigest: string; contentDigest: string } | null {
  const jobId = request.headers.get("x-personal-job-id") ?? "";
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  const contentDigest = request.headers.get("x-content-sha256") ?? "";
  if (
    !isPersonalResearchJobId(jobId) ||
    !DIGEST_RE.test(requestDigest) ||
    !DIGEST_RE.test(contentDigest)
  ) {
    return null;
  }
  return { jobId, requestDigest, contentDigest };
}

function snapshotGzipIdentity(
  request: Request,
): {
  jobId: string;
  requestDigest: string;
  contentDigest: string;
  rawDigest: string;
} | null {
  const identity = outputIdentity(request);
  const rawDigest = request.headers.get("x-personal-raw-sha256") ?? "";
  if (!identity || !DIGEST_RE.test(rawDigest)) return null;
  return { ...identity, rawDigest };
}

function digestBytes(digest: string): Uint8Array {
  if (!DIGEST_RE.test(digest)) throw new Error("invalid sha256 digest");
  const hex = digest.slice("sha256:".length);
  const bytes = new Uint8Array(32);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return bytes;
}

function checksumMatches(object: R2Object, digest: string): boolean {
  const actual = object.checksums.sha256;
  if (!actual) return false;
  const expected = digestBytes(digest);
  const actualBytes = new Uint8Array(actual);
  return (
    actualBytes.byteLength === expected.byteLength &&
    actualBytes.every((value, index) => value === expected[index])
  );
}

function existingMatches(
  object: R2Object,
  identity: { requestDigest: string; contentDigest: string },
): boolean {
  return (
    object.customMetadata?.request_digest === identity.requestDigest &&
    object.customMetadata?.sha256 === identity.contentDigest &&
    checksumMatches(object, identity.contentDigest)
  );
}

function gzipObjectMatches(
  object: R2Object,
  identity: { contentDigest: string; rawDigest: string },
  format: string,
): boolean {
  return (
    object.customMetadata?.sha256 === identity.contentDigest &&
    object.customMetadata?.raw_sha256 === identity.rawDigest &&
    object.customMetadata?.format === format &&
    checksumMatches(object, identity.contentDigest)
  );
}

type SqliteGzipKind = {
  format: string;
  plane: "personal_snapshot" | "receipt_candidate";
  label: "snapshot" | "receipt candidate";
  objectKey: (rawHex: string) => string;
  manifestKey: (jobId: string) => string;
  closedManifest: (
    manifest: Record<string, unknown>,
    status: string,
  ) => string | null;
};

async function exactTerminalExists(
  env: R2Env,
  key: string,
  identity: { jobId: string; requestDigest: string },
): Promise<boolean> {
  const terminal = await env.STRUCTURED_BUCKET.head(key);
  return (
    terminal?.customMetadata?.job_id === identity.jobId &&
    terminal.customMetadata.request_digest === identity.requestDigest &&
    (terminal.customMetadata.status === "COMPLETED" ||
      terminal.customMetadata.status === "FAILED")
  );
}

async function putResult(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const identity = outputIdentity(request);
  if (!identity || key !== personalResearchResultKey(identity.jobId)) {
    return responseJson({ error: "invalid result identity" }, 400);
  }
  const length = contentLength(request, RESULT_MAX_BYTES);
  if (length === null || request.body === null) {
    return responseJson({ error: "invalid result length" }, 400);
  }
  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return existingMatches(existing, identity)
      ? responseJson({ ok: true, created: false, key })
      : responseJson({ error: "immutable result conflict" }, 409);
  }
  if (
    await exactTerminalExists(
      env,
      personalResearchManifestKey(identity.jobId),
      identity,
    )
  ) {
    return responseJson({ error: "terminal already exists" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, request.body, {
      httpMetadata: {
        contentType: "application/gzip",
        contentDisposition: `attachment; filename="${identity.jobId}.tar.gz"`,
      },
      customMetadata: {
        plane: "personal_research",
        job_id: identity.jobId,
        request_digest: identity.requestDigest,
        sha256: identity.contentDigest,
        immutable: "true",
      },
      sha256: digestBytes(identity.contentDigest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return responseJson({ error: "result upload checksum rejected" }, 502);
  }
  if (put !== null) return responseJson({ ok: true, created: true, key }, 201);
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && existingMatches(raced, identity)
    ? responseJson({ ok: true, created: false, key })
    : responseJson({ error: "immutable result conflict" }, 409);
}

async function putManifest(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const identity = outputIdentity(request);
  if (!identity || key !== personalResearchManifestKey(identity.jobId)) {
    return responseJson({ error: "invalid manifest identity" }, 400);
  }
  const length = contentLength(request, MANIFEST_MAX_BYTES);
  if (length === null) return responseJson({ error: "invalid manifest length" }, 400);
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength !== length) {
    return responseJson({ error: "manifest length mismatch" }, 400);
  }
  const actualDigest = `sha256:${await sha256Hex(bytes)}`;
  if (actualDigest !== identity.contentDigest) {
    return responseJson({ error: "manifest digest mismatch" }, 400);
  }
  let manifest: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("not object");
    }
    manifest = parsed as Record<string, unknown>;
  } catch {
    return responseJson({ error: "manifest must be JSON object" }, 400);
  }
  const status = manifest.status;
  if (
    manifest.job_id !== identity.jobId ||
    manifest.request_digest !== identity.requestDigest ||
    (status !== "COMPLETED" && status !== "FAILED")
  ) {
    return responseJson({ error: "manifest identity mismatch" }, 400);
  }
  if (status === "COMPLETED") {
    const resultDigest =
      typeof manifest.result_sha256 === "string" ? manifest.result_sha256 : "";
    const result = await env.STRUCTURED_BUCKET.head(
      personalResearchResultKey(identity.jobId),
    );
    if (
      !result ||
      !DIGEST_RE.test(resultDigest) ||
      result.customMetadata?.request_digest !== identity.requestDigest ||
      resultDigest !== result.customMetadata?.sha256 ||
      !checksumMatches(result, resultDigest)
    ) {
      return responseJson({ error: "completed manifest has no matching result" }, 409);
    }
  }

  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return existingMatches(existing, identity)
      ? responseJson({ ok: true, created: false, key })
      : responseJson({ error: "immutable manifest conflict" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, bytes, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
      customMetadata: {
        plane: "personal_research",
        job_id: identity.jobId,
        request_digest: identity.requestDigest,
        sha256: identity.contentDigest,
        status,
        immutable: "true",
      },
      sha256: digestBytes(identity.contentDigest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return responseJson({ error: "manifest upload checksum rejected" }, 502);
  }
  if (put !== null) return responseJson({ ok: true, created: true, key }, 201);
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && existingMatches(raced, identity)
    ? responseJson({ ok: true, created: false, key })
    : responseJson({ error: "immutable manifest conflict" }, 409);
}

async function getSnapshot(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  if (!isPersonalResearchSnapshotKey(key)) {
    return responseJson({ error: "snapshot key denied" }, 403);
  }
  if (request.method === "HEAD") {
    const object = await env.STRUCTURED_BUCKET.head(key);
    if (!object) return responseJson({ error: "snapshot not found" }, 404);
    if (object.size < 1 || object.size > PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES) {
      return responseJson({ error: "invalid snapshot length" }, 400);
    }
    return new Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        "content-type": key.endsWith(".sqlite.gz")
          ? "application/gzip"
          : "application/vnd.sqlite3",
        etag: object.httpEtag,
      },
    });
  }
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object) return responseJson({ error: "snapshot not found" }, 404);
  if (object.size < 1 || object.size > PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES) {
    return responseJson({ error: "invalid snapshot length" }, 400);
  }
  const headers = new Headers({
    "content-length": String(object.size),
    etag: object.httpEtag,
  });
  object.writeHttpMetadata(headers);
  headers.delete("content-encoding");
  headers.set("content-length", String(object.size));
  headers.set(
    "content-type",
    key.endsWith(".sqlite.gz") ? "application/gzip" : "application/vnd.sqlite3",
  );
  const body = object.body.pipeThrough(new FixedLengthStream(object.size));
  return new Response(body, { status: 200, headers });
}

function snapshotManifestForbidsSecrets(manifest: Record<string, unknown>): boolean {
  const serialized = JSON.stringify(manifest).toLowerCase();
  return !["api_key", "jquants_api_key", "authorization", "secret", "password"].some(
    (token) => serialized.includes(token),
  );
}

function snapshotManifestClosed(
  manifest: Record<string, unknown>,
  status: string,
): string | null {
  if (
    manifest.research_state !== "PERSONAL_DRAFT" ||
    manifest.completeness_claim !== "NONE" ||
    manifest.controlled_live_eligibility !== "FORBIDDEN"
  ) {
    return "snapshot manifest identity mismatch";
  }
  if (status !== "COMPLETED") return null;
  const observedThrough =
    typeof manifest.observed_through === "string" ? manifest.observed_through : "";
  const revisionDays = manifest.revision_window_calendar_days;
  const revisionCoverage =
    typeof manifest.revision_coverage === "string" ? manifest.revision_coverage : "";
  if (
    !observedThrough ||
    typeof revisionDays !== "number" ||
    !Number.isInteger(revisionDays) ||
    revisionDays < 1 ||
    (revisionCoverage !== "WINDOW_COMPLETE" &&
      revisionCoverage !== "BOUNDED_WINDOW")
  ) {
    return "completed snapshot identity is invalid";
  }
  return null;
}

function receiptCandidateManifestClosed(
  manifest: Record<string, unknown>,
  _status: string,
): string | null {
  if (
    manifest.format !== RECEIPT_CANDIDATE_FORMAT ||
    manifest.pending_ready !== true ||
    manifest.ready !== false ||
    manifest.go !== false ||
    manifest.completeness_claim !== "NONE" ||
    manifest.controlled_live_eligibility !== "FORBIDDEN"
  ) {
    return "receipt candidate manifest identity mismatch";
  }
  return null;
}

const SNAPSHOT_GZIP_KIND: SqliteGzipKind = {
  format: PERSONAL_SNAPSHOT_FORMAT,
  plane: "personal_snapshot",
  label: "snapshot",
  objectKey: personalSnapshotObjectKey,
  manifestKey: personalSnapshotManifestKey,
  closedManifest: snapshotManifestClosed,
};

const RECEIPT_CANDIDATE_GZIP_KIND: SqliteGzipKind = {
  format: RECEIPT_CANDIDATE_FORMAT,
  plane: "receipt_candidate",
  label: "receipt candidate",
  objectKey: personalReceiptCandidateObjectKey,
  manifestKey: personalReceiptCandidateManifestKey,
  closedManifest: receiptCandidateManifestClosed,
};

async function putSqliteGzip(
  request: Request,
  env: R2Env,
  key: string,
  kind: SqliteGzipKind,
): Promise<Response> {
  const identity = snapshotGzipIdentity(request);
  const rawHex = identity?.rawDigest.slice("sha256:".length) ?? "";
  if (
    !identity ||
    !SHA_HEX_RE.test(rawHex) ||
    key !== kind.objectKey(rawHex)
  ) {
    return responseJson({ error: `invalid ${kind.label} identity` }, 400);
  }
  const length = contentLength(request, SNAPSHOT_GZIP_MAX_BYTES);
  if (length === null || request.body === null) {
    return responseJson({ error: `invalid ${kind.label} length` }, 400);
  }
  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return gzipObjectMatches(existing, identity, kind.format)
      ? responseJson({ ok: true, created: false, key })
      : responseJson({ error: `immutable ${kind.label} conflict` }, 409);
  }
  if (await exactTerminalExists(env, kind.manifestKey(identity.jobId), identity)) {
    return responseJson({ error: "terminal already exists" }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, request.body, {
      httpMetadata: { contentType: "application/gzip" },
      customMetadata: {
        plane: kind.plane,
        format: kind.format,
        sha256: identity.contentDigest,
        raw_sha256: identity.rawDigest,
        immutable: "true",
      },
      sha256: digestBytes(identity.contentDigest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return responseJson({ error: `${kind.label} upload checksum rejected` }, 502);
  }
  if (put !== null) return responseJson({ ok: true, created: true, key }, 201);
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && gzipObjectMatches(raced, identity, kind.format)
    ? responseJson({ ok: true, created: false, key })
    : responseJson({ error: `immutable ${kind.label} conflict` }, 409);
}

async function putSqliteManifest(
  request: Request,
  env: R2Env,
  key: string,
  kind: SqliteGzipKind,
): Promise<Response> {
  const identity = outputIdentity(request);
  if (!identity || key !== kind.manifestKey(identity.jobId)) {
    return responseJson({ error: `invalid ${kind.label} manifest identity` }, 400);
  }
  const length = contentLength(request, MANIFEST_MAX_BYTES);
  if (length === null) {
    return responseJson({ error: `invalid ${kind.label} manifest length` }, 400);
  }
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength !== length) {
    return responseJson({ error: `${kind.label} manifest length mismatch` }, 400);
  }
  const actualDigest = `sha256:${await sha256Hex(bytes)}`;
  if (actualDigest !== identity.contentDigest) {
    return responseJson({ error: `${kind.label} manifest digest mismatch` }, 400);
  }
  let manifest: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("not object");
    }
    manifest = parsed as Record<string, unknown>;
  } catch {
    return responseJson({ error: `${kind.label} manifest must be JSON object` }, 400);
  }
  const status = manifest.status;
  if (
    manifest.job_id !== identity.jobId ||
    manifest.request_digest !== identity.requestDigest ||
    (status !== "COMPLETED" && status !== "FAILED") ||
    !snapshotManifestForbidsSecrets(manifest)
  ) {
    return responseJson({ error: `${kind.label} manifest identity mismatch` }, 400);
  }
  const closed = kind.closedManifest(manifest, status);
  if (closed) return responseJson({ error: closed }, 400);
  if (status === "COMPLETED") {
    const rawDigest =
      typeof manifest.raw_sha256 === "string" ? manifest.raw_sha256 : "";
    const gzipDigest =
      typeof manifest.gzip_sha256 === "string" ? manifest.gzip_sha256 : "";
    const snapshotKey =
      typeof manifest.snapshot_key === "string" ? manifest.snapshot_key : "";
    const rawHex = rawDigest.startsWith("sha256:") ? rawDigest.slice(7) : "";
    if (
      !DIGEST_RE.test(rawDigest) ||
      !DIGEST_RE.test(gzipDigest) ||
      !SHA_HEX_RE.test(rawHex) ||
      snapshotKey !== kind.objectKey(rawHex)
    ) {
      return responseJson({ error: `completed ${kind.label} identity is invalid` }, 400);
    }
    const uploaded = await env.STRUCTURED_BUCKET.head(snapshotKey);
    if (
      !uploaded ||
      uploaded.customMetadata?.sha256 !== gzipDigest ||
      uploaded.customMetadata?.raw_sha256 !== rawDigest ||
      uploaded.customMetadata?.format !== kind.format ||
      !checksumMatches(uploaded, gzipDigest)
    ) {
      return responseJson(
        { error: `completed ${kind.label} manifest has no matching object` },
        409,
      );
    }
  } else if (
    manifest.snapshot_key != null ||
    manifest.gzip_sha256 != null ||
    manifest.raw_sha256 != null
  ) {
    return responseJson(
      { error: `failed ${kind.label} must not publish an object` },
      400,
    );
  }
  const existing = await env.STRUCTURED_BUCKET.head(key);
  if (existing) {
    return existingMatches(existing, identity)
      ? responseJson({ ok: true, created: false, key })
      : responseJson({ error: `immutable ${kind.label} manifest conflict` }, 409);
  }
  let put: R2Object | null;
  try {
    put = await env.STRUCTURED_BUCKET.put(key, bytes, {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
      customMetadata: {
        plane: kind.plane,
        job_id: identity.jobId,
        request_digest: identity.requestDigest,
        sha256: identity.contentDigest,
        status,
        immutable: "true",
      },
      sha256: digestBytes(identity.contentDigest),
      onlyIf: { etagDoesNotMatch: "*" },
    });
  } catch {
    return responseJson({ error: `${kind.label} manifest upload checksum rejected` }, 502);
  }
  if (put !== null) return responseJson({ ok: true, created: true, key }, 201);
  const raced = await env.STRUCTURED_BUCKET.head(key);
  return raced && existingMatches(raced, identity)
    ? responseJson({ ok: true, created: false, key })
    : responseJson({ error: `immutable ${kind.label} manifest conflict` }, 409);
}

async function putSnapshotGzip(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  return putSqliteGzip(request, env, key, SNAPSHOT_GZIP_KIND);
}

async function putSnapshotManifest(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  return putSqliteManifest(request, env, key, SNAPSHOT_GZIP_KIND);
}

async function putReceiptCandidateGzip(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  return putSqliteGzip(request, env, key, RECEIPT_CANDIDATE_GZIP_KIND);
}

async function putReceiptCandidateManifest(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  return putSqliteManifest(request, env, key, RECEIPT_CANDIDATE_GZIP_KIND);
}

function parseTerminalManifestKey(
  key: string,
): { kind: PersonalContainerKind; jobId: string } | null {
  const patterns: Array<[PersonalContainerKind, RegExp]> = [
    ["research", /^research\/personal\/jobs\/job=([a-z0-9][a-z0-9._-]{0,63})\/manifest\.json$/],
    ["snapshot", /^research\/personal\/snapshot-builds\/job=([a-z0-9][a-z0-9._-]{0,63})\/manifest\.json$/],
    ["receipt-candidate", /^research\/receipt-candidates\/job=([a-z0-9][a-z0-9._-]{0,63})\/manifest\.json$/],
    ["svi", /^research\/personal\/svi-2023\/job=([a-z0-9][a-z0-9._-]{0,63})\/manifest\.json$/],
    ["overlay", /^research\/personal\/(?:index-vol-overlay-2023|index-smile-transport-2023)(?:-am-pm)?\/job=([a-z0-9][a-z0-9._-]{0,63})\/manifest\.json$/],
    ["vol-panel", /^research\/personal\/vol-ratio-am-pm-v1\/panel-builds\/job=([a-z0-9][a-z0-9._-]{0,63})\/manifest\.json$/],
    ["option-sidecar", /^research\/personal\/option-sidecar\/job=([a-z0-9][a-z0-9._-]{0,63})\/manifest\.json$/],
  ];
  for (const [kind, pattern] of patterns) {
    const match = pattern.exec(key);
    if (match) return { kind, jobId: match[1]! };
  }
  return null;
}

function expectedTerminalManifestKey(
  kind: PersonalContainerKind,
  jobId: string,
  cohortId: string,
): string | null {
  if (!isPersonalResearchJobId(jobId)) return null;
  if (kind === "research") return personalResearchManifestKey(jobId);
  if (kind === "snapshot") return personalSnapshotManifestKey(jobId);
  if (kind === "receipt-candidate") {
    return personalReceiptCandidateManifestKey(jobId);
  }
  if (kind === "svi") return personalSviTerminalManifestKey(jobId);
  if (kind === "vol-panel") return personalVolAmPmPanelBuildTerminalKey(jobId);
  if (kind === PERSONAL_OPTION_SIDECAR_KIND) {
    return personalOptionSidecarTerminalKey(jobId);
  }
  if (isPersonalIndexOverlayFamilyCohort(cohortId)) {
    return personalIndexOverlayFamilyTerminalManifestKey(
      jobId,
      cohortId as PersonalIndexVolOverlay2023CohortId,
    );
  }
  return null;
}

function requiredTerminalHeaders(kind: PersonalContainerKind): string[] {
  const common = [
    "x-personal-job-id",
    "x-personal-request-digest",
    "x-personal-runner-version",
    "x-personal-job-kind",
  ];
  if (kind === "research") {
    return [...common, "x-personal-cohort-id", "x-personal-universe-id"];
  }
  if (kind === "snapshot" || kind === "receipt-candidate") return common;
  return [...common, "x-personal-cohort-id"];
}

function expectedRunnerVersion(
  kind: PersonalContainerKind,
  cohortId: string,
): string | null {
  if (
    kind === "research" ||
    kind === "snapshot" ||
    kind === "receipt-candidate"
  ) {
    return PERSONAL_RESEARCH_RUNNER_VERSION;
  }
  if (kind === "svi") return PERSONAL_SVI_2023_RUNNER_VERSION;
  if (kind === "vol-panel") return PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION;
  if (kind === PERSONAL_OPTION_SIDECAR_KIND) {
    return PERSONAL_OPTION_SIDECAR_RUNNER_VERSION;
  }
  if (isPersonalIndexOverlayFamilyCohort(cohortId)) {
    return personalIndexOverlayFamilyRunnerVersion(cohortId);
  }
  return null;
}

type ClosedTerminalIdentity = {
  parsedKey: { kind: PersonalContainerKind; jobId: string };
  jobId: string;
  requestDigest: string;
  runnerVersion: string;
  kind: string;
  cohortId: string;
  universeId: string;
};

function closedTerminalIdentity(
  request: Request,
  key: string,
): ClosedTerminalIdentity | Response {
  const parsedKey = parseTerminalManifestKey(key);
  if (!parsedKey) return responseJson({ error: "terminal key denied" }, 403);
  const personalHeaders: string[] = [];
  for (const [name] of request.headers) {
    const lower = name.toLowerCase();
    if (lower.startsWith("x-personal-")) personalHeaders.push(lower);
  }
  const required = requiredTerminalHeaders(parsedKey.kind);
  if (
    personalHeaders.length !== required.length ||
    required.some((name) => !personalHeaders.includes(name))
  ) {
    return responseJson({ error: "terminal identity headers denied" }, 403);
  }
  const jobId = request.headers.get("x-personal-job-id") ?? "";
  const requestDigest = request.headers.get("x-personal-request-digest") ?? "";
  const runnerVersion = request.headers.get("x-personal-runner-version") ?? "";
  const kind = request.headers.get("x-personal-job-kind") ?? "";
  const cohortId = request.headers.get("x-personal-cohort-id") ?? "";
  const universeId = request.headers.get("x-personal-universe-id") ?? "";
  const expectedKey = expectedTerminalManifestKey(parsedKey.kind, jobId, cohortId);
  const expectedRunner = expectedRunnerVersion(parsedKey.kind, cohortId);
  if (
    kind !== parsedKey.kind ||
    jobId !== parsedKey.jobId ||
    expectedKey !== key ||
    !DIGEST_RE.test(requestDigest) ||
    expectedRunner === null ||
    runnerVersion !== expectedRunner
  ) {
    return responseJson({ error: "terminal identity denied" }, 403);
  }
  if (parsedKey.kind === "svi" && cohortId !== PERSONAL_SVI_2023_COHORT_ID) {
    return responseJson({ error: "terminal identity denied" }, 403);
  }
  if (
    parsedKey.kind === "vol-panel" &&
    cohortId !== PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID
  ) {
    return responseJson({ error: "terminal identity denied" }, 403);
  }
  if (
    parsedKey.kind === PERSONAL_OPTION_SIDECAR_KIND &&
    cohortId !== PERSONAL_OPTION_SIDECAR_COHORT_ID
  ) {
    return responseJson({ error: "terminal identity denied" }, 403);
  }
  return {
    parsedKey,
    jobId,
    requestDigest,
    runnerVersion,
    kind,
    cohortId,
    universeId,
  };
}

function terminalBodyMatchesGetContract(
  identity: ClosedTerminalIdentity,
  manifest: Record<string, unknown>,
): boolean {
  if (
    manifest.job_id !== identity.jobId ||
    manifest.request_digest !== identity.requestDigest ||
    manifest.runner_version !== identity.runnerVersion ||
    (manifest.status !== "COMPLETED" && manifest.status !== "FAILED")
  ) {
    return false;
  }
  if (
    identity.parsedKey.kind === "research" &&
    (manifest.cohort_id !== identity.cohortId ||
      manifest.universe_id !== identity.universeId)
  ) {
    return false;
  }
  if (
    (identity.parsedKey.kind === "svi" ||
      identity.parsedKey.kind === "overlay" ||
      identity.parsedKey.kind === "vol-panel" ||
      identity.parsedKey.kind === PERSONAL_OPTION_SIDECAR_KIND) &&
    manifest.cohort_id !== identity.cohortId
  ) {
    return false;
  }
  if (
    identity.parsedKey.kind === "overlay" &&
    isPersonalIndexOverlayFamilyCohort(identity.cohortId) &&
    manifest.schema_version !==
      personalIndexOverlayFamilyTerminalSchema(identity.cohortId)
  ) {
    return false;
  }
  return true;
}

async function getTerminalManifest(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const identity = closedTerminalIdentity(request, key);
  if (identity instanceof Response) return identity;
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object) return responseJson({ error: "terminal not found" }, 404);
  if (object.size < 1 || object.size > MANIFEST_MAX_BYTES) {
    return responseJson({ error: "terminal size denied" }, 403);
  }
  const stored = new Uint8Array(await object.arrayBuffer());
  if (stored.byteLength !== object.size) {
    return responseJson({ error: "terminal length mismatch" }, 403);
  }
  let manifest: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(stored));
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("not object");
    }
    manifest = parsed as Record<string, unknown>;
  } catch {
    return responseJson({ error: "terminal is not JSON" }, 403);
  }
  if (!terminalBodyMatchesGetContract(identity, manifest)) {
    return responseJson({ error: "terminal identity mismatch" }, 403);
  }
  if (request.method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: { "content-length": String(object.size) },
    });
  }
  return new Response(stored, {
    status: 200,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "content-length": String(stored.byteLength),
    },
  });
}

/** Narrow R2 capability exposed only to the private Container virtual host. */
export async function personalResearchR2Outbound(
  request: Request,
  env: R2Env,
): Promise<Response> {
  const url = new URL(request.url);
  const key = url.pathname.startsWith("/") ? url.pathname.slice(1) : url.pathname;
  if (url.hostname !== "research.r2" || url.search || url.hash || key.includes("%")) {
    return responseJson({ error: "R2 request denied" }, 403);
  }
  // The generic personal-container capability must never reach Controlled Pilot
  // objects. Controlled jobs receive a separately bound handler whose runtime
  // context is tied to the deterministic job container.
  if (key.startsWith(CONTROLLED_PILOT_KEY_PREFIX)) {
    return responseJson({ error: "controlled R2 prefix denied" }, 403);
  }
  if (
    (request.method === "GET" || request.method === "HEAD") &&
    parseTerminalManifestKey(key)
  ) {
    return getTerminalManifest(request, env, key);
  }
  if (isPersonalIndexVolOverlayOutboundRequest(request, key)) {
    return personalIndexVolOverlayR2Outbound(request, env, key);
  }
  if (isPersonalSviOutboundRequest(request, key)) {
    return personalSviR2Outbound(request, env, key);
  }
  if (isPersonalVolAmPmPanelOutboundRequest(request, key)) {
    return personalVolAmPmPanelR2Outbound(request, env, key);
  }
  if (isPersonalOptionSidecarOutboundRequest(request, key)) {
    return personalOptionSidecarR2Outbound(request, env, key);
  }
  if (isPersonalAcquisitionCacheOutboundRequest(request, key)) {
    return personalAcquisitionCacheR2Outbound(request, env, key);
  }
  if ((request.method === "GET" || request.method === "HEAD") &&
      isPersonalResearchSnapshotKey(key)) {
    return getSnapshot(request, env, key);
  }
  if (request.method === "PUT" && isReceiptCandidateObjectKey(key)) {
    return putReceiptCandidateGzip(request, env, key);
  }
  if (request.method === "PUT" && isReceiptCandidateManifestKey(key)) {
    return putReceiptCandidateManifest(request, env, key);
  }
  if (request.method === "PUT" && isPersonalResearchSnapshotKey(key) && key.endsWith(".sqlite.gz")) {
    return putSnapshotGzip(request, env, key);
  }
  if (request.method === "PUT" && isPersonalSnapshotManifestKey(key)) {
    return putSnapshotManifest(request, env, key);
  }
  if (request.method === "PUT" && /\/result\.tar\.gz$/.test(key)) {
    return putResult(request, env, key);
  }
  if (request.method === "PUT" && /\/manifest\.json$/.test(key)) {
    return putManifest(request, env, key);
  }
  return responseJson({ error: "R2 method or key denied" }, 403);
}
