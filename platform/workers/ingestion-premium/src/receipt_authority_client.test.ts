import { describe, expect, it, vi } from "vitest";
import type { ReceiptIssueResultV1 } from "../../receipt-evidence-authority/src/types";
import { canonicalDigest } from "../../receipt-evidence-authority/src/canonical";
import {
  issueGovernedReceipt,
  recoverGovernedReceipt,
  recoverPreparedReceipt,
  recoverPreparedReceipts,
  type ReceiptAuthorityClientEnv,
} from "./receipt_authority_client";

function fakeEnv() {
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
            if (!rows.has(operationId)) {
              rows.set(operationId, {
                operation_id: operationId,
                request_nonce: String(args[1]),
                environment: String(args[2]),
                dataset: String(args[3]),
                segment_id: String(args[4]),
                state: "PREPARED",
                receipt_digest: null,
              });
            }
          } else if (sql.includes("UPDATE receipt_authority_requests")) {
            const row = rows.get(String(args[2]));
            if (row !== undefined) {
              row.state = "FINALIZED";
              row.receipt_digest = String(args[0]);
            }
          }
          return { success: true };
        },
        async first<T>() {
          return (rows.get(String(args[0])) ?? null) as T | null;
        },
        async all<T>() {
          return {
            results: [...rows.values()]
              .filter((row) => row.state === "PREPARED")
              .slice(0, Number(args[0]))
              .map((row) => ({ operation_id: row.operation_id })) as T[],
            success: true,
          };
        },
      };
      return statement;
    },
  } as unknown as D1Database;
  const rpcResult = async (
    request: Record<string, unknown>,
    replayed: boolean,
  ): Promise<ReceiptIssueResultV1> => {
    const operationId = await canonicalDigest({
      ...request,
      operation: "issue_for_segment",
    });
    return {
      schema_version: "receipt-evidence-issue-result/v1",
      operation_id: operationId,
      state: "FINALIZED",
      replayed,
      receipt_digest: `sha256:${"b".repeat(64)}`,
      receipt: {},
    } as unknown as ReceiptIssueResultV1;
  };
  const issue = vi.fn(async (request: Record<string, unknown>) =>
    rpcResult(request, false)
  );
  const recover = vi.fn(async (request: Record<string, unknown>) =>
    rpcResult(request, true)
  );
  return {
    env: {
      DB: db,
      RECEIPT_EVIDENCE_AUTHORITY: {
        issue_for_segment: issue,
        recover_issue: recover,
        public_key_registration: vi.fn(),
      },
    } as unknown as ReceiptAuthorityClientEnv,
    issue,
    recover,
    rows,
  };
}

describe("Receipt Evidence Authority client", () => {
  it("supplies only dataset/month and a CSPRNG nonce over typed RPC", async () => {
    const { env, issue } = fakeEnv();
    const issued = await issueGovernedReceipt(
      env,
      "production",
      "indices_bars_daily_topix",
      "2024-02",
    );
    expect(issued.requestNonce).toMatch(/^[0-9a-f]{64}$/);
    expect(issue).toHaveBeenCalledWith({
      schema_version: "receipt-evidence-issue-request/v1",
      operation: "issue_for_segment",
      environment: "production",
      dataset_id: "indices_bars_daily_topix",
      segment_id: "2024-02",
      request_nonce: issued.requestNonce,
    });
    expect(Object.keys(issue.mock.calls[0]![0]).sort()).toEqual([
      "dataset_id",
      "environment",
      "operation",
      "request_nonce",
      "schema_version",
      "segment_id",
    ]);
  });

  it("recovers only the exact persisted nonce and rejects non-V3 input", async () => {
    const { env, recover } = fakeEnv();
    const nonce = "c".repeat(64);
    await recoverGovernedReceipt(
      env,
      "staging",
      "markets_calendar",
      "2024-02",
      nonce,
    );
    expect(recover).toHaveBeenCalledWith(expect.objectContaining({
      operation: "recover_issue",
      request_nonce: nonce,
    }));
    await expect(issueGovernedReceipt(
      env,
      "production",
      "equities_investor_types",
      "2024-02",
    )).rejects.toThrow("outside the governed Receipt V3 inventory");
    await expect(recoverGovernedReceipt(
      env,
      "production",
      "markets_calendar",
      "2024-02",
      "not-a-nonce",
    )).rejects.toThrow("recovery nonce is invalid");
  });

  it("persists the exact request before RPC and recovers a lost response", async () => {
    const { env, issue, recover, rows } = fakeEnv();
    issue.mockRejectedValueOnce(new Error("simulated lost RPC response"));
    await expect(issueGovernedReceipt(
      env,
      "production",
      "markets_calendar",
      "2024-02",
    )).rejects.toThrow("simulated lost RPC response");
    expect(rows.size).toBe(1);
    const [operationId, prepared] = [...rows.entries()][0]!;
    expect(prepared).toMatchObject({
      state: "PREPARED",
      receipt_digest: null,
    });

    const recovered = await recoverPreparedReceipt(env, operationId);
    expect(recovered.replayed).toBe(true);
    expect(recover).toHaveBeenCalledTimes(1);
    expect(rows.get(operationId)).toMatchObject({
      state: "FINALIZED",
      receipt_digest: recovered.receipt_digest,
    });
  });

  it("cron recovery consumes only durable PREPARED operation identities", async () => {
    const { env, issue, recover, rows } = fakeEnv();
    issue.mockRejectedValueOnce(new Error("lost response"));
    await expect(issueGovernedReceipt(
      env,
      "production",
      "markets_calendar",
      "2024-02",
    )).rejects.toThrow("lost response");
    const sweep = await recoverPreparedReceipts(env);
    expect(sweep).toEqual({ attempted: 1, recovered: 1, failed: 0 });
    expect(recover).toHaveBeenCalledTimes(1);
    expect(Object.keys(recover.mock.calls[0]![0]).sort()).toEqual([
      "dataset_id",
      "environment",
      "operation",
      "request_nonce",
      "schema_version",
      "segment_id",
    ]);
    expect([...rows.values()][0]).toMatchObject({ state: "FINALIZED" });
  });
});
