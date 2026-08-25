/**
 * P0 CF-native write-path guard.
 * J-Quants Premium core (23) structured history → R2 by default.
 * D1 keeps control-plane + optional tiny hot allowlist only.
 */

import { PREMIUM_CORE_DATASETS } from "./catalog";

/** Full Premium core set (23) — all default to R2 structured path. */
export const PREMIUM_CORE_DATASET_IDS = PREMIUM_CORE_DATASETS.map(
  (spec) => spec.id,
);

/** High-volume / history-heavy (R2-only structured always). */
export const HIGH_VOLUME_DATASETS = new Set<string>(PREMIUM_CORE_DATASET_IDS);

/**
 * Tiny datasets that may still dual-write D1 for MCP hot lookups.
 * Empty by default = all Premium core structured goes R2-only.
 * Override with env ALLOW_D1_STRUCTURED_DATASETS=markets_calendar,fins_summary
 */
export function d1StructuredAllowlist(
  env?: { ALLOW_D1_STRUCTURED_DATASETS?: string },
): Set<string> {
  const raw = env?.ALLOW_D1_STRUCTURED_DATASETS?.trim();
  if (!raw) return new Set();
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

/** Datasets that must never full-history upsert into jquants_records. */
export function isR2Only(
  dataset: string,
  env?: {
    MASTER_SCD2_ONLY?: string;
    ALLOW_D1_STRUCTURED_DATASETS?: string;
  },
): boolean {
  if (d1StructuredAllowlist(env).has(dataset)) return false;
  if (HIGH_VOLUME_DATASETS.has(dataset)) return true;
  // Any other jquants dataset id: prefer R2 to protect D1.
  if (dataset.startsWith("jsda_") || dataset.startsWith("edinet_")) return true;
  return false;
}

export function wantsSummaryChangeLog(dataset: string): boolean {
  return isR2Only(dataset);
}

export function r2DatasetSegment(dataset: string): string {
  return dataset.replace(/[^A-Za-z0-9_.-]/g, "_");
}

export function r2DateSegment(eventTime: string | undefined | null): string {
  if (eventTime && typeof eventTime === "string") {
    const m = /^(\d{4}-\d{2}-\d{2})/.exec(eventTime);
    if (m) return m[1];
  }
  return "0000-01-01";
}
