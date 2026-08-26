import { env, exports as workerExports } from "cloudflare:workers";
import {
  applyD1Migrations,
  evictDurableObject,
  reset,
  runInDurableObject,
} from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, inject, it } from "vitest";
import {
  fetchGovernedPage,
  type AcquisitionEnv,
} from "../../ingestion-secrets/src/jquants_acquisition";
import { canonicalDigest } from "../src/canonical";
import { ReceiptEvidenceAuthority } from "../src/authority_do";
import {
  unwrapEd25519PrivateKey,
  wrapEd25519PrivateKey,
} from "../src/key_crypto";
import { executeReceiptRequest } from "../src/reconcile";
import type {
  ReceiptAuthorityEnv,
  ReceiptEvidenceAuthorityRpc,
  ReceiptIssueRequestV1,
  UnsignedReceiptClaimsV2,
} from "../src/types";

const runtimeEnv = env as ReceiptAuthorityEnv;
const migrations = inject<Array<{ name: string; queries: string[] }>>(
  "receiptD1Migrations",
);
const originalFetch = globalThis.fetch;

const request: ReceiptIssueRequestV1 = {
  schema_version: "receipt-evidence-issue-request/v1",
  operation: "issue_for_segment",
  environment: "production",
  dataset_id: "indices_bars_daily_topix",
  segment_id: "2024-02",
  request_nonce: "a".repeat(64),
};

const acquisitionEnv: AcquisitionEnv = {
  ENVIRONMENT: "production",
  JQUANTS_API_KEY: "jq-runtime-api-key-not-for-live",
  JQUANTS_RPC_CURSOR_HMAC_KEY:
    "jq-runtime-cursor-hmac-key-not-for-live-00000000000000000000000000000000",
  PROXY_RATE_LIMITER: {
    limit: async () => ({ success: true }),
  },
};

function withAcquisition(): ReceiptAuthorityEnv {
  const binding = {
    fetch_governed_page: (input: Parameters<typeof fetchGovernedPage>[0]) =>
      fetchGovernedPage(input, acquisitionEnv),
  };
  return {
    ...runtimeEnv,
    JQUANTS_ACQUISITION: binding as unknown as ReceiptAuthorityEnv["JQUANTS_ACQUISITION"],
  };
}

function installSinglePageUpstream(): void {
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("x-api-key")).toBe(
      "jq-runtime-api-key-not-for-live",
    );
    return new Response(
      '{"data":[{"Date":"2024-02-01","Open":1,"Close":2}],"pagination_key":null}',
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
}

function decodeBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

beforeEach(async () => {
  await reset();
  await applyD1Migrations(runtimeEnv.DB, migrations);
  installSinglePageUpstream();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("Receipt Evidence Authority in workerd", () => {
  it("has no public HTTP surface and exposes only typed service RPC", async () => {
    const rpc = workerExports.default as unknown as ReceiptEvidenceAuthorityRpc & Fetcher;
    const response = await rpc.fetch(new Request("https://authority.invalid/health"));
    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).toBe("");

    const registration = await rpc.public_key_registration();
    expect(registration).toMatchObject({
      schema_version: "receipt-public-key-registration/v1",
      purpose: "receipt_verification",
      environment: "production",
      authority_status: "PENDING",
      algorithm: "Ed25519",
      private_key_extractable: false,
      status: "pending",
    });
    expect(registration.registration_digest).toBe(
      await canonicalDigest({
        schema_version: registration.schema_version,
        purpose: registration.purpose,
        environment: registration.environment,
        authority_status: registration.authority_status,
        key_id: registration.key_id,
        key_generation: registration.key_generation,
        algorithm: registration.algorithm,
        public_key_base64: registration.public_key_base64,
        private_key_extractable: registration.private_key_extractable,
        status: registration.status,
        generated_at: registration.generated_at,
      }),
    );
  });

  it("recovers an issued envelope after eviction and rejects claims replay", async () => {
    const authorityEnv = withAcquisition();
    await expect(executeReceiptRequest(
      authorityEnv,
      request,
      { crashAfterIssueBeforeFinalize: true },
    )).rejects.toThrow("injected crash after issue before finalize");

    const operationId = await canonicalDigest(request);
    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:production",
    );
    const pending = await stub.recover_operation(operationId, operationId);
    expect(pending.state).toBe("ISSUED_PENDING_FINALIZE");
    expect(pending.envelope).not.toBeNull();
    expect(pending.claims).not.toBeNull();

    const substituted = {
      ...pending.claims!,
      observed_items: pending.claims!.observed_items + 1,
    } satisfies UnsignedReceiptClaimsV2;
    await expect(runInDurableObject(stub, async (instance) =>
      instance.append_issued(operationId, operationId, substituted)
    )).rejects.toThrow("claims replay was substituted");

    const registration = await stub.public_key_registration();
    await runInDurableObject(stub, async (
      _instance: ReceiptEvidenceAuthority,
      state,
    ) => {
      const wrapped = state.storage.sql.exec<{
        wrap_algorithm: string;
        wrapped_private_key_base64: string;
      }>(
        `SELECT wrap_algorithm,wrapped_private_key_base64
           FROM authority_key_metadata WHERE key_generation=1`,
      ).one();
      expect(wrapped.wrap_algorithm).toBe("AES-GCM");
      expect(wrapped.wrapped_private_key_base64.length).toBeGreaterThan(64);
      const operational = await (
        _instance as unknown as {
          ensureKey(): Promise<{ privateKey: CryptoKey }>;
        }
      ).ensureKey();
      expect(operational.privateKey.type).toBe("private");
      expect(operational.privateKey.extractable).toBe(false);
      await expect(
        crypto.subtle.exportKey("pkcs8", operational.privateKey),
      ).rejects.toThrow();
    });
    await evictDurableObject(stub);

    const afterEvictionRegistration = await stub.public_key_registration();
    expect(afterEvictionRegistration.key_id).toBe(registration.key_id);
    expect(afterEvictionRegistration.public_key_base64).toBe(
      registration.public_key_base64,
    );

    const recovered = await executeReceiptRequest(authorityEnv, {
      ...request,
      operation: "recover_issue",
    });
    expect(recovered).toMatchObject({
      operation_id: operationId,
      state: "FINALIZED",
      replayed: true,
    });
    expect(recovered.receipt.digests).toEqual(pending.envelope);

    const publicKey = await crypto.subtle.importKey(
      "raw",
      decodeBase64(registration.public_key_base64),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const signature = decodeBase64(
      recovered.receipt.digests.signature.replace(/^ed25519:/, ""),
    );
    expect(await crypto.subtle.verify(
      "Ed25519",
      publicKey,
      signature,
      decodeBase64(recovered.receipt.digests.signed_body_b64),
    )).toBe(true);

    const replay = await executeReceiptRequest(authorityEnv, request);
    expect(replay.replayed).toBe(true);
    expect(replay.receipt_digest).toBe(recovered.receipt_digest);
    expect(replay.receipt).toEqual(recovered.receipt);
  });

  it("rejects operation identity substitution and never signs in PENDING mode", async () => {
    const operationId = await canonicalDigest(request);
    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:production",
    );
    await stub.begin_operation(operationId, operationId);
    await expect(runInDurableObject(stub, async (instance) =>
      instance.begin_operation(operationId, `sha256:${"f".repeat(64)}`)
    )).rejects.toThrow("operation identity must equal the request digest");

    await expect(executeReceiptRequest({
      ...withAcquisition(),
      AUTHORITY_MODE: "PENDING",
    }, {
      ...request,
      request_nonce: "b".repeat(64),
    })).rejects.toThrow("PENDING activation");
    const receiptCount = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM collection_receipts",
    ).first<{ count: number }>();
    expect(receiptCount?.count).toBe(0);
  });

  it("authenticates the wrap key, AAD, ciphertext, and key generation", async () => {
    const pair = await crypto.subtle.generateKey(
      { name: "Ed25519" },
      true,
      ["sign", "verify"],
    );
    const secret = "1".repeat(64);
    const aad = '{"authority":"receipt","environment":"production","generation":1}';
    const wrapped = await wrapEd25519PrivateKey({
      privateKey: pair.privateKey,
      wrappingSecret: secret,
      aad,
    });
    const operational = await unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: secret,
      aad,
    });
    expect(operational.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("pkcs8", operational)).rejects.toThrow();
    await expect(unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: "2".repeat(64),
      aad,
    })).rejects.toThrow("authenticated unwrap");
    await expect(unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: secret,
      aad: `${aad}-substituted`,
    })).rejects.toThrow("authenticated unwrap");
    const changed = `${wrapped.wrapped_private_key_base64[0] === "A" ? "B" : "A"}${wrapped.wrapped_private_key_base64.slice(1)}`;
    await expect(unwrapEd25519PrivateKey({
      wrapped: { ...wrapped, wrapped_private_key_base64: changed },
      wrappingSecret: secret,
      aad,
    })).rejects.toThrow("authenticated unwrap");

    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:production",
    );
    const first = await stub.public_key_registration();
    const rotated = await runInDurableObject(stub, async (instance) => {
      const internal = instance as unknown as {
        env: ReceiptAuthorityEnv;
        keyPromise: null;
      };
      internal.env.RECEIPT_KEY_GENERATION = "2";
      internal.keyPromise = null;
      return instance.public_key_registration();
    });
    expect(rotated.key_generation).toBe(2);
    expect(rotated.key_id).not.toBe(first.key_id);
    const repeated = await runInDurableObject(stub, async (instance) => {
      const internal = instance as unknown as { keyPromise: null };
      internal.keyPromise = null;
      return instance.public_key_registration();
    });
    expect(repeated).toEqual(rotated);
    const keyRows = await runInDurableObject(stub, async (_instance, state) =>
      state.storage.sql.exec<{ key_generation: number }>(
        "SELECT key_generation FROM authority_key_metadata ORDER BY key_generation",
      ).toArray()
    );
    expect(keyRows.map((row) => row.key_generation)).toEqual([1, 2]);
  });
});
