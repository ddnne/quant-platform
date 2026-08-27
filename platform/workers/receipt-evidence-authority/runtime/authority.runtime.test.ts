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
import type {
  AcquisitionResponseMetadataV2,
} from "../../ingestion-secrets/src/jquants_acquisition_types";
import { canonicalDigest } from "../src/canonical";
import { ReceiptEvidenceAuthority } from "../src/authority_do";
import {
  unwrapEd25519PrivateKey,
  wrapEd25519PrivateKey,
} from "../src/key_crypto";
import { executeReceiptRequest } from "../src/reconcile";
import premiumWorker, {
  type Env as PremiumEnv,
} from "../../ingestion-premium/src/index";
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

function withAcquisition(
  transform?: (response: Response) => Promise<Response>,
): ReceiptAuthorityEnv {
  const binding = {
    fetch_governed_page: async (input: Parameters<typeof fetchGovernedPage>[0]) => {
      const response = await fetchGovernedPage(input, acquisitionEnv);
      return transform === undefined ? response : transform(response);
    },
  };
  return {
    ...runtimeEnv,
    JQUANTS_ACQUISITION: binding as unknown as ReceiptAuthorityEnv["JQUANTS_ACQUISITION"],
  };
}

function installSinglePageUpstream(
  body = '{"data":[{"Date":"2024-02-01","Open":1,"Close":2}],"pagination_key":null}',
): void {
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("x-api-key")).toBe(
      "jq-runtime-api-key-not-for-live",
    );
    return new Response(body, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
}

function nullHeader(value: string): string | null {
  return value === "NONE" ? null : value;
}

function integerHeader(value: string): number | null {
  return value === "NONE" ? null : Number(value);
}

function acquisitionMetadata(headers: Headers): AcquisitionResponseMetadataV2 {
  const get = (name: string): string => {
    const value = headers.get(name);
    if (value === null) throw new Error(`test acquisition header absent: ${name}`);
    return value;
  };
  return {
    schema_version: "jquants-acquisition-rpc-response-metadata/v2",
    evidence_state: get("x-quant-acquisition-evidence-state") as AcquisitionResponseMetadataV2["evidence_state"],
    environment: nullHeader(get("x-quant-acquisition-environment")) as AcquisitionResponseMetadataV2["environment"],
    dataset_id: nullHeader(get("x-quant-acquisition-dataset")),
    segment_id: nullHeader(get("x-quant-acquisition-segment")),
    segment_start: nullHeader(get("x-quant-acquisition-segment-start")),
    segment_end: nullHeader(get("x-quant-acquisition-segment-end")),
    request_digest: nullHeader(get("x-quant-acquisition-request-digest")),
    request_identity_digest: nullHeader(get("x-quant-acquisition-request-identity-digest")),
    previous_request_digest: nullHeader(get("x-quant-acquisition-previous-request-digest")),
    acquisition_id: nullHeader(get("x-quant-acquisition-acquisition-id")),
    acquisition_issued_at: nullHeader(get("x-quant-acquisition-acquisition-issued-at")),
    acquisition_expires_at: nullHeader(get("x-quant-acquisition-acquisition-expires-at")),
    target_registry_digest: nullHeader(get("x-quant-acquisition-registry-digest")),
    source_capability_digest: nullHeader(get("x-quant-acquisition-source-capability-digest")),
    dataset_contract_digest: nullHeader(get("x-quant-acquisition-dataset-contract-digest")),
    coverage_policy_digest: nullHeader(get("x-quant-acquisition-coverage-policy-digest")),
    query_contract_digest: nullHeader(get("x-quant-acquisition-query-contract-digest")),
    cursor_key_id: nullHeader(get("x-quant-acquisition-cursor-key-id")),
    slice_date: nullHeader(get("x-quant-acquisition-slice-date")),
    query_digest: nullHeader(get("x-quant-acquisition-query-digest")),
    page_ordinal: integerHeader(get("x-quant-acquisition-page-ordinal")),
    slice_ordinal: integerHeader(get("x-quant-acquisition-slice-ordinal")),
    provider_page_ordinal: integerHeader(get("x-quant-acquisition-provider-page-ordinal")),
    provider_pagination_state: get("x-quant-acquisition-provider-pagination-state") as AcquisitionResponseMetadataV2["provider_pagination_state"],
    upstream_http_status: integerHeader(get("x-quant-acquisition-upstream-status")),
    body_digest: get("x-quant-acquisition-body-digest"),
    body_kind: get("x-quant-acquisition-body-kind") as AcquisitionResponseMetadataV2["body_kind"],
    pagination_state: get("x-quant-acquisition-pagination-state") as AcquisitionResponseMetadataV2["pagination_state"],
    continuation_token: nullHeader(get("x-quant-acquisition-continuation")),
    content_type: get("content-type") as AcquisitionResponseMetadataV2["content_type"],
    redirect_count: Number(get("x-quant-acquisition-redirect-count")),
    previous_chain_digest: nullHeader(get("x-quant-acquisition-previous-chain-digest")),
    chain_digest: nullHeader(get("x-quant-acquisition-chain-digest")),
  };
}

async function forgeSegmentExhaustion(response: Response): Promise<Response> {
  const body = await response.arrayBuffer();
  const headers = new Headers(response.headers);
  headers.set("x-quant-acquisition-pagination-state", "EXHAUSTED");
  headers.set("x-quant-acquisition-continuation", "NONE");
  const metadata = acquisitionMetadata(headers);
  metadata.chain_digest = await canonicalDigest({
    schema_version: "jquants-acquisition-chain-link/v2",
    acquisition_id: metadata.acquisition_id,
    cursor_key_id: metadata.cursor_key_id,
    acquisition_issued_at: metadata.acquisition_issued_at,
    acquisition_expires_at: metadata.acquisition_expires_at,
    request_digest: metadata.request_digest,
    request_identity_digest: metadata.request_identity_digest,
    previous_request_digest: metadata.previous_request_digest,
    previous_chain_digest: metadata.previous_chain_digest,
    page_ordinal: metadata.page_ordinal,
    slice_date: metadata.slice_date,
    slice_ordinal: metadata.slice_ordinal,
    provider_page_ordinal: metadata.provider_page_ordinal,
    query_digest: metadata.query_digest,
    body_digest: metadata.body_digest,
    upstream_http_status: metadata.upstream_http_status,
    evidence_state: metadata.evidence_state,
    provider_pagination_state: metadata.provider_pagination_state,
    pagination_state: metadata.pagination_state,
  });
  headers.set("x-quant-acquisition-chain-digest", metadata.chain_digest);
  headers.set(
    "x-quant-acquisition-metadata-digest",
    await canonicalDigest(metadata),
  );
  return new Response(body, { status: response.status, headers });
}

function decodeBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

async function activateRegisteredTestKey(): Promise<{
  stub: ReturnType<typeof runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName>;
  registration: Awaited<ReturnType<ReceiptEvidenceAuthority["public_key_registration"]>>;
}> {
  const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
    "receipt:production",
  );
  const registration = await stub.public_key_registration();
  await runInDurableObject(stub, async (instance) => {
    const internal = instance as unknown as { env: ReceiptAuthorityEnv };
    internal.env.ACTIVATED_KEY_ID = registration.key_id;
  });
  return { stub, registration };
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
    const { stub, registration } = await activateRegisteredTestKey();
    await expect(executeReceiptRequest(
      authorityEnv,
      request,
      { crashAfterIssueBeforeFinalize: true },
    )).rejects.toThrow("injected crash after issue before finalize");

    const operationId = await canonicalDigest(request);
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
      await expect(state.storage.put(
        "unsupported-direct-cryptokey",
        operational.privateKey,
      )).rejects.toThrow(/Could not serialize.*CryptoKey/);
      expect(await state.storage.get("unsupported-direct-cryptokey"))
        .toBeUndefined();
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

    await expect(executeReceiptRequest({
      ...withAcquisition(),
      AUTHORITY_MODE: "ACTIVE_TEST" as never,
    }, {
      ...request,
      request_nonce: "d".repeat(64),
    })).rejects.toThrow("PENDING activation");
  });

  it("rejects a forged terminal header while immutable raw has a provider cursor", async () => {
    installSinglePageUpstream('{"data":[],"pagination_key":"page-2"}');
    await expect(executeReceiptRequest(
      withAcquisition(forgeSegmentExhaustion),
      { ...request, request_nonce: "e".repeat(64) },
    )).rejects.toThrow("provider continuation cannot terminate the segment");
  });

  it("rejects a forged terminal header before the final deterministic slice", async () => {
    installSinglePageUpstream('{"data":[],"pagination_key":null}');
    await expect(executeReceiptRequest(
      withAcquisition(forgeSegmentExhaustion),
      {
        ...request,
        dataset_id: "fins_summary",
        request_nonce: "f".repeat(64),
      },
    )).rejects.toThrow("sliced acquisition terminated before the final date");
  });

  it("makes reconciled rows, committed receipts, and authority history append-only", async () => {
    const { stub } = await activateRegisteredTestKey();
    const result = await executeReceiptRequest(withAcquisition(), {
      ...request,
      request_nonce: "9".repeat(64),
    });
    const operation = await runtimeEnv.DB.prepare(
      `SELECT run_id FROM receipt_authority_operations WHERE operation_id=?`,
    ).bind(result.operation_id).first<{ run_id: number }>();
    expect(operation).not.toBeNull();

    await expect(runtimeEnv.DB.prepare(
      `UPDATE receipt_authority_structured_rows SET payload='{}'
        WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `DELETE FROM receipt_authority_structured_rows WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `UPDATE receipt_authority_operations SET dataset='substituted'
        WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("immutable");
    await expect(runtimeEnv.DB.prepare(
      `DELETE FROM receipt_authority_operations WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `UPDATE collection_receipts SET checked_at='2000-01-01T00:00:00.000Z'
        WHERE run_id=?`,
    ).bind(operation!.run_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `DELETE FROM collection_receipts WHERE run_id=?`,
    ).bind(operation!.run_id).run()).rejects.toThrow("append-only");

    await expect(runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        "UPDATE authority_events SET event_type='SUBSTITUTED' WHERE sequence=1",
      );
    })).rejects.toThrow("append-only");
    await expect(runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        "DELETE FROM authority_operations WHERE operation_id=?",
        result.operation_id,
      );
    })).rejects.toThrow("append-only");
    await expect(runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        "UPDATE authority_key_metadata SET key_id='substituted' WHERE key_generation=1",
      );
    })).rejects.toThrow("append-only");
  });

  it("executes the authenticated Premium route through the live typed RPC export", async () => {
    await activateRegisteredTestKey();
    const acquisition = withAcquisition().JQUANTS_ACQUISITION;
    (runtimeEnv as unknown as Record<string, unknown>).JQUANTS_ACQUISITION =
      acquisition;
    const rpc = workerExports.default as unknown as ReceiptEvidenceAuthorityRpc;
    const premiumEnv = {
      ...runtimeEnv,
      RECEIPT_AUTHORITY_ENVIRONMENT: "production",
      INGESTION_RUN_TOKEN: "workerd-premium-receipt-route-token",
      JQUANTS_API_KEY: "unused-by-receipt-route",
      RECEIPT_EVIDENCE_AUTHORITY: rpc,
    } as unknown as PremiumEnv;
    const registrationResponse = await premiumWorker.fetch(new Request(
      "https://premium.invalid/v1/admin/receipt-evidence/public-key-registration",
      {
        method: "POST",
        headers: {
          "x-ingestion-token": "workerd-premium-receipt-route-token",
        },
      },
    ), premiumEnv);
    expect(registrationResponse.status).toBe(200);
    expect(await registrationResponse.json<Record<string, unknown>>()).toMatchObject({
      ok: true,
      registration: {
        authority_status: "PENDING",
        algorithm: "Ed25519",
        private_key_extractable: false,
        status: "pending",
      },
    });
    const response = await premiumWorker.fetch(new Request(
      "https://premium.invalid/v1/admin/receipt-evidence/reconcile" +
        "?dataset=indices_bars_daily_topix&segment=2024-02",
      {
        method: "POST",
        headers: {
          "x-ingestion-token": "workerd-premium-receipt-route-token",
        },
      },
    ), premiumEnv);
    expect(response.status).toBe(200);
    const payload = await response.json<Record<string, unknown>>();
    expect(payload).toMatchObject({ ok: true, state: "FINALIZED" });
    expect(payload).not.toHaveProperty("receipt");
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM receipt_authority_requests
        WHERE operation_id=? AND state='FINALIZED'`,
    ).bind(payload.operation_id).first<{ count: number }>()).toEqual({ count: 1 });
    await expect(runtimeEnv.DB.prepare(
      `UPDATE receipt_authority_requests SET dataset='substituted'
        WHERE operation_id=?`,
    ).bind(payload.operation_id).run()).rejects.toThrow("monotonic");
    await expect(runtimeEnv.DB.prepare(
      `DELETE FROM receipt_authority_requests WHERE operation_id=?`,
    ).bind(payload.operation_id).run()).rejects.toThrow("append-only");
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
      internal.env.AUTHORITY_MODE = "PENDING";
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
