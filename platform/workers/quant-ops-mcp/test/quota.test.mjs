import assert from "node:assert/strict";
import test from "node:test";

import { MemoryDailyQuota, QuotaExceeded, quotaCost } from "../src/quota.js";

const human = { subject: "human:alice", clientId: "chatgpt" };

test("local memory quota separates subject, client, and UTC day", async () => {
  const quota = new MemoryDailyQuota(3);
  const day1 = Date.parse("2026-08-11T23:59:00Z");
  assert.equal((await quota.charge(human, 2, day1)).remaining, 1);
  await assert.rejects(quota.charge(human, 2, day1), QuotaExceeded);
  assert.equal((await quota.charge({ ...human, clientId: "claude" }, 2, day1)).remaining, 1);
  assert.equal((await quota.charge(human, 2, Date.parse("2026-08-12T00:01:00Z"))).remaining, 1);
});

test("quota cost is bounded to rows returned by Ops tools", () => {
  assert.equal(quotaCost({ plane: "ops_current" }), 1);
  assert.equal(quotaCost({ segments: [{}, {}, {}] }), 3);
});
