import { env } from "cloudflare:workers";
import { applyD1Migrations, createExecutionContext, reset } from "cloudflare:test";
import { afterEach, expect, inject, it, vi } from "vitest";
import worker, { type Env } from "../src/index";
import { publishOpsProjection } from "../src/ops_projection";
import { bytesToBase64 } from "../../receipt-evidence-authority/src/canonical";

// The audit protocol has its own tests. Isolate that precondition here; the
// Cron, publisher, crypto, source/target D1 and R2 paths below are all real.
vi.mock("../src/receipt_authority_audit_canary", () => ({
  runStagingReceiptAuditRecoveryCanary: vi.fn(),
  readStagingReceiptAuditRecoveryEvidence: vi.fn(),
}));

type Migration = { name: string; queries: string[] };
const sourceMigrations = inject<Migration[]>("premiumD1Migrations");
const projectionMigrations = inject<Migration[]>("projectionD1Migrations");

afterEach(async () => {
  vi.restoreAllMocks();
  await reset();
});

it("staging Cron publishes a sealed R2/D1 generation only after verification-key provisioning", async () => {
  await applyD1Migrations(env.DB, sourceMigrations);
  await applyD1Migrations(env.OPS_PROJECTION_DB, projectionMigrations);
  // Synthetic metadata only: not an authentic market body or READY evidence.
  await env.DB.prepare(`INSERT INTO ingestion_change_log
    (table_name,source,dataset,natural_key,event_time,available_at,ingested_at,payload,changed_at)
    VALUES ('jquants_daily_bars','jquants','equities_bars','1301',
      '2026-08-01','2026-08-01','2026-08-01','{}','2026-08-01T00:00:00Z')`).run();
  const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
  const sourceSha = "a".repeat(40);
  const versionId = "10000000-0000-4000-8000-000000000001";
  // Test harness omits secret refinements; no live credentials are used.
  const testEnv = {
    ...env,
    RECEIPT_AUTHORITY_OPERATION_MODE: "ACTIVE",
    RECEIPT_AUTHORITY_ENVIRONMENT: "staging",
    OPS_PROJECTION_ENVIRONMENT: "staging",
    OPS_PROJECTION_SIGNING_KEY_ID: "ops-projection-cloud-test-v1",
    OPS_PROJECTION_SIGNING_PKCS8_B64: bytesToBase64(new Uint8Array(
      await crypto.subtle.exportKey("pkcs8", pair.privateKey),
    )),
    OPS_PROJECTION_VERIFY_SPKI_B64: "",
    CF_VERSION_METADATA: { id: versionId, tag: `ra-s-c-${sourceSha}` },
  } as Env;
  const controller: ScheduledController = {
    cron: "* * * * *", scheduledTime: Date.now(), noRetry() {},
  };
  const active = () => env.OPS_PROJECTION_DB.prepare(`SELECT g.*
    FROM ops_projection_active a JOIN ops_projection_generation g
    ON g.generation_id=a.generation_id WHERE a.singleton=1`).first();
  await worker.scheduled(controller, testEnv, createExecutionContext());
  expect(await active()).toBeNull();
  testEnv.OPS_PROJECTION_VERIFY_SPKI_B64 = bytesToBase64(new Uint8Array(
    await crypto.subtle.exportKey("spki", pair.publicKey),
  ));
  testEnv.RECEIPT_AUTHORITY_OPERATION_MODE = "PENDING";
  await worker.scheduled(controller, testEnv, createExecutionContext());
  expect(await active()).toBeNull();
  testEnv.RECEIPT_AUTHORITY_OPERATION_MODE = "ACTIVE";
  await worker.scheduled(controller, testEnv, createExecutionContext());
  const generation = await active();
  expect(generation).toMatchObject({ status: "SEALED", producer_commit_sha: sourceSha });
  const object = await env.STRUCTURED_BUCKET.get(
    `ops-projection/staging/${generation!.generation_id}/export.json`,
  );
  expect(await object!.json()).toMatchObject({
    producer_commit_sha: sourceSha, worker_version_id: versionId, source_cursor: 1,
  });
  expect(await env.OPS_PROJECTION_DB.prepare("SELECT status FROM ops_ready_state").first())
    .toEqual({ status: "NOT_READY" });
  await expect(publishOpsProjection({ ...testEnv, OPS_PROJECTION_ENVIRONMENT: "production" }))
    .rejects.toThrow("Worker tag is not a clean merged Git SHA");
  await expect(publishOpsProjection({
    ...testEnv, CF_VERSION_METADATA: { id: versionId, tag: `rp-s-c-${sourceSha}` },
  })).rejects.toThrow("Worker tag is not a clean merged Git SHA");
  expect((await active())!.generation_id).toBe(generation!.generation_id);
});
