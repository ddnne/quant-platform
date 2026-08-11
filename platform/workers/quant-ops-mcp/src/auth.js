export const OPS_READ_SCOPE = "quant.read.ops";

export class AuthError extends Error {
  /** @param {string} message @param {number} status */
  constructor(message, status = 401) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

/** @param {string} value */
function decodeBase64Url(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - normalized.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

/** @param {string} value */
function decodeJson(value) {
  try {
    return JSON.parse(new TextDecoder().decode(decodeBase64Url(value)));
  } catch {
    throw new AuthError("invalid access token");
  }
}

/** @param {unknown} aud @param {string} required */
function audienceMatches(aud, required) {
  return typeof aud === "string" ? aud === required : Array.isArray(aud) && aud.includes(required);
}

/** @param {Record<string, unknown>} claims */
function principalFromClaims(claims) {
  const subject = typeof claims.sub === "string" ? claims.sub : "";
  const email = typeof claims.email === "string" ? claims.email : "";
  const commonName = typeof claims.common_name === "string" ? claims.common_name : "";
  const serviceId = typeof claims.service_token_id === "string" ? claims.service_token_id : "";
  const identityNonce = typeof claims.identity_nonce === "string" ? claims.identity_nonce : "";
  let kind;
  let identity;
  if (email) {
    kind = "human";
    identity = subject || email;
  } else if (commonName || serviceId || claims.type === "service_token") {
    kind = "service";
    identity = serviceId || subject || commonName;
  } else {
    throw new AuthError("access token does not identify a human or service principal");
  }
  // Managed OAuth intentionally gives the client an opaque token; the origin
  // receives a normal Access assertion without an OAuth client_id. The
  // identity nonce is the stable authenticated grant/session partition for a
  // human. Service assertions expose their Access client ID as common_name.
  const authenticatedClientValue = [claims.azp, claims.client_id].find(
    (item) => typeof item === "string" && item,
  );
  const authenticatedClient = typeof authenticatedClientValue === "string"
    ? authenticatedClientValue
    : "";
  const clientId = authenticatedClient || (kind === "service" ? commonName || serviceId : identityNonce);
  if (!clientId) throw new AuthError("access token has no authenticated client/grant identity");
  return {
    kind,
    subject: `${kind}:${identity}`,
    clientId,
    // The isolated Access application audience is the authorization boundary
    // for this Ops-only server. Access assertions do not carry OAuth scopes.
    scopes: [OPS_READ_SCOPE],
  };
}

const jwksCache = new Map();

/** @param {string} teamDomain @param {typeof fetch} fetchImpl @param {number} now */
async function loadJwks(teamDomain, fetchImpl, now) {
  const cached = jwksCache.get(teamDomain);
  if (cached && cached.expiresAt > now) return cached.keys;
  const response = await fetchImpl(`https://${teamDomain}/cdn-cgi/access/certs`, {
    headers: { accept: "application/json" },
  });
  if (!response.ok) throw new AuthError("unable to validate access token");
  const body = /** @type {{keys?:JsonWebKey[]}} */ (await response.json());
  if (!body || !Array.isArray(body.keys)) throw new AuthError("invalid Access JWKS");
  jwksCache.set(teamDomain, { keys: body.keys, expiresAt: now + 300_000 });
  return body.keys;
}

/**
 * Validate the Access/Managed OAuth JWT at the Worker even when Access already
 * protects the route. Identity tokens and automation service tokens remain
 * distinguishable principals. The dedicated Access application/AUD grants
 * only the advertised Ops-read resource capability; Access assertions do not
 * contain the OAuth scope requested by the client.
 * @param {Request} request
 * @param {{ACCESS_TEAM_DOMAIN:string, ACCESS_AUD:string}} env
 * @param {{fetchImpl?:typeof fetch, now?:number, jwks?:JsonWebKey[]}} deps
 */
export async function authenticateAccess(request, env, deps = {}) {
  const teamDomain = String(env.ACCESS_TEAM_DOMAIN || "").trim().replace(/^https:\/\//, "").replace(/\/$/, "");
  const audience = String(env.ACCESS_AUD || "").trim();
  if (!teamDomain || teamDomain.startsWith("replace-") || !audience || audience.startsWith("replace-")) {
    throw new AuthError("Access authentication is not configured", 503);
  }
  const assertion = request.headers.get("Cf-Access-Jwt-Assertion");
  const authorization = request.headers.get("Authorization") || "";
  const bearer = authorization.match(/^Bearer\s+(.+)$/i)?.[1];
  const token = assertion || bearer;
  if (!token) throw new AuthError("authentication required");

  const parts = token.split(".");
  if (parts.length !== 3) throw new AuthError("invalid access token");
  const header = decodeJson(parts[0]);
  const claims = decodeJson(parts[1]);
  if (!header || header.alg !== "RS256" || typeof header.kid !== "string") {
    throw new AuthError("unsupported access token");
  }
  if (!claims || typeof claims !== "object" || Array.isArray(claims)) {
    throw new AuthError("invalid access token claims");
  }
  const now = deps.now ?? Date.now();
  /** @type {JsonWebKey[]} */
  const keys = deps.jwks || await loadJwks(teamDomain, deps.fetchImpl || fetch, now);
  const jwk = keys.find((candidate) => {
    const values = /** @type {JsonWebKey & {kid?:string, alg?:string}} */ (candidate);
    return values.kid === header.kid && (!values.alg || values.alg === "RS256");
  });
  if (!jwk) throw new AuthError("unknown access signing key");
  let key;
  try {
    key = await crypto.subtle.importKey(
      "jwk", jwk,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"],
    );
  } catch {
    throw new AuthError("invalid access signing key");
  }
  const valid = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", key, decodeBase64Url(parts[2]),
    new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
  );
  if (!valid) throw new AuthError("invalid access token signature");

  const typedClaims = /** @type {Record<string, unknown>} */ (claims);
  const seconds = Math.floor(now / 1000);
  if (typeof typedClaims.exp !== "number" || typedClaims.exp <= seconds) throw new AuthError("expired access token");
  if (typeof typedClaims.nbf === "number" && typedClaims.nbf > seconds + 30) throw new AuthError("access token not active");
  if (typedClaims.iss !== `https://${teamDomain}`) throw new AuthError("invalid access token issuer");
  if (!audienceMatches(typedClaims.aud, audience)) throw new AuthError("invalid access token audience");
  return principalFromClaims(typedClaims);
}
