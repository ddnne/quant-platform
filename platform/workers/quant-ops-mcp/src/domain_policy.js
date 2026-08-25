/** Domain-only Quant Ops reads. No SQL or storage handles cross this boundary. */

/** Official JSDA product/index locators. Overlay when inventory SLA omits them. */
export const JSDA_UPSTREAM_LOCATORS = Object.freeze({
  jsda_otc_bond_reference_prices:
    "https://market.jsda.or.jp/shijyo/saiken/baibai/baisanchi/index.html",
  jsda_tokyo_repo_rates: "https://www.jsda.or.jp/shiryoshitsu/toukei/trr/index.html",
  jsda_corporate_bond_transactions:
    "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/",
});

/** @param {unknown} raw */
export function parseDetailJson(raw) {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) return { ...raw };
  if (typeof raw !== "string" || !raw.trim()) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Honest projection status. Stored FRESH is not FRESH unless coverage refresh
 * succeeded (detail_json.refresh_status === "success") and age ≤ 86400s.
 * @param {{generated_at?: unknown, age_seconds?: unknown, status?: unknown, detail_json?: unknown}} metadata
 * @param {number} [now]
 */
export function honestProjectionStatus(metadata, now = Date.now()) {
  let age = null;
  const genAt = Date.parse(String(metadata?.generated_at ?? ""));
  if (!Number.isNaN(genAt)) age = Math.max(0, Math.floor((now - genAt) / 1000));
  else if (metadata?.age_seconds != null && metadata.age_seconds !== "") {
    const stored = Number(metadata.age_seconds);
    age = Number.isFinite(stored) ? Math.max(0, stored) : null;
  }
  let status = String(metadata?.status || "UNKNOWN");
  const refreshStatus = parseDetailJson(metadata?.detail_json).refresh_status ?? null;
  const refreshAttempt =
    refreshStatus != null && refreshStatus !== "" && refreshStatus !== "skipped";
  const refreshOk = refreshStatus === "success";
  if (age == null && String(metadata?.generated_at || "")) status = "UNKNOWN";
  if (status === "FRESH" && age != null && age > 86400) status = "STALE";
  if (status === "FRESH" && age == null) status = "UNKNOWN";
  if (status === "FRESH" && !refreshOk) {
    status = refreshStatus === "failed" ? "DEGRADED_REFRESH_FAILED" : "STALE";
  }
  return { status, age, refreshStatus, refreshAttempt, refreshOk };
}

export function parseSla(raw) {
  if (raw && typeof raw === "object" && !Array.isArray(raw)) return { ...raw };
  if (typeof raw !== "string" || !raw.trim()) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function overlayInventoryRow(row) {
  const sla = parseSla(row.sla);
  const loc = JSDA_UPSTREAM_LOCATORS[row.dataset_id];
  if (loc && !sla.upstream_locator) sla.upstream_locator = loc;
  return { ...row, sla };
}

/**
 * Raw-plane captured labels. ACQUIRED is the live write; COMPLETE is a
 * historical raw-captured label. Neither is dataset Coverage COMPLETE.
 */
export function isRawCaptured(completeness) {
  return completeness === "ACQUIRED" || completeness === "COMPLETE";
}

/**
 * ops_status.raw_retention counts. acquired is the canonical SUM of
 * ACQUIRED|legacy completeness=COMPLETE. complete is a deprecated alias of
 * that sum so live MCP readers of .complete are not Dataset COMPLETE.
 */
export function rawRetentionOpsCounts(raw) {
  const manifests = Number(raw?.manifests || 0);
  const acquired = Number(raw?.acquired || 0);
  return {
    manifests,
    acquired,
    // Deprecated alias of acquired. Not dataset Coverage COMPLETE.
    complete: acquired,
  };
}

/** Raw acquisition ≠ dataset Coverage COMPLETE. */
export function classifyRawAcquisition(row) {
  const completeness = String(row?.completeness || "");
  const rows = Number(row?.row_count ?? 0);
  const bytes = Number(row?.raw_bytes ?? 0);
  if (completeness === "FAILED") return "DOWNLOAD_FAILED";
  if (!isRawCaptured(completeness)) return "UNVERIFIED";
  if (rows > 0) return "EXPECTED_AND_CAPTURED";
  if (bytes > 0) return "EXPECTED_EMPTY_WITH_EVIDENCE";
  return "SOURCE_NOT_PUBLISHED";
}

/**
 * CURRENT requires a local applied cursor. Export lag 0 with applied_cursor null
 * is EXPORT_CURRENT_APPLY_UNPINNED, never CURRENT.
 */
export function syncDatasetState({ exported, applied, lag, changeLogRows }) {
  if (exported == null) {
    return changeLogRows === 0 ? "CHANGE_LOG_EMPTY" : "EXPORT_CURSOR_NULL";
  }
  if (applied == null) {
    if (lag === 0) return "EXPORT_CURRENT_APPLY_UNPINNED";
    if (lag != null && lag > 0) return "LAGGING_APPLY_UNPINNED";
    return "APPLY_UNPINNED";
  }
  if (lag === 0 && Number(applied) === Number(exported)) return "CURRENT";
  if (lag != null && lag > 0) return "LAGGING";
  return "UNKNOWN";
}

/** @param {unknown} row */
export function storedPolicyVersion(row) {
  if (!row || typeof row !== "object") return "";
  const policy = /** @type {{policy_version?: unknown}} */ (row).policy_version;
  return typeof policy === "string" && policy.trim() ? policy.trim() : "";
}

/**
 * Missing-projection reason. Echo stored policy_version; never freeze "Coverage V2".
 * @param {unknown} [row]
 */
export function coverageProjectionMissingReason(row) {
  const policy = storedPolicyVersion(row);
  if (policy) return `Coverage projection (${policy}) has not been populated`;
  return "Coverage projection has not been populated";
}

/**
 * Last-known-good is not current COMPLETE. Echo stored policy_version when present.
 * @param {unknown} lkg
 * @param {{hasActive: boolean}} options
 */
export function lastKnownGoodNotCurrentReason(lkg, { hasActive }) {
  const policy = storedPolicyVersion(lkg);
  const policyNote = policy ? `; policy_version ${policy}` : "";
  if (hasActive) {
    return `active generation missing dataset; last-known-good is not current COMPLETE${policyNote}`;
  }
  return `no active projection generation; last-known-good is not current COMPLETE${policyNote}`;
}

/** @param {string} policy */
export function _parseFreshnessWindow(policy) {
  const map = {
    "intraday_best_effort": 86400000, // 1 day
    "trading_day": 172800000, // 2 days
    "same_trading_day_am": 43200000, // 12 hours (11:30->12:30)
    "event_driven": 604800000, // 7 days
    "weekly": 1209600000, // 14 days
    "calendar_day": 86400000, // 1 day
    "archive": 31536000000, // 1 year (effectively infinite)
    "event_publication": 604800000, // 7 days
  };
  return map[policy] || 604800000; // default 7 days
}
