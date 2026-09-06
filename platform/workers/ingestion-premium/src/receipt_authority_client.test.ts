import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import type {
  ReceiptAuditRecoveryAttestationClaimsV1,
  ReceiptAuditRecoveryCanaryBeginRequestV1,
  ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ReceiptAuditRecoveryResultV1,
  ReceiptAuditFirstRecoveryResultV1,
  ReceiptIssueResultV1,
} from "../../receipt-evidence-authority/src/types";
import {
  base64ToBytes,
  bytesToBase64,
  canonicalDigest,
  canonicalJson,
  sha256Digest,
} from "../../receipt-evidence-authority/src/canonical";
import {
  auditInitialEventDocument,
  auditFirstRecoveryResult,
  auditInitialResult,
  auditInitialStateDocument,
  auditRecoveryEventPayload,
  auditRecoveryEventTail,
  auditRecoveryOperationId,
  auditReplayEventPayload,
  auditReplayEventTail,
} from "../../receipt-evidence-authority/src/audit_recovery_contract";
import {
  issueGovernedReceipt,
  recoverGovernedReceipt,
  recoverPreparedReceipt,
  recoverPreparedReceipts,
  type ReceiptAuthorityClientEnv,
} from "./receipt_authority_client";
import {
  readStagingReceiptAuditRecoveryEvidence,
  readStagingReceiptAuditRecoveryAttestation,
  runStagingReceiptAuditRecoveryCanary,
  type ReceiptAuthorityAuditCanaryEnv,
} from "./receipt_authority_audit_canary";

const here = dirname(fileURLToPath(import.meta.url));
const auditSchema = new DatabaseSync(":memory:");
auditSchema.exec(readFileSync(
  join(here, "..", "migrations", "0019_receipt_authority_recovery_smoke.sql"),
  "utf8",
));
const AUDIT_SCHEMA_ROWS = auditSchema.prepare(
  `SELECT type,name,tbl_name,sql FROM sqlite_schema
    WHERE name IN (?,?,?) ORDER BY type,name`,
).all(
  "receipt_authority_recovery_audit_attestations",
  "receipt_authority_recovery_audit_monotonic",
  "receipt_authority_recovery_audit_no_delete",
) as Record<string, unknown>[];

type AuditRow = {
  reservation_id: string;
  source_sha: string;
  caller_worker_version_id: string;
  authority_operation_id: string;
  request_nonce: string;
  state: "PREPARED" | "ATTESTED";
  signed_attestation_digest: string | null;
  signed_attestation_json: string | null;
};

function fakeEnv() {
  const rows = new Map<string, Record<string, unknown>>();
  const auditRows = new Map<string, AuditRow>();
  const preparedSql: string[] = [];
  const runSql: string[] = [];
  const db = {
    prepare(sql: string) {
      preparedSql.push(sql);
      let args: unknown[] = [];
      const statement = {
        bind(...values: unknown[]) {
          args = values;
          return statement;
        },
        async run() {
          runSql.push(sql);
          if (sql.includes("INSERT OR IGNORE INTO receipt_authority_requests")) {
            const operationId = String(args[0]);
            if (!rows.has(operationId)) {
              rows.set(operationId, {
                operation_id: operationId,
                request_nonce: String(args[1]),
                environment: String(args[2]),
                source: String(args[3]),
                contract_id: String(args[4]),
                dataset: String(args[5]),
                segment_id: String(args[6]),
                state: "PREPARED",
                receipt_digest: null,
                work_key: args[9] == null ? undefined : String(args[9]),
                expected_contract_digest: args[10] == null ? undefined : String(args[10]),
                raw_object_key: args[11] == null ? undefined : String(args[11]),
              });
            }
          } else if (sql.includes("UPDATE receipt_authority_requests")) {
            const row = rows.get(String(args[2]));
            if (row !== undefined) {
              row.state = "FINALIZED";
              row.receipt_digest = String(args[0]);
            }
          } else if (
            sql.includes(
              "INSERT OR IGNORE INTO receipt_authority_recovery_audit_attestations",
            )
          ) {
            const key = `${String(args[1])}:${String(args[2])}`;
            if (!auditRows.has(key)) {
              auditRows.set(key, {
                reservation_id: String(args[0]),
                source_sha: String(args[1]),
                caller_worker_version_id: String(args[2]),
                authority_operation_id: String(args[3]),
                request_nonce: String(args[4]),
                state: "PREPARED",
                signed_attestation_digest: null,
                signed_attestation_json: null,
              });
            }
          } else if (
            sql.includes("UPDATE receipt_authority_recovery_audit_attestations")
          ) {
            const row = [...auditRows.values()].find(
              (candidate) => candidate.reservation_id === String(args[3]),
            );
            if (row?.state === "PREPARED") {
              row.state = "ATTESTED";
              row.signed_attestation_digest = String(args[0]);
              row.signed_attestation_json = String(args[1]);
            }
          }
          return { success: true };
        },
        async first<T>() {
          if (sql.includes("FROM receipt_authority_recovery_audit_attestations")) {
            const row = sql.includes("WHERE reservation_id")
              ? [...auditRows.values()].find(
                (candidate) => candidate.reservation_id === String(args[0]),
              )
              : auditRows.get(`${String(args[0])}:${String(args[1])}`);
            return (row ?? null) as T | null;
          }
          const request = rows.get(String(args[0]));
          if (sql.includes("FROM receipt_authority_operations")) {
            if (request === undefined) return null as T | null;
            return {
              operation_id: request.operation_id,
              state: "RECEIPT_COMMITTED",
              raw_manifest_digest: "sha256:" + "11".repeat(32),
              structured_digest: "sha256:" + "22".repeat(32),
            } as T;
          }
          if (sql.includes("FROM receipt_product_materializations")) {
            if (request === undefined) return null as T | null;
            return {
              operation_id: request.operation_id,
              raw_manifest_digest: "sha256:" + "11".repeat(32),
              artifact_digest: "sha256:" + "22".repeat(32),
            } as T;
          }
          return (request ?? null) as T | null;
        },
        async all<T>() {
          if (sql.includes("FROM sqlite_schema")) {
            return { results: AUDIT_SCHEMA_ROWS as T[], success: true };
          }
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
  ): Promise<ReceiptIssueResultV1> => ({
    schema_version: "receipt-evidence-issue-result/v1",
    operation_id: await canonicalDigest({
      ...request,
      operation: "issue_for_segment",
    }),
    state: "FINALIZED",
    replayed,
    receipt_digest: `sha256:${"b".repeat(64)}`,
    receipt: {},
  } as unknown as ReceiptIssueResultV1);
  const issuedOperations = new Set<string>();
  const issue = vi.fn(async (request: Record<string, unknown>) => {
    const operationId = await canonicalDigest({
      ...request,
      operation: "issue_for_segment",
    });
    const replayed = issuedOperations.has(operationId);
    issuedOperations.add(operationId);
    return rpcResult(request, replayed);
  });
  const recover = vi.fn(async (request: Record<string, unknown>) =>
    rpcResult(request, true)
  );

  const begun = new Map<string, {
    request: ReceiptAuditRecoveryCanaryBeginRequestV1;
    createdAt: string;
    initialStateDigest: string;
    initialResultDigest: string;
    initialResult: ReturnType<typeof auditInitialResult>;
  }>();
  const auditResults = new Map<string, ReceiptAuditRecoveryResultV1>();
  const firstRecoveries = new Map<string, {
    result: ReceiptAuditFirstRecoveryResultV1;
    digest: string;
  }>();
  const beginAudit = vi.fn(async (
    request: ReceiptAuditRecoveryCanaryBeginRequestV1,
  ) => {
    const operationId = await auditRecoveryOperationId(request);
    const existing = begun.get(operationId);
    if (existing !== undefined) {
      return {
        schema_version: "receipt-audit-recovery-begin-result/v1" as const,
        purpose: "receipt_authority_recovery_canary" as const,
        eligibility: "AUDIT_ONLY" as const,
        operation_id: operationId,
        initial_result_digest: existing.initialResultDigest,
        initial_result: existing.initialResult,
        rpc_replayed: true,
      };
    }
    const createdAt = "2026-08-28T01:00:00.000Z";
    const initialStateDigest = await canonicalDigest(
      auditInitialStateDocument(operationId, createdAt),
    );
    const initialResult = auditInitialResult(
      operationId,
      request.request_nonce,
      initialStateDigest,
      createdAt,
    );
    const initialResultDigest = await canonicalDigest(initialResult);
    begun.set(operationId, {
      request,
      createdAt,
      initialStateDigest,
      initialResultDigest,
      initialResult,
    });
    return {
      schema_version: "receipt-audit-recovery-begin-result/v1" as const,
      purpose: "receipt_authority_recovery_canary" as const,
      eligibility: "AUDIT_ONLY" as const,
      operation_id: operationId,
      initial_result_digest: initialResultDigest,
      initial_result: initialResult,
      rpc_replayed: false,
    };
  });
  const recoverAudit = vi.fn(async (
    request: ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ) => {
    const operationId = await auditRecoveryOperationId(request);
    const existingResult = auditResults.get(operationId);
    if (existingResult !== undefined) {
      return { ...existingResult, rpc_replayed: true };
    }
    const initial = begun.get(operationId);
    if (initial === undefined) throw new Error("audit operation was not begun");
    const storedFirst = firstRecoveries.get(operationId);
    const recoveredAt = storedFirst?.result.recovered_at ??
      "2026-08-28T01:00:01.000Z";
    const recoveryEventDigest = await canonicalDigest(auditRecoveryEventPayload(
      operationId,
      request.request_nonce,
      initial.initialStateDigest,
      initial.initialResultDigest,
      recoveredAt,
    ));
    const initialEventDigest = await canonicalDigest(auditInitialEventDocument(
      operationId,
      initial.initialStateDigest,
      initial.createdAt,
    ));
    const recoveryEventTailDigest = await canonicalDigest(auditRecoveryEventTail(
      operationId,
      recoveryEventDigest,
      initialEventDigest,
      recoveredAt,
    ));
    if (storedFirst === undefined) {
      const result = auditFirstRecoveryResult(
        operationId,
        request.request_nonce,
        initial.initialStateDigest,
        initial.initialResultDigest,
        recoveryEventDigest,
        recoveryEventTailDigest,
        recoveredAt,
      );
      const digest = await canonicalDigest(result);
      firstRecoveries.set(operationId, { result, digest });
      return {
        schema_version: "receipt-audit-recovery-pending-replay-result/v1" as const,
        purpose: "receipt_authority_recovery_canary" as const,
        eligibility: "AUDIT_ONLY" as const,
        operation_id: operationId,
        state: "RECOVERED_PENDING_REPLAY" as const,
        first_recovery_result_digest: digest,
        first_recovery_result: result,
        rpc_replayed: false as const,
      };
    }
    const replayConfirmedAt = "2026-08-28T01:00:02.000Z";
    const replayEventDigest = await canonicalDigest(auditReplayEventPayload(
      operationId,
      request.request_nonce,
      storedFirst.digest,
      recoveryEventDigest,
      recoveryEventTailDigest,
      replayConfirmedAt,
    ));
    const replayEventTailDigest = await canonicalDigest(auditReplayEventTail(
      operationId,
      replayEventDigest,
      recoveryEventTailDigest,
      replayConfirmedAt,
    ));
    const claims: ReceiptAuditRecoveryAttestationClaimsV1 = {
      schema_version: "receipt-audit-recovery-attestation-claims/v1",
      purpose: "receipt_authority_recovery_canary",
      eligibility: "AUDIT_ONLY",
      environment: "staging",
      authority_instance_digest: `sha256:${"a".repeat(64)}`,
      authority_source_sha: request.caller_source_sha,
      authority_worker_version_id: "20000000-0000-4000-8000-000000000002",
      authority_worker_version_tag: `ra-s-r-${request.caller_source_sha}`,
      caller_source_sha: request.caller_source_sha,
      caller_worker_version_id: request.caller_worker_version_id,
      caller_worker_version_tag: request.caller_worker_version_tag,
      operation_id: operationId,
      request_nonce: request.request_nonce,
      initial_state: "RECOVERY_REQUIRED",
      initial_state_digest: initial.initialStateDigest,
      initial_result_digest: initial.initialResultDigest,
      initial_created_at: initial.createdAt,
      recovery_event: "RECOVERY_COMPLETED",
      recovery_event_digest: recoveryEventDigest,
      recovery_event_tail_digest: recoveryEventTailDigest,
      recovered_at: recoveredAt,
      first_recovery_state: "RECOVERED_PENDING_REPLAY",
      first_recovery_result_digest: storedFirst.digest,
      replay_event: "REPLAY_CONFIRMED",
      replay_event_digest: replayEventDigest,
      replay_event_tail_digest: replayEventTailDigest,
      replay_confirmed_at: replayConfirmedAt,
      replayed: true,
      final_state: "AUDIT_FINALIZED",
      issuer_key_id: `receipt-staging-${"a".repeat(16)}`,
      issued_at: replayConfirmedAt,
    };
    const signedClaims = new TextEncoder().encode(canonicalJson(claims));
    const signedAttestation = {
      schema_version: "receipt-audit-recovery-attestation/v1" as const,
      purpose: "receipt_authority_recovery_canary" as const,
      eligibility: "AUDIT_ONLY" as const,
      environment: "staging" as const,
      issuer_class: "ReceiptEvidenceAuthorityAuditSigner" as const,
      issuer_key_id: claims.issuer_key_id,
      authority_instance_digest: claims.authority_instance_digest,
      signed_claims_base64: bytesToBase64(signedClaims),
      signed_claims_digest: await sha256Digest(signedClaims),
      signature: `ed25519:${bytesToBase64(new Uint8Array(64))}`,
      issued_at: replayConfirmedAt,
    };
    const result = {
      schema_version: "receipt-audit-recovery-result/v1" as const,
      purpose: "receipt_authority_recovery_canary" as const,
      eligibility: "AUDIT_ONLY" as const,
      operation_id: operationId,
      final_state: "AUDIT_FINALIZED" as const,
      signed_attestation_digest: await canonicalDigest(signedAttestation),
      signed_attestation: signedAttestation,
      rpc_replayed: true as const,
    };
    auditResults.set(operationId, result);
    return result;
  });
  return {
    env: {
      DB: db,
      RECEIPT_EVIDENCE_AUTHORITY: {
        issue_for_segment: issue,
        recover_issue: recover,
        begin_audit_recovery_canary: beginAudit,
        recover_audit_recovery_canary: recoverAudit,
        public_key_registration: vi.fn(),
      },
    } as unknown as ReceiptAuthorityClientEnv & ReceiptAuthorityAuditCanaryEnv,
    issue,
    recover,
    beginAudit,
    recoverAudit,
    rows,
    auditRows,
    preparedSql,
    runSql,
  };
}

function activateAudit(env: ReceiptAuthorityAuditCanaryEnv): void {
  env.RECEIPT_AUTHORITY_OPERATION_MODE = "ACTIVE";
  env.CF_VERSION_METADATA = {
    id: "10000000-0000-4000-8000-000000000003",
    tag: `ra-s-c-${"1".repeat(40)}`,
    timestamp: "2026-08-28T00:00:00.000Z",
  };
}

describe("Receipt Evidence Authority client", () => {
  it("derives AM snapshot and JSDA year/file ranges and rejects invented ranges", async () => {
    const { env, issue } = fakeEnv();
    await issueGovernedReceipt(env, "production", "equities_bars_daily_am", "2026-09-02");
    expect(issue).toHaveBeenCalledWith(expect.objectContaining({
      segment_grain: "same_trading_day_am_snapshot",
      expected_key_start: "2026-09-02",
      expected_key_end: "2026-09-02",
    }));
    await issueGovernedReceipt(
      env,
      "production",
      "jsda_otc_bond_reference_prices",
      "2026-08-01",
      {
        work_key: "jsda:v2:root:jsda_otc_bond_reference_prices:cron:2026-08-01",
        expected_contract_digest: `sha256:${"ab".repeat(32)}`,
        raw_object_key: "raw/jsda/jsda_otc_bond_reference_prices/index_root_2026-08-01/html",
      },
    );
    expect(issue).toHaveBeenCalledWith(expect.objectContaining({
      segment_grain: "official_archive_index_day",
      expected_key_start: "2026-08-01",
      expected_key_end: "2026-08-01",
      work_key: "jsda:v2:root:jsda_otc_bond_reference_prices:cron:2026-08-01",
      raw_object_key: "raw/jsda/jsda_otc_bond_reference_prices/index_root_2026-08-01/html",
    }));
  });

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
      source: "jquants",
      contract_id: "jquants_premium_core",
      dataset_id: "indices_bars_daily_topix",
      segment_grain: "calendar_month",
      segment_id: "2024-02",
      expected_key_start: "2024-02-01",
      expected_key_end: "2024-02-29",
      request_nonce: issued.requestNonce,
    });
  });

  it("recovers only the exact persisted nonce and rejects non-V3 input", async () => {
    const { env, recover } = fakeEnv();
    const nonce = "c".repeat(64);
    await recoverGovernedReceipt(env, "staging", "markets_calendar", "2024-02", nonce);
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

  it("recovers a JSDA PREPARED request from the persisted locator", async () => {
    const { env, issue, recover, rows } = fakeEnv();
    const locator = {
      work_key: "jsda:v2:file:jsda_otc_bond_reference_prices:abc",
      expected_contract_digest: `sha256:${"ab".repeat(32)}`,
      raw_object_key: "raw/jsda/file.csv",
    };
    issue.mockRejectedValueOnce(new Error("simulated lost JSDA RPC"));
    await expect(issueGovernedReceipt(
      env,
      "production",
      "jsda_otc_bond_reference_prices",
      "file_2002-08-02_otc",
      locator,
    )).rejects.toThrow("simulated lost JSDA RPC");
    const [operationId, prepared] = [...rows.entries()][0]!;
    expect(prepared).toMatchObject({
      state: "PREPARED",
      work_key: locator.work_key,
      raw_object_key: locator.raw_object_key,
      expected_contract_digest: locator.expected_contract_digest,
    });
    const recovered = await recoverPreparedReceipt(env, operationId);
    expect(recovered.replayed).toBe(true);
    expect(recover).toHaveBeenCalledWith(expect.objectContaining({
      operation: "recover_issue",
      work_key: locator.work_key,
      raw_object_key: locator.raw_object_key,
      expected_contract_digest: locator.expected_contract_digest,
    }));
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
    const [operationId, prepared] = [...rows.entries()][0]!;
    expect(prepared).toMatchObject({ state: "PREPARED", receipt_digest: null });
    const recovered = await recoverPreparedReceipt(env, operationId);
    expect(recovered.replayed).toBe(true);
    expect(recover).toHaveBeenCalledOnce();
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
    expect(await recoverPreparedReceipts(env)).toEqual({
      attempted: 1,
      recovered: 1,
      failed: 0,
    });
    expect(recover).toHaveBeenCalledOnce();
    expect([...rows.values()][0]).toMatchObject({ state: "FINALIZED" });
  });

  it("persists only one signed AUDIT_ONLY attestation per exact staging version", async () => {
    const { env, issue, recover, beginAudit, recoverAudit, auditRows } = fakeEnv();
    activateAudit(env);
    const first = await runStagingReceiptAuditRecoveryCanary(env);
    expect(first).toMatchObject({
      schema_version: "receipt-audit-recovery-attestation/v1",
      eligibility: "AUDIT_ONLY",
      environment: "staging",
      issuer_class: "ReceiptEvidenceAuthorityAuditSigner",
    });
    expect(issue).not.toHaveBeenCalled();
    expect(recover).not.toHaveBeenCalled();
    expect(beginAudit).toHaveBeenCalledOnce();
    expect(recoverAudit).toHaveBeenCalledTimes(2);
    expect(auditRows.size).toBe(1);
    expect([...auditRows.values()][0]).toMatchObject({
      state: "ATTESTED",
      signed_attestation_json: canonicalJson(first),
    });

    expect(await runStagingReceiptAuditRecoveryCanary(env)).toEqual(first);
    expect(await readStagingReceiptAuditRecoveryAttestation(env)).toEqual(first);
    expect(beginAudit).toHaveBeenCalledOnce();
    expect(recoverAudit).toHaveBeenCalledTimes(2);
  });

  it("reads exact D1 TEXT bytes and pinned schema with SELECT-only evidence RPC", async () => {
    const { env, preparedSql, runSql } = fakeEnv();
    activateAudit(env);
    const attestation = await runStagingReceiptAuditRecoveryCanary(env);
    const preparedBefore = preparedSql.length;
    const runsBefore = runSql.length;

    const evidence = await readStagingReceiptAuditRecoveryEvidence(env);
    const exactBytes = base64ToBytes(
      evidence.signed_attestation_json_utf8_base64,
    );
    expect(new TextDecoder().decode(exactBytes)).toBe(canonicalJson(attestation));
    expect(evidence).toMatchObject({
      schema_version: "receipt-operator-audit-evidence/v1",
      purpose: "receipt_authority_recovery_canary",
      eligibility: "AUDIT_ONLY",
      environment: "staging",
      caller_source_sha: "1".repeat(40),
      caller_worker_version_id: "10000000-0000-4000-8000-000000000003",
      caller_worker_version_tag: `ra-s-c-${"1".repeat(40)}`,
      d1_schema_digest:
        "sha256:fba0bdada764ff2dc67caa5c11b3a31b2c3c28d673a25712a853e0b0566b5259",
      signed_attestation_json_utf8_length: exactBytes.length,
      signed_attestation_digest: await canonicalDigest(attestation),
      evidence_digest: expect.stringMatching(/^sha256:[0-9a-f]{64}$/),
    });
    const { evidence_digest: suppliedDigest, ...body } = evidence;
    expect(suppliedDigest).toBe(await canonicalDigest(body));
    expect(preparedSql.slice(preparedBefore)).toHaveLength(2);
    expect(preparedSql.slice(preparedBefore).every((sql) =>
      /^\s*SELECT\b/i.test(sql)
    )).toBe(true);
    expect(runSql).toHaveLength(runsBefore);
  });

  it("creates a new immutable audit row after a coordinated caller redeploy", async () => {
    const { env, beginAudit, recoverAudit, auditRows } = fakeEnv();
    activateAudit(env);
    const first = await runStagingReceiptAuditRecoveryCanary(env);
    const firstRow = [...auditRows.values()][0]!;

    env.CF_VERSION_METADATA = {
      id: "20000000-0000-4000-8000-000000000003",
      tag: `ra-s-c-${"1".repeat(40)}`,
      timestamp: "2026-08-28T00:01:00.000Z",
    };
    const second = await runStagingReceiptAuditRecoveryCanary(env);

    expect(auditRows.size).toBe(2);
    expect(beginAudit).toHaveBeenCalledTimes(2);
    expect(recoverAudit).toHaveBeenCalledTimes(4);
    expect(second).not.toEqual(first);
    expect(new Set(
      [...auditRows.values()].map((row) => row.reservation_id),
    ).size).toBe(2);
    expect([...auditRows.values()][1]).toMatchObject({
      source_sha: firstRow.source_sha,
      caller_worker_version_id:
        "20000000-0000-4000-8000-000000000003",
      state: "ATTESTED",
      signed_attestation_json: canonicalJson(second),
    });
  });

  it("rejects PENDING and colliding reservations before every positive audit RPC", async () => {
    const { env, issue, recover, beginAudit, recoverAudit, auditRows } = fakeEnv();
    env.RECEIPT_AUTHORITY_OPERATION_MODE = "PENDING";
    env.CF_VERSION_METADATA = {
      id: "10000000-0000-4000-8000-000000000003",
      tag: `rp-s-c-${"1".repeat(40)}`,
      timestamp: "2026-08-28T00:00:00.000Z",
    };
    await expect(runStagingReceiptAuditRecoveryCanary(env)).rejects.toThrow(
      "not ACTIVE",
    );
    await expect(readStagingReceiptAuditRecoveryAttestation(env)).rejects.toThrow(
      "not ACTIVE",
    );

    activateAudit(env);
    const sourceSha = "1".repeat(40);
    const versionId = env.CF_VERSION_METADATA!.id;
    auditRows.set(`${sourceSha}:${versionId}`, {
      reservation_id: `sha256:${"f".repeat(64)}`,
      source_sha: sourceSha,
      caller_worker_version_id: versionId,
      authority_operation_id: `sha256:${"e".repeat(64)}`,
      request_nonce: "d".repeat(64),
      state: "PREPARED",
      signed_attestation_digest: null,
      signed_attestation_json: null,
    });
    await expect(runStagingReceiptAuditRecoveryCanary(env)).rejects.toThrow(
      "reservation drifted",
    );
    expect(issue).not.toHaveBeenCalled();
    expect(recover).not.toHaveBeenCalled();
    expect(beginAudit).not.toHaveBeenCalled();
    expect(recoverAudit).not.toHaveBeenCalled();
  });

  it("recovers the same audit operation after a lost authority response", async () => {
    const { env, beginAudit, recoverAudit, auditRows } = fakeEnv();
    activateAudit(env);
    recoverAudit.mockRejectedValueOnce(new Error("simulated lost audit response"));
    await expect(runStagingReceiptAuditRecoveryCanary(env)).rejects.toThrow(
      "simulated lost audit response",
    );
    expect([...auditRows.values()][0]).toMatchObject({
      state: "PREPARED",
      signed_attestation_json: null,
    });
    const recovered = await runStagingReceiptAuditRecoveryCanary(env);
    expect(recovered.eligibility).toBe("AUDIT_ONLY");
    expect(beginAudit).toHaveBeenCalledTimes(2);
    expect(recoverAudit).toHaveBeenCalledTimes(3);
    expect(new Set(beginAudit.mock.calls.map((call) => call[0].request_nonce)).size)
      .toBe(1);
    expect(auditRows.size).toBe(1);
  });

  it("accepts a finalized first response after the unsigned response was lost", async () => {
    const { env, beginAudit, recoverAudit, auditRows } = fakeEnv();
    activateAudit(env);
    const commitRecovery = recoverAudit.getMockImplementation();
    if (commitRecovery === undefined) throw new Error("test recovery fake absent");
    recoverAudit.mockImplementationOnce(async (request) => {
      await commitRecovery(request);
      throw new Error("simulated loss after first recovery commit");
    });
    await expect(runStagingReceiptAuditRecoveryCanary(env)).rejects.toThrow(
      "simulated loss after first recovery commit",
    );
    expect([...auditRows.values()][0]).toMatchObject({
      state: "PREPARED",
      signed_attestation_json: null,
    });

    const recovered = await runStagingReceiptAuditRecoveryCanary(env);
    expect(recovered.eligibility).toBe("AUDIT_ONLY");
    expect(beginAudit).toHaveBeenCalledTimes(2);
    expect(recoverAudit).toHaveBeenCalledTimes(2);
    expect(auditRows.size).toBe(1);
    expect([...auditRows.values()][0]).toMatchObject({ state: "ATTESTED" });
  });

  it("converges concurrent canaries to one version-scoped attestation", async () => {
    const { env, issue, recover, recoverAudit, auditRows } = fakeEnv();
    activateAudit(env);
    const [first, second] = await Promise.all([
      runStagingReceiptAuditRecoveryCanary(env),
      runStagingReceiptAuditRecoveryCanary(env),
    ]);
    expect(second).toEqual(first);
    expect(auditRows.size).toBe(1);
    expect([...auditRows.values()][0]).toMatchObject({
      state: "ATTESTED",
      signed_attestation_json: canonicalJson(first),
    });
    expect(recoverAudit).toHaveBeenCalledTimes(4);
    expect(issue).not.toHaveBeenCalled();
    expect(recover).not.toHaveBeenCalled();
  });
});
