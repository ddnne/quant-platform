import { describe, expect, it } from "vitest";
import {
  CHILD_ENQUEUE_BATCH_SIZE,
  descriptorForFile,
  isJsdaQueueJob,
  makeChildJob,
  makeRootJob,
  queueContractDigest,
} from "./queue_contract";

describe("JSDA Queue v2 contract", () => {
  it("makes daily cron roots stable and contains no random identifier", async () => {
    const requestedAt = "2026-08-25T01:30:00.000Z";
    const left = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      requestedAt,
    );
    const right = await makeRootJob(
      "jsda_otc_bond_reference_prices",
      "cron",
      "2026-08-25T23:59:59.000Z",
    );
    expect(left.work_key).toBe(right.work_key);
    expect(left.work_key).toBe(
      "jsda:v2:root:jsda_otc_bond_reference_prices:cron:2026-08-25",
    );
    expect(left.contract_digest).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(isJsdaQueueJob(left)).toBe(true);
  });

  it("deduplicates a child by canonical URL across different daily roots", async () => {
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
    const descriptor = await descriptorForFile(
      "https://market.jsda.or.jp/archive/data/otc-20020802.csv#ignored",
    );
    const first = await makeChildJob(firstRoot, descriptor);
    const second = await makeChildJob(secondRoot, descriptor);
    expect(first.work_key).toBe(second.work_key);
    expect(first.parent_work_key).not.toBe(second.parent_work_key);
    expect(first.target_url).not.toContain("#");
  });

  it("uses a bounded continuation batch without an archive convergence cap", () => {
    expect(CHILD_ENQUEUE_BATCH_SIZE).toBeGreaterThan(0);
    expect(CHILD_ENQUEUE_BATCH_SIZE).toBeLessThanOrEqual(100);
  });

  it("rejects unknown fields and a caller-selected contract digest", async () => {
    const root = await makeRootJob(
      "jsda_tokyo_repo_rates",
      "manual",
      "2026-08-25T00:00:00.000Z",
    );
    expect(isJsdaQueueJob({ ...root, arbitrary_url: "https://evil.test" })).toBe(false);
    expect(root.contract_digest).toBe(await queueContractDigest());
    expect(isJsdaQueueJob({ ...root, contract_digest: "caller-value" })).toBe(false);
  });
});
