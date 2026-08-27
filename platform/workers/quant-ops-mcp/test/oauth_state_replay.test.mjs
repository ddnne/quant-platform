import assert from "node:assert/strict";
import test from "node:test";

import {
  STATE_TTL_SECONDS,
  consumeStateNonce,
  githubHandler,
  recordStateNonce,
  signState,
  verifyState,
} from "../src/github-handler.js";

function quotaDb() {
  const rows = new Map();

  function statement(sql, args = []) {
    return {
      bind(...values) {
        return statement(sql, values);
      },
      async run() {
        let changes = 0;
        if (sql.startsWith("INSERT INTO oauth_state_nonce")) {
          const [digest, issuedAt, expiresAt] = args;
          if (!rows.has(digest)) {
            rows.set(digest, { issuedAt, expiresAt });
            changes = 1;
          } else {
            throw new Error("UNIQUE constraint failed");
          }
        } else if (sql.includes("nonce_digest = ?")) {
          const [digest, observedAt] = args;
          const row = rows.get(digest);
          if (row && row.expiresAt > observedAt) {
            rows.delete(digest);
            changes = 1;
          }
        } else if (sql.includes("expires_at <= ?")) {
          const [observedAt] = args;
          for (const [digest, row] of rows) {
            if (row.expiresAt <= observedAt) {
              rows.delete(digest);
              changes += 1;
            }
          }
        } else {
          throw new Error(`unexpected SQL: ${sql}`);
        }
        return { success: true, meta: { changes } };
      },
    };
  }

  return {
    rows,
    prepare(sql) {
      return statement(sql);
    },
    async batch(statements) {
      const results = [];
      for (const bound of statements) results.push(await bound.run());
      return results;
    },
  };
}

test("signed OAuth state has a closed five-minute validity envelope", async () => {
  const issuedAt = 1_000;
  const nonce = "a".repeat(43);
  const state = await signState(
    { clientId: "client" },
    "dedicated-state-secret",
    { issuedAt, nonce },
  );

  const verified = await verifyState(state, "dedicated-state-secret", issuedAt);
  assert.deepEqual(verified, {
    version: 2,
    issued_at: issuedAt,
    expires_at: issuedAt + STATE_TTL_SECONDS,
    nonce,
    request: { clientId: "client" },
  });
  assert.equal(
    await verifyState(state, "dedicated-state-secret", issuedAt + STATE_TTL_SECONDS),
    null,
  );
  assert.equal(await verifyState(state, "dedicated-state-secret", issuedAt - 31), null);
  assert.equal(await verifyState(`${state}x`, "dedicated-state-secret", issuedAt), null);
});

test("D1 nonce authority atomically consumes state once", async () => {
  const db = quotaDb();
  const env = { QUOTA_DB: db };
  const nonce = "b".repeat(43);
  await recordStateNonce(env, nonce, 2_000, 2_000 + STATE_TTL_SECONDS);

  assert.equal(await consumeStateNonce(env, nonce, 2_001), true);
  assert.equal(await consumeStateNonce(env, nonce, 2_001), false);
  assert.equal(db.rows.size, 0);
});

test("callback consumes state before provider calls and rejects replay", async () => {
  const db = quotaDb();
  let completions = 0;
  let tokenRequests = 0;
  const env = {
    GITHUB_CLIENT_ID: "github-client",
    GITHUB_CLIENT_SECRET: "github-provider-secret",
    STATE_SECRET: "dedicated-state-secret",
    ALLOWED_LOGIN: "allowed",
    QUOTA_DB: db,
    OAUTH_PROVIDER: {
      parseAuthRequest: async () => ({ clientId: "mcp-client" }),
      completeAuthorization: async () => {
        completions += 1;
        return { redirectTo: "https://client.test/complete" };
      },
    },
  };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) => {
    const url = String(input);
    if (url === "https://github.com/login/oauth/access_token") {
      tokenRequests += 1;
      return Response.json({ access_token: "provider-access-token" });
    }
    if (url === "https://api.github.com/user") {
      return Response.json({ login: "allowed", name: "Allowed User" });
    }
    throw new Error(`unexpected external URL: ${url}`);
  };

  try {
    const authorize = await githubHandler.fetch(
      new Request("https://ops.test/authorize"),
      env,
    );
    assert.equal(authorize.status, 302);
    const state = new URL(authorize.headers.get("location")).searchParams.get("state");
    assert.ok(state);
    assert.equal(db.rows.size, 1);

    const callbackUrl = `https://ops.test/callback?code=once&state=${encodeURIComponent(state)}`;
    const first = await githubHandler.fetch(new Request(callbackUrl), env);
    assert.equal(first.status, 302);
    assert.equal(first.headers.get("location"), "https://client.test/complete");
    assert.equal(completions, 1);
    assert.equal(tokenRequests, 1);

    const replay = await githubHandler.fetch(new Request(callbackUrl), env);
    assert.equal(replay.status, 400);
    assert.equal(await replay.text(), "invalid state");
    assert.equal(completions, 1);
    assert.equal(tokenRequests, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
