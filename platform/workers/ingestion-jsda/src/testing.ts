/** Test-harness-only cutover pin; this module is not the Worker entrypoint. */

import { createJsdaWorker } from "./worker";
import type { V3CutoverPin } from "./cutover";

export const FIXTURE_V3_CUTOVER_PIN: V3CutoverPin = Object.freeze({
  configDigest: `sha256:${"b".repeat(64)}`,
});

export const FIXTURE_DRAIN_EVIDENCE_DIGEST = `sha256:${"d".repeat(64)}`;
export const FIXTURE_CUTOVER_SOURCE_SHA = "a".repeat(40);
export const FIXTURE_CUTOVER_ACTIVATED_AT = "2026-08-25T01:29:00.000Z";

export const FIXTURE_DRAIN_INSERT_SQL = `INSERT INTO jsda_v3_drain_evidence
        (drain_evidence_digest, observed_at, document_json)
      VALUES (?, ?, '{"schema_version":"jsda-v3-drain-evidence/v1"}')`;

export const FIXTURE_CUTOVER_ACTIVATE_SQL = `UPDATE jsda_v3_cutover_control
        SET phase='v3_active', activated_at=?, activated_source_sha=?,
            cutover_config_digest=?, drain_evidence_digest=?
      WHERE singleton=1 AND phase='bridge'`;

export function fixtureDrainBind(): [string, string] {
  return [FIXTURE_DRAIN_EVIDENCE_DIGEST, FIXTURE_CUTOVER_ACTIVATED_AT];
}

export function fixtureCutoverBind(): [string, string, string, string] {
  return [
    FIXTURE_CUTOVER_ACTIVATED_AT,
    FIXTURE_CUTOVER_SOURCE_SHA,
    FIXTURE_V3_CUTOVER_PIN.configDigest,
    FIXTURE_DRAIN_EVIDENCE_DIGEST,
  ];
}

export async function writeFixtureCutover(db: D1Database): Promise<void> {
  await db.prepare(FIXTURE_DRAIN_INSERT_SQL).bind(...fixtureDrainBind()).run();
  await db
    .prepare(FIXTURE_CUTOVER_ACTIVATE_SQL)
    .bind(...fixtureCutoverBind())
    .run();
}

export default createJsdaWorker(FIXTURE_V3_CUTOVER_PIN);
