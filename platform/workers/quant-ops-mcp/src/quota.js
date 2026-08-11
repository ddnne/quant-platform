export class QuotaExceeded extends Error {
  constructor() {
    super("daily Quant Ops Read quota exceeded");
    this.name = "QuotaExceeded";
  }
}

/** @param {unknown} value */
function positiveLimit(value) {
  const limit = Number(value);
  if (!Number.isInteger(limit) || limit < 1) throw new TypeError("daily quota must be a positive integer");
  return limit;
}

/** @param {{subject:string, clientId:string}} principal */
function keyParts(principal) {
  if (!principal || typeof principal.subject !== "string" || !principal.subject ||
      typeof principal.clientId !== "string" || !principal.clientId) {
    throw new TypeError("quota requires an authenticated subject and client");
  }
  return [principal.subject, principal.clientId];
}

/** @param {number} now */
function utcDay(now) {
  return new Date(now).toISOString().slice(0, 10);
}

export class DurableDailyQuota {
  /** @param {D1Database} db @param {number|string} limit */
  constructor(db, limit) {
    this.db = db;
    this.limit = positiveLimit(limit);
  }

  /** @param {{subject:string, clientId:string}} principal @param {number} units @param {number} now */
  async charge(principal, units, now = Date.now()) {
    const amount = Number(units);
    if (!Number.isInteger(amount) || amount < 0) throw new TypeError("quota units must be a nonnegative integer");
    if (amount > this.limit) throw new QuotaExceeded();
    const [subject, client] = keyParts(principal);
    const day = utcDay(now);
    const updatedAt = new Date(now).toISOString();
    const row = await this.db.prepare(
      `INSERT INTO remote_mcp_daily_quota
         (quota_day, subject_id, client_id, used, limit_value, updated_at)
       VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(quota_day, subject_id, client_id) DO UPDATE SET
         used = remote_mcp_daily_quota.used + excluded.used,
         limit_value = excluded.limit_value,
         updated_at = excluded.updated_at
       WHERE remote_mcp_daily_quota.used + excluded.used <= excluded.limit_value
       RETURNING used, limit_value`,
    ).bind(day, subject, client, amount, this.limit, updatedAt).first();
    if (!row) throw new QuotaExceeded();
    const used = Number(row.used);
    return { day, used, remaining: this.limit - used, limit: this.limit };
  }
}

/** In-memory implementation is intentionally for local/unit tests only. */
export class MemoryDailyQuota {
  /** @param {number|string} limit */
  constructor(limit) {
    this.limit = positiveLimit(limit);
    this.values = new Map();
  }

  /** @param {{subject:string, clientId:string}} principal @param {number} units @param {number} now */
  async charge(principal, units, now = Date.now()) {
    const amount = Number(units);
    if (!Number.isInteger(amount) || amount < 0) throw new TypeError("quota units must be a nonnegative integer");
    const [subject, client] = keyParts(principal);
    const day = utcDay(now);
    const key = `${day}\u0000${subject}\u0000${client}`;
    const used = (this.values.get(key) || 0) + amount;
    if (used > this.limit) throw new QuotaExceeded();
    this.values.set(key, used);
    return { day, used, remaining: this.limit - used, limit: this.limit };
  }
}

/** @param {unknown} value */
export function quotaCost(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return 1;
  const record = /** @type {Record<string, unknown>} */ (value);
  const collections = [
    "segments", "gaps", "datasets", "failures", "quality", "attestations", "watermarks",
  ];
  const rows = collections.reduce((total, key) => {
    const candidate = record[key];
    return total + (Array.isArray(candidate) ? candidate.length : 0);
  }, 0);
  return Math.max(1, rows);
}

