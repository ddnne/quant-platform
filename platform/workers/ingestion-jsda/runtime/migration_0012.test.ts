import { env } from "cloudflare:workers";
import { applyD1Migrations, reset } from "cloudflare:test";
import { beforeEach, describe, expect, inject, it } from "vitest";
import type { JsdaWorkerEnv } from "../src/env";
import { registerJob } from "../src/job_store";
import { makeChildJob, makeRootJob } from "../src/queue_contract";
import { descriptorForFile } from "../src/queue_contract";

const runtimeEnv = env as JsdaWorkerEnv;
const migrations = inject<Array<{ name: string; queries: string[] }>>(
  "jsdaD1Migrations",
);

const before0012 = migrations.filter((row) => !row.name.includes("0012"));
const only0012 = migrations.filter((row) => row.name.includes("0012"));

beforeEach(async () => {
  await reset();
});

async function pragma(sql: string): Promise<Record<string, unknown>[]> {
  const rows = await runtimeEnv.DB.prepare(sql).all();
  return rows.results as Record<string, unknown>[];
}

describe("0012 populated JSDA migration semantics and FK preservation", () => {
  it("keeps a legacy rolling locator eligible for a later governed run", async () => {
    await applyD1Migrations(runtimeEnv.DB, before0012);
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
    const locator = await descriptorForFile(
      "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trrts.xls",
    );
    const oldObservation = await makeChildJob(rootA, locator);
    const laterObservation = await makeChildJob(rootB, locator);
    const now = "2026-08-24T02:00:00.000Z";

    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v2 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         requested_by, requested_at, first_seen_at, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'pending', 0, 0, ?, ?, ?, ?)`,
    )
      .bind(
        rootA.work_key,
        rootA.run_key,
        rootA.dataset,
        rootA.job_type,
        rootA.target_url,
        rootA.segment_id,
        rootA.contract_digest,
        rootA.requested_by,
        rootA.requested_at,
        now,
        now,
      )
      .run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v2 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         requested_by, requested_at, first_seen_at, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, 0, ?, ?, ?, ?)`,
    )
      .bind(
        oldObservation.work_key,
        oldObservation.run_key,
        oldObservation.dataset,
        oldObservation.job_type,
        oldObservation.target_url,
        oldObservation.segment_id,
        oldObservation.parent_work_key,
        oldObservation.contract_digest,
        oldObservation.requested_by,
        oldObservation.requested_at,
        now,
        now,
      )
      .run();

    await applyD1Migrations(runtimeEnv.DB, only0012);
    const migrated = await runtimeEnv.DB.prepare(
      `SELECT freshness, observation_epoch
         FROM jsda_acquisition_jobs_v3 WHERE work_key=?`,
    )
      .bind(oldObservation.work_key)
      .first<{ freshness: string; observation_epoch: string }>();
    expect(migrated).toEqual({
      freshness: "rolling",
      observation_epoch: rootA.run_key,
    });

    await registerJob(runtimeEnv.DB, rootB);
    await registerJob(runtimeEnv.DB, laterObservation);
    const observations = await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v3
        WHERE dataset=? AND job_type='fetch_file' AND target_url=?`,
    )
      .bind(rootA.dataset, locator.target_url)
      .first<{ n: number }>();
    expect(observations?.n).toBe(2);
  });

  it("keeps populated rows, repairs false-complete roots, and preserves FKs", async () => {
    expect(only0012).toHaveLength(1);
    await applyD1Migrations(runtimeEnv.DB, before0012);

    const root = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const rejectedChild = await makeChildJob(
      root,
      await descriptorForFile(
        "https://market.jsda.or.jp/archive/data/otc-20020802.csv",
      ),
    );
    const openChild = await makeChildJob(
      root,
      await descriptorForFile(
        "https://market.jsda.or.jp/archive/data/otc-20020805.csv",
      ),
    );
    const archiveOk = await makeChildJob(
      root,
      await descriptorForFile(
        "https://market.jsda.or.jp/archive/data/otc-20020808.csv",
      ),
    );
    const archiveBare = await makeChildJob(
      root,
      await descriptorForFile(
        "https://market.jsda.or.jp/archive/data/otc-20020811.csv",
      ),
    );

    const now = "2026-08-24T02:00:00.000Z";
    const audit = { key: "audit/jsda/legacy.json", digest: "d".repeat(64) };
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v2 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         last_error, content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
         requested_by, requested_at, first_seen_at, updated_at, completed_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', 1, 1, NULL, ?, ?, ?, ?, 'cron', ?, ?, ?, ?)`,
    )
      .bind(
        root.work_key,
        root.run_key,
        root.dataset,
        root.job_type,
        root.target_url,
        root.segment_id,
        null,
        root.contract_digest,
        "1".repeat(64),
        "raw/jsda/legacy/root.html",
        audit.key,
        audit.digest,
        root.requested_at,
        now,
        now,
        now,
      )
      .run();

    async function insertChild(
      job: typeof rejectedChild,
      state: "completed" | "rejected" | "queued",
      extras: {
        last_error?: string | null;
        content_digest?: string | null;
        raw_key?: string | null;
        audit_key?: string | null;
        audit_digest?: string | null;
      },
    ) {
      await runtimeEnv.DB.prepare(
        `INSERT INTO jsda_acquisition_jobs_v2 (
           work_key, run_key, dataset, job_type, target_url, segment_id,
           parent_work_key, contract_digest, state, attempt, cursor,
           last_error, content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
           requested_by, requested_at, first_seen_at, updated_at, completed_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, 'cron', ?, ?, ?, ?)`,
      )
        .bind(
          job.work_key,
          job.run_key,
          job.dataset,
          job.job_type,
          job.target_url,
          job.segment_id,
          job.parent_work_key,
          job.contract_digest,
          state,
          extras.last_error ?? null,
          extras.content_digest ?? null,
          extras.raw_key ?? null,
          extras.audit_key ?? null,
          extras.audit_digest ?? null,
          job.requested_at,
          now,
          now,
          state === "queued" ? null : now,
        )
        .run();
      await runtimeEnv.DB.prepare(
        `INSERT INTO jsda_acquisition_discoveries_v2
         (parent_work_key, child_work_key, run_key, discovered_at)
         VALUES (?, ?, ?, ?)`,
      )
        .bind(job.parent_work_key, job.work_key, job.run_key, now)
        .run();
    }

    await insertChild(rejectedChild, "rejected", {
      last_error: "permanent JSDA HTTP 410",
      audit_key: "audit/jsda/legacy-reject.json",
      audit_digest: "e".repeat(64),
    });
    await insertChild(openChild, "queued", {});
    await insertChild(archiveOk, "completed", {
      content_digest: "2".repeat(64),
      raw_key: "raw/jsda/legacy/ok.csv",
      audit_key: "audit/jsda/legacy-ok.json",
      audit_digest: "f".repeat(64),
    });
    await insertChild(archiveBare, "completed", {
      audit_key: "audit/jsda/legacy-bare.json",
      audit_digest: "a".repeat(64),
    });

    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_events_v2 (
         work_key, run_key, dataset, job_type, segment_id, attempt, cursor,
         result, reason_code, detail, content_digest, raw_key,
         audit_receipt_key, audit_receipt_digest, occurred_at
       ) VALUES (?, ?, ?, ?, ?, 1, 0, 'completed', NULL, 'legacy event', NULL, NULL, ?, ?, ?)`,
    )
      .bind(
        archiveOk.work_key,
        archiveOk.run_key,
        archiveOk.dataset,
        archiveOk.job_type,
        archiveOk.segment_id,
        "audit/jsda/legacy-ok.json",
        "f".repeat(64),
        now,
      )
      .run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_queue_rejects_v2 (
         message_id, attempt, reason_code, body_json, body_digest,
         audit_receipt_key, audit_receipt_digest, rejected_at
       ) VALUES ('legacy-reject', 1, 'invalid_job_schema', '{}', ?, ?, ?, ?)`,
    )
      .bind("b".repeat(64), "audit/jsda/legacy-msg.json", "c".repeat(64), now)
      .run();

    await runtimeEnv.DB.prepare(
      `INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
       VALUES (?, 'jsda', 'cloudflare_queue_v2', 'pass', ?)`,
    )
      .bind(
        now,
        JSON.stringify({
          mode: "cloudflare_queue_v2",
          run_id: root.run_key,
          job_id: archiveOk.work_key,
          result: "completed",
          detail: "legacy leaf incorrectly published run PASS",
        }),
      )
      .run();

    const secondRoot = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T01:30:00.000Z",
    );
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v2 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         last_error, content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
         requested_by, requested_at, first_seen_at, updated_at, completed_at
       ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'completed', 1, 1, NULL, ?, ?, ?, ?, 'cron', ?, ?, ?, ?)`,
    )
      .bind(
        secondRoot.work_key,
        secondRoot.run_key,
        secondRoot.dataset,
        secondRoot.job_type,
        secondRoot.target_url,
        secondRoot.segment_id,
        secondRoot.contract_digest,
        "3".repeat(64),
        "raw/jsda/legacy/root2.html",
        "audit/jsda/legacy-root2.json",
        "9".repeat(64),
        secondRoot.requested_at,
        now,
        now,
        now,
      )
      .run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_discoveries_v2
       (parent_work_key, child_work_key, run_key, discovered_at)
       VALUES (?, ?, ?, ?)`,
    )
      .bind(secondRoot.work_key, archiveOk.work_key, secondRoot.run_key, now)
      .run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_discoveries_v2
       (parent_work_key, child_work_key, run_key, discovered_at)
       VALUES (?, ?, ?, ?)`,
    )
      .bind(secondRoot.work_key, archiveBare.work_key, secondRoot.run_key, now)
      .run();

    const jobsBefore = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2",
    ).first<{ n: number }>();
    const eventsBefore = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2",
    ).first<{ n: number }>();
    const discoveriesBefore = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_acquisition_discoveries_v2",
    ).first<{ n: number }>();
    const rejectsBefore = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS n FROM jsda_queue_rejects_v2",
    ).first<{ n: number }>();

    await applyD1Migrations(runtimeEnv.DB, only0012);

    expect(
      (
        await runtimeEnv.DB.prepare(
          "SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v3",
        ).first<{ n: number }>()
      )?.n,
    ).toBe(jobsBefore?.n);
    expect(
      (
        await runtimeEnv.DB.prepare(
          "SELECT COUNT(*) AS n FROM jsda_acquisition_events_v3",
        ).first<{ n: number }>()
      )?.n,
    ).toBe(eventsBefore?.n);
    expect(
      (
        await runtimeEnv.DB.prepare(
          "SELECT COUNT(*) AS n FROM jsda_acquisition_discoveries_v3",
        ).first<{ n: number }>()
      )?.n,
    ).toBe(discoveriesBefore?.n);
    expect(
      (
        await runtimeEnv.DB.prepare(
          "SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v2",
        ).first<{ n: number }>()
      )?.n,
    ).toBe(jobsBefore?.n);
    expect(
      (
        await runtimeEnv.DB.prepare(
          "SELECT COUNT(*) AS n FROM jsda_acquisition_events_v2",
        ).first<{ n: number }>()
      )?.n,
    ).toBe(eventsBefore?.n);
    expect(
      (
        await runtimeEnv.DB.prepare(
          "SELECT COUNT(*) AS n FROM jsda_acquisition_discoveries_v2",
        ).first<{ n: number }>()
      )?.n,
    ).toBe(discoveriesBefore?.n);
    expect(
      (
        await runtimeEnv.DB.prepare(
          "SELECT COUNT(*) AS n FROM jsda_queue_rejects_v2",
        ).first<{ n: number }>()
      )?.n,
    ).toBe(rejectsBefore?.n);

    const fk = await runtimeEnv.DB.prepare("PRAGMA foreign_key_check").all();
    expect(fk.results).toEqual([]);

    const fkSql = (await pragma("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
      .map((row) => String(row.sql))
      .join("\n");
    expect(fkSql).not.toMatch(/__old/i);
    expect(fkSql).not.toMatch(/jobs_v2_next/);

    const firstRoot = await runtimeEnv.DB.prepare(
      "SELECT state FROM jsda_acquisition_jobs_v3 WHERE work_key=?",
    )
      .bind(root.work_key)
      .first<{ state: string }>();
    expect(firstRoot?.state).toBe("rejected");

    const waitingRoot = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const waitingChild = await makeChildJob(
      waitingRoot,
      await descriptorForFile(
        "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/files/trrts.xls",
      ),
    );
    await applyD1Migrations(runtimeEnv.DB, []);
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v3 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         requested_by, requested_at, first_seen_at, updated_at,
         audit_receipt_key, audit_receipt_digest
       ) VALUES (?, ?, ?, 'discover_root', ?, ?, NULL, ?, 'waiting_children', 0, 0,
                 'cron', ?, ?, ?, ?, ?)`,
    )
      .bind(
        waitingRoot.work_key,
        waitingRoot.run_key,
        waitingRoot.dataset,
        waitingRoot.target_url,
        waitingRoot.segment_id,
        waitingRoot.contract_digest,
        waitingRoot.requested_at,
        now,
        now,
        "audit/jsda/post.json",
        "8".repeat(64),
      )
      .run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v3 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         requested_by, requested_at, first_seen_at, updated_at
       ) VALUES (?, ?, ?, 'fetch_file', ?, ?, ?, ?, 'pending', 0, 0,
                 'cron', ?, ?, ?)`,
    )
      .bind(
        waitingChild.work_key,
        waitingChild.run_key,
        waitingChild.dataset,
        waitingChild.target_url,
        waitingChild.segment_id,
        waitingChild.parent_work_key,
        waitingChild.contract_digest,
        waitingChild.requested_at,
        now,
        now,
      )
      .run();

    const adopted = await runtimeEnv.DB.prepare(
      `SELECT membership_kind, terminal_state, failure_reason_code
         FROM jsda_run_membership
        WHERE run_key=? AND child_work_key=?`,
    )
      .bind(secondRoot.run_key, archiveOk.work_key)
      .first<{
        membership_kind: string;
        terminal_state: string;
        failure_reason_code: string | null;
      }>();
    expect(adopted).toMatchObject({
      membership_kind: "adopted",
      terminal_state: "completed",
      failure_reason_code: null,
    });
    const bare = await runtimeEnv.DB.prepare(
      `SELECT membership_kind, terminal_state, failure_reason_code
         FROM jsda_run_membership
        WHERE run_key=? AND child_work_key=?`,
    )
      .bind(secondRoot.run_key, archiveBare.work_key)
      .first<{
        membership_kind: string;
        terminal_state: string;
        failure_reason_code: string | null;
      }>();
    expect(bare).toMatchObject({
      membership_kind: "adopted",
      terminal_state: "rejected",
      failure_reason_code: "insufficient_legacy_evidence",
    });

    const secondRootJob = await runtimeEnv.DB.prepare(
      "SELECT state FROM jsda_acquisition_jobs_v3 WHERE work_key=?",
    )
      .bind(secondRoot.work_key)
      .first<{ state: string }>();
    expect(secondRootJob?.state).toBe("rejected");
    const secondClosure = await runtimeEnv.DB.prepare(
      `SELECT closure_state FROM jsda_run_closures WHERE run_key=?`,
    )
      .bind(secondRoot.run_key)
      .first<{ closure_state: string }>();
    expect(secondClosure?.closure_state).toBe("partial");

    const firstClosure = await runtimeEnv.DB.prepare(
      `SELECT closure_state FROM jsda_run_closures WHERE run_key=?`,
    )
      .bind(root.run_key)
      .first<{ closure_state: string }>();
    expect(["failed", "partial"]).toContain(firstClosure?.closure_state);
    expect(firstRoot?.state).not.toBe("completed");

    const correctedLog = await runtimeEnv.DB.prepare(
      `SELECT status, json_extract(detail, '$.reason') AS reason
         FROM ingestion_run_log
        WHERE source='jsda' AND runtime='cloudflare_queue_v2'
          AND json_extract(detail, '$.run_id')=?
        ORDER BY id DESC LIMIT 1`,
    )
      .bind(root.run_key)
      .first<{ status: string; reason: string | null }>();
    expect(correctedLog?.status).not.toBe("pass");
    expect(correctedLog?.reason).toBe("migration_invalidated_legacy_false_pass");
  });

  it("reopens a legacy completed root that still has a nonterminal child", async () => {
    await applyD1Migrations(runtimeEnv.DB, before0012);
    const root = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-24T01:30:00.000Z",
    );
    const child = await makeChildJob(
      root,
      await descriptorForFile(
        "https://market.jsda.or.jp/archive/data/otc-20020802.csv",
      ),
    );
    const now = "2026-08-24T02:00:00.000Z";
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v2 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
         requested_by, requested_at, first_seen_at, updated_at, completed_at
       ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'completed', 1, 1, ?, ?, ?, ?, 'cron', ?, ?, ?, ?)`,
    )
      .bind(
        root.work_key,
        root.run_key,
        root.dataset,
        root.job_type,
        root.target_url,
        root.segment_id,
        root.contract_digest,
        "1".repeat(64),
        "raw/jsda/legacy/root.html",
        "audit/jsda/wait.json",
        "d".repeat(64),
        root.requested_at,
        now,
        now,
        now,
      )
      .run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v2 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         requested_by, requested_at, first_seen_at, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, 0, 'cron', ?, ?, ?)`,
    )
      .bind(
        child.work_key,
        child.run_key,
        child.dataset,
        child.job_type,
        child.target_url,
        child.segment_id,
        child.parent_work_key,
        child.contract_digest,
        child.requested_at,
        now,
        now,
      )
      .run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_discoveries_v2
       (parent_work_key, child_work_key, run_key, discovered_at)
       VALUES (?, ?, ?, ?)`,
    )
      .bind(root.work_key, child.work_key, root.run_key, now)
      .run();

    await applyD1Migrations(runtimeEnv.DB, only0012);
    const after = await runtimeEnv.DB.prepare(
      "SELECT state FROM jsda_acquisition_jobs_v3 WHERE work_key=?",
    )
      .bind(root.work_key)
      .first<{ state: string }>();
    expect(after?.state).toBe("waiting_children");
    const closure = await runtimeEnv.DB.prepare(
      "SELECT closure_state FROM jsda_run_closures WHERE run_key=?",
    )
      .bind(root.run_key)
      .first<{ closure_state: string }>();
    expect(closure?.closure_state).toBe("waiting_children");
  });

  it("migrates an in-flight cross-run archive adoption as nonterminal", async () => {
    await applyD1Migrations(runtimeEnv.DB, before0012);
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
    const childA = await makeChildJob(
      rootA,
      await descriptorForFile(
        "https://market.jsda.or.jp/archive/data/otc-20020802.csv",
      ),
    );
    const now = "2026-08-25T01:31:00.000Z";

    for (const root of [rootA, rootB]) {
      await runtimeEnv.DB.prepare(
        `INSERT INTO jsda_acquisition_jobs_v2 (
           work_key, run_key, dataset, job_type, target_url, segment_id,
           parent_work_key, contract_digest, state, attempt, cursor,
           requested_by, requested_at, first_seen_at, updated_at
         ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 'pending', 0, 0, ?, ?, ?, ?)`,
      )
        .bind(
          root.work_key,
          root.run_key,
          root.dataset,
          root.job_type,
          root.target_url,
          root.segment_id,
          root.contract_digest,
          root.requested_by,
          root.requested_at,
          now,
          now,
        )
        .run();
    }
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs_v2 (
         work_key, run_key, dataset, job_type, target_url, segment_id,
         parent_work_key, contract_digest, state, attempt, cursor,
         requested_by, requested_at, first_seen_at, updated_at
       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, 0, ?, ?, ?, ?)`,
    )
      .bind(
        childA.work_key,
        childA.run_key,
        childA.dataset,
        childA.job_type,
        childA.target_url,
        childA.segment_id,
        childA.parent_work_key,
        childA.contract_digest,
        childA.requested_by,
        childA.requested_at,
        now,
        now,
      )
      .run();
    for (const parent of [rootA, rootB]) {
      await runtimeEnv.DB.prepare(
        `INSERT INTO jsda_acquisition_discoveries_v2
         (parent_work_key, child_work_key, run_key, discovered_at)
         VALUES (?, ?, ?, ?)`,
      )
        .bind(parent.work_key, childA.work_key, parent.run_key, now)
        .run();
    }

    await applyD1Migrations(runtimeEnv.DB, only0012);
    const adopted = await runtimeEnv.DB.prepare(
      `SELECT membership_kind, terminal_state, failure_reason_code
         FROM jsda_run_membership
        WHERE run_key=? AND parent_work_key=? AND child_work_key=?`,
    )
      .bind(rootB.run_key, rootB.work_key, childA.work_key)
      .first<{
        membership_kind: string;
        terminal_state: string;
        failure_reason_code: string | null;
      }>();
    expect(adopted).toEqual({
      membership_kind: "adopted",
      terminal_state: "queued",
      failure_reason_code: null,
    });
  });

  it("rejects late v1 writes, NULL activation, and INSERT OR REPLACE reverse", async () => {
    await applyD1Migrations(runtimeEnv.DB, migrations);
    await expect(
      runtimeEnv.DB.prepare(
        `UPDATE jsda_v3_cutover_control
            SET phase='v3_active', activated_at='not-a-time',
                activated_source_sha=?, cutover_config_digest=NULL,
                drain_evidence_digest=NULL
          WHERE singleton=1`,
      )
        .bind("a".repeat(40))
        .run(),
    ).rejects.toThrow(/activation is incomplete/);
    const pending = await runtimeEnv.DB.prepare(
      "SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1",
    ).first<{ phase: string }>();
    expect(pending?.phase).toBe("bridge");

    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_v3_drain_evidence
         (drain_evidence_digest, observed_at, document_json)
       VALUES (?, ?, '{"schema_version":"jsda-v3-drain-evidence/v1"}')`,
    )
      .bind(`sha256:${"d".repeat(64)}`, "2026-08-26T00:01:00.000Z")
      .run();
    await runtimeEnv.DB.prepare(
      `UPDATE jsda_v3_cutover_control
          SET phase='v3_active', activated_at=?, activated_source_sha=?,
              cutover_config_digest=?, drain_evidence_digest=?
        WHERE singleton=1 AND phase='bridge'`,
    )
      .bind(
        "2026-08-26T00:01:00.000Z",
        "a".repeat(40),
        `sha256:${"b".repeat(64)}`,
        `sha256:${"d".repeat(64)}`,
      )
      .run();
    await expect(
      runtimeEnv.DB.prepare(
        `INSERT INTO jsda_acquisition_jobs (
           job_id, dataset, job_type, target_url, state, attempt, priority,
           created_at, updated_at
         ) VALUES ('late-v1', 'jsda_otc_bond_reference_prices', 'discover_root',
                   'https://market.jsda.or.jp/', 'pending', 0, 100, ?, ?)`,
      )
        .bind("2026-08-26T00:02:00.000Z", "2026-08-26T00:02:00.000Z")
        .run(),
    ).rejects.toThrow(/v1 acquisition graph is retired/);
    await expect(
      runtimeEnv.DB.prepare(
        "INSERT OR REPLACE INTO jsda_v3_cutover_control(singleton,phase) VALUES (1,'bridge')",
      ).run(),
    ).rejects.toThrow(/cannot be replaced/);
    await expect(
      runtimeEnv.DB.prepare(
        `UPDATE jsda_v3_cutover_control SET phase='bridge' WHERE singleton=1`,
      ).run(),
    ).rejects.toThrow(/immutable after activation/);
    await expect(
      runtimeEnv.DB.prepare(
        "DELETE FROM jsda_v3_cutover_control WHERE singleton=1",
      ).run(),
    ).rejects.toThrow(/cannot be deleted/);
    const active = await runtimeEnv.DB.prepare(
      "SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1",
    ).first<{ phase: string }>();
    expect(active?.phase).toBe("v3_active");
  });

  it("fences a late v1 write during bridge so it is not lost", async () => {
    await applyD1Migrations(runtimeEnv.DB, before0012);
    await applyD1Migrations(runtimeEnv.DB, only0012);
    const phase = await runtimeEnv.DB.prepare(
      "SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1",
    ).first<{ phase: string }>();
    expect(phase?.phase).toBe("bridge");
    await runtimeEnv.DB.prepare(
      `INSERT INTO jsda_acquisition_jobs (
         job_id, dataset, job_type, target_url, state, attempt, priority,
         created_at, updated_at
       ) VALUES ('late-v1-bridge', 'jsda_otc_bond_reference_prices', 'discover_root',
                 'https://market.jsda.or.jp/', 'pending', 0, 100, ?, ?)`,
    )
      .bind("2026-08-26T00:02:00.000Z", "2026-08-26T00:02:00.000Z")
      .run();
    const bridged = await runtimeEnv.DB.prepare(
      "SELECT job_id, state FROM jsda_v1_bridge_writes WHERE job_id=?",
    )
      .bind("late-v1-bridge")
      .first<{ job_id: string; state: string }>();
    expect(bridged).toEqual({ job_id: "late-v1-bridge", state: "pending" });
  });
});
