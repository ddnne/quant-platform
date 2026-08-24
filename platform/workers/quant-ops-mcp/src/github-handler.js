/**
 * GitHub OAuth default handler (news-mcp pattern, single-user ALLOWED_LOGIN).
 * /authorize → GitHub → /callback → OAUTH_PROVIDER.completeAuthorization
 */
import { Hono } from "hono";

const STATE_LABEL = "quant-ops-mcp.oauth-state.v1";

/** @param {{ STATE_SECRET?: string, GITHUB_CLIENT_SECRET?: string }} env */
function stateSecret(env) {
  return env.STATE_SECRET || env.GITHUB_CLIENT_SECRET || "";
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

/** @param {unknown} req @param {string} secret */
export async function signState(req, secret) {
  if (!secret) throw new Error("state secret unset");
  const payload = bytesToB64url(new TextEncoder().encode(JSON.stringify(req)));
  const sig = bytesToB64url(await hmacSha256(secret, `${STATE_LABEL}.${payload}`));
  return `${payload}.${sig}`;
}

/** @param {string} state @param {string} secret */
export async function verifyState(state, secret) {
  if (!secret) return null;
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
    return JSON.parse(new TextDecoder().decode(b64urlToBytes(payload)));
  } catch {
    return null;
  }
}

/**
 * @typedef {{
 *   GITHUB_CLIENT_ID?: string,
 *   GITHUB_CLIENT_SECRET?: string,
 *   STATE_SECRET?: string,
 *   ALLOWED_LOGIN?: string,
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
    return c.text(
      "server misconfigured: set GITHUB_CLIENT_SECRET (or STATE_SECRET)",
      500,
    );
  }
  if (!c.env.GITHUB_CLIENT_ID) {
    return c.text("server misconfigured: GITHUB_CLIENT_ID missing", 500);
  }
  const oauthReq = await c.env.OAUTH_PROVIDER.parseAuthRequest(c.req.raw);
  const redirectUri = new URL("/callback", c.req.url).toString();
  const githubUrl = new URL("https://github.com/login/oauth/authorize");
  githubUrl.searchParams.set("client_id", c.env.GITHUB_CLIENT_ID);
  githubUrl.searchParams.set("redirect_uri", redirectUri);
  githubUrl.searchParams.set("scope", "read:user");
  githubUrl.searchParams.set("state", await signState(oauthReq, secret));
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
  const oauthReq = await verifyState(state, secret);
  if (!oauthReq) return c.text("invalid state", 400);

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
    request: oauthReq,
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
