/**
 * GitHub OAuth default handler (news-mcp pattern, single-user ALLOWED_LOGIN).
 * /authorize → GitHub → /callback → OAUTH_PROVIDER.completeAuthorization
 */
import { Hono } from "hono";

const STATE_LABEL = "quant-ops-mcp.oauth-state.v2";
export const STATE_TTL_SECONDS = 300;
const STATE_CLOCK_SKEW_SECONDS = 30;
const NONCE_BYTES = 32;
const NONCE_PATTERN = /^[A-Za-z0-9_-]{43}$/u;

/** @param {{ STATE_SECRET?: string }} env */
function stateSecret(env) {
  const value = env.STATE_SECRET;
  return typeof value === "string" && value.trim() ? value : "";
}

/** @param {Uint8Array} bytes */
function bytesToB64url(bytes) {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/u, "");
}

/** @param {string} s */
function b64urlToBytes(s) {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64.padEnd(b64.length + ((4 - (b64.length % 4)) % 4), "=");
  const bin = atob(padded);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** @param {string} secret @param {string} message */
async function hmacSha256(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message)),
  );
}

/** @param {string} value */
async function sha256B64url(value) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return bytesToB64url(new Uint8Array(digest));
}

function randomNonce() {
  return bytesToB64url(crypto.getRandomValues(new Uint8Array(NONCE_BYTES)));
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

/**
 * @param {unknown} req
 * @param {string} secret
 * @param {{ issuedAt?: number, nonce?: string }} [options]
 */
export async function signState(req, secret, options = {}) {
  if (!secret) throw new Error("state secret unset");
  const issuedAt = options.issuedAt ?? nowSeconds();
  const nonce = options.nonce ?? randomNonce();
  if (!Number.isSafeInteger(issuedAt) || !NONCE_PATTERN.test(nonce)) {
    throw new Error("invalid state issuance parameters");
  }
  const envelope = {
    version: 2,
    issued_at: issuedAt,
    expires_at: issuedAt + STATE_TTL_SECONDS,
    nonce,
    request: req,
  };
  const payload = bytesToB64url(
    new TextEncoder().encode(JSON.stringify(envelope)),
  );
  const sig = bytesToB64url(await hmacSha256(secret, `${STATE_LABEL}.${payload}`));
  return `${payload}.${sig}`;
}

/**
 * @param {string} state
 * @param {string} secret
 * @param {number} [observedAt]
 */
export async function verifyState(state, secret, observedAt = nowSeconds()) {
  if (!secret || typeof state !== "string" || state.length > 32_768) return null;
  const dot = state.lastIndexOf(".");
  if (dot <= 0 || dot === state.length - 1) return null;
  const payload = state.slice(0, dot);
  const providedSig = state.slice(dot + 1);
  const expected = await hmacSha256(secret, `${STATE_LABEL}.${payload}`);
  let provided;
  try {
    provided = b64urlToBytes(providedSig);
  } catch {
    return null;
  }
  if (provided.byteLength !== expected.byteLength) return null;
  // Constant-time compare
  let diff = 0;
  for (let i = 0; i < expected.byteLength; i++) diff |= expected[i] ^ provided[i];
  if (diff !== 0) return null;
  try {
    const parsed = JSON.parse(new TextDecoder().decode(b64urlToBytes(payload)));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const expectedFields = ["expires_at", "issued_at", "nonce", "request", "version"];
    if (
      Object.keys(parsed).sort().join("\n") !== expectedFields.join("\n") ||
      parsed.version !== 2 ||
      !Number.isSafeInteger(parsed.issued_at) ||
      !Number.isSafeInteger(parsed.expires_at) ||
      parsed.expires_at - parsed.issued_at !== STATE_TTL_SECONDS ||
      parsed.issued_at > observedAt + STATE_CLOCK_SKEW_SECONDS ||
      parsed.expires_at <= observedAt ||
      typeof parsed.nonce !== "string" ||
      !NONCE_PATTERN.test(parsed.nonce)
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Record the nonce before redirecting to GitHub. D1 batch is transactional, so
 * cleanup and insertion either both commit or neither does.
 * @param {GithubHandlerEnv} env
 * @param {string} nonce
 * @param {number} issuedAt
 * @param {number} expiresAt
 */
export async function recordStateNonce(env, nonce, issuedAt, expiresAt) {
  if (!env.QUOTA_DB || typeof env.QUOTA_DB.batch !== "function") {
    throw new Error("OAuth state store unavailable");
  }
  const nonceDigest = await sha256B64url(nonce);
  const results = await env.QUOTA_DB.batch([
    env.QUOTA_DB.prepare(
      "DELETE FROM oauth_state_nonce WHERE expires_at <= ?",
    ).bind(issuedAt),
    env.QUOTA_DB.prepare(
      "INSERT INTO oauth_state_nonce (nonce_digest, issued_at, expires_at) VALUES (?, ?, ?)",
    ).bind(nonceDigest, issuedAt, expiresAt),
  ]);
  if (
    !Array.isArray(results) ||
    results.length !== 2 ||
    Number(results[1]?.meta?.changes ?? 0) !== 1
  ) {
    throw new Error("OAuth state nonce was not persisted");
  }
}

/**
 * Atomically consume exactly one unexpired nonce before any provider call.
 * @param {GithubHandlerEnv} env
 * @param {string} nonce
 * @param {number} observedAt
 */
export async function consumeStateNonce(env, nonce, observedAt) {
  if (!env.QUOTA_DB || typeof env.QUOTA_DB.prepare !== "function") {
    throw new Error("OAuth state store unavailable");
  }
  const nonceDigest = await sha256B64url(nonce);
  const result = await env.QUOTA_DB.prepare(
    "DELETE FROM oauth_state_nonce WHERE nonce_digest = ? AND expires_at > ?",
  ).bind(nonceDigest, observedAt).run();
  return Number(result?.meta?.changes ?? 0) === 1;
}

/**
 * @typedef {{
 *   GITHUB_CLIENT_ID?: string,
 *   GITHUB_CLIENT_SECRET?: string,
 *   STATE_SECRET?: string,
 *   ALLOWED_LOGIN?: string,
 *   QUOTA_DB: D1Database,
 *   OAUTH_PROVIDER: {
 *     parseAuthRequest: (request: Request) => Promise<unknown>,
 *     completeAuthorization: (opts: {
 *       request: unknown,
 *       userId: string,
 *       metadata: Record<string, unknown>,
 *       scope: string[],
 *       props: { login: string, name: string },
 *     }) => Promise<{ redirectTo: string }>,
 *   },
 * }} GithubHandlerEnv
 */

/** @type {import("hono").Hono<{ Bindings: GithubHandlerEnv }>} */
export const githubHandler = new Hono();

githubHandler.get("/authorize", async (c) => {
  const secret = stateSecret(c.env);
  if (!secret) {
    return c.text("server misconfigured: STATE_SECRET missing", 500);
  }
  if (!c.env.GITHUB_CLIENT_ID) {
    return c.text("server misconfigured: GITHUB_CLIENT_ID missing", 500);
  }
  const oauthReq = await c.env.OAUTH_PROVIDER.parseAuthRequest(c.req.raw);
  const issuedAt = nowSeconds();
  const nonce = randomNonce();
  const expiresAt = issuedAt + STATE_TTL_SECONDS;
  let state;
  try {
    state = await signState(oauthReq, secret, { issuedAt, nonce });
    await recordStateNonce(c.env, nonce, issuedAt, expiresAt);
  } catch {
    return c.text("OAuth state store unavailable", 503);
  }
  const redirectUri = new URL("/callback", c.req.url).toString();
  const githubUrl = new URL("https://github.com/login/oauth/authorize");
  githubUrl.searchParams.set("client_id", c.env.GITHUB_CLIENT_ID);
  githubUrl.searchParams.set("redirect_uri", redirectUri);
  githubUrl.searchParams.set("scope", "read:user");
  githubUrl.searchParams.set("state", state);
  return c.redirect(githubUrl.toString());
});

githubHandler.get("/callback", async (c) => {
  const code = c.req.query("code");
  const state = c.req.query("state");
  if (!code || !state) return c.text("missing code/state", 400);

  const secret = stateSecret(c.env);
  if (!secret) {
    return c.text("server misconfigured: state secret unset", 500);
  }
  const observedAt = nowSeconds();
  const verified = await verifyState(state, secret, observedAt);
  if (!verified) return c.text("invalid state", 400);
  try {
    if (!await consumeStateNonce(c.env, verified.nonce, observedAt)) {
      return c.text("invalid state", 400);
    }
  } catch {
    return c.text("OAuth state validation unavailable", 503);
  }

  const tokenRes = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({
      client_id: c.env.GITHUB_CLIENT_ID,
      client_secret: c.env.GITHUB_CLIENT_SECRET,
      code,
      redirect_uri: new URL("/callback", c.req.url).toString(),
    }),
  });
  const tokenBody = /** @type {{ access_token?: string }} */ (await tokenRes.json());
  if (!tokenBody.access_token) return c.text("GitHub token exchange failed", 400);

  const userRes = await fetch("https://api.github.com/user", {
    headers: {
      authorization: `Bearer ${tokenBody.access_token}`,
      accept: "application/vnd.github+json",
      "user-agent": "quant-platform-ops-mcp",
    },
  });
  const user = /** @type {{ login?: string, name?: string }} */ (await userRes.json());
  const allowed = String(c.env.ALLOWED_LOGIN || "").trim();
  if (!user.login || user.login !== allowed) {
    return c.text(
      `access denied: GitHub user "${user.login ?? "unknown"}" is not allowed`,
      403,
    );
  }

  const { redirectTo } = await c.env.OAUTH_PROVIDER.completeAuthorization({
    request: verified.request,
    userId: user.login,
    metadata: { label: user.login },
    scope: ["quant.read.ops"],
    props: { login: user.login, name: user.name ?? user.login },
  });
  return c.redirect(redirectTo);
});

githubHandler.get("/", (c) =>
  c.text(
    "quant-ops-mcp: remote Ops MCP (GitHub OAuth). Register this origin's /mcp in ChatGPT/Claude Connectors.",
  ),
);
