import { env } from "cloudflare:workers";
import {
  applyD1Migrations,
  createExecutionContext,
  createMessageBatch,
  getQueueResult,
  reset,
} from "cloudflare:test";
import { beforeEach, describe, expect, inject, it } from "vitest";
import worker from "../src/index";
import type { JsdaWorkerEnv } from "../src/env";
import { loadJob, loadRunClosure, registerJob } from "../src/job_store";
import {
  descriptorForFile,
  JSDA_QUEUE_JOB_VERSION,
  makeRootJob,
  type ChildDescriptor,
  type JsdaQueueJob,
} from "../src/queue_contract";

const runtimeEnv = env as JsdaWorkerEnv;
const migrations = inject<Array<{ name: string; queries: string[] }>>(
  "jsdaD1Migrations",
);

beforeEach(async () => {
  await reset();
  await applyD1Migrations(runtimeEnv.DB, migrations);
});

const FILE_A = "https://market.jsda.or.jp/archive/data/otc-20020802.csv";

async function deliverOn(
  queue: string,
  body: unknown,
  id: string,
  attempts: number,
) {
  const batch = createMessageBatch(queue, [
    {
      id,
      timestamp: new Date("2026-08-25T01:30:00.000Z"),
      attempts,
      body,
    },
  ]);
  const ctx = createExecutionContext();
  await worker.queue(batch, runtimeEnv, ctx);
  return getQueueResult(batch, ctx);
}

async function childJob(workKey: string): Promise<JsdaQueueJob> {
  const row = await loadJob(runtimeEnv.DB, workKey);
  if (row === null) throw new Error(`missing child ${workKey}`);
  return {
    version: JSDA_QUEUE_JOB_VERSION,
    work_key: row.work_key,
    run_key: row.run_key,
    job_type: row.job_type,
    dataset: row.dataset,
    target_url: row.target_url,
    segment_id: row.segment_id,
    parent_work_key: row.parent_work_key,
    cursor: row.cursor,
    attempt: row.attempt,
    requested_by: row.requested_by,
    requested_at: row.requested_at,
    contract_digest: row.contract_digest,
  };
}

async function seedWaitingChild() {
  const root = await makeRootJob(
    "jsda_otc_bond_reference_prices",
    "cron",
    "2026-08-25T01:30:00.000Z",
  );
  await registerJob(runtimeEnv.DB, root);
  const frontier: ChildDescriptor[] = [await descriptorForFile(FILE_A)];
  await runtimeEnv.DB.prepare(
    `UPDATE jsda_acquisition_jobs_v2
     SET state='queued', frontier_json=?, raw_key=?, content_digest=?
     WHERE work_key=?`,
  )
    .bind(
      JSON.stringify(frontier),
      "raw/jsda/test/dlq-index.html",
      "a".repeat(64),
      root.work_key,
    )
    .run();
  const seeded = await deliverOn(
    "quant-jsda-ingestion-test",
    root,
    "dlq-seed-root",
    1,
  );
  expect(seeded.explicitAcks).toEqual(["dlq-seed-root"]);
  const children = await runtimeEnv.DB.prepare(
    `SELECT work_key FROM jsda_acquisition_jobs_v2 WHERE parent_work_key=?`,
  )
    .bind(root.work_key)
    .all<{ work_key: string }>();
  return { root, childKey: children.results[0].work_key };
}

async function passCount(runKey: string): Promise<number> {
  const row = await runtimeEnv.DB.prepare(
    `SELECT COUNT(*) AS n FROM ingestion_run_log
      WHERE status='pass' AND json_extract(detail, '$.run_id')=?`,
  )
    .bind(runKey)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

describe("JSDA DLQ terminal convergence", () => {
  it("keeps retries on the primary queue nonterminal", async () => {
    const { root, childKey } = await seedWaitingChild();
    const original = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(null, { status: 500 })) as typeof fetch;
    try {
      for (const attempt of [1, 2, 3] as const) {
        const result = await deliverOn(
          "quant-jsda-ingestion-test",
          await childJob(childKey),
          `primary-retry-${attempt}`,
          attempt,
        );
        expect(result.explicitAcks).toEqual([]);
        expect(result.retryMessages.map((message) => message.msgId)).toEqual([
          `primary-retry-${attempt}`,
        ]);
        expect((await loadJob(runtimeEnv.DB, childKey))?.state).toBe(
          "failed_transient",
        );
        expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe(
          "waiting_children",
        );
        expect(await passCount(root.run_key)).toBe(0);
      }
    } finally {
      globalThis.fetch = original;
    }
  });

  it("terminalizes child and root exactly once on simulated DLQ delivery", async () => {
    const { root, childKey } = await seedWaitingChild();
    const original = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(null, { status: 500 })) as typeof fetch;
    try {
      await deliverOn(
        "quant-jsda-ingestion-test",
        await childJob(childKey),
        "dlq-primary-fail",
        1,
      );
    } finally {
      globalThis.fetch = original;
    }
    expect((await loadJob(runtimeEnv.DB, childKey))?.state).toBe("failed_transient");

    const first = await deliverOn(
      "quant-jsda-ingestion-dlq-test",
      await childJob(childKey),
      "dlq-first",
      1,
    );
    expect(first.explicitAcks).toEqual(["dlq-first"]);
    expect((await loadJob(runtimeEnv.DB, childKey))?.state).toBe("rejected");
    expect((await loadJob(runtimeEnv.DB, childKey))?.last_error).toMatch(
      /dead-lettered on quant-jsda-ingestion-dlq-test after 1 attempts/,
    );
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("rejected");
    expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
      "failed",
    );
    expect(await passCount(root.run_key)).toBe(0);

    const second = await deliverOn(
      "quant-jsda-ingestion-dlq-test",
      await childJob(childKey),
      "dlq-second",
      2,
    );
    expect(second.explicitAcks).toEqual(["dlq-second"]);
    const rejectEvents = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2
        WHERE work_key=? AND result='rejected' AND reason_code='dead_lettered'`,
    )
      .bind(childKey)
      .first<{ n: number }>();
    expect(rejectEvents?.n).toBe(1);
    expect(await passCount(root.run_key)).toBe(0);
  });

  it("retries without ack when DLQ evidence cannot be written to D1", async () => {
    const { childKey } = await seedWaitingChild();
    await runtimeEnv.DB.exec("DROP TABLE jsda_acquisition_events_v2");
    const result = await deliverOn(
      "quant-jsda-ingestion-dlq-test",
      await childJob(childKey),
      "dlq-d1-down",
      4,
    );
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((message) => message.msgId)).toEqual([
      "dlq-d1-down",
    ]);
    expect((await loadJob(runtimeEnv.DB, childKey))?.state).not.toBe("completed");
  });

  it("does not terminalize or ack a DLQ leaf whose observation is missing", async () => {
    const { root, childKey } = await seedWaitingChild();
    await runtimeEnv.DB.prepare(
      "DELETE FROM jsda_observations WHERE observation_key=?",
    )
      .bind(childKey)
      .run();
    const result = await deliverOn(
      "quant-jsda-ingestion-dlq-test",
      await childJob(childKey),
      "dlq-observation-missing",
      4,
    );
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((message) => message.msgId)).toEqual([
      "dlq-observation-missing",
    ]);
    expect((await loadJob(runtimeEnv.DB, childKey))?.state).toBe("queued");
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe(
      "waiting_children",
    );
    expect(await passCount(root.run_key)).toBe(0);
  });

  it("records invalid DLQ deliveries as reject evidence before ack", async () => {
    const result = await deliverOn(
      "quant-jsda-ingestion-dlq-test",
      { version: "invalid" },
      "dlq-invalid",
      4,
    );
    expect(result.explicitAcks).toEqual(["dlq-invalid"]);
    const rejected = await runtimeEnv.DB.prepare(
      "SELECT reason_code FROM jsda_queue_rejects_v2 WHERE message_id=?",
    )
      .bind("dlq-invalid")
      .first<{ reason_code: string }>();
    expect(rejected?.reason_code).toBe("dead_letter_invalid_job_schema");
  });

  it("rejects an unregistered DLQ job without creating acquisition state", async () => {
    const root = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "manual",
      "2026-08-25T05:00:00.000Z",
    );
    const result = await deliverOn(
      "quant-jsda-ingestion-dlq-test",
      root,
      "dlq-unregistered",
      4,
    );
    expect(result.explicitAcks).toEqual(["dlq-unregistered"]);
    expect(await loadJob(runtimeEnv.DB, root.work_key)).toBeNull();
    expect(await loadRunClosure(runtimeEnv.DB, root.run_key)).toBeNull();
    const rejected = await runtimeEnv.DB.prepare(
      "SELECT reason_code FROM jsda_queue_rejects_v2 WHERE message_id=?",
    )
      .bind("dlq-unregistered")
      .first<{ reason_code: string }>();
    expect(rejected?.reason_code).toBe("dead_letter_unregistered_job");
  });
});
