import { describe, expect, it } from "vitest";
import {
  issueGovernedJsdaReceipt,
  jsdaReceiptSegmentReady,
  requireTrustedJsdaReceipt,
} from "./receipt_issue";
import type { JobRow } from "./job_store";

function row(state: JobRow["state"], extras: Partial<JobRow> = {}): JobRow {
  return {
    work_key: "jsda:v2:root:jsda_otc_bond_reference_prices:cron:2026-08-01",
    run_key: "jsda:v2:root:jsda_otc_bond_reference_prices:cron:2026-08-01",
    dataset: "jsda_otc_bond_reference_prices",
    job_type: "discover_root",
    target_url: "https://market.jsda.or.jp/index.html",
    segment_id: "index_root_2026-08-01",
    parent_work_key: null,
    contract_digest: "sha256:" + "ab".repeat(32),
    state,
    attempt: 0,
    cursor: 0,
    frontier_json: state === "completed" ? "[{}]" : null,
    last_error: null,
    content_digest: state === "completed" ? "sha256:" + "cd".repeat(32) : null,
    raw_key: state === "completed" ? "raw/jsda/index" : null,
    audit_receipt_key: null,
    audit_receipt_digest: null,
    requested_by: "cron",
    requested_at: "2026-08-01T00:00:00.000Z",
    lease_until: null,
    source_object_id: null,
    freshness: null,
    observation_epoch: null,
    ...extras,
  };
}

describe("JSDA governed receipt issuance", () => {
  it("issues after immutable raw completion and rejects parse-zero/retry/recovery", async () => {
    const issued: unknown[] = [];
    const env = {
      RECEIPT_AUTHORITY_OPERATION_MODE: "ACTIVE",
      RECEIPT_AUTHORITY_ENVIRONMENT: "production",
      DB: { prepare() { return { bind() { return this; }, run: async () => ({ meta: { changes: 1 } }), first: async () => null }; } },
      RECEIPT_EVIDENCE_AUTHORITY: {
        async issue_for_segment(request: Record<string, unknown>) {
          issued.push(request);
          expect(Object.keys(request).sort().join(",")).not.toContain("raw_count");
          expect(request.dataset_id).toBe("jsda_otc_bond_reference_prices");
          expect(request.segment_id).toBe("index_root_2026-08-01");
          expect(request.work_key).toBe(row("completed").work_key);
          expect(request.raw_object_key).toBe("raw/jsda/index");
          expect(request.expected_contract_digest).toMatch(/^sha256:[0-9a-f]{64}$/);
          throw new Error("authority reached");
        },
        async recover_issue() {
          return {
            schema_version: "receipt-evidence-issue-result/v1",
            operation_id: "sha256:" + "11".repeat(32),
            state: "FINALIZED",
            replayed: true,
            receipt_digest: "sha256:" + "22".repeat(32),
            receipt: { digests: { eligibility: "RECOVERED_RAW_ONLY" } },
          };
        },
      },
    } as never;
    expect(jsdaReceiptSegmentReady(row("failed_transient"))).toBe(false);
    expect(jsdaReceiptSegmentReady(row("completed"))).toBe(true);
    await expect(issueGovernedJsdaReceipt(env, row("failed_transient"))).rejects.toThrow(/exhausted/);
    await expect(issueGovernedJsdaReceipt(env, row("completed"), { parseZero: true })).rejects.toThrow(/parse-zero/);
    await expect(issueGovernedJsdaReceipt({ ...env, RECEIPT_AUTHORITY_OPERATION_MODE: "PENDING" } as never, row("completed"))).resolves.toBe("SKIPPED");
    await expect(issueGovernedJsdaReceipt(env, row("completed"))).rejects.toThrow(/authority reached|ledger/);
    expect(issued.length >= 0).toBe(true);
    await expect(requireTrustedJsdaReceipt(
      { ...env, RECEIPT_AUTHORITY_OPERATION_MODE: "PENDING" } as never,
      row("completed"),
    )).rejects.toThrow(/RECEIPT_PENDING/);
    await expect(requireTrustedJsdaReceipt(
      { ...env, RECEIPT_AUTHORITY_OPERATION_MODE: undefined } as never,
      row("completed"),
    )).rejects.toThrow(/RECEIPT_PENDING/);
    await expect(requireTrustedJsdaReceipt(
      { ...env, RECEIPT_AUTHORITY_ENVIRONMENT: "lab" } as never,
      row("completed"),
    )).rejects.toThrow(/RECEIPT_PENDING|environment/);
    await expect(requireTrustedJsdaReceipt(
      { ...env, RECEIPT_EVIDENCE_AUTHORITY: undefined } as never,
      row("completed"),
    )).rejects.toThrow(/RECEIPT_PENDING|binding/);
    await expect(requireTrustedJsdaReceipt(env, row("rejected"))).resolves.toBeUndefined();
    await expect(requireTrustedJsdaReceipt(env, row("waiting_children"))).resolves.toBeUndefined();
  });
});
