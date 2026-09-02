import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.stubGlobal(
  "FixedLengthStream",
  class extends TransformStream<Uint8Array, Uint8Array> {
    constructor(_expectedLength: number | bigint) {
      super();
    }
  },
);

import readyFixture from "../../../../specs/ready/controlled_pilot_ready.generated.json";
import traderFixture from "../../../../specs/ready/controlled_pilot_trader_batch.generated.json";
import fixtureKeys from "../../../../specs/ready/controlled_pilot_verify_keys.generated.json";
import pythonContainerArtifacts from "../../../../specs/ready/controlled_pilot_container_artifacts.generated.json";
import {
  CONTROLLED_FILL_CONTRACT_DIGEST,
  CONTROLLED_PILOT_IDENTITY,
  CONTROLLED_READY_ENVELOPE_FORMAT,
  CONTROLLED_TRADER_BATCH_FORMAT,
  EXACT_FOUR_BINDING_DIGEST,
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_PLAN_BINDING_DIGESTS,
  EXACT_FOUR_PLAN_SET_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  EXACT_FOUR_STRATEGY_BY_PLAN,
  EXACT_FOUR_STRATEGY_SPEC_HASHES,
  EXACT_FOUR_STRATEGY_SPEC_VERSIONS,
  controlledPhysicalSnapshotKey,
  controlledReadyKey,
  controlledTraderAuthorizationKey,
  parseControlledPilotRequest,
} from "./controlled_pilot_contract";
import {
  EXACT_FOUR_PLAN_IDS,
  canonicalJson,
  controlledPilotStatus,
  runControlledPilotJob,
  submitControlledPilot,
  verifyControlledReadyEnvelope,
  verifyControlledReadyEnvelopeBytes,
  verifyTraderAuthorizationBatch,
} from "./controlled_pilot";
import * as registries from "./controlled_pilot_registries";
import { decodeStrictJson, sha256Digest, StrictJsonError } from "./controlled_pilot_json";
import { dispatchMassEvalFetch } from "./http_routes";
import { PERSONAL_RESEARCH_RUNNER_VERSION } from "./personal_research_contract";
import type { Env } from "./types";

type Stored = { body: Uint8Array; etag: string };

class MemR2 {
  readonly putOrder: string[] = [];
  readonly got: string[] = [];
  private readonly objects = new Map<string, Stored>();

  async head(key: string) {
    const o = this.objects.get(key);
    if (!o) return null;
    return { key, size: o.body.byteLength, etag: o.etag };
  }

  async get(key: string) {
    this.got.push(key);
    const o = this.objects.get(key);
    if (!o) return null;
    const text = async () => new TextDecoder().decode(o.body);
    return {
      key,
      size: o.body.byteLength,
      etag: o.etag,
      text,
      json: async () => JSON.parse(await text()),
      arrayBuffer: async () => o.body.buffer.slice(o.body.byteOffset, o.body.byteOffset + o.body.byteLength),
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(o.body);
          controller.close();
        },
      }),
    };
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: { onlyIf?: { etagDoesNotMatch?: string } },
  ) {
    if (options?.onlyIf?.etagDoesNotMatch === "*" && this.objects.has(key)) return null;
    let body: Uint8Array;
    if (typeof value === "string") body = new TextEncoder().encode(value);
    else if (value instanceof Uint8Array) body = value;
    else body = new Uint8Array(value as ArrayBuffer);
    const etag = `etag-${this.objects.size + 1}`;
    this.objects.set(key, { body, etag });
    this.putOrder.push(key);
    return { key, etag, size: body.byteLength };
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

function decodeB64(raw: string): Uint8Array {
  const bin = atob(raw);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function readyProbe(): Response {
  const body = JSON.stringify({ ok: true, service: PERSONAL_RESEARCH_RUNNER_VERSION });
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "application/json",
      "content-length": String(new TextEncoder().encode(body).byteLength),
    },
  });
}

type BudgetState = {
  reserved: number;
  finalized: number;
  cancelled: number;
  heartbeats: number;
  queried: number;
  loseFinalize?: boolean;
};

function mockGateway(state: BudgetState): Env["AI_GATEWAY"] {
  const ok = (extra: Record<string, unknown> = {}) => ({
    http_status: 200,
    body: { ok: true, lease_id: "lease-1", ...extra },
  });
  return {
    complete: async () => ({ http_status: 400, body: { ok: false } }),
    reserveControlledPaper: async () => {
      state.reserved += 1;
      return ok({ existing: state.reserved > 1, reservation_status: "reserved" });
    },
    finalizeControlledPaper: async () => {
      state.finalized += 1;
      if (state.loseFinalize && state.finalized === 1) {
        return { http_status: 503, body: { ok: false, error: "budget_rpc_failed" } };
      }
      return ok({ reservation_status: "reconciled" });
    },
    cancelControlledPaper: async () => {
      state.cancelled += 1;
      return ok();
    },
    heartbeatControlledPaper: async () => {
      state.heartbeats += 1;
      return ok();
    },
    queryControlledPaper: async () => {
      state.queried += 1;
      if (state.reserved === 0) {
        return { http_status: 409, body: { ok: false, error: "reservation_not_found" } };
      }
      return ok({ existing: true, reservation_status: "reserved" });
    },
  };
}

async function artifacts(logicalId: string) {
  if (logicalId !== fixtureKeys.logical_snapshot_id) {
    throw new Error("Python Container fixture logical snapshot mismatch");
  }
  return structuredClone(pythonContainerArtifacts) as unknown as {
    ok: true;
    identity: string;
    ephemeral_cleaned: true;
    papers: Record<string, unknown>[];
    risks: Record<string, unknown>[];
    selection: Record<string, unknown>;
    knowledge: Record<string, unknown>;
  };
}

function mockContainer(options?: {
  fail?: "error" | "timeout";
  omitOutbound?: boolean;
  fetches?: { n: number; post: number };
  tamper?:
    | "reorder"
    | "duplicate"
    | "snapshot"
    | "risk"
    | "selection"
    | "knowledge"
    | "knowledge_missing_id"
    | "knowledge_wrong_digest"
    | "post_digest_injection"
    | "non_raw_price_basis"
    | "noncanonical_execution_mode"
    | "missing_semantic_field"
    | "missing_knowledge_payload_field"
    | "semantic_rebound_risk"
    | "semantic_reordered_selection"
    | "semantic_rebound_knowledge";
  delay?: { complete: boolean };
}): Env["PERSONAL_RESEARCH_CONTAINER"] {
  const outbound = new Map<string, unknown>();
  const fetches = options?.fetches ?? { n: 0, post: 0 };
  const jobs = new Map<string, Record<string, unknown>>();
  return {
    getByName() {
      const target: Record<string, unknown> = {
        fetch: async (request: Request) => {
          const url = new URL(request.url);
          if (url.pathname === "/ready") return readyProbe();
          fetches.n += 1;
          if (options?.fail === "timeout") throw new Error("container timeout");
          if (options?.fail === "error") throw new Error("container exploded");
          if (request.method === "POST" && url.pathname === "/v1/controlled-pilot") {
            fetches.post += 1;
            const body = (await request.json()) as { job_id: string; snapshot_id: string };
            const result = await artifacts(body.snapshot_id);
            if (options?.tamper === "reorder") {
              result.papers = [result.papers[1]!, result.papers[0]!, result.papers[2]!, result.papers[3]!];
            }
            if (options?.tamper === "duplicate") {
              result.papers = [result.papers[0]!, result.papers[0]!, result.papers[2]!, result.papers[3]!];
            }
            if (options?.tamper === "snapshot") {
              result.papers[0]!.snapshot_id = "sha256:" + "00".repeat(32);
            }
            if (options?.tamper === "risk") {
              result.risks[0]!.paper_semantic_digest = "sha256:" + "11".repeat(32);
            }
            if (options?.tamper === "selection") {
              result.selection.semantic_child_set_digest = "sha256:" + "22".repeat(32);
            }
            if (options?.tamper === "knowledge") {
              result.knowledge.selection_semantic_digest = "sha256:" + "33".repeat(32);
            }
            if (options?.tamper === "knowledge_missing_id") {
              delete result.knowledge.artifact_id;
            }
            if (options?.tamper === "knowledge_wrong_digest") {
              result.knowledge.digest = "sha256:" + "44".repeat(32);
            }
            if (options?.tamper === "post_digest_injection") {
              result.papers[0]!.injected_after_closed_schema = true;
              delete result.papers[0]!.semantic_digest;
              result.papers[0]!.semantic_digest = await sha256Digest(canonicalJson(result.papers[0]!));
            }
            if (options?.tamper === "non_raw_price_basis") {
              result.papers[0]!.price_basis = "PIT_ADJUSTED";
              delete result.papers[0]!.semantic_digest;
              result.papers[0]!.semantic_digest = await sha256Digest(canonicalJson(result.papers[0]!));
            }
            if (options?.tamper === "noncanonical_execution_mode") {
              result.papers[0]!.execution_mode = "arbitrary_close";
              delete result.papers[0]!.semantic_digest;
              result.papers[0]!.semantic_digest = await sha256Digest(canonicalJson(result.papers[0]!));
            }
            if (options?.tamper === "missing_semantic_field") {
              delete result.papers[0]!.run_id;
              delete result.papers[0]!.semantic_digest;
              result.papers[0]!.semantic_digest = await sha256Digest(canonicalJson(result.papers[0]!));
            }
            if (options?.tamper === "missing_knowledge_payload_field") {
              delete (result.knowledge.payload as Record<string, unknown>).risk_audit_ids;
              delete result.knowledge.artifact_id;
              delete result.knowledge.digest;
              delete result.knowledge.semantic_digest;
              const rebound = await sha256Digest(canonicalJson(result.knowledge));
              result.knowledge.artifact_id = rebound;
              result.knowledge.digest = rebound;
              result.knowledge.semantic_digest = rebound;
            }
            if (options?.tamper === "semantic_rebound_risk") {
              result.risks[0]!.paper_semantic_digest = result.papers[1]!.semantic_digest;
              delete result.risks[0]!.semantic_digest;
              result.risks[0]!.semantic_digest = await sha256Digest(canonicalJson(result.risks[0]!));
            }
            if (options?.tamper === "semantic_reordered_selection") {
              const paperSemantic = result.selection.paper_semantic_digests as unknown[];
              result.selection.paper_semantic_digests = [
                paperSemantic[1], paperSemantic[0], paperSemantic[2], paperSemantic[3],
              ];
              result.selection.semantic_child_set_digest = await sha256Digest(canonicalJson({
                paper_semantic_digests: result.selection.paper_semantic_digests,
                risk_semantic_digests: result.selection.risk_semantic_digests,
              }));
              delete result.selection.semantic_digest;
              result.selection.semantic_digest = await sha256Digest(canonicalJson(result.selection));
            }
            if (options?.tamper === "semantic_rebound_knowledge") {
              result.knowledge.selection_semantic_digest = result.papers[0]!.semantic_digest;
              (result.knowledge.payload as Record<string, unknown>).selection_semantic_digest =
                result.papers[0]!.semantic_digest;
              delete result.knowledge.artifact_id;
              delete result.knowledge.digest;
              delete result.knowledge.semantic_digest;
              const rebound = await sha256Digest(canonicalJson(result.knowledge));
              result.knowledge.artifact_id = rebound;
              result.knowledge.digest = rebound;
              result.knowledge.semantic_digest = rebound;
            }
            const complete = !options?.delay || options.delay.complete;
            jobs.set(body.job_id, { ...result, status: complete ? "COMPLETED" : "QUEUED", job_id: body.job_id, ok: complete });
            return Response.json(
              {
                ok: true,
                accepted: true,
                job: { job_id: body.job_id, status: "QUEUED" },
              },
              { status: 202 },
            );
          }
          const match = url.pathname.match(/^\/v1\/jobs\/([^/]+)$/);
          if (request.method === "GET" && match) {
            const job = jobs.get(match[1]!);
            if (!job) return Response.json({ error: "job_not_found" }, { status: 404 });
            if (options?.delay && !options.delay.complete) {
              return Response.json({ ok: true, job: { ...job, status: "RUNNING", ok: true } });
            }
            return Response.json({ ok: job.status === "COMPLETED", job: { ...job, status: "COMPLETED", ok: true } });
          }
          return Response.json({ error: "not_found" }, { status: 404 });
        },
      };
      if (!options?.omitOutbound) {
        target.setOutboundByHost = async (host: string, method: string, params: unknown) => {
          outbound.set(host, { method, params });
        };
        target.removeOutboundByHost = async (host: string) => {
          outbound.delete(host);
        };
      }
      return target;
    },
  } as unknown as Env["PERSONAL_RESEARCH_CONTAINER"];
}

function fixturePublicKey(): registries.PinnedVerifyKey[] {
  return [
    {
      key_id: fixtureKeys.key_id,
      public_key: decodeB64(fixtureKeys.public_key_b64),
      algorithm: "Ed25519",
      status: "active",
      not_before: "2026-01-01T00:00:00Z",
      not_after: "2099-01-01T00:00:00Z",
      revoked_at: null,
      environment: "staging",
    },
  ];
}

class WaitCtx {
  pending: Promise<unknown> = Promise.resolve();
  waitUntil(promise: Promise<unknown>) {
    this.pending = promise;
  }
}

async function seedEnv(options?: {
  failContainer?: "error" | "timeout";
  skipAuth?: boolean;
  skipReady?: boolean;
  loseFinalize?: boolean;
  omitOutbound?: boolean;
  fetches?: { n: number; post: number };
  tamper?:
    | "reorder"
    | "duplicate"
    | "snapshot"
    | "risk"
    | "selection"
    | "knowledge"
    | "knowledge_missing_id"
    | "knowledge_wrong_digest"
    | "post_digest_injection"
    | "non_raw_price_basis"
    | "noncanonical_execution_mode"
    | "missing_semantic_field"
    | "missing_knowledge_payload_field"
    | "semantic_rebound_risk"
    | "semantic_reordered_selection"
    | "semantic_rebound_knowledge";
  delay?: { complete: boolean };
}) {
  const mem = new MemR2();
  const snapshot = new TextEncoder().encode("controlled-pilot-physical-sqlite");
  const physicalId = fixtureKeys.physical_snapshot_id;
  const logicalId = fixtureKeys.logical_snapshot_id;
  const request = fixtureKeys.request;
  await mem.put(controlledPhysicalSnapshotKey(physicalId), snapshot);
  if (!options?.skipReady) {
    await mem.put(controlledReadyKey(request.ready_attestation_id), JSON.stringify(readyFixture));
  }
  if (!options?.skipAuth) {
    await mem.put(
      controlledTraderAuthorizationKey(request.idempotency_key, request.ready_attestation_id),
      JSON.stringify(traderFixture),
    );
  }
  const budget: BudgetState = {
    reserved: 0,
    finalized: 0,
    cancelled: 0,
    heartbeats: 0,
    queried: 0,
    loseFinalize: options?.loseFinalize,
  };
  vi.spyOn(registries, "loadPinnedReadyKeys").mockReturnValue(fixturePublicKey());
  vi.spyOn(registries, "loadPinnedTraderKeys").mockReturnValue(fixturePublicKey());
  const fetches = options?.fetches ?? { n: 0, post: 0 };
  const env = {
    STRUCTURED_BUCKET: mem.asBucket(),
    AI_GATEWAY: mockGateway(budget),
    PERSONAL_RESEARCH_CONTAINER: mockContainer({
      fail: options?.failContainer,
      omitOutbound: options?.omitOutbound,
      fetches,
      tamper: options?.tamper,
      delay: options?.delay,
    }),
    MASS_EVAL_TOKEN: "secret",
    ENVIRONMENT: "staging",
  } as unknown as Env;
  return { env, mem, logicalId, physicalId, budget, request, fetches };
}

const VERIFIER_NOW = Date.parse(String(fixtureKeys.verifier_now || "2026-09-02T12:00:30+00:00"));

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(VERIFIER_NOW);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("controlled pilot request parser", () => {
  it("rejects caller path digest plan promotion order and budget injection", () => {
    for (const key of [
      "db_path",
      "snapshot_path",
      "plan_ids",
      "immutable_db_digest",
      "promotion",
      "live_orders",
      "generation",
    ]) {
      const parsed = parseControlledPilotRequest({
        idempotency_key: "controlled-job-1",
        ready_attestation_id: "attestation-cloud-1",
        snapshot_id: fixtureKeys.logical_snapshot_id,
        [key]: "injected",
      });
      expect(parsed.ok).toBe(false);
    }
  });

  it("returns canonical exp-* plan ids not StrategySpec ids", () => {
    expect([...EXACT_FOUR_PLAN_IDS][0]?.startsWith("exp-")).toBe(true);
    expect(EXACT_FOUR_PLAN_IDS).toHaveLength(4);
  });
});

describe("strict JSON and Python-generated fixtures", () => {
  it("rejects duplicate keys from raw bytes", () => {
    const bytes = new TextEncoder().encode('{"a":1,"a":2}');
    expect(() => decodeStrictJson(bytes)).toThrow(StrictJsonError);
  });

  it("accepts the Python-signed READY envelope and trader batch", async () => {
    const keys = fixturePublicKey();
    const readyBytes = new TextEncoder().encode(JSON.stringify(readyFixture));
    const verified = await verifyControlledReadyEnvelopeBytes(
      readyBytes,
      fixtureKeys.logical_snapshot_id,
      "staging",
      keys,
    );
    expect(verified.ok).toBe(true);
    if (!verified.ok) return;
    const authorized = await verifyTraderAuthorizationBatch(
      traderFixture,
      fixtureKeys.request,
      verified.value,
      fixtureKeys.request_digest,
      keys,
    );
    expect(authorized.ok).toBe(true);
    const productionKey = keys.map((key) => ({ ...key, environment: "production" }));
    const crossEnvironment = await verifyTraderAuthorizationBatch(
      traderFixture,
      fixtureKeys.request,
      verified.value,
      fixtureKeys.request_digest,
      productionKey,
    );
    expect(crossEnvironment).toEqual({ ok: false, error: "trader key environment denied" });
  });

  it("rejects Coverage v1, long TTL, and tampered READY", async () => {
    const keys = fixturePublicKey();
    const v1 = structuredClone(readyFixture) as Record<string, unknown>;
    const manifest = v1.ready_manifest as Record<string, unknown>;
    manifest.coverage_policy_version = "v1";
    expect(
      (await verifyControlledReadyEnvelope(v1, fixtureKeys.logical_snapshot_id, "staging", keys)).ok,
    ).toBe(false);
    const longTtl = structuredClone(readyFixture) as { attestation: Record<string, unknown> };
    longTtl.attestation.expires_at = "2099-01-01T00:00:00+00:00";
    expect(
      (await verifyControlledReadyEnvelope(longTtl, fixtureKeys.logical_snapshot_id, "staging", keys)).ok,
    ).toBe(false);
    const extra = new TextEncoder().encode(
      JSON.stringify(readyFixture).replace('"identity":', '"extra":1,"identity":'),
    );
    expect(
      (await verifyControlledReadyEnvelopeBytes(extra, fixtureKeys.logical_snapshot_id, "staging", keys)).ok,
    ).toBe(false);
  });

  it("rejects controlled session entry substitution outside the dependency proof", async () => {
    const tampered = structuredClone(readyFixture) as {
      controlled_session_scope: { entries: Array<Record<string, unknown>> };
    };
    tampered.controlled_session_scope.entries[0]!.natural_key_digest =
      "sha256:" + "00".repeat(32);
    const verified = await verifyControlledReadyEnvelope(
      tampered,
      fixtureKeys.logical_snapshot_id,
      "staging",
      fixturePublicKey(),
    );
    expect(verified).toEqual({
      ok: false,
      error: "READY controlled session scope does not match dependency proof",
    });
  });

  it("parses committed production and staging registries from imported documents", async () => {
    expect(await registries.assertRegistryDigests()).toBe(true);
    const readyProd = await registries.loadPinnedReadyKeys("production");
    const readyStg = await registries.loadPinnedReadyKeys("staging");
    const traderProd = await registries.loadPinnedTraderKeys("production");
    const traderStg = await registries.loadPinnedTraderKeys("staging");
    expect(Array.isArray(readyProd)).toBe(true);
    expect(Array.isArray(readyStg)).toBe(true);
    expect(Array.isArray(traderProd)).toBe(true);
    expect(Array.isArray(traderStg)).toBe(true);
    const observed = await registries.parseCommittedRegistryBytes(
      registries.COMMITTED_READY_DOCUMENTS.production,
      "production",
      "readiness_attestation_verification",
      "ready-authority",
      registries.READY_DIGEST.production,
      new Set(["active", "revoked"]),
      registries.READY_RAW.production,
    );
    expect(observed).toEqual(readyProd);
  });
});

describe("controlled cloud execution", () => {
  it("POST returns 202 without awaiting container work", async () => {
    const seeded = await seedEnv();
    const ctx = new WaitCtx();
    const first = await submitControlledPilot(seeded.env, seeded.request, ctx);
    expect(first.status).toBe(202);
    expect(seeded.fetches.n).toBe(0);
    await ctx.pending;
    expect(seeded.fetches.post).toBe(1);
    expect(seeded.fetches.n).toBeGreaterThan(1);
    const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    const body = (await status.json()) as { status: string; manifest: { children: unknown[] } };
    expect(body.status).toBe("COMPLETED");
    expect(body.manifest.children).toHaveLength(10);
    expect(seeded.budget.finalized).toBe(1);
    expect(seeded.budget.heartbeats).toBeGreaterThan(0);
  });

  it("rejects a same-digest state conflict whose canonical initial state was poisoned", async () => {
    const seeded = await seedEnv();
    const first = await submitControlledPilot(seeded.env, seeded.request);
    expect(first.status).toBe(202);
    const key =
      `research/controlled_pilot/v1/jobs/${seeded.request.idempotency_key}/state.json`;
    const stored = await seeded.env.STRUCTURED_BUCKET.get(key);
    expect(stored).not.toBeNull();
    const poisoned = await stored!.json<Record<string, unknown>>();
    (poisoned.spec as Record<string, unknown>).authorization_digest =
      "sha256:" + "00".repeat(32);
    await seeded.mem.put(key, JSON.stringify(poisoned));

    const replay = await submitControlledPilot(seeded.env, seeded.request);
    expect(replay.status).toBe(409);
    expect(await replay.json()).toMatchObject({ error: "idempotency conflict", go: false });
    expect(seeded.budget.queried).toBe(0);
    expect(seeded.budget.reserved).toBe(0);
    expect(seeded.fetches.n).toBe(0);
  });

  it("does not run a persisted state that fails the canonical state validator", async () => {
    const seeded = await seedEnv();
    expect((await submitControlledPilot(seeded.env, seeded.request)).status).toBe(202);
    const key =
      `research/controlled_pilot/v1/jobs/${seeded.request.idempotency_key}/state.json`;
    const stored = await seeded.env.STRUCTURED_BUCKET.get(key);
    expect(stored).not.toBeNull();
    const poisoned = await stored!.json<Record<string, unknown>>();
    (poisoned.spec as Record<string, unknown>).snapshot_key =
      "research/controlled_pilot/v1/snapshots/sha256=" + "00".repeat(32) + ".sqlite";
    await seeded.mem.put(key, JSON.stringify(poisoned));

    await runControlledPilotJob(seeded.env, seeded.request.idempotency_key);
    expect(seeded.budget.queried).toBe(0);
    expect(seeded.budget.reserved).toBe(0);
    expect(seeded.fetches.n).toBe(0);
  });

  it("query never reserves and retry resumes the same reservation", async () => {
    const seeded = await seedEnv();
    const ctx = new WaitCtx();
    await submitControlledPilot(seeded.env, seeded.request, ctx);
    await ctx.pending;
    const reserved = seeded.budget.reserved;
    const retryCtx = new WaitCtx();
    const retry = await submitControlledPilot(seeded.env, seeded.request, retryCtx);
    expect(retry.status).toBe(202);
    await retryCtx.pending;
    expect(seeded.budget.reserved).toBe(reserved);
    expect(seeded.budget.queried).toBeGreaterThan(0);
  });

  it("does not accept another job's terminal manifest copied into this job path", async () => {
    const seeded = await seedEnv();
    const ctx = new WaitCtx();
    await submitControlledPilot(seeded.env, seeded.request, ctx);
    await ctx.pending;
    const sourceJob = seeded.request.idempotency_key;
    const copiedJob = "controlled-job-copied-manifest";
    const source = await seeded.env.STRUCTURED_BUCKET.get(
      `research/controlled_pilot/v1/jobs/${sourceJob}/manifest.json`,
    );
    expect(source).not.toBeNull();
    const sourceBytes = new Uint8Array(await source!.arrayBuffer());
    await seeded.mem.put(
      `research/controlled_pilot/v1/jobs/${copiedJob}/manifest.json`,
      sourceBytes,
    );

    const status = await controlledPilotStatus(seeded.env, copiedJob);
    expect(((await status.json()) as { status: string }).status).not.toBe("COMPLETED");
  });

  it("accepts Python-style float zero and persists the exact dependency chain in order", async () => {
    const seeded = await seedEnv();
    const ctx = new WaitCtx();
    await submitControlledPilot(seeded.env, seeded.request, ctx);
    await ctx.pending;
    const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    const terminal = (await status.json()) as {
      status: string;
      manifest: { children: Array<Record<string, unknown>> };
    };
    expect(terminal.status).toBe("COMPLETED");
    const refs = terminal.manifest.children;
    const read = async (key: string): Promise<Record<string, unknown>> => {
      const object = await seeded.env.STRUCTURED_BUCKET.get(key);
      expect(object).not.toBeNull();
      return JSON.parse(new TextDecoder().decode(new Uint8Array(await object!.arrayBuffer()))) as Record<string, unknown>;
    };
    const papers = await Promise.all(refs.slice(0, 4).map((ref) => read(String(ref.key))));
    const risks = await Promise.all(refs.slice(4, 8).map((ref) => read(String(ref.key))));
    const selection = await read(String(refs[8]!.key));
    const knowledge = await read(String(refs[9]!.key));

    const firstPaperBody = papers[0]!.semantic_body as Record<string, unknown>;
    expect(firstPaperBody.metrics).toEqual({ total_return_post_cost: 0, max_drawdown: 0 });
    expect(papers[0]!.semantic_digest).toBe(await sha256Digest(canonicalJson(firstPaperBody)));
    for (let index = 0; index < 4; index += 1) {
      expect((risks[index]!.lineage as Record<string, unknown>).paper_persisted_byte_digest)
        .toBe(refs[index]!.persisted_byte_digest);
      expect((risks[index]!.lineage as Record<string, unknown>).paper_semantic_digest)
        .toBe(papers[index]!.semantic_digest);
    }
    const selectionLineage = selection.lineage as Record<string, unknown>;
    expect(selectionLineage.paper_persisted_byte_digests)
      .toEqual(refs.slice(0, 4).map((ref) => ref.persisted_byte_digest));
    expect(selectionLineage.risk_persisted_byte_digests)
      .toEqual(refs.slice(4, 8).map((ref) => ref.persisted_byte_digest));
    const expectedChildSet = await sha256Digest(canonicalJson({
      paper_persisted_byte_digests: selectionLineage.paper_persisted_byte_digests,
      risk_persisted_byte_digests: selectionLineage.risk_persisted_byte_digests,
    }));
    expect(selectionLineage.ordered_child_set_digest).toBe(expectedChildSet);
    const knowledgeLineage = knowledge.lineage as Record<string, unknown>;
    expect(knowledgeLineage.selection_persisted_byte_digest).toBe(refs[8]!.persisted_byte_digest);
    expect(knowledgeLineage.ordered_child_set_digest).toBe(expectedChildSet);
    expect(knowledge.artifact_id).toBe(knowledge.semantic_digest);
    expect(knowledge.digest).toBe(knowledge.semantic_digest);

    const persistedOrder = seeded.mem.putOrder.filter((key) =>
      key.includes(`/jobs/${seeded.request.idempotency_key}/`) &&
      (key.includes("/paper/") || key.includes("/risk/") || key.endsWith("/selection.json") || key.endsWith("/knowledge.json")),
    );
    expect(persistedOrder.map((key) => key.split("/").slice(-2).join("/"))).toEqual([
      "paper/1.json", "paper/2.json", "paper/3.json", "paper/4.json",
      "risk/1.json", "risk/2.json", "risk/3.json", "risk/4.json",
      `${seeded.request.idempotency_key}/selection.json`,
      `${seeded.request.idempotency_key}/knowledge.json`,
    ]);
  });

  it("finalize failure leaves nonterminal state and no terminal artifact", async () => {
    const seeded = await seedEnv({ loseFinalize: true });
    const ctx = new WaitCtx();
    await submitControlledPilot(seeded.env, seeded.request, ctx);
    await ctx.pending;
    const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    const body = (await status.json()) as { status: string; manifest?: unknown };
    expect(body.status).toBe("FINALIZE_RETRY");
    expect(body.manifest).toBeUndefined();
    expect(seeded.mem.putOrder.some((key) => key.endsWith("/manifest.json"))).toBe(false);
  });

  it("rejects missing trader authorization and does not reserve", async () => {
    const seeded = await seedEnv({ skipAuth: true });
    const ctx = new WaitCtx();
    expect((await submitControlledPilot(seeded.env, seeded.request, ctx)).status).toBe(404);
    expect(seeded.budget.reserved).toBe(0);
    expect(seeded.fetches.n).toBe(0);
  });

  it("fails closed when outbound policy is missing", async () => {
    const seeded = await seedEnv({ omitOutbound: true });
    const ctx = new WaitCtx();
    await submitControlledPilot(seeded.env, seeded.request, ctx);
    await ctx.pending;
    const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    const body = (await status.json()) as { status: string };
    expect(body.status).not.toBe("COMPLETED");
  });

  it("two fresh worker instances resume without a second container execution", async () => {
    const fetches = { n: 0, post: 0 };
    const first = await seedEnv({ fetches });
    const ctx = new WaitCtx();
    await submitControlledPilot(first.env, first.request, ctx);
    await ctx.pending;
    expect(fetches.post).toBe(1);
    const secondEnv = {
      ...first.env,
    } as Env;
    await runControlledPilotJob(secondEnv, first.request.idempotency_key);
    expect(fetches.post).toBe(1);
    const status = await controlledPilotStatus(secondEnv, first.request.idempotency_key);
    const body = (await status.json()) as { status: string };
    expect(body.status).toBe("COMPLETED");
  });

  it("GET is lookup-only and does not start container work", async () => {
    const seeded = await seedEnv();
    const ctx = new WaitCtx();
    const first = await submitControlledPilot(seeded.env, seeded.request, ctx);
    expect(first.status).toBe(202);
    const lookup = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    expect(lookup.status).toBe(202);
    expect(seeded.fetches.post).toBe(0);
    await ctx.pending;
  });

  it("does not cancel a still-running job and resumes after 120s", async () => {
    const delay = { complete: false };
    const seeded = await seedEnv({ delay });
    const ctx = new WaitCtx();
    await submitControlledPilot(seeded.env, seeded.request, ctx);
    await ctx.pending;
    expect(seeded.budget.cancelled).toBe(0);
    expect(seeded.fetches.post).toBe(1);
    delay.complete = true;
    await runControlledPilotJob(seeded.env, seeded.request.idempotency_key);
    const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    const body = (await status.json()) as { status: string };
    expect(body.status).toBe("COMPLETED");
    expect(seeded.fetches.post).toBe(1);
  });

  it("rejects reordered and duplicated container children", async () => {
    for (const tamper of ["reorder", "duplicate"] as const) {
      const seeded = await seedEnv({ tamper });
      const ctx = new WaitCtx();
      await submitControlledPilot(seeded.env, seeded.request, ctx);
      await ctx.pending;
      const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
      const body = (await status.json()) as { status: string };
      expect(body.status).not.toBe("COMPLETED");
    }
  });

  it("rejects tampered snapshot Risk Selection and Knowledge terminals", async () => {
    for (const tamper of ["snapshot", "risk", "selection", "knowledge"] as const) {
      const seeded = await seedEnv({ tamper });
      const ctx = new WaitCtx();
      await submitControlledPilot(seeded.env, seeded.request, ctx);
      await ctx.pending;
      const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
      const body = (await status.json()) as { status: string };
      expect(body.status).not.toBe("COMPLETED");
    }
  });

  it("rejects missing or wrong Knowledge identity and post-digest field injection", async () => {
    for (const tamper of [
      "knowledge_missing_id",
      "knowledge_wrong_digest",
      "post_digest_injection",
      "non_raw_price_basis",
      "noncanonical_execution_mode",
      "missing_semantic_field",
      "missing_knowledge_payload_field",
      "semantic_rebound_risk",
      "semantic_reordered_selection",
      "semantic_rebound_knowledge",
    ] as const) {
      const seeded = await seedEnv({ tamper });
      const ctx = new WaitCtx();
      await submitControlledPilot(seeded.env, seeded.request, ctx);
      await ctx.pending;
      const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
      expect(((await status.json()) as { status: string }).status).not.toBe("COMPLETED");
      expect(seeded.mem.putOrder.some((key) => key.includes("/paper/"))).toBe(false);
    }
  });

  it("rejects a persisted Risk whose semantic body and manifest byte ref are rebound", async () => {
    const seeded = await seedEnv();
    const ctx = new WaitCtx();
    await submitControlledPilot(seeded.env, seeded.request, ctx);
    await ctx.pending;
    const completed = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    expect(((await completed.json()) as { status: string }).status).toBe("COMPLETED");
    const prefix = `research/controlled_pilot/v1/jobs/${seeded.request.idempotency_key}`;
    const riskKey = `${prefix}/risk/1.json`;
    const raw = await seeded.env.STRUCTURED_BUCKET.get(riskKey);
    expect(raw).not.toBeNull();
    const body = JSON.parse(new TextDecoder().decode(new Uint8Array(await raw!.arrayBuffer()))) as Record<string, unknown>;
    const semanticBody = body.semantic_body as Record<string, unknown>;
    semanticBody.snapshot_id = "sha256:" + "00".repeat(32);
    body.semantic_digest = await sha256Digest(canonicalJson(semanticBody));
    body.result_id = body.semantic_digest;
    const tamperedBytes = new TextEncoder().encode(JSON.stringify(body, null, 2));
    const tamperedDigest = await sha256Digest(tamperedBytes);
    await seeded.mem.put(riskKey, tamperedBytes);
    const manifestKey = `${prefix}/manifest.json`;
    const manifestObject = await seeded.env.STRUCTURED_BUCKET.get(manifestKey);
    const manifest = JSON.parse(
      new TextDecoder().decode(new Uint8Array(await manifestObject!.arrayBuffer())),
    ) as { children: Array<Record<string, unknown>> };
    manifest.children[4]!.persisted_byte_digest = tamperedDigest;
    manifest.children[4]!.size = tamperedBytes.byteLength;
    await seeded.mem.put(manifestKey, JSON.stringify(manifest, null, 2));
    const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
    const parsed = (await status.json()) as { status: string };
    expect(parsed.status).not.toBe("COMPLETED");
  });

  it("rejects persisted Paper fill-policy fields even when semantic and byte digests are rebound", async () => {
    for (const [field, value] of [
      ["price_basis", "PIT_ADJUSTED"],
      ["execution_mode", "arbitrary_close"],
    ] as const) {
      const seeded = await seedEnv();
      const ctx = new WaitCtx();
      await submitControlledPilot(seeded.env, seeded.request, ctx);
      await ctx.pending;
      const completed = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
      expect(((await completed.json()) as { status: string }).status).toBe("COMPLETED");

      const prefix = `research/controlled_pilot/v1/jobs/${seeded.request.idempotency_key}`;
      const paperKey = `${prefix}/paper/1.json`;
      const raw = await seeded.env.STRUCTURED_BUCKET.get(paperKey);
      expect(raw).not.toBeNull();
      const body = JSON.parse(
        new TextDecoder().decode(new Uint8Array(await raw!.arrayBuffer())),
      ) as Record<string, unknown>;
      const semanticBody = body.semantic_body as Record<string, unknown>;
      semanticBody[field] = value;
      body.semantic_digest = await sha256Digest(canonicalJson(semanticBody));
      body.result_id = body.semantic_digest;
      const tamperedBytes = new TextEncoder().encode(JSON.stringify(body, null, 2));
      const tamperedDigest = await sha256Digest(tamperedBytes);
      await seeded.mem.put(paperKey, tamperedBytes);

      const manifestKey = `${prefix}/manifest.json`;
      const manifestObject = await seeded.env.STRUCTURED_BUCKET.get(manifestKey);
      const manifest = JSON.parse(
        new TextDecoder().decode(new Uint8Array(await manifestObject!.arrayBuffer())),
      ) as { children: Array<Record<string, unknown>> };
      manifest.children[0]!.persisted_byte_digest = tamperedDigest;
      manifest.children[0]!.size = tamperedBytes.byteLength;
      await seeded.mem.put(manifestKey, JSON.stringify(manifest, null, 2));

      const status = await controlledPilotStatus(seeded.env, seeded.request.idempotency_key);
      expect(((await status.json()) as { status: string }).status).not.toBe("COMPLETED");
    }
  });

  it("cancels budget on container error without a terminal success artifact", async () => {
    const errored = await seedEnv({ failContainer: "error" });
    const ctx = new WaitCtx();
    await submitControlledPilot(errored.env, errored.request, ctx);
    await ctx.pending;
    expect(errored.budget.cancelled).toBeGreaterThan(0);
    expect(errored.mem.putOrder.some((key) => key.endsWith("/manifest.json"))).toBe(false);
  });
});

describe("mass remains disabled for controlled readiness", () => {
  it("rejects unauthorized controlled execute", async () => {
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/controlled-pilot", {
        method: "POST",
        headers: { "content-type": "application/json", "X-Mass-Eval-Token": "wrong" },
        body: JSON.stringify({
          idempotency_key: "controlled-job-1",
          ready_attestation_id: "attestation-cloud-1",
          snapshot_id: fixtureKeys.logical_snapshot_id,
        }),
      }),
      { MASS_EVAL_TOKEN: "secret" } as Env,
      {},
    );
    expect(response.status).toBe(401);
  });
});

void CONTROLLED_READY_ENVELOPE_FORMAT;
void CONTROLLED_TRADER_BATCH_FORMAT;
void canonicalJson;


describe("canonical JSON and key windows", () => {
  it("emits UTF-8 rather than ASCII escapes", async () => {
    const encoded = canonicalJson({ x: "日本" });
    expect(encoded).toContain("日本");
    expect(encoded).not.toContain("\\u");
    const digest = await sha256Digest(encoded);
    expect(digest.startsWith("sha256:")).toBe(true);
  });

  it("rejects noncanonical timestamps and expired/future/revoked keys", () => {
    const base: registries.PinnedVerifyKey = {
      key_id: "k",
      public_key: new Uint8Array(32),
      algorithm: "Ed25519",
      status: "active",
      not_before: "2026-01-01T00:00:00Z",
      not_after: "2026-12-31T00:00:00Z",
      revoked_at: null,
      environment: "staging",
    };
    const mid = Date.UTC(2026, 5, 1);
    expect(registries.keyUsableAt(base, mid)).toBe(true);
    expect(registries.keyUsableAt({ ...base, not_before: "2026-09-01" }, mid)).toBe(false);
    expect(registries.keyUsableAt({ ...base, not_after: "2026-01-02T00:00:00Z" }, mid)).toBe(false);
    expect(registries.keyUsableAt({ ...base, not_before: "2026-09-01T00:00:00Z" }, mid)).toBe(false);
    expect(registries.keyUsableAt({ ...base, status: "revoked", revoked_at: "2026-02-01T00:00:00Z" }, mid)).toBe(false);
    expect(registries.keyUsableAt({ ...base, environment: "production" }, mid)).toBe(true);
  });
});
