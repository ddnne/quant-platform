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
import {
  claimJob,
  completeJob,
  loadJob,
  loadRunClosure,
  registerJob,
  registerJobs,
} from "../src/job_store";
import {
  continuationJob,
  descriptorForFile,
  descriptorForYear,
  JSDA_QUEUE_JOB_VERSION,
  makeChildJob,
  makeRootJob,
  sourceObjectId,
  type ChildDescriptor,
  type JsdaQueueJob,
} from "../src/queue_contract";
import { enqueueRoots } from "../src/queue_producer";
import { putImmutableRaw, putQueueAuditReceipt } from "../src/raw_store";
import { sha256Hex } from "../src/sha256";

const runtimeEnv = env as JsdaWorkerEnv;
const migrations = inject<
  Array<{ name: string; queries: string[] }>
>("jsdaD1Migrations");

beforeEach(async () => {
  await reset();
  await applyD1Migrations(runtimeEnv.DB, migrations);
});

const ROLLING_URL =
  "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trrts.xls";
const ARCHIVE_URL =
  "https://market.jsda.or.jp/archive/data/otc-20020802.csv";

function mockOfficialFetch(bodies: Record<string, string>): () => void {
  const original = globalThis.fetch;
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input instanceof Request ? input.url : input);
    const body = bodies[url];
    if (body === undefined) return new Response(null, { status: 404 });
    return new Response(body, {
      status: 200,
      headers: { "content-type": "application/octet-stream" },
    });
  }) as typeof fetch;
  return () => {
    globalThis.fetch = original;
  };
}

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

  it("rejects an existing R2 object whose metadata digest hides a different body", async () => {
    const body = new TextEncoder().encode("authoritative-jsda-body").buffer;
    const first = await putImmutableRaw(
      runtimeEnv.RAW_BUCKET,
      "jsda_otc_bond_reference_prices",
      "metadata-collision",
      "csv",
      body,
      "text/csv",
      { kind: "data" },
    );
    await runtimeEnv.RAW_BUCKET.put(first.key, "forged-body", {
      customMetadata: { sha256: first.digest },
    });

    await expect(
      putImmutableRaw(
        runtimeEnv.RAW_BUCKET,
        "jsda_otc_bond_reference_prices",
        "metadata-collision",
        "csv",
        body,
        "text/csv",
        { kind: "data" },
      ),
    ).rejects.toThrow("immutable R2 collision or unverifiable object");
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

  it("revisits a year index in each run while preserving both discovery edges", async () => {
    const firstRoot = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const secondRoot = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJobs(runtimeEnv.DB, [firstRoot, secondRoot]);
    const descriptor = await descriptorForYear(
      "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/archive2026.html",
    );
    const firstYear = await makeChildJob(firstRoot, descriptor);
    const secondYear = await makeChildJob(secondRoot, descriptor);
    await registerJobs(runtimeEnv.DB, [firstYear]);
    await registerJobs(runtimeEnv.DB, [secondYear]);
    const years = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2
        WHERE dataset=? AND job_type='discover_year' AND target_url=?`,
    )
      .bind(firstRoot.dataset, descriptor.target_url)
      .first<{ n: number }>();
    expect(years?.n).toBe(2);
    const edges = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_discoveries_v2
        WHERE child_work_key IN (?, ?)`,
    )
      .bind(firstYear.work_key, secondYear.work_key)
      .first<{ n: number }>();
    expect(edges?.n).toBe(2);
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

  it("rejects a schema-valid unregistered delivery without creating graph rows", async () => {
    const root = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "manual",
      "2026-08-25T04:00:00.000Z",
    );
    const result = await deliver(root, "unregistered-runtime-message");
    expect(result.explicitAcks).toEqual(["unregistered-runtime-message"]);
    expect(await loadJob(runtimeEnv.DB, root.work_key)).toBeNull();
    expect(await loadRunClosure(runtimeEnv.DB, root.run_key)).toBeNull();
    const rejected = await runtimeEnv.DB.prepare(
      "SELECT reason_code FROM jsda_queue_rejects_v2 WHERE message_id=?",
    )
      .bind("unregistered-runtime-message")
      .first<{ reason_code: string }>();
    expect(rejected?.reason_code).toBe("unregistered_job");
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

  it("advances a 30-child frontier in bounded continuations then waits for descendants", async () => {
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
    const waiting = await loadJob(runtimeEnv.DB, root.work_key);
    expect(waiting).toMatchObject({ state: "waiting_children", cursor: 30 });
    expect(waiting?.audit_receipt_key).not.toBeNull();
    expect(await runtimeEnv.RAW_BUCKET.head(waiting?.audit_receipt_key ?? "missing")).not.toBeNull();
    const runClosure = await loadRunClosure(runtimeEnv.DB, root.run_key);
    expect(runClosure).toMatchObject({
      closure_state: "waiting_children",
      frontier_exhausted: 1,
      descendant_total: 30,
      descendant_nonterminal: 30,
    });
    const runLog = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM ingestion_run_log
        WHERE status='pass' AND json_extract(detail, '$.run_id')=?`,
    )
      .bind(root.run_key)
      .first<{ n: number }>();
    expect(runLog?.n).toBe(0);
    const finalChildCount = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2 WHERE parent_work_key=?",
    )
      .bind(root.work_key)
      .first<{ n: number }>();
    expect(finalChildCount?.n).toBe(30);
    const discoveryEdges = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_discoveries_v2 WHERE parent_work_key=?",
    )
      .bind(root.work_key)
      .first<{ n: number }>();
    expect(discoveryEdges?.n).toBe(30);
  });

  it("acks terminal work without fetching or duplicating it", async () => {
    const root = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJob(runtimeEnv.DB, root);
    const terminal = await makeChildJob(
      root,
      await descriptorForFile(
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trrts.xls",
      ),
    );
    await registerJob(runtimeEnv.DB, terminal);
    const terminalBody = new TextEncoder().encode("terminal fixture");
    const terminalDigest = await sha256Hex(terminalBody);
    const audit = await putQueueAuditReceipt(runtimeEnv.RAW_BUCKET, {
      event: "completed",
      work_key: terminal.work_key,
      run_key: terminal.run_key,
      dataset: terminal.dataset,
      job_type: terminal.job_type,
      segment_id: terminal.segment_id,
      target_url: terminal.target_url,
      parent_work_key: terminal.parent_work_key,
      contract_digest: terminal.contract_digest,
      attempt: 1,
      cursor: 0,
      frontier_size: 1,
      raw_key: "raw/jsda/already-complete.html",
      content_digest: terminalDigest,
      reason_code: null,
      detail: "runtime terminal fixture",
      recorded_at: "2026-08-25T01:31:00.000Z",
    });
    await runtimeEnv.RAW_BUCKET.put(
      "raw/jsda/already-complete.html",
      terminalBody,
      { customMetadata: { sha256: terminalDigest } },
    );
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
        terminalDigest,
        "raw/jsda/already-complete.html",
        terminal.work_key,
      )
      .run();
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_observations
          SET state='completed', content_digest=?, raw_key=?, observed_at=?, updated_at=?
        WHERE observation_key=? AND work_key=?`,
    )
      .bind(
        terminalDigest,
        "raw/jsda/already-complete.html",
        "2026-08-25T01:31:00.000Z",
        "2026-08-25T01:31:00.000Z",
        terminal.work_key,
        terminal.work_key,
      )
      .run();
    const result = await deliver(terminal, "completed-duplicate");
    expect(result.explicitAcks).toEqual(["completed-duplicate"]);
    expect(result.retryMessages).toEqual([]);
    const events = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2 WHERE work_key=?",
    )
      .bind(terminal.work_key)
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
    await runtimeEnv.DB.exec("DROP TABLE jsda_acquisition_events_v2");

    const result = await deliver(root, "run-log-down");
    expect(result.explicitAcks).toEqual([]);
    expect(result.retryMessages.map((message) => message.msgId)).toEqual([
      "run-log-down",
    ]);
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("running");
  });

  it("fences a stale claimant from terminal state and event writes", async () => {
    const root = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "manual",
      "2026-08-25T03:00:00.000Z",
    );
    await registerJob(runtimeEnv.DB, root);
    const child = await makeChildJob(root, await descriptorForFile(ROLLING_URL));
    await registerJobs(runtimeEnv.DB, [child]);
    const first = await claimJob(
      runtimeEnv.DB,
      child.work_key,
      "2026-08-25T03:00:01.000Z",
      "2026-08-25T03:00:02.000Z",
    );
    expect(first?.attempt).toBe(1);
    const second = await claimJob(
      runtimeEnv.DB,
      child.work_key,
      "2026-08-25T03:00:03.000Z",
      "2026-08-25T03:15:03.000Z",
    );
    expect(second?.attempt).toBe(2);
    const audit = await putQueueAuditReceipt(runtimeEnv.RAW_BUCKET, {
      event: "completed",
      work_key: child.work_key,
      run_key: child.run_key,
      dataset: child.dataset,
      job_type: child.job_type,
      segment_id: child.segment_id,
      target_url: child.target_url,
      parent_work_key: child.parent_work_key,
      contract_digest: child.contract_digest,
      attempt: 1,
      cursor: 0,
      frontier_size: 0,
      raw_key: "raw/jsda/stale/file.xls",
      content_digest: "5".repeat(64),
      reason_code: null,
      detail: "stale claimant must not finalize",
      recorded_at: "2026-08-25T03:00:04.000Z",
    });
    await expect(
      completeJob(
        runtimeEnv.DB,
        { ...first!, raw_key: "raw/jsda/stale/file.xls", content_digest: "5".repeat(64) },
        0,
        audit,
        "2026-08-25T03:00:04.000Z",
      ),
    ).rejects.toThrow("lost job claim");
    expect(await loadJob(runtimeEnv.DB, child.work_key)).toMatchObject({
      state: "running",
      attempt: 2,
    });
    const events = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2 WHERE work_key=?",
    )
      .bind(child.work_key)
      .first<{ n: number }>();
    expect(events?.n).toBe(0);
  });

  it("re-observes a rolling locator A then B then B across three runs", async () => {
    const bytesA = "rolling-content-A";
    const bytesB = "rolling-content-B";
    const digestA = await sha256Hex(new TextEncoder().encode(bytesA));
    const digestB = await sha256Hex(new TextEncoder().encode(bytesB));
    const restore = mockOfficialFetch({ [ROLLING_URL]: bytesA });
    const workKeys: string[] = [];
    try {
      for (const [day, body] of [
        ["24", bytesA],
        ["25", bytesB],
        ["26", bytesB],
      ] as const) {
        restore();
        mockOfficialFetch({ [ROLLING_URL]: body });
        const root = await makeRootJob(
          "jsda_tokyo_repo_rates",
          "cron",
          `2026-08-${day}T01:30:00.000Z`,
        );
        await registerJob(runtimeEnv.DB, root);
        const child = await makeChildJob(
          root,
          await descriptorForFile(ROLLING_URL),
        );
        await registerJobs(runtimeEnv.DB, [child]);
        workKeys.push(child.work_key);
        const result = await deliver(child, `rolling-${day}`);
        expect(result.explicitAcks).toEqual([`rolling-${day}`]);
        expect(result.retryMessages).toEqual([]);
      }
    } finally {
      restore();
    }

    expect(new Set(workKeys).size).toBe(3);
    const objectId = await sourceObjectId("jsda_tokyo_repo_rates", ROLLING_URL);
    const observations = await runtimeEnv.DB.prepare(
      `SELECT observation_key, content_digest, state
         FROM jsda_observations
        WHERE source_object_id=?`,
    )
      .bind(objectId)
      .all<{ observation_key: string; content_digest: string; state: string }>();
    expect(observations.results).toHaveLength(3);
    const digestByKey = new Map(
      observations.results.map((row) => [row.observation_key, row.content_digest]),
    );
    expect(observations.results.every((row) => row.state === "completed")).toBe(true);
    expect(digestByKey.get(workKeys[0])).toBe(digestA);
    expect(digestByKey.get(workKeys[1])).toBe(digestB);
    expect(digestByKey.get(workKeys[2])).toBe(digestB);
    const artifacts = await runtimeEnv.DB.prepare(
      `SELECT DISTINCT o.content_digest, o.raw_key
         FROM jsda_observations o
        WHERE o.source_object_id=? AND o.content_digest IS NOT NULL`,
    )
      .bind(objectId)
      .all<{ content_digest: string; raw_key: string }>();
    expect(new Set(artifacts.results.map((row) => row.content_digest))).toEqual(
      new Set([digestA, digestB]),
    );
    expect(new Set(artifacts.results.map((row) => row.raw_key)).size).toBe(2);
    const digestRows = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_artifacts
        WHERE content_digest IN (?, ?)`,
    )
      .bind(digestA, digestB)
      .first<{ n: number }>();
    expect(digestRows?.n).toBe(2);
    expect(
      await runtimeEnv.RAW_BUCKET.head(artifacts.results[0]?.raw_key ?? "missing"),
    ).not.toBeNull();
    expect(
      await runtimeEnv.RAW_BUCKET.head(artifacts.results[1]?.raw_key ?? "missing"),
    ).not.toBeNull();
    const source = await runtimeEnv.DB.prepare(
      `SELECT current_digest, current_observation_key, current_observation_seq
         FROM jsda_source_objects WHERE source_object_id=?`,
    )
      .bind(objectId)
      .first<{
        current_digest: string;
        current_observation_key: string;
        current_observation_seq: number;
      }>();
    expect(source?.current_digest).toBe(digestB);
    expect(source?.current_observation_key).toBe(workKeys[2]);
    expect(source?.current_observation_seq).toBe(3);
  });

  it("acks rolling redelivery without a second observation or artifact", async () => {
    const body = "stable-rolling-bytes";
    const restore = mockOfficialFetch({ [ROLLING_URL]: body });
    try {
      const root = await makeRootJob(
        "jsda_tokyo_repo_rates",
        "cron",
        "2026-08-25T01:30:00.000Z",
      );
      await registerJob(runtimeEnv.DB, root);
      const child = await makeChildJob(root, await descriptorForFile(ROLLING_URL));
      await registerJobs(runtimeEnv.DB, [child]);
      const first = await deliver(child, "rolling-first");
      const second = await deliver(child, "rolling-redeliver");
      expect(first.explicitAcks).toEqual(["rolling-first"]);
      expect(second.explicitAcks).toEqual(["rolling-redeliver"]);
      expect(second.retryMessages).toEqual([]);
      const objectId = await sourceObjectId("jsda_tokyo_repo_rates", ROLLING_URL);
      const observations = await runtimeEnv.DB.prepare(
        "SELECT COUNT(*) AS n FROM jsda_observations WHERE source_object_id=?",
      )
        .bind(objectId)
        .first<{ n: number }>();
      const artifacts = await runtimeEnv.DB.prepare(
        `SELECT COUNT(*) AS n FROM jsda_artifacts
          WHERE content_digest IN (
            SELECT content_digest FROM jsda_observations WHERE source_object_id=?
          )`,
      )
        .bind(objectId)
        .first<{ n: number }>();
      expect(observations?.n).toBe(1);
      expect(artifacts?.n).toBe(1);
    } finally {
      restore();
    }
  });

  it("does not ack a rolling fetch when observation evidence cannot be written", async () => {
    const restore = mockOfficialFetch({ [ROLLING_URL]: "evidence-failure" });
    try {
      const root = await makeRootJob(
        "jsda_tokyo_repo_rates",
        "manual",
        "2026-08-25T04:00:00.000Z",
      );
      await registerJob(runtimeEnv.DB, root);
      const child = await makeChildJob(root, await descriptorForFile(ROLLING_URL));
      await registerJobs(runtimeEnv.DB, [child]);
      await runtimeEnv.DB.exec("DROP TABLE jsda_artifacts");
      const result = await deliver(child, "rolling-evidence-down");
      expect(result.explicitAcks).toEqual([]);
      expect(result.retryMessages.map((message) => message.msgId)).toEqual([
        "rolling-evidence-down",
      ]);
      expect((await loadJob(runtimeEnv.DB, child.work_key))?.state).not.toBe(
        "completed",
      );
      const observation = await runtimeEnv.DB.prepare(
        "SELECT state FROM jsda_observations WHERE observation_key=?",
      )
        .bind(child.work_key)
        .first<{ state: string }>();
      expect(observation?.state).not.toBe("completed");
    } finally {
      restore();
    }
  });

  it("keeps archive files unique by URL while rolling files re-observe per run", async () => {
    const firstOtc = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const secondOtc = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    const firstRepo = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const secondRepo = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJobs(runtimeEnv.DB, [firstOtc, secondOtc, firstRepo, secondRepo]);
    const archive = await descriptorForFile(ARCHIVE_URL);
    const rolling = await descriptorForFile(ROLLING_URL);
    await registerJobs(runtimeEnv.DB, [
      await makeChildJob(firstOtc, archive),
      await makeChildJob(secondOtc, archive),
      await makeChildJob(firstRepo, rolling),
      await makeChildJob(secondRepo, rolling),
    ]);
    const archiveJobs = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2
        WHERE dataset=? AND job_type='fetch_file' AND target_url=?`,
    )
      .bind(firstOtc.dataset, archive.target_url)
      .first<{ n: number }>();
    const rollingJobs = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2
        WHERE dataset=? AND job_type='fetch_file' AND target_url=?`,
    )
      .bind(firstRepo.dataset, rolling.target_url)
      .first<{ n: number }>();
    expect(archiveJobs?.n).toBe(1);
    expect(rollingJobs?.n).toBe(2);
    const archiveObs = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_observations
        WHERE dataset=? AND target_url=?`,
    )
      .bind(firstOtc.dataset, archive.target_url)
      .first<{ n: number }>();
    const rollingObs = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_observations
        WHERE dataset=? AND target_url=?`,
    )
      .bind(firstRepo.dataset, rolling.target_url)
      .first<{ n: number }>();
    expect(archiveObs?.n).toBe(1);
    expect(rollingObs?.n).toBe(2);
  });

  it("keeps current on B when A is registered first but completes after B", async () => {
    const bytesA = "delayed-older-A";
    const bytesB = "newer-winner-B";
    const digestA = await sha256Hex(new TextEncoder().encode(bytesA));
    const digestB = await sha256Hex(new TextEncoder().encode(bytesB));
    const rootA = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const rootB = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJobs(runtimeEnv.DB, [rootA, rootB]);
    const childA = await makeChildJob(rootA, await descriptorForFile(ROLLING_URL));
    const childB = await makeChildJob(rootB, await descriptorForFile(ROLLING_URL));
    await registerJobs(runtimeEnv.DB, [childA]);
    await registerJobs(runtimeEnv.DB, [childB]);
    const restoreB = mockOfficialFetch({ [ROLLING_URL]: bytesB });
    try {
      expect((await deliver(childB, "complete-B-first")).explicitAcks).toEqual([
        "complete-B-first",
      ]);
    } finally {
      restoreB();
    }
    const restoreA = mockOfficialFetch({ [ROLLING_URL]: bytesA });
    try {
      expect((await deliver(childA, "complete-A-late")).explicitAcks).toEqual([
        "complete-A-late",
      ]);
    } finally {
      restoreA();
    }
    const objectId = await sourceObjectId("jsda_tokyo_repo_rates", ROLLING_URL);
    const source = await runtimeEnv.DB.prepare(
      `SELECT current_digest, current_observation_key, current_observation_seq
         FROM jsda_source_objects WHERE source_object_id=?`,
    )
      .bind(objectId)
      .first<{
        current_digest: string;
        current_observation_key: string;
        current_observation_seq: number;
      }>();
    expect(source?.current_digest).toBe(digestB);
    expect(source?.current_observation_key).toBe(childB.work_key);
    expect(source?.current_observation_seq).toBe(2);
    const seq = await runtimeEnv.DB.prepare(
      `SELECT observation_key, observation_seq, content_digest, state
         FROM jsda_observations WHERE source_object_id=? ORDER BY observation_seq`,
    )
      .bind(objectId)
      .all<{
        observation_key: string;
        observation_seq: number;
        content_digest: string;
        state: string;
      }>();
    expect(seq.results).toEqual([
      {
        observation_key: childA.work_key,
        observation_seq: 1,
        content_digest: digestA,
        state: "completed",
      },
      {
        observation_key: childB.work_key,
        observation_seq: 2,
        content_digest: digestB,
        state: "completed",
      },
    ]);
  });

  it("treats an equal-sequence retry as idempotent and exact", async () => {
    const body = "equal-retry-bytes";
    const digest = await sha256Hex(new TextEncoder().encode(body));
    const restore = mockOfficialFetch({ [ROLLING_URL]: body });
    try {
      const root = await makeRootJob(
        "jsda_tokyo_repo_rates",
        "cron",
        "2026-08-25T01:30:00.000Z",
      );
      await registerJob(runtimeEnv.DB, root);
      const child = await makeChildJob(root, await descriptorForFile(ROLLING_URL));
      await registerJobs(runtimeEnv.DB, [child]);
      expect((await deliver(child, "equal-first")).explicitAcks).toEqual(["equal-first"]);
      expect((await deliver(child, "equal-retry")).explicitAcks).toEqual(["equal-retry"]);
      const objectId = await sourceObjectId("jsda_tokyo_repo_rates", ROLLING_URL);
      const source = await runtimeEnv.DB.prepare(
        `SELECT current_digest, current_raw_key, current_observation_key,
                current_observation_seq
           FROM jsda_source_objects WHERE source_object_id=?`,
      )
        .bind(objectId)
        .first<{
          current_digest: string;
          current_raw_key: string;
          current_observation_key: string;
          current_observation_seq: number;
        }>();
      const observation = await runtimeEnv.DB.prepare(
        `SELECT raw_key, content_digest FROM jsda_observations WHERE observation_key=?`,
      )
        .bind(child.work_key)
        .first<{ raw_key: string; content_digest: string }>();
      expect(source).toMatchObject({
        current_digest: digest,
        current_raw_key: observation?.raw_key,
        current_observation_key: child.work_key,
        current_observation_seq: 1,
      });
      const count = await runtimeEnv.DB.prepare(
        "SELECT COUNT(*) AS n FROM jsda_observations WHERE source_object_id=?",
      )
        .bind(objectId)
        .first<{ n: number }>();
      expect(count?.n).toBe(1);
    } finally {
      restore();
    }
  });

  it("does not let a rejected older observation replace current", async () => {
    const bytesB = "current-keeper-B";
    const digestB = await sha256Hex(new TextEncoder().encode(bytesB));
    const rootA = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const rootB = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJobs(runtimeEnv.DB, [rootA, rootB]);
    const childA = await makeChildJob(rootA, await descriptorForFile(ROLLING_URL));
    const childB = await makeChildJob(rootB, await descriptorForFile(ROLLING_URL));
    await registerJobs(runtimeEnv.DB, [childA]);
    await registerJobs(runtimeEnv.DB, [childB]);
    const restoreB = mockOfficialFetch({ [ROLLING_URL]: bytesB });
    try {
      expect((await deliver(childB, "reject-older-complete-B")).explicitAcks).toEqual([
        "reject-older-complete-B",
      ]);
    } finally {
      restoreB();
    }
    const original = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response("gone", { status: 410 })) as typeof fetch;
    try {
      expect((await deliver(childA, "reject-older-A")).explicitAcks).toEqual([
        "reject-older-A",
      ]);
    } finally {
      globalThis.fetch = original;
    }
    const objectId = await sourceObjectId("jsda_tokyo_repo_rates", ROLLING_URL);
    const source = await runtimeEnv.DB.prepare(
      `SELECT current_digest, current_observation_key, current_observation_seq
         FROM jsda_source_objects WHERE source_object_id=?`,
    )
      .bind(objectId)
      .first<{
        current_digest: string;
        current_observation_key: string;
        current_observation_seq: number;
      }>();
    expect(source).toMatchObject({
      current_digest: digestB,
      current_observation_key: childB.work_key,
      current_observation_seq: 2,
    });
    expect((await loadJob(runtimeEnv.DB, childA.work_key))?.state).toBe("rejected");
  });

  it("keeps one digest row for identical bytes observed from two source objects", async () => {
    const bytes = "shared-content-bytes";
    const digest = await sha256Hex(new TextEncoder().encode(bytes));
    const urlA = "https://market.jsda.or.jp/archive/data/otc-20020802.csv";
    const urlB = "https://market.jsda.or.jp/archive/data/otc-20020805.csv";
    const restore = mockOfficialFetch({ [urlA]: bytes, [urlB]: bytes });
    try {
      const root = await makeRootJob(
        "jsda_otc_bond_reference_prices",
        "cron",
        "2026-08-25T01:30:00.000Z",
      );
      await registerJob(runtimeEnv.DB, root);
      const childA = await makeChildJob(root, await descriptorForFile(urlA));
      const childB = await makeChildJob(root, await descriptorForFile(urlB));
      await registerJobs(runtimeEnv.DB, [childA, childB]);
      expect((await deliver(childA, "shared-a")).explicitAcks).toEqual(["shared-a"]);
      expect((await deliver(childB, "shared-b")).explicitAcks).toEqual(["shared-b"]);
      const artifacts = await runtimeEnv.DB.prepare(
        "SELECT COUNT(*) AS n FROM jsda_artifacts WHERE content_digest=?",
      )
        .bind(digest)
        .first<{ n: number }>();
      const locations = await runtimeEnv.DB.prepare(
        "SELECT COUNT(*) AS n FROM jsda_artifact_locations WHERE content_digest=?",
      )
        .bind(digest)
        .first<{ n: number }>();
      const observations = await runtimeEnv.DB.prepare(
        `SELECT COUNT(*) AS n FROM jsda_observations
          WHERE content_digest=? AND state='completed'`,
      )
        .bind(digest)
        .first<{ n: number }>();
      expect(artifacts?.n).toBe(1);
      expect(locations?.n).toBe(2);
      expect(observations?.n).toBe(2);
      const columns = await runtimeEnv.DB.prepare(
        "PRAGMA table_info(jsda_artifacts)",
      ).all<{ name: string }>();
      expect(columns.results.map((row) => row.name)).toEqual([
        "content_digest",
        "first_seen_at",
      ]);
    } finally {
      restore();
    }
  });
});

describe("JSDA descendant run closure", () => {
  async function seedWaitingRoot(fileUrls: string[]) {
    const root = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJob(runtimeEnv.DB, root);
    const frontier: ChildDescriptor[] = await Promise.all(
      fileUrls.map((url) => descriptorForFile(url)),
    );
    const discoveryBody = new TextEncoder().encode("closure discovery fixture");
    const discoveryDigest = await sha256Hex(discoveryBody);
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_acquisition_jobs_v2
       SET state='queued', frontier_json=?, raw_key=?, content_digest=?
       WHERE work_key=?`,
    )
      .bind(
        JSON.stringify(frontier),
        "raw/jsda/test/closure-index.html",
        discoveryDigest,
        root.work_key,
      )
      .run();
    await runtimeEnv.RAW_BUCKET.put(
      "raw/jsda/test/closure-index.html",
      discoveryBody,
      { customMetadata: { sha256: discoveryDigest } },
    );
    const result = await deliver(root, "seed-waiting-root");
    expect(result.explicitAcks).toEqual(["seed-waiting-root"]);
    const waiting = await loadJob(runtimeEnv.DB, root.work_key);
    expect(waiting?.state).toBe("waiting_children");
    const children = await runtimeEnv.DB.prepare(
      `SELECT work_key, target_url FROM jsda_acquisition_jobs_v2
        WHERE parent_work_key=? ORDER BY target_url`,
    )
      .bind(root.work_key)
      .all<{ work_key: string; target_url: string }>();
    return { root, children: children.results };
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

  const FILE_A = "https://market.jsda.or.jp/archive/data/otc-20020802.csv";
  const FILE_B = "https://market.jsda.or.jp/archive/data/otc-20020805.csv";

  it("keeps a root nonterminal while a child is still queued", async () => {
    const { root } = await seedWaitingRoot([FILE_A]);
    const closure = await loadRunClosure(runtimeEnv.DB, root.run_key);
    expect(closure).toMatchObject({
      closure_state: "waiting_children",
      descendant_total: 1,
      descendant_completed: 0,
      descendant_nonterminal: 1,
    });
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("waiting_children");
  });

  it("does not publish run PASS when a leaf succeeds while a sibling is queued", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A, FILE_B]);
    const restore = mockOfficialFetch({ [FILE_A]: "leaf-only" });
    try {
      expect(
        (await deliver(await childJob(children[0].work_key), "leaf-only")).explicitAcks,
      ).toEqual(["leaf-only"]);
    } finally {
      restore();
    }
    expect((await loadJob(runtimeEnv.DB, children[0].work_key))?.state).toBe("completed");
    expect((await loadJob(runtimeEnv.DB, children[1].work_key))?.state).toBe("queued");
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("waiting_children");
    expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
      "waiting_children",
    );
    const passLogs = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM ingestion_run_log
        WHERE status='pass' AND json_extract(detail, '$.run_id')=?`,
    )
      .bind(root.run_key)
      .first<{ n: number }>();
    expect(passLogs?.n).toBe(0);
  });

  it("keeps a root nonterminal while a child is in transient retry", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A]);
    const original = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(null, { status: 500 })) as typeof fetch;
    try {
      const result = await deliver(await childJob(children[0].work_key), "child-500");
      expect(result.explicitAcks).toEqual([]);
      expect(result.retryMessages.map((message) => message.msgId)).toEqual(["child-500"]);
    } finally {
      globalThis.fetch = original;
    }
    expect((await loadJob(runtimeEnv.DB, children[0].work_key))?.state).toBe(
      "failed_transient",
    );
    const closure = await loadRunClosure(runtimeEnv.DB, root.run_key);
    expect(closure?.closure_state).toBe("waiting_children");
    expect(closure?.descendant_failed_transient).toBe(1);
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("waiting_children");
  });

  it("closes the root once after every child succeeds", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A, FILE_B]);
    const restore = mockOfficialFetch({
      [FILE_A]: "child-A-bytes",
      [FILE_B]: "child-B-bytes",
    });
    try {
      expect(
        (await deliver(await childJob(children[0].work_key), "child-A")).explicitAcks,
      ).toEqual(["child-A"]);
      expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("waiting_children");
      expect(
        (await deliver(await childJob(children[1].work_key), "child-B")).explicitAcks,
      ).toEqual(["child-B"]);
    } finally {
      restore();
    }
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("completed");
    const closure = await loadRunClosure(runtimeEnv.DB, root.run_key);
    expect(closure).toMatchObject({
      closure_state: "completed",
      descendant_total: 2,
      descendant_completed: 2,
      descendant_nonterminal: 0,
    });
    const completedEvents = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2
        WHERE work_key=? AND result='completed'`,
    )
      .bind(root.work_key)
      .first<{ n: number }>();
    expect(completedEvents?.n).toBe(1);
    const passLogs = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM ingestion_run_log
        WHERE status='pass' AND json_extract(detail, '$.run_id')=?`,
    )
      .bind(root.run_key)
      .first<{ n: number }>();
    expect(passLogs?.n).toBe(1);
  });

  it("does not PASS until the discovery artifact is durably revalidated", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A]);
    const rootRow = await loadJob(runtimeEnv.DB, root.work_key);
    expect(rootRow?.raw_key).toBe("raw/jsda/test/closure-index.html");
    await runtimeEnv.RAW_BUCKET.delete(rootRow!.raw_key!);

    const restoreFetch = mockOfficialFetch({ [FILE_A]: "child-before-root-repair" });
    try {
      const first = await deliver(
        await childJob(children[0].work_key),
        "root-evidence-missing",
      );
      expect(first.explicitAcks).toEqual([]);
      expect(first.retryMessages.map((message) => message.msgId)).toEqual([
        "root-evidence-missing",
      ]);
    } finally {
      restoreFetch();
    }
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe(
      "waiting_children",
    );
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM ingestion_run_log
        WHERE status='pass' AND json_extract(detail, '$.run_id')=?`,
    ).bind(root.run_key).first<{ n: number }>()).toMatchObject({ n: 0 });

    const discoveryBody = new TextEncoder().encode("closure discovery fixture");
    const discoveryDigest = await sha256Hex(discoveryBody);
    await runtimeEnv.RAW_BUCKET.put(rootRow!.raw_key!, discoveryBody, {
      customMetadata: { sha256: discoveryDigest },
    });
    const repaired = await deliver(
      await childJob(children[0].work_key),
      "root-evidence-repaired",
    );
    expect(repaired.explicitAcks).toEqual(["root-evidence-repaired"]);
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("completed");
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM ingestion_run_log
        WHERE status='pass' AND json_extract(detail, '$.run_id')=?`,
    ).bind(root.run_key).first<{ n: number }>()).toMatchObject({ n: 1 });
  });

  it("closes the root once when delayed children finish out of order", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A, FILE_B]);
    const restore = mockOfficialFetch({
      [FILE_A]: "late-A",
      [FILE_B]: "first-B",
    });
    try {
      expect(
        (await deliver(await childJob(children[1].work_key), "out-of-order-B")).explicitAcks,
      ).toEqual(["out-of-order-B"]);
      expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
        "waiting_children",
      );
      expect(
        (await deliver(await childJob(children[0].work_key), "out-of-order-A")).explicitAcks,
      ).toEqual(["out-of-order-A"]);
      expect(
        (await deliver(await childJob(children[1].work_key), "out-of-order-B-retry"))
          .explicitAcks,
      ).toEqual(["out-of-order-B-retry"]);
    } finally {
      restore();
    }
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("completed");
    const completedEvents = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2
        WHERE work_key=? AND result='completed'`,
    )
      .bind(root.work_key)
      .first<{ n: number }>();
    expect(completedEvents?.n).toBe(1);
  });

  it("propagates a rejected descendant as run failure, never PASS", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A, FILE_B]);
    const restore = mockOfficialFetch({ [FILE_A]: "ok-sibling" });
    try {
      expect(
        (await deliver(await childJob(children[0].work_key), "reject-sibling-ok")).explicitAcks,
      ).toEqual(["reject-sibling-ok"]);
    } finally {
      restore();
    }
    const original = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response("gone", { status: 410 })) as typeof fetch;
    try {
      expect(
        (await deliver(await childJob(children[1].work_key), "reject-child")).explicitAcks,
      ).toEqual(["reject-child"]);
    } finally {
      globalThis.fetch = original;
    }
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("rejected");
    const closure = await loadRunClosure(runtimeEnv.DB, root.run_key);
    expect(closure?.closure_state).toBe("partial");
    expect(closure?.failure_work_key).toBe(children[1].work_key);
    expect(closure?.failure_reason_code).toBe("descendant_rejected");
    const passLogs = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM ingestion_run_log
        WHERE status='pass' AND instr(detail, ?) > 0`,
    )
      .bind(`"job_id":"${root.work_key}"`)
      .first<{ n: number }>();
    expect(passLogs?.n).toBe(0);
  });

  it("retries and converges when the D1 ancestor-update fails after the child completed", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A]);
    const restore = mockOfficialFetch({ [FILE_A]: "closure-fail-bytes" });
    try {
      await runtimeEnv.DB.exec("DROP TABLE jsda_run_closures");
      const first = await deliver(await childJob(children[0].work_key), "closure-write-fail");
      expect(first.explicitAcks).toEqual([]);
      expect(first.retryMessages.map((message) => message.msgId)).toEqual([
        "closure-write-fail",
      ]);
      expect((await loadJob(runtimeEnv.DB, children[0].work_key))?.state).toBe(
        "completed",
      );
      expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("waiting_children");
      await runtimeEnv.DB.exec(
        "CREATE TABLE jsda_run_closures (run_key TEXT PRIMARY KEY, root_work_key TEXT NOT NULL, dataset TEXT NOT NULL, closure_state TEXT NOT NULL, frontier_exhausted INTEGER NOT NULL DEFAULT 0, descendant_total INTEGER NOT NULL DEFAULT 0, descendant_completed INTEGER NOT NULL DEFAULT 0, descendant_rejected INTEGER NOT NULL DEFAULT 0, descendant_failed_transient INTEGER NOT NULL DEFAULT 0, descendant_nonterminal INTEGER NOT NULL DEFAULT 0, failure_work_key TEXT, failure_reason_code TEXT, failure_detail TEXT, closed_at TEXT, updated_at TEXT NOT NULL)",
      );
      await runtimeEnv.DB.prepare(
        `INSERT INTO jsda_run_closures
         (run_key, root_work_key, dataset, closure_state, frontier_exhausted, updated_at)
         VALUES (?, ?, ?, 'waiting_children', 1, ?)`,
      )
        .bind(root.run_key, root.work_key, root.dataset, "2026-08-25T01:30:00.000Z")
        .run();
      const second = await deliver(
        await childJob(children[0].work_key),
        "closure-write-retry",
      );
      expect(second.explicitAcks).toEqual(["closure-write-retry"]);
      expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("completed");
      expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
        "completed",
      );
    } finally {
      restore();
    }
  });

  it("repairs a missing run aggregate on redelivery of a completed child", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A]);
    const restore = mockOfficialFetch({ [FILE_A]: "repair-aggregate-bytes" });
    try {
      expect(
        (await deliver(await childJob(children[0].work_key), "repair-complete")).explicitAcks,
      ).toEqual(["repair-complete"]);
      expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
        "completed",
      );
      await runtimeEnv.DB.prepare(
        `UPDATE jsda_run_closures
            SET closure_state='waiting_children',
                descendant_completed=0,
                descendant_nonterminal=1,
                closed_at=NULL
          WHERE run_key=?`,
      )
        .bind(root.run_key)
        .run();
      expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
        "waiting_children",
      );
      expect(
        (await deliver(await childJob(children[0].work_key), "repair-redeliver")).explicitAcks,
      ).toEqual(["repair-redeliver"]);
      expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
        "completed",
      );
      expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.descendant_completed).toBe(
        1,
      );
    } finally {
      restore();
    }
  });

  it("repairs an incomplete ancestor aggregate on cron re-enqueue instead of skipping it", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A]);
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_run_closures
          SET descendant_total=0, descendant_nonterminal=0
        WHERE run_key=?`,
    )
      .bind(root.run_key)
      .run();
    const repaired = await enqueueRoots(
      runtimeEnv,
      "cron",
      "jsda_otc_bond_reference_prices",
      "2026-08-25T01:30:00.000Z",
    );
    expect(repaired.queued).toHaveLength(0);
    const closure = await loadRunClosure(runtimeEnv.DB, root.run_key);
    expect(closure).toMatchObject({
      closure_state: "waiting_children",
      descendant_total: 1,
      descendant_nonterminal: 1,
    });
    expect((await loadJob(runtimeEnv.DB, children[0].work_key))?.state).toBe("queued");
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("waiting_children");
  });

  it("closes a waiting_children origin on redelivery, not only its ancestors", async () => {
    const { root, children } = await seedWaitingRoot([FILE_A]);
    const restore = mockOfficialFetch({ [FILE_A]: "origin-close-bytes" });
    try {
      expect(
        (await deliver(await childJob(children[0].work_key), "origin-child")).explicitAcks,
      ).toEqual(["origin-child"]);
    } finally {
      restore();
    }
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("completed");
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_acquisition_jobs_v2
          SET state='waiting_children', completed_at=NULL
        WHERE work_key=?`,
    )
      .bind(root.work_key)
      .run();
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_run_closures
          SET closure_state='waiting_children', closed_at=NULL
        WHERE run_key=?`,
    )
      .bind(root.run_key)
      .run();
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("waiting_children");
    expect(
      (await deliver(root, "waiting-origin-redeliver")).explicitAcks,
    ).toEqual(["waiting-origin-redeliver"]);
    expect((await loadJob(runtimeEnv.DB, root.work_key))?.state).toBe("completed");
    expect((await loadRunClosure(runtimeEnv.DB, root.run_key))?.closure_state).toBe(
      "completed",
    );
  });
});
