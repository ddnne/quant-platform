/** Test-harness-only authority; this module is not the Worker entrypoint. */

import type { V3CutoverAuthority } from "./cutover";
import { createJsdaWorker } from "./worker";

const FIXTURE_CUTOVER_AUTHORITY: V3CutoverAuthority = Object.freeze({
  async verifyActivation(_db, record): Promise<boolean> {
    return (
      record.activated_source_sha === "a".repeat(40) &&
      record.drain_evidence_digest === `sha256:${"b".repeat(64)}`
    );
  },
});

export default createJsdaWorker(FIXTURE_CUTOVER_AUTHORITY);
