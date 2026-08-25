import { env } from "cloudflare:workers";
import {
  applyD1Migrations,
  createExecutionContext,
  createMessageBatch,
  createScheduledController,
  getQueueResult,
  reset,
  waitOnExecutionContext,
} from "cloudflare:test";
import { beforeEach, describe, expect, inject, it } from "vitest";
import worker from "../src/index";
import type { JsdaWorkerEnv } from "../src/env";
import { loadJob, registerJob } from "../src/job_store";
import {
  continuationJob,
  descriptorForFile,
  makeRootJob,
  type ChildDescriptor,
  type JsdaQueueJob,
} from "../src/queue_contract";
import { putQueueAuditReceipt } from "../src/raw_store";

const runtimeEnv = env as JsdaWorkerEnv;
const migrations = inject<
  Array<{ name: string; queries: string[] }>
>("jsdaD1Migrations");

beforeEach(async () => {
  await reset();
  await applyD1Migrations(runtimeEnv.DB, migrations);
});

async function deliver(body: unknown, id: string) {
  const batch = createMessageBatch("quant-jsda-ingestion-test", [
    {
      id,
      timestamp: new Date("2026-08-25T01:30:00.000Z"),
      attempts: 1,
      body,
    },
  ]);
  const ctx = createExecutionContext();
  await worker.queue(batch, runtimeEnv, ctx);
  return getQueueResult(batch, ctx);
}

describe("JSDA Queue v2 in the Workers runtime", () => {
  it("dispatches Cron roots once per scheduled instant and persists all datasets", async () => {
    const scheduledTime = new Date("2026-08-25T01:30:00.000Z");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const controller = createScheduledController({
        cron: "30 1 * * *",
        scheduledTime,
      });
      const ctx = createExecutionContext();
      await worker.scheduled(controller, runtimeEnv, ctx);
      await waitOnExecutionContext(ctx);
    }

    const rows = await runtimeEnv.DB.prepare(
      `SELECT dataset, job_type, state, attempt, run_key
         FROM jsda_acquisition_jobs_v2
        WHERE run_key LIKE 'jsda:v2:root:%:cron:2026-08-25'
        ORDER BY dataset`,
    ).all<{
      dataset: string;
      job_type: string;
      state: string;
      attempt: number;
      run_key: string;
    }>();
    expect(rows.results).toHaveLength(3);
    expect(rows.results.map((row) => row.dataset)).toEqual([
      "jsda_corporate_bond_transactions",
      "jsda_otc_bond_reference_prices",
      "jsda_tokyo_repo_rates",
    ]);
    for (const row of rows.results) {
      expect(row).toMatchObject({
        job_type: "discover_root",
        state: "queued",
        attempt: 0,
      });
      expect(row.run_key).toBe(
        `jsda:v2:root:${row.dataset}:cron:2026-08-25`,
      );
    }
  });

  it("treats an identical content-addressed audit retry as idempotent", async () => {
    const input = {
      event: "completed" as const,
      work_key: "jsda:v2:file:test:idempotent",
      run_key: "jsda:v2:root:jsda_tokyo_repo_rates:cron:2026-08-25",
      dataset: "jsda_tokyo_repo_rates" as const,
      job_type: "fetch_file" as const,
      segment_id: "idempotent-audit",
      target_url: "https://www.jsda.or.jp/idempotent.xls",
      parent_work_key: "jsda:v2:year:test:parent",
      contract_digest: `sha256:${"0".repeat(64)}`,
      attempt: 1,
      cursor: 0,
      frontier_size: null,
      raw_key: "raw/jsda/idempotent.xls",
      content_digest: "1".repeat(64),
      reason_code: null,
      detail: "same content",
      recorded_at: "2026-08-25T01:30:00.000Z",
    };
    const first = await putQueueAuditReceipt(runtimeEnv.RAW_BUCKET, input);
    const second = await putQueueAuditReceipt(runtimeEnv.RAW_BUCKET, input);
    expect(second).toEqual(first);
    expect(
      (await runtimeEnv.RAW_BUCKET.head(first.key))?.customMetadata?.sha256,
    ).toBe(first.digest);
  });

  it("deduplicates repeated same-day root submissions in D1", async () => {
    const request = () =>
      new Request(
        "https://ingestion-jsda.test/v1/run?dataset=jsda_tokyo_repo_rates",
        {
          method: "POST",
          headers: { "X-Ingestion-Token": "jsda-runtime-test-token" },
        },
      );
    const first = await worker.fetch(request(), runtimeEnv);
    const second = await worker.fetch(request(), runtimeEnv);
    expect(first.status).toBe(202);
    expect(second.status).toBe(202);
    await expect(first.json()).resolves.toMatchObject({ queued: 1 });
    await expect(second.json()).resolves.toMatchObject({ queued: 0 });
    const roots = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2
       WHERE dataset='jsda_tokyo_repo_rates' AND job_type='discover_root'`,
    ).first<{ n: number }>();
    expect(roots?.n).toBe(1);
  });

  it("persists invalid delivery evidence in R2 and D1 before ack", async () => {
    const result = await deliver(
      { version: "caller-controlled", url: "https://evil.test/payload" },
      "invalid-runtime-message",
    );
    expect(result.explicitAcks).toEqual(["invalid-runtime-message"]);
    expect(result.retryMessages).toEqual([]);

    const rejected = await runtimeEnv.DB.prepare(
      `SELECT reason_code, body_json, audit_receipt_key, audit_receipt_digest
       FROM jsda_queue_rejects_v2 WHERE message_id=?`,
    )
      .bind("invalid-runtime-message")
      .first<{
        reason_code: string;
        body_json: string;
        audit_receipt_key: string;
        audit_receipt_digest: string;
      }>();
    expect(rejected?.reason_code).toBe("invalid_job_schema");
    expect(rejected?.body_json).not.toContain("evil.test");
    expect(rejected?.audit_receipt_digest).toMatch(/^[0-9a-f]{64}$/);
    expect(await runtimeEnv.RAW_BUCKET.head(rejected?.audit_receipt_key ?? "missing")).not.toBeNull();
  });

  it("stores only an invalid-body shape summary, never caller values", async () => {
    const secret = "caller-secret-must-not-enter-d1";
    const result = await deliver(
      { version: "invalid", token: secret, nested: { password: secret } },
      "invalid-secret-message",
    );
    expect(result.explicitAcks).toEqual(["invalid-secret-message"]);
    const rejected = await runtimeEnv.DB.prepare(
      "SELECT body_json, body_digest FROM jsda_queue_rejects_v2 WHERE message_id=?",
    )
      .bind("invalid-secret-message")
      .first<{ body_json: string; body_digest: string }>();
    expect(rejected?.body_json).not.toContain(secret);
    expect(JSON.parse(rejected?.body_json ?? "{}")).toMatchObject({
      kind: "object",
      keys: ["nested", "token", "version"],
    });
    expect(rejected?.body_digest).toMatch(/^[0-9a-f]{64}$/);
  });

  it("does not ack an invalid delivery when the reject audit table is unavailable", async () => {
    await runtimeEnv.DB.exec("DROP TABLE jsda_queue_rejects_v2");
    const result = await deliver({ version: "invalid" }, "reject-store-down");
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((message) => message.msgId)).toEqual([
      "reject-store-down",
    ]);
  });

  it("advances a 30-child frontier in bounded continuations and completes", async () => {
    const root = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJob(runtimeEnv.DB, root);
    const frontier: ChildDescriptor[] = await Promise.all(
      Array.from({ length: 30 }, (_, index) =>
        descriptorForFile(
          `https://market.jsda.or.jp/archive/data/otc-${String(index).padStart(3, "0")}.csv`,
        ),
      ),
    );
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET state='queued', frontier_json=?, raw_key=?, content_digest=?
       WHERE work_key=?`,
    )
      .bind(
        JSON.stringify(frontier),
        "raw/jsda/test/index.html",
        "0".repeat(64),
        root.work_key,
      )
      .run();

    const first = await deliver(root, "frontier-first");
    expect(first.explicitAcks).toEqual(["frontier-first"]);
    const afterFirst = await loadJob(runtimeEnv.DB, root.work_key);
    expect(afterFirst).toMatchObject({ state: "queued", cursor: 25 });
    const firstChildCount = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2 WHERE parent_work_key=?",
    )
      .bind(root.work_key)
      .first<{ n: number }>();
    expect(firstChildCount?.n).toBe(25);

    const secondBody: JsdaQueueJob = continuationJob(root, 25, 1);
    const second = await deliver(secondBody, "frontier-second");
    expect(second.explicitAcks).toEqual(["frontier-second"]);
    const completed = await loadJob(runtimeEnv.DB, root.work_key);
    expect(completed).toMatchObject({ state: "completed", cursor: 30 });
    expect(completed?.audit_receipt_key).not.toBeNull();
    expect(await runtimeEnv.RAW_BUCKET.head(completed?.audit_receipt_key ?? "missing")).not.toBeNull();
    const finalChildCount = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2 WHERE parent_work_key=?",
    )
      .bind(root.work_key)
      .first<{ n: number }>();
    expect(finalChildCount?.n).toBe(30);
  });

  it("acks terminal work without fetching or duplicating it", async () => {
    const root = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJob(runtimeEnv.DB, root);
    const audit = await putQueueAuditReceipt(runtimeEnv.RAW_BUCKET, {
      event: "completed",
      work_key: root.work_key,
      run_key: root.run_key,
      dataset: root.dataset,
      job_type: root.job_type,
      segment_id: root.segment_id,
      target_url: root.target_url,
      parent_work_key: null,
      contract_digest: root.contract_digest,
      attempt: 1,
      cursor: 0,
      frontier_size: 1,
      raw_key: "raw/jsda/already-complete.html",
      content_digest: "2".repeat(64),
      reason_code: null,
      detail: "runtime terminal fixture",
      recorded_at: "2026-08-25T01:31:00.000Z",
    });
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET state='completed', completed_at=?, audit_receipt_key=?,
           audit_receipt_digest=?, content_digest=?, raw_key=?
       WHERE work_key=?`,
    )
      .bind(
        "2026-08-25T01:31:00.000Z",
        audit.key,
        audit.digest,
        "2".repeat(64),
        "raw/jsda/already-complete.html",
        root.work_key,
      )
      .run();
    const result = await deliver(root, "completed-duplicate");
    expect(result.explicitAcks).toEqual(["completed-duplicate"]);
    expect(result.retryMessages).toEqual([]);
    const events = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2 WHERE work_key=?",
    )
      .bind(root.work_key)
      .first<{ n: number }>();
    expect(events?.n).toBe(0);
  });

  it("does not ack a terminal D1 row whose R2 audit object is missing", async () => {
    const root = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "manual",
      "2026-08-25T02:00:00.000Z",
    );
    await registerJob(runtimeEnv.DB, root);
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET state='completed', completed_at=?, audit_receipt_key=?,
           audit_receipt_digest=? WHERE work_key=?`,
    )
      .bind(
        "2026-08-25T02:01:00.000Z",
        "audit/jsda/missing.json",
        "4".repeat(64),
        root.work_key,
      )
      .run();
    const result = await deliver(root, "missing-terminal-audit");
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((message) => message.msgId)).toEqual([
      "missing-terminal-audit",
    ]);
  });

  it("does not ack when the required run-log transaction fails", async () => {
    const root = await makeRootJob(
      "jsda_corporate_bond_transactions",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJob(runtimeEnv.DB, root);
    const frontier = [
      await descriptorForFile(
        "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/TORIHIKI2026.csv",
      ),
    ];
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET state='queued', frontier_json=?, raw_key=?, content_digest=?
       WHERE work_key=?`,
    )
      .bind(
        JSON.stringify(frontier),
        "raw/jsda/test/corporate-index.html",
        "3".repeat(64),
        root.work_key,
      )
      .run();
    await runtimeEnv.DB.exec("DROP TABLE ingestion_run_log");

    const result = await deliver(root, "run-log-down");
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((message) => message.msgId)).toEqual([
      "run-log-down",
    ]);
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("running");
  });
});
