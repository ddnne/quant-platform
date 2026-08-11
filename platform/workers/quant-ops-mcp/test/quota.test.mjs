import assert from "node:assert/strict";
import test from "node:test";

import { DurableDailyQuota, MemoryDailyQuota, QuotaExceeded, quotaCost } from "../src/quota.js";

const human = { subject: "human:alice", clientId: "chatgpt" };

test("local memory quota separates subject, client, and UTC day", async () => {
  const quota = new MemoryDailyQuota(3);
  const day1 = Date.parse("2026-08-11T23:59:00Z");
  assert.equal((await quota.charge(human, 2, day1)).remaining, 1);
  await assert.rejects(quota.charge(human, 2, day1), QuotaExceeded);
  assert.equal((await quota.charge({ ...human, clientId: "claude" }, 2, day1)).remaining, 1);
  assert.equal((await quota.charge(human, 2, Date.parse("2026-08-12T00:01:00Z"))).remaining, 1);
});

test("durable quota uses one conditional D1 upsert", async () => {
  let capturedSql = "";
  let capturedBinds = [];
  const db = {
    prepare(sql) {
      capturedSql = sql;
      return {
        bind(...values) {
          capturedBinds = values;
          return { async first() { return { used: 7, limit_value: 10 }; } };
        },
      };
    },
  };
  const result = await new DurableDailyQuota(db, 10).charge(human, 2, Date.parse("2026-08-11T12:00:00Z"));
  assert.match(capturedSql, /ON CONFLICT\(quota_day, subject_id, client_id\) DO UPDATE/);
  assert.match(capturedSql, /WHERE remote_mcp_daily_quota\.used \+ excluded\.used <= excluded\.limit_value/);
  assert.match(capturedSql, /RETURNING used, limit_value/);
  assert.deepEqual(capturedBinds.slice(0, 4), ["2026-08-11", "human:alice", "chatgpt", 2]);
  assert.deepEqual(result, { day: "2026-08-11", used: 7, remaining: 3, limit: 10 });
});

test("quota cost is bounded to rows returned by Ops tools", () => {
  assert.equal(quotaCost({ plane: "ops_current" }), 1);
  assert.equal(quotaCost({ segments: [{}, {}, {}] }), 3);
});

