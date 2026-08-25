import { env } from "cloudflare:workers";
import {
  applyD1Migrations,
  createExecutionContext,
  reset,
} from "cloudflare:test";
import { beforeEach, describe, expect, inject, it, vi } from "vitest";

import { callOpsTool } from "../src/domain.js";
import {
  githubHandler,
  signState,
  verifyState,
} from "../src/github-handler.js";
import { canonicalProjectionBytes } from "../src/projection_signature.js";

const projectionMigrations = inject("opsProjectionD1Migrations");
const quotaMigrations = inject("opsQuotaD1Migrations");

beforeEach(async () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  await reset();
  await applyD1Migrations(env.OPS_PROJECTION_DB, projectionMigrations);
  await applyD1Migrations(env.QUOTA_DB, quotaMigrations);
});

function base64(bytes) {
  let binary = "";
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function digest(character) {
  return `sha256:${character.repeat(64)}`;
}

async function projectionSigner() {
  const keys = await crypto.subtle.generateKey(
    { name: "Ed25519" },
    true,
    ["sign", "verify"],
  );
  const keyId = "ops-runtime-ed25519-v1";
  const publicKey = await crypto.subtle.exportKey("raw", keys.publicKey);
  return {
    keys,
    keyId,
    registry: {
      schema_version: 1,
      keys: [{
        key_id: keyId,
        algorithm: "Ed25519",
        status: "active",
        public_key_base64: base64(publicKey),
      }],
    },
  };
}

async function seedSignedGeneration(signer, generationId, marker) {
  const generatedAt = "2026-08-25T06:00:00.000Z";
  const envelope = {
    schema_version: "ops-projection-envelope/v1",
    generation_id: generationId,
    content_digest: digest(marker),
    source_db_digest: digest("2"),
    generated_at: generatedAt,
    producer_commit_sha: "a".repeat(40),
    contract_digest: digest("3"),
    registry_digest: digest("4"),
    coverage_policy_version: "collection-coverage/v3",
    projection_status: "FRESH",
    source_generation: 11,
    source_snapshot_generation: 11,
    source_cursor: 11,
    export_cursor: 11,
    applied_cursor: 11,
    coverage_status_digest: digest("5"),
    dataset_coverage: {},
    b0_status: "PASS",
    b0_evidence_digest: digest("6"),
    b4_status: "PASS",
    b4_evidence_digest: digest("7"),
    evidence_digests: { coverage: digest("5") },
    row_counts: { ops_storage_plane_status: 1 },
  };
  const unsigned = {
    schema_version: "ops-projection-signed-envelope/v1",
    algorithm: "Ed25519",
    issuer_key_id: signer.keyId,
    envelope,
  };
  const rawSignature = await crypto.subtle.sign(
    { name: "Ed25519" },
    signer.keys.privateKey,
    canonicalProjectionBytes(unsigned),
  );
  const signature = `ed25519:${base64(rawSignature)}`;
  const document = { ...unsigned, signature };

  await env.OPS_PROJECTION_DB.prepare(
    `INSERT INTO ops_projection_generation
       (generation_id,status,source_db_digest,content_digest,generated_at,
        producer_commit_sha,contract_digest,registry_digest,coverage_policy_version,
        sealed_at,signed_envelope_json,issuer_key_id,signature,detail_json)
     VALUES (?, 'SEALED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')`,
  ).bind(
    generationId,
    envelope.source_db_digest,
    envelope.content_digest,
    generatedAt,
    envelope.producer_commit_sha,
    envelope.contract_digest,
    envelope.registry_digest,
    envelope.coverage_policy_version,
    generatedAt,
    JSON.stringify(document),
    signer.keyId,
    signature,
  ).run();
  await env.OPS_PROJECTION_DB.prepare(
    `INSERT INTO ops_storage_plane_status
       (projection_generation_id, materialized_at, payload_json)
     VALUES (?, ?, ?)`,
  ).bind(
    generationId,
    generatedAt,
    JSON.stringify({ schema: "ops-storage/runtime-v1", marker }),
  ).run();
}

async function activate(generationId) {
  await env.OPS_PROJECTION_DB.prepare(
    `INSERT INTO ops_projection_active (singleton,generation_id,activated_at)
     VALUES (1,?,?)
     ON CONFLICT(singleton) DO UPDATE SET
       generation_id=excluded.generation_id,
       activated_at=excluded.activated_at`,
  ).bind(generationId, "2026-08-25T06:01:00.000Z").run();
}

describe("Ops Projection in the Workers runtime", () => {
  it("reads only the signed generation selected by the pointer", async () => {
    const signer = await projectionSigner();
    await seedSignedGeneration(signer, "runtime-old", "8");
    await seedSignedGeneration(signer, "runtime-current", "9");
    await activate("runtime-current");

    const value = await callOpsTool(
      env.OPS_PROJECTION_DB,
      "storage_plane_status",
      {},
      { projectionPublicKeyRegistry: signer.registry },
    );
    expect(value).toMatchObject({
      status: "AVAILABLE",
      mutable: false,
      projection_generation: "runtime-current",
      projection_signature_verified: true,
      marker: "9",
    });
  });

  it("fails closed when the active generation signature is tampered", async () => {
    const signer = await projectionSigner();
    await seedSignedGeneration(signer, "runtime-tampered", "a");
    await activate("runtime-tampered");
    const row = await env.OPS_PROJECTION_DB.prepare(
      `SELECT signed_envelope_json FROM ops_projection_generation
        WHERE generation_id='runtime-tampered'`,
    ).first();
    const document = JSON.parse(row.signed_envelope_json);
    document.envelope.applied_cursor = 10;
    await env.OPS_PROJECTION_DB.prepare(
      `UPDATE ops_projection_generation SET signed_envelope_json=?
        WHERE generation_id='runtime-tampered'`,
    ).bind(JSON.stringify(document)).run();

    const value = await callOpsTool(
      env.OPS_PROJECTION_DB,
      "storage_plane_status",
      {},
      { projectionPublicKeyRegistry: signer.registry },
    );
    expect(value).toMatchObject({
      status: "NOT_PROJECTED",
      projection_generation: "runtime-tampered",
    });
    expect(value.reason).toContain("signature is invalid");
  });
});

describe("GitHub OAuth boundary in the Workers runtime", () => {
  const oauthRequest = {
    responseType: "code",
    clientId: "runtime-client",
    redirectUri: "https://client.test/oauth/callback",
    scope: ["quant.read.ops"],
    state: "client-state",
    codeChallenge: "runtime-challenge",
    codeChallengeMethod: "S256",
  };

  function handlerEnv(overrides = {}) {
    return {
      GITHUB_CLIENT_ID: "runtime-github-client",
      GITHUB_CLIENT_SECRET: "runtime-github-secret",
      STATE_SECRET: "runtime-state-secret",
      ALLOWED_LOGIN: "ddnne",
      OAUTH_PROVIDER: {
        parseAuthRequest: vi.fn(async () => oauthRequest),
        completeAuthorization: vi.fn(async () => ({
          redirectTo: "https://client.test/oauth/callback?code=issued",
        })),
      },
      ...overrides,
    };
  }

  it("starts authorization with an integrity-bound state", async () => {
    const runtimeEnv = handlerEnv();
    const ctx = createExecutionContext();
    const response = await githubHandler.fetch(
      new Request("https://ops.test/authorize"),
      runtimeEnv,
      ctx,
    );
    expect(response.status).toBe(302);
    const redirect = new URL(response.headers.get("location"));
    expect(redirect.origin + redirect.pathname).toBe(
      "https://github.com/login/oauth/authorize",
    );
    expect(redirect.searchParams.get("client_id")).toBe(
      "runtime-github-client",
    );
    await expect(
      verifyState(
        redirect.searchParams.get("state"),
        "runtime-state-secret",
      ),
    ).resolves.toEqual(oauthRequest);
  });

  it("rejects a tampered callback state before provider or network I/O", async () => {
    const runtimeEnv = handlerEnv();
    const network = vi.fn();
    vi.stubGlobal("fetch", network);
    const state = await signState(oauthRequest, "runtime-state-secret");
    const tampered = `${state.slice(0, -4)}xxxx`;
    const response = await githubHandler.fetch(
      new Request(
        `https://ops.test/callback?code=github-code&state=${tampered}`,
      ),
      runtimeEnv,
      createExecutionContext(),
    );
    expect(response.status).toBe(400);
    expect(await response.text()).toBe("invalid state");
    expect(network).not.toHaveBeenCalled();
    expect(runtimeEnv.OAUTH_PROVIDER.completeAuthorization).not.toHaveBeenCalled();
  });

  it("grants the closed scope only to the configured GitHub login", async () => {
    const runtimeEnv = handlerEnv();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(Response.json({ access_token: "github-token" }))
      .mockResolvedValueOnce(Response.json({ login: "ddnne", name: "Taku" })));
    const state = await signState(oauthRequest, "runtime-state-secret");
    const response = await githubHandler.fetch(
      new Request(`https://ops.test/callback?code=github-code&state=${state}`),
      runtimeEnv,
      createExecutionContext(),
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "https://client.test/oauth/callback?code=issued",
    );
    expect(runtimeEnv.OAUTH_PROVIDER.completeAuthorization).toHaveBeenCalledWith({
      request: oauthRequest,
      userId: "ddnne",
      metadata: { label: "ddnne" },
      scope: ["quant.read.ops"],
      props: { login: "ddnne", name: "Taku" },
    });
  });

  it("denies a valid GitHub callback for every other login", async () => {
    const runtimeEnv = handlerEnv();
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(Response.json({ access_token: "github-token" }))
      .mockResolvedValueOnce(Response.json({ login: "intruder" })));
    const state = await signState(oauthRequest, "runtime-state-secret");
    const response = await githubHandler.fetch(
      new Request(`https://ops.test/callback?code=github-code&state=${state}`),
      runtimeEnv,
      createExecutionContext(),
    );
    expect(response.status).toBe(403);
    expect(await response.text()).toContain("is not allowed");
    expect(runtimeEnv.OAUTH_PROVIDER.completeAuthorization).not.toHaveBeenCalled();
  });
});
