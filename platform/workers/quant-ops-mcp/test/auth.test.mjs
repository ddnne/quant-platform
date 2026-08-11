import assert from "node:assert/strict";
import { generateKeyPairSync, sign, webcrypto } from "node:crypto";
import test from "node:test";

import { AuthError, authenticateAccess } from "../src/auth.js";
import { createFetchHandler } from "../src/index.js";

if (!globalThis.crypto) globalThis.crypto = webcrypto;

const env = {
  ACCESS_TEAM_DOMAIN: "quant.cloudflareaccess.com",
  ACCESS_AUD: "ops-audience",
  OAUTH_AUTHORIZATION_SERVER: "https://oauth.example",
  ALLOWED_ORIGINS: "https://chatgpt.com",
  DAILY_ROW_QUOTA: "25000",
  OPS_DB: {},
};

function base64url(value) {
  const bytes = typeof value === "string" ? Buffer.from(value) : Buffer.from(value);
  return bytes.toString("base64url");
}

function signedToken(claimOverrides = {}) {
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const header = base64url(JSON.stringify({ alg: "RS256", kid: "test-key", typ: "JWT" }));
  const now = Math.floor(Date.now() / 1000);
  const claims = base64url(JSON.stringify({
    iss: "https://quant.cloudflareaccess.com", aud: "ops-audience",
    exp: now + 300, sub: "person-1", email: "person@example.com",
    type: "app", identity_nonce: "managed-oauth-grant-1", ...claimOverrides,
  }));
  const signingInput = `${header}.${claims}`;
  const signature = sign("RSA-SHA256", Buffer.from(signingInput), privateKey);
  return {
    token: `${signingInput}.${base64url(signature)}`,
    jwk: { ...publicKey.export({ format: "jwk" }), kid: "test-key", alg: "RS256" },
  };
}

test("unauthenticated MCP call is rejected", async () => {
  const response = await createFetchHandler()(
    new Request("https://ops.example/mcp", { method: "POST" }), env,
  );
  assert.equal(response.status, 401);
  assert.match(response.headers.get("www-authenticate"), /oauth-protected-resource/);
});

test("valid human Access assertion is signature/issuer/audience checked", async () => {
  const { token, jwk } = signedToken();
  const principal = await authenticateAccess(new Request("https://ops.example/mcp", {
    headers: { authorization: `Bearer ${token}` },
  }), env, { jwks: [jwk] });
  assert.deepEqual(principal, {
    kind: "human", subject: "human:person-1", clientId: "managed-oauth-grant-1",
    scopes: ["quant.read.ops"],
  });
});

test("automation service tokens remain distinct and wrong Access AUD rejects", async () => {
  const { token, jwk } = signedToken({
    sub: "service-1", email: undefined, common_name: "nightly",
    identity_nonce: undefined,
  });
  const principal = await authenticateAccess(new Request("https://ops.example/mcp", {
    headers: { "Cf-Access-Jwt-Assertion": token },
  }), env, { jwks: [jwk] });
  assert.equal(principal.kind, "service");
  assert.equal(principal.clientId, "nightly");

  const wrongAudience = signedToken({ aud: "research-audience" });
  await assert.rejects(
    authenticateAccess(new Request("https://ops.example/mcp", {
      headers: { authorization: `Bearer ${wrongAudience.token}` },
    }), env, { jwks: [wrongAudience.jwk] }),
    (error) => error instanceof AuthError && error.status === 401,
  );
});

test("authenticated Streamable HTTP smoke reaches initialize", async () => {
  const handler = createFetchHandler({ authenticate: async () => ({
    kind: "human", subject: "human:test", clientId: "chatgpt", scopes: ["quant.read.ops"],
  }) });
  const response = await handler(new Request("https://ops.example/mcp", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      origin: "https://chatgpt.com",
    },
    body: JSON.stringify({
      jsonrpc: "2.0", id: 1, method: "initialize",
      params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "smoke", version: "1" } },
    }),
  }), env);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).result.protocolVersion, "2025-06-18");
});

test("authenticated Ops tool smoke is read-only and durably quota charged", async () => {
  const db = {
    prepare(sql) {
      return {
        bind() {
          return {
            async all() { return { results: [] }; },
            async first() {
              return sql.includes("remote_mcp_daily_quota")
                ? { used: 1, limit_value: 25000 }
                : null;
            },
          };
        },
      };
    },
  };
  const handler = createFetchHandler({ authenticate: async () => ({
    kind: "service", subject: "service:smoke", clientId: "automation",
    scopes: ["quant.read.ops"],
  }) });
  const response = await handler(new Request("https://ops.example/mcp", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
    },
    body: JSON.stringify({
      jsonrpc: "2.0", id: 2, method: "tools/call",
      params: { name: "ops_status", arguments: {} },
    }),
  }), { ...env, OPS_DB: db });
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.result.structuredContent.plane, "ops_current");
  assert.equal(body.result.structuredContent.mutable, true);
  assert.equal(body.result._meta.quota.used, 1);
});
