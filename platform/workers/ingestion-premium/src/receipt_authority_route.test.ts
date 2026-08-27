import { describe, expect, it, vi } from "vitest";
import type {
  ReceiptIssueResultV1,
  ReceiptRequestV1,
} from "../../receipt-evidence-authority/src/types";
import { canonicalDigest } from "../../receipt-evidence-authority/src/canonical";
import worker, { type Env } from "./index";

const TOKEN = "receipt-route-test-token-not-for-live";

function routeEnv() {
  const rows = new Map<string, Record<string, unknown>>();
  const db = {
    prepare(sql: string) {
      let args: unknown[] = [];
      const statement = {
        bind(...values: unknown[]) {
          args = values;
          return statement;
        },
        async run() {
          if (sql.includes("INSERT OR IGNORE INTO receipt_authority_requests")) {
            const operationId = String(args[0]);
            rows.set(operationId, rows.get(operationId) ?? {
              operation_id: operationId,
              request_nonce: String(args[1]),
              environment: String(args[2]),
              dataset: String(args[3]),
              segment_id: String(args[4]),
              state: "PREPARED",
              receipt_digest: null,
            });
          } else if (sql.includes("UPDATE receipt_authority_requests")) {
            const row = rows.get(String(args[2]));
            if (row !== undefined) {
              row.state = "FINALIZED";
              row.receipt_digest = String(args[0]);
            }
          }
          return { success: true, meta: {} };
        },
        async first<T>() {
          return (rows.get(String(args[0])) ?? null) as T | null;
        },
      };
      return statement;
    },
  } as unknown as D1Database;

  const issue = vi.fn(async (request: ReceiptRequestV1) => {
    const operationId = await canonicalDigest(request);
    return {
      schema_version: "receipt-evidence-issue-result/v1",
      operation_id: operationId,
      state: "FINALIZED",
      replayed: false,
      receipt_digest: `sha256:${"c".repeat(64)}`,
      receipt: {},
    } as unknown as ReceiptIssueResultV1;
  });
  const publicKeyRegistration = vi.fn(async () => ({
    schema_version: "receipt-public-key-registration/v1" as const,
    purpose: "receipt_verification" as const,
    environment: "production" as const,
    authority_status: "PENDING" as const,
    key_id: "receipt-production-test-registration",
    key_generation: 1,
    algorithm: "Ed25519" as const,
    public_key_base64: "public-key-only",
    private_key_extractable: false as const,
    status: "pending" as const,
    generated_at: "2026-08-27T00:00:00.000Z",
    registration_digest: `sha256:${"d".repeat(64)}`,
  }));
  const env = {
    DB: db,
    INGESTION_RUN_TOKEN: TOKEN,
    JQUANTS_API_KEY: "not-used-by-receipt-route",
    RAW_BUCKET: {} as R2Bucket,
    STRUCTURED_BUCKET: {} as R2Bucket,
    RECEIPT_AUTHORITY_ENVIRONMENT: "production",
    RECEIPT_EVIDENCE_AUTHORITY: {
      issue_for_segment: issue,
      recover_issue: vi.fn(),
      public_key_registration: publicKeyRegistration,
    },
  } as unknown as Env;
  return { env, issue, publicKeyRegistration, rows };
}

function request(url: string, init: RequestInit = {}): Request {
  return new Request(url, {
    method: "POST",
    headers: { "x-ingestion-token": TOKEN, ...init.headers },
    ...init,
  });
}

describe("authenticated Receipt Evidence Authority route", () => {
  it("calls the typed binding with only dataset, segment, and a durable nonce", async () => {
    const { env, issue, rows } = routeEnv();
    const response = await worker.fetch(request(
      "https://premium.invalid/v1/admin/receipt-evidence/reconcile" +
        "?dataset=indices_bars_daily_topix&segment=2024-02",
    ), env);
    expect(response.status).toBe(200);
    const result = await response.json<Record<string, unknown>>();
    expect(result).toMatchObject({ ok: true, state: "FINALIZED" });
    expect(result).not.toHaveProperty("receipt");
    expect(issue).toHaveBeenCalledTimes(1);
    const rpcRequest = issue.mock.calls[0]![0];
    expect(Object.keys(rpcRequest).sort()).toEqual([
      "dataset_id",
      "environment",
      "operation",
      "request_nonce",
      "schema_version",
      "segment_id",
    ]);
    expect(rpcRequest).toMatchObject({
      operation: "issue_for_segment",
      environment: "production",
      dataset_id: "indices_bars_daily_topix",
      segment_id: "2024-02",
    });
    expect(rpcRequest.request_nonce).toMatch(/^[0-9a-f]{64}$/);
    expect(rows.get(String(result.operation_id))).toMatchObject({
      state: "FINALIZED",
      receipt_digest: result.receipt_digest,
    });
  });

  it("rejects unauthenticated, body-supplied, duplicate, and extra inputs before RPC", async () => {
    const { env, issue } = routeEnv();
    const url = "https://premium.invalid/v1/admin/receipt-evidence/reconcile" +
      "?dataset=markets_calendar&segment=2024-02";
    expect((await worker.fetch(new Request(url, { method: "POST" }), env)).status)
      .toBe(401);
    expect((await worker.fetch(request(url, {
      body: JSON.stringify({ structured_digest: `sha256:${"0".repeat(64)}` }),
    }), env)).status).toBe(400);
    expect((await worker.fetch(request(`${url}&segment=2024-03`), env)).status)
      .toBe(400);
    expect((await worker.fetch(request(`${url}&raw_count=1`), env)).status)
      .toBe(400);
    expect(issue).not.toHaveBeenCalled();
  });

  it("returns only the pending public-key registration over the same auth gate", async () => {
    const { env, publicKeyRegistration } = routeEnv();
    const url = "https://premium.invalid/v1/admin/receipt-evidence/" +
      "public-key-registration";
    expect((await worker.fetch(new Request(url, { method: "POST" }), env)).status)
      .toBe(401);
    const response = await worker.fetch(request(url), env);
    expect(response.status).toBe(200);
    const payload = await response.json<Record<string, unknown>>();
    expect(payload).toMatchObject({
      ok: true,
      registration: {
        authority_status: "PENDING",
        algorithm: "Ed25519",
        private_key_extractable: false,
        status: "pending",
      },
    });
    expect(payload).not.toHaveProperty("registration.wrapped_private_key_base64");
    expect(payload).not.toHaveProperty("registration.private_key_pkcs8");
    expect(publicKeyRegistration).toHaveBeenCalledTimes(1);
    expect((await worker.fetch(request(`${url}?generation=1`), env)).status)
      .toBe(400);
  });
});
