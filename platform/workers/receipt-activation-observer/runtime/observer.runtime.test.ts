import { SELF } from "cloudflare:test";
import { describe, expect, it, vi } from "vitest";
import bindingManifest from "../../../../specs/cloudflare/active_worker_bindings.json";
import {
  canonicalDigest,
  canonicalJson,
  bytesToBase64,
} from "../../receipt-evidence-authority/src/canonical";
import {
  handleReceiptActivationObserverRequest,
  type ObserverEnv,
  type PremiumAuditEvidence,
} from "../src/observer";

const SHA = "1".repeat(40);
const CHALLENGE = "a".repeat(64);
const VERSION_ID = "10000000-0000-4000-8000-000000000004";

async function premiumEvidence(): Promise<PremiumAuditEvidence> {
  const attestation = {
    schema_version: "receipt-audit-recovery-attestation/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
  };
  const bytes = new TextEncoder().encode(canonicalJson(attestation));
  const body = {
    schema_version: "receipt-operator-audit-evidence/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    caller_source_sha: SHA,
    caller_worker_version_id: "10000000-0000-4000-8000-000000000003",
    caller_worker_version_tag: `ra-s-c-${SHA}`,
    d1_schema_digest: `sha256:${"b".repeat(64)}`,
    reservation_id: `sha256:${"c".repeat(64)}`,
    authority_operation_id: `sha256:${"d".repeat(64)}`,
    request_nonce: "e".repeat(64),
    signed_attestation_digest: await canonicalDigest(attestation),
    signed_attestation_json_utf8_base64: bytesToBase64(bytes),
    signed_attestation_json_utf8_length: bytes.length,
  };
  return { ...body, evidence_digest: await canonicalDigest(body) };
}

function context(access: unknown): ExecutionContext {
  return {
    access,
    waitUntil: vi.fn(),
    passThroughOnException: vi.fn(),
    props: {},
  } as unknown as ExecutionContext;
}

function request(suffix = `?challenge=${CHALLENGE}`): Request {
  return new Request(
    `https://observer.invalid/v1/receipt-authority/audit-evidence${suffix}`,
  );
}

function envWith(
  rpc: () => Promise<PremiumAuditEvidence>,
): ObserverEnv {
  return {
    ENVIRONMENT: "staging",
    CF_VERSION_METADATA: {
      id: VERSION_ID,
      tag: `rao-s-o-${SHA}`,
      timestamp: "2026-08-28T01:00:00.000Z",
    },
    PREMIUM_RECEIPT_OPERATOR: {
      staging_recovery_audit_evidence: rpc,
    },
  } as unknown as ObserverEnv;
}

describe("Receipt activation observer runtime boundary", () => {
  it("rejects runtime requests without a verified Access context", async () => {
    const response = await SELF.fetch(request());
    expect(response.status).toBe(403);
    expect(response.headers.get("content-type")).toBe(
      "application/json; charset=utf-8",
    );
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).not.toContain("<html");
  });

  it("rejects absent or malformed Access context before invoking Premium", async () => {
    const rpc = vi.fn(premiumEvidence);
    const environment = envWith(rpc);
    for (const access of [undefined, {}, { aud: "" }]) {
      const response = await handleReceiptActivationObserverRequest(
        request(), environment, context(access),
      );
      expect(response.status).toBe(403);
    }
    expect(rpc).not.toHaveBeenCalled();
  });

  it("accepts only the exact challenge request and invokes one no-arg read RPC", async () => {
    const rpc = vi.fn(premiumEvidence);
    const environment = envWith(rpc);
    const access = context({ aud: "receipt-observer-access-aud" });
    for (const candidate of [
      request("?challenge=ABC"),
      request(`?challenge=${CHALLENGE}&extra=1`),
      request(`?challenge=${CHALLENGE}&challenge=${CHALLENGE}`),
      new Request(request().url, { headers: { "content-length": "1" } }),
    ]) {
      expect((await handleReceiptActivationObserverRequest(
        candidate, environment, access,
      )).status).toBe(400);
    }
    expect(rpc).not.toHaveBeenCalled();

    const response = await handleReceiptActivationObserverRequest(
      request(), environment, access,
    );
    expect(response.status).toBe(200);
    expect(rpc).toHaveBeenCalledOnce();
    expect(rpc.mock.calls[0]).toEqual([]);
    expect(response.headers.get("pragma")).toBe("no-cache");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("location")).toBeNull();
    const exact = await response.text();
    expect(new TextEncoder().encode(exact).length).toBeLessThanOrEqual(64 * 1024);
    const document = JSON.parse(exact) as Record<string, unknown>;
    expect(canonicalJson(document)).toBe(exact);
    expect(document).toMatchObject({
      schema_version: "receipt-activation-observer-response/v1",
      eligibility: "AUDIT_ONLY",
      challenge: CHALLENGE,
      observer_source_sha: SHA,
      observer_worker_version_id: VERSION_ID,
      observer_worker_version_tag: `rao-s-o-${SHA}`,
      access_authenticated: true,
      access_aud: "receipt-observer-access-aud",
    });
    const { response_digest: supplied, ...body } = document;
    expect(supplied).toBe(await canonicalDigest(body));
  });

  it("rejects byte, digest, provenance, and oversize substitution", async () => {
    const valid = await premiumEvidence();
    const cases: PremiumAuditEvidence[] = [
      { ...valid, signed_attestation_json_utf8_length: 1 },
      { ...valid, evidence_digest: `sha256:${"0".repeat(64)}` },
      { ...valid, caller_worker_version_tag: `ra-s-c-${"2".repeat(40)}` },
      {
        ...valid,
        signed_attestation_json_utf8_length: 48 * 1024 + 1,
      },
    ];
    for (const evidence of cases) {
      const response = await handleReceiptActivationObserverRequest(
        request(), envWith(async () => evidence),
        context({ aud: "receipt-observer-access-aud" }),
      );
      expect(response.status).toBe(502);
    }
  });

  it("freezes no storage/secret/DO/named RPC binding and one staging service", () => {
    const worker = bindingManifest.workers["receipt-activation-observer"];
    for (const environment of ["base", "production"] as const) {
      const surface = worker[environment];
      expect(surface.workers_dev).toBe(false);
      expect(surface.routes).toEqual([]);
      expect(surface.route).toBeNull();
      expect(surface.services).toEqual([]);
      expect(surface.secret_names).toEqual([]);
      expect(surface.d1_databases).toEqual([]);
      expect(surface.r2_buckets).toEqual([]);
      expect(surface.kv_namespaces).toEqual([]);
      expect(surface.queue_producers).toEqual([]);
      expect(surface.queue_consumers).toEqual([]);
      expect(surface.durable_objects).toEqual([]);
      expect(surface.worker_entrypoints).toEqual([]);
      expect(surface.default_handler).toEqual({ fetch_reserved_special: true });
    }
    expect(worker.staging).toMatchObject({
      workers_dev: true,
      preview_urls: false,
      services: [{
        binding: "PREMIUM_RECEIPT_OPERATOR",
        service: "quant-platform-ingestion-premium-staging",
        entrypoint: "PremiumReceiptOperatorService",
      }],
      secret_names: [],
      worker_entrypoints: [],
      durable_object_class_handlers: [],
      default_handler: { fetch_reserved_special: true },
    });
  });
});
