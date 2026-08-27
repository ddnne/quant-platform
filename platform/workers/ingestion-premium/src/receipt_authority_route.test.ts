import { describe, expect, it, vi } from "vitest";
import worker, {
  PremiumReceiptOperatorService,
  type Env,
} from "./index";
import {
  base64ToBytes,
  canonicalDigest,
  sha256Digest,
} from "../../receipt-evidence-authority/src/canonical";

const SHA = "1".repeat(40);
const RECEIPT_PATHS = [
  "/v1/admin/receipt-evidence/reconcile",
  "/v1/admin/receipt-evidence/recover",
  "/v1/admin/receipt-evidence/public-key-registration",
] as const;

function registrationEnv(overrides: Partial<Env> = {}): Env {
  return {
    RECEIPT_AUTHORITY_ENVIRONMENT: "staging",
    CF_VERSION_METADATA: {
      id: "10000000-0000-4000-8000-000000000003",
      tag: `rp-s-c-${SHA}`,
      timestamp: "2026-08-27T08:00:00.000Z",
    },
    RECEIPT_EVIDENCE_AUTHORITY: {
      issue_for_segment: vi.fn(),
      recover_issue: vi.fn(),
      begin_audit_recovery_canary: vi.fn(),
      recover_audit_recovery_canary: vi.fn(),
      public_key_registration: vi.fn(async () => {
        const publicKeyBase64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
        const keyDigest = await sha256Digest(base64ToBytes(publicKeyBase64));
        const keyId = `receipt-staging-${keyDigest.slice(7, 23)}`;
        const operationBody = {
          schema_version: "receipt-registration-operation/v1",
          authority: "receipt-evidence-authority",
          action: "public_key_registration",
          environment: "staging",
          authority_resource_digest: `sha256:${"a".repeat(64)}`,
          deployment_source_sha: SHA,
          authority_worker_version_id:
            "10000000-0000-4000-8000-000000000002",
          authority_worker_version_tag: `rp-s-r-${SHA}`,
          key_id: keyId,
          key_generation: 1,
          generated_at: "2026-08-27T08:00:00.000Z",
        } as const;
        const body = {
        schema_version: "receipt-public-key-registration/v1" as const,
        purpose: "receipt_verification" as const,
        environment: "staging" as const,
        authority_instance_digest: `sha256:${"a".repeat(64)}`,
        authority_resource_digest: `sha256:${"a".repeat(64)}`,
        authority_status: "PENDING" as const,
        action: "public_key_registration" as const,
        deployment_source_sha: SHA,
        authority_worker_version_id:
          "10000000-0000-4000-8000-000000000002",
        authority_worker_version_tag: `rp-s-r-${SHA}`,
        operation_binding_digest: await canonicalDigest(operationBody),
        key_id: keyId,
        key_generation: 1,
        algorithm: "Ed25519" as const,
        public_key_base64: publicKeyBase64,
        private_key_extractable: false as const,
        status: "pending" as const,
        generated_at: "2026-08-27T08:00:00.000Z",
        };
        return {
          ...body,
          registration_digest: await canonicalDigest(body),
        };
      }),
    },
    ...overrides,
  } as unknown as Env;
}

function operator(env: Env): PremiumReceiptOperatorService {
  return new PremiumReceiptOperatorService(
    {} as ExecutionContext,
    env,
  );
}

async function bindRegistrationDigests(
  input: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const body = { ...input };
  delete body.registration_digest;
  body.operation_binding_digest = await canonicalDigest({
    schema_version: "receipt-registration-operation/v1",
    authority: "receipt-evidence-authority",
    action: "public_key_registration",
    environment: body.environment,
    authority_resource_digest: body.authority_resource_digest,
    deployment_source_sha: body.deployment_source_sha,
    authority_worker_version_id: body.authority_worker_version_id,
    authority_worker_version_tag: body.authority_worker_version_tag,
    key_id: body.key_id,
    key_generation: body.key_generation,
    generated_at: body.generated_at,
  });
  return { ...body, registration_digest: await canonicalDigest(body) };
}

describe("Receipt positive-operation boundary", () => {
  it.each(RECEIPT_PATHS)(
    "does not dispatch the former bearer-token route %s",
    async (path) => {
      const env = registrationEnv({
        INGESTION_RUN_TOKEN: "ambient-token-must-not-authorize-receipts",
      });
      const response = await worker.fetch(new Request(
        `https://premium.invalid${path}?dataset=markets_calendar&segment=2024-02`,
        {
          method: "POST",
          headers: { "x-ingestion-token": env.INGESTION_RUN_TOKEN! },
          body: JSON.stringify({
            raw_count: 1,
            structured_digest: `sha256:${"0".repeat(64)}`,
            go_override: true,
          }),
        },
      ), env);
      expect(response.status).toBe(404);
      expect(env.RECEIPT_EVIDENCE_AUTHORITY.issue_for_segment)
        .not.toHaveBeenCalled();
      expect(env.RECEIPT_EVIDENCE_AUTHORITY.recover_issue)
        .not.toHaveBeenCalled();
      expect(env.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration)
        .not.toHaveBeenCalled();
    },
  );

  it("exports only an argument-free, PENDING registration operator method", async () => {
    const env = registrationEnv();
    const result = await operator(env).pending_public_key_registration();
    expect(result).toMatchObject({
      schema_version: "receipt-operator-registration/v1",
      authority: "receipt-evidence-authority",
      action: "public_key_registration",
      environment: "staging",
      caller_worker_version_id: "10000000-0000-4000-8000-000000000003",
      caller_worker_version_tag: `rp-s-c-${SHA}`,
      registration: {
        authority_status: "PENDING",
        action: "public_key_registration",
        deployment_source_sha: SHA,
        environment: "staging",
        operation_binding_digest: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
        private_key_extractable: false,
        status: "pending",
      },
    });
    expect(env.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration)
      .toHaveBeenCalledOnce();
    expect(env.RECEIPT_EVIDENCE_AUTHORITY.issue_for_segment)
      .not.toHaveBeenCalled();
    expect(env.RECEIPT_EVIDENCE_AUTHORITY.recover_issue)
      .not.toHaveBeenCalled();
    expect(
      Reflect.ownKeys(PremiumReceiptOperatorService.prototype)
        .map((key) => String(key))
        .filter((key) => key !== "constructor")
        .sort(),
    ).toEqual(["pending_public_key_registration"]);
  });

  it("rejects deployment or registration provenance drift fail-closed", async () => {
    await expect(operator(registrationEnv({
      CF_VERSION_METADATA: {
        id: "10000000-0000-4000-8000-000000000003",
        tag: `rp-p-c-${SHA}`,
        timestamp: "2026-08-27T08:00:00.000Z",
      },
    })).pending_public_key_registration()).rejects.toThrow(
      "deployment provenance is invalid",
    );

    const env = registrationEnv();
    const original = await env.RECEIPT_EVIDENCE_AUTHORITY
      .public_key_registration();
    env.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration = vi.fn(async () => ({
      ...original,
      deployment_source_sha: "2".repeat(40),
    }));
    await expect(operator(env).pending_public_key_registration()).rejects.toThrow(
      "invalid PENDING registration",
    );

    const digestSubstitution = registrationEnv();
    const valid = await digestSubstitution.RECEIPT_EVIDENCE_AUTHORITY
      .public_key_registration();
    digestSubstitution.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration =
      vi.fn(async () => ({
        ...valid,
        authority_worker_version_id:
          "20000000-0000-4000-8000-000000000002",
      }));
    await expect(
      operator(digestSubstitution).pending_public_key_registration(),
    ).rejects.toThrow("invalid PENDING registration");
  });

  it.each([
    {
      name: "an extra caller-controlled field",
      mutate: (row: Record<string, unknown>) => {
        row.go_override = true;
      },
    },
    {
      name: "substituted algorithm and key material",
      mutate: (row: Record<string, unknown>) => {
        row.algorithm = "HMAC";
        row.public_key_base64 = "not-an-ed25519-public-key";
      },
    },
    {
      name: "a string key generation",
      mutate: (row: Record<string, unknown>) => {
        row.key_generation = "1";
      },
    },
  ])("rejects $name even with self-consistent digests", async ({ mutate }) => {
    const env = registrationEnv();
    const valid = await env.RECEIPT_EVIDENCE_AUTHORITY
      .public_key_registration();
    const substituted = { ...valid } as Record<string, unknown>;
    mutate(substituted);
    const rebound = await bindRegistrationDigests(substituted);
    env.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration = vi.fn(
      async () => rebound as never,
    );
    await expect(operator(env).pending_public_key_registration()).rejects.toThrow(
      "invalid PENDING registration",
    );
  });
});
