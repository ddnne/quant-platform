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
import {
  loadJob,
  loadRunClosure,
  loadRunMembership,
  registerJob,
} from "../src/job_store";
import {
  descriptorForFile,
  JSDA_QUEUE_JOB_VERSION,
  makeChildJob,
  makeRootJob,
  type ChildDescriptor,
  type JsdaQueueJob,
} from "../src/queue_contract";
import { sha256Hex } from "../src/sha256";

const runtimeEnv = env as JsdaWorkerEnv;
const migrations = inject<Array<{ name: string; queries: string[] }>>(
  "jsdaD1Migrations",
);

beforeEach(async () => {
  await reset();
  await applyD1Migrations(runtimeEnv.DB, migrations);
  await runtimeEnv.DB.prepare(
    `UPDATE jsda_v3_cutover_control
        SET phase='v3_active', activated_at=?, activated_source_sha=?,
            drain_evidence_digest=?
      WHERE singleton=1 AND phase='bridge'`,
  )
    .bind(
      "2026-08-25T01:29:00.000Z",
      "a".repeat(40),
      `sha256:${"b".repeat(64)}`,
    )
    .run();
});

const ARCHIVE_A = "https://market.jsda.or.jp/archive/data/otc-20020802.csv";
const ARCHIVE_B = "https://market.jsda.or.jp/archive/data/otc-20020805.csv";
const ROLLING = "https://market.jsda.or.jp/archive/data/otc-current.csv";

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

async function seedWaitingRoot(
  requestedAt: string,
  fileUrls: string[],
  messageId: string,
) {
  const root = await makeRootJob(
    "jsda_otc_bond_reference_prices",
    "cron",
    requestedAt,
  );
  await registerJob(runtimeEnv.DB, root);
  const frontier: ChildDescriptor[] = await Promise.all(
    fileUrls.map((url) => descriptorForFile(url)),
  );
  const discoveryBody = new TextEncoder().encode("discovery fixture");
  const discoveryDigest = await sha256Hex(discoveryBody);
  await runtimeEnv.DB.prepare(
    `UPDATE jsda_acquisition_jobs_v3
     SET state='queued', frontier_json=?, raw_key=?, content_digest=?
     WHERE work_key=?`,
  )
    .bind(
      JSON.stringify(frontier),
      `raw/jsda/test/${messageId}.html`,
      discoveryDigest,
      root.work_key,
    )
    .run();
  await runtimeEnv.RAW_BUCKET.put(
    `raw/jsda/test/${messageId}.html`,
    discoveryBody,
    { customMetadata: { sha256: discoveryDigest } },
  );
  const result = await deliver(root, messageId);
  expect(result.explicitAcks).toEqual([messageId]);
  const membership = await loadRunMembership(runtimeEnv.DB, root.run_key);
  return { root, membership };
}

async function passLogCount(runKey: string): Promise<number> {
  const row = await runtimeEnv.DB.prepare(
    `SELECT COUNT(*) AS n FROM ingestion_run_log
      WHERE status='pass' AND json_extract(detail, '$.run_id')=?`,
  )
    .bind(runKey)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

describe("JSDA run-scoped membership and archive adoption", () => {
  it("adopts a prior completed archive into a new run and closes that run once", async () => {
    const restore = mockOfficialFetch({ [ARCHIVE_A]: "archive-bytes" });
    try {
      const first = await seedWaitingRoot(
        "2026-08-24T01:30:00.000Z",
        [ARCHIVE_A],
        "adopt-first-root",
      );
      const firstChild = first.membership[0];
      expect(firstChild.membership_kind).toBe("enqueued");
      expect(
        (await deliver(await childJob(firstChild.child_work_key), "adopt-first-child"))
          .explicitAcks,
      ).toEqual(["adopt-first-child"]);
      expect((await loadRunClosure(runtimeEnv.DB, first.root.run_key))?.closure_state).toBe(
        "completed",
      );
      expect(await passLogCount(first.root.run_key)).toBe(1);
      const stored = await loadJob(runtimeEnv.DB, firstChild.child_work_key);
      expect(stored?.run_key).toBe(first.root.run_key);

      const second = await seedWaitingRoot(
        "2026-08-25T01:30:00.000Z",
        [ARCHIVE_A],
        "adopt-second-root",
      );
      expect(second.membership).toHaveLength(1);
      expect(second.membership[0]).toMatchObject({
        child_work_key: firstChild.child_work_key,
        membership_kind: "adopted",
        terminal_state: "completed",
      });
      expect(second.membership[0].audit_receipt_key).toBeTruthy();
      expect(second.membership[0].content_digest).toBeTruthy();
      expect((await loadJob(runtimeEnv.DB, firstChild.child_work_key))?.run_key).toBe(
        first.root.run_key,
      );
      expect((await loadJob(runtimeEnv.DB, second.root.work_key))?.state).toBe(
        "completed",
      );
      expect((await loadRunClosure(runtimeEnv.DB, second.root.run_key))?.closure_state).toBe(
        "completed",
      );
      expect(await passLogCount(second.root.run_key)).toBe(1);
      expect(
        (await runtimeEnv.DB.prepare(
          `SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v3
            WHERE parent_work_key=?`,
        )
          .bind(second.root.work_key)
          .first<{ n: number }>())?.n,
      ).toBe(0);
    } finally {
      restore();
    }
  });

  it("rejects an adopted archive when its immutable R2 raw evidence is absent", async () => {
    const restore = mockOfficialFetch({ [ARCHIVE_A]: "archive-to-lose" });
    try {
      const first = await seedWaitingRoot(
        "2026-08-24T01:30:00.000Z",
        [ARCHIVE_A],
        "missing-adopt-first-root",
      );
      const firstChild = first.membership[0];
      await deliver(await childJob(firstChild.child_work_key), "missing-adopt-first-child");
      const stored = await loadJob(runtimeEnv.DB, firstChild.child_work_key);
      expect(stored?.raw_key).toBeTruthy();
      await runtimeEnv.RAW_BUCKET.delete(stored!.raw_key!);

      const second = await seedWaitingRoot(
        "2026-08-25T01:30:00.000Z",
        [ARCHIVE_A],
        "missing-adopt-second-root",
      );
      expect(second.membership[0]).toMatchObject({
        membership_kind: "adopted",
        terminal_state: "rejected",
        failure_reason_code: "adopted_evidence_missing",
      });
      expect((await loadJob(runtimeEnv.DB, second.root.work_key))?.state).toBe(
        "rejected",
      );
      expect((await loadRunClosure(runtimeEnv.DB, second.root.run_key))?.closure_state).toBe(
        "failed",
      );
      expect(await passLogCount(second.root.run_key)).toBe(0);
    } finally {
      restore();
    }
  });

  it("rejects adopted evidence when R2 metadata masks a forged body", async () => {
    const restore = mockOfficialFetch({ [ARCHIVE_A]: "archive-authentic-body" });
    try {
      const first = await seedWaitingRoot(
        "2026-08-24T01:30:00.000Z",
        [ARCHIVE_A],
        "forged-adopt-first-root",
      );
      const childKey = first.membership[0].child_work_key;
      await deliver(await childJob(childKey), "forged-adopt-first-child");
      const stored = await loadJob(runtimeEnv.DB, childKey);
      expect(stored?.raw_key).toBeTruthy();
      expect(stored?.content_digest).toBeTruthy();
      await runtimeEnv.RAW_BUCKET.put(stored!.raw_key!, "forged-body", {
        customMetadata: { sha256: stored!.content_digest! },
      });

      const second = await seedWaitingRoot(
        "2026-08-25T01:30:00.000Z",
        [ARCHIVE_A],
        "forged-adopt-second-root",
      );
      expect(second.membership[0]).toMatchObject({
        membership_kind: "adopted",
        terminal_state: "rejected",
        failure_reason_code: "adopted_evidence_missing",
      });
      expect((await loadRunClosure(runtimeEnv.DB, second.root.run_key))?.closure_state).toBe(
        "failed",
      );
    } finally {
      restore();
    }
  });

  it("counts mixed adopted archive and new rolling children and does not PASS early", async () => {
    const restore = mockOfficialFetch({
      [ARCHIVE_A]: "mixed-archive",
      [ROLLING]: "mixed-rolling",
    });
    try {
      const first = await seedWaitingRoot(
        "2026-08-24T01:30:00.000Z",
        [ARCHIVE_A],
        "mixed-first-root",
      );
      expect(
        (
          await deliver(
            await childJob(first.membership[0].child_work_key),
            "mixed-first-child",
          )
        ).explicitAcks,
      ).toEqual(["mixed-first-child"]);

      const second = await seedWaitingRoot(
        "2026-08-25T01:30:00.000Z",
        [ARCHIVE_A, ROLLING],
        "mixed-second-root",
      );
      expect(second.membership).toHaveLength(2);
      const adopted = second.membership.find((row) => row.membership_kind === "adopted");
      const enqueued = second.membership.find((row) => row.membership_kind === "enqueued");
      expect(adopted?.child_work_key).toBe(first.membership[0].child_work_key);
      expect(adopted?.terminal_state).toBe("completed");
      expect(enqueued?.terminal_state).toBe("queued");
      expect((await loadJob(runtimeEnv.DB, second.root.work_key))?.state).toBe(
        "waiting_children",
      );
      expect(await passLogCount(second.root.run_key)).toBe(0);
      expect(
        (await deliver(await childJob(enqueued!.child_work_key), "mixed-rolling")).explicitAcks,
      ).toEqual(["mixed-rolling"]);
      const closure = await loadRunClosure(runtimeEnv.DB, second.root.run_key);
      expect(closure).toMatchObject({
        closure_state: "completed",
        descendant_total: 2,
        descendant_completed: 2,
      });
      expect(await passLogCount(second.root.run_key)).toBe(1);
    } finally {
      restore();
    }
  });

  it("fail-closes adoption of a completed archive that lacks artifact evidence", async () => {
    const first = await seedWaitingRoot(
      "2026-08-24T01:30:00.000Z",
      [ARCHIVE_B],
      "bare-first-root",
    );
    const childKey = first.membership[0].child_work_key;
    await runtimeEnv.DB.prepare(
      `DELETE FROM jsda_run_membership WHERE child_work_key=? AND run_key=?`,
    )
      .bind(childKey, first.root.run_key)
      .run();
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_acquisition_jobs_v3
          SET state='completed',
              completed_at=?,
              audit_receipt_key=?,
              audit_receipt_digest=?,
              content_digest=NULL,
              raw_key=NULL
        WHERE work_key=?`,
    )
      .bind(
        "2026-08-24T02:00:00.000Z",
        "audit/jsda/insufficient.json",
        "c".repeat(64),
        childKey,
      )
      .run();
    const second = await seedWaitingRoot(
      "2026-08-25T01:30:00.000Z",
      [ARCHIVE_B],
      "bare-second-root",
    );
    expect(second.membership[0]).toMatchObject({
      child_work_key: childKey,
      membership_kind: "adopted",
      terminal_state: "rejected",
      failure_reason_code: "adopted_evidence_missing",
    });
    expect((await loadJob(runtimeEnv.DB, childKey))?.run_key).toBe(first.root.run_key);
    expect((await loadJob(runtimeEnv.DB, second.root.work_key))?.state).toBe("rejected");
    expect((await loadRunClosure(runtimeEnv.DB, second.root.run_key))?.closure_state).toBe(
      "failed",
    );
    expect(await passLogCount(second.root.run_key)).toBe(0);
  });

  it("does not leave a pending observation for a completed fetch missing source_object_id", async () => {
    const restore = mockOfficialFetch({ [ARCHIVE_A]: "identity-bytes" });
    try {
      const first = await seedWaitingRoot(
        "2026-08-24T01:30:00.000Z",
        [ARCHIVE_A],
        "identity-first-root",
      );
      const childKey = first.membership[0].child_work_key;
      expect(
        (await deliver(await childJob(childKey), "identity-first-child")).explicitAcks,
      ).toEqual(["identity-first-child"]);
      await runtimeEnv.DB.prepare(
        `UPDATE jsda_acquisition_jobs_v3 SET source_object_id=NULL WHERE work_key=?`,
      )
        .bind(childKey)
        .run();
      await runtimeEnv.DB.prepare(
        `DELETE FROM jsda_observations WHERE work_key=?`,
      )
        .bind(childKey)
        .run();
      const second = await seedWaitingRoot(
        "2026-08-25T01:30:00.000Z",
        [ARCHIVE_A],
        "identity-second-root",
      );
      const pending = await runtimeEnv.DB.prepare(
        `SELECT COUNT(*) AS n FROM jsda_observations
          WHERE work_key=? AND state='pending'`,
      )
        .bind(childKey)
        .first<{ n: number }>();
      expect(pending?.n).toBe(0);
      const repaired = await loadJob(runtimeEnv.DB, childKey);
      expect(repaired?.source_object_id).not.toBeNull();
      expect(second.membership[0].membership_kind).toBe("adopted");
    } finally {
      restore();
    }
  });

  it("does not mutate a different run before rejecting a work-key identity mismatch", async () => {
    const rootA = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const rootB = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJob(runtimeEnv.DB, rootA);
    await registerJob(runtimeEnv.DB, rootB);
    const childA = await makeChildJob(rootA, await descriptorForFile(ARCHIVE_A));
    await registerJob(runtimeEnv.DB, childA);

    const mismatched = {
      ...childA,
      run_key: rootB.run_key,
      parent_work_key: rootB.work_key,
    } satisfies JsdaQueueJob;
    const result = await deliver(mismatched, "identity-mismatch-side-effect");
    expect(result.explicitAcks).toEqual(["identity-mismatch-side-effect"]);

    expect(await loadRunMembership(runtimeEnv.DB, rootB.run_key)).toEqual([]);
  });

  it("keeps an overlapping run nonterminal while an archive observation is in flight", async () => {
    const rootA = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const rootB = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await registerJob(runtimeEnv.DB, rootA);
    await registerJob(runtimeEnv.DB, rootB);
    const descriptor = await descriptorForFile(ARCHIVE_B);
    const childA = await makeChildJob(rootA, descriptor);
    const childB = await makeChildJob(rootB, descriptor);
    expect(childA.work_key).toBe(childB.work_key);
    await registerJob(runtimeEnv.DB, childA);
    await registerJob(runtimeEnv.DB, childB);

    expect(await loadRunMembership(runtimeEnv.DB, rootB.run_key)).toMatchObject([
      {
        child_work_key: childB.work_key,
        membership_kind: "adopted",
        terminal_state: "pending",
        failure_reason_code: null,
      },
    ]);
  });

  it("propagates a terminal archive into every overlapping run and advances closure", async () => {
    const restore = mockOfficialFetch({ [ARCHIVE_B]: "overlap-archive-bytes" });
    try {
      const first = await seedWaitingRoot(
        "2026-08-24T01:30:00.000Z",
        [ARCHIVE_B],
        "overlap-first-root",
      );
      const second = await seedWaitingRoot(
        "2026-08-25T01:30:00.000Z",
        [ARCHIVE_B],
        "overlap-second-root",
      );
      expect(second.membership).toMatchObject([
        {
          child_work_key: first.membership[0].child_work_key,
          membership_kind: "adopted",
          terminal_state: "queued",
          failure_reason_code: null,
        },
      ]);
      expect((await loadJob(runtimeEnv.DB, second.root.work_key))?.state).toBe(
        "waiting_children",
      );

      const completed = await deliver(
        await childJob(first.membership[0].child_work_key),
        "overlap-shared-child",
      );
      expect(completed.explicitAcks).toEqual(["overlap-shared-child"]);
      expect(await loadRunMembership(runtimeEnv.DB, second.root.run_key)).toMatchObject([
        {
          membership_kind: "adopted",
          terminal_state: "completed",
          failure_reason_code: null,
        },
      ]);
      for (const run of [first.root.run_key, second.root.run_key]) {
        expect((await loadRunClosure(runtimeEnv.DB, run))?.closure_state).toBe(
          "completed",
        );
        expect(await passLogCount(run)).toBe(1);
      }

      await runtimeEnv.DB.prepare(
        `UPDATE jsda_run_closures
            SET closure_state='waiting_children', descendant_completed=0,
                descendant_nonterminal=1, closed_at=NULL
          WHERE run_key=?`,
      )
        .bind(second.root.run_key)
        .run();
      await runtimeEnv.DB.prepare(
        `UPDATE jsda_run_membership
            SET audit_receipt_digest=?
          WHERE run_key=? AND child_work_key=? AND membership_kind='adopted'`,
      )
        .bind(
          "0".repeat(64),
          second.root.run_key,
          first.membership[0].child_work_key,
        )
        .run();
      const repaired = await deliver(
        await childJob(first.membership[0].child_work_key),
        "overlap-terminal-redelivery",
      );
      expect(repaired.explicitAcks).toEqual(["overlap-terminal-redelivery"]);
      expect((await loadRunClosure(runtimeEnv.DB, second.root.run_key))?.closure_state).toBe(
        "completed",
      );
      expect(await loadRunMembership(runtimeEnv.DB, second.root.run_key)).toMatchObject([
        {
          membership_kind: "adopted",
          terminal_state: "completed",
          audit_receipt_digest: expect.not.stringMatching(/^0+$/),
        },
      ]);
      expect(await passLogCount(second.root.run_key)).toBe(1);
    } finally {
      restore();
    }
  });
});
