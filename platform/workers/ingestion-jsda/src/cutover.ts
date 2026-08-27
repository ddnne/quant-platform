import type { JsdaWorkerEnv } from "./env";

export type V3CutoverStatus = {
  productReady: boolean;
  cutover: "V3_ACTIVE" | "PENDING" | "INVALID" | "UNKNOWN";
};

export async function loadV3CutoverStatus(
  db: JsdaWorkerEnv["DB"],
): Promise<V3CutoverStatus> {
  const row = await db
    .prepare(
      `SELECT phase, activated_at, activated_source_sha, drain_evidence_digest
         FROM jsda_v3_cutover_control
        WHERE singleton=1`,
    )
    .first<{
      phase: string;
      activated_at: string | null;
      activated_source_sha: string | null;
      drain_evidence_digest: string | null;
    }>();
  if (row?.phase === "bridge") {
    return { productReady: false, cutover: "PENDING" };
  }
  if (
    row?.phase === "v3_active" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(
      row.activated_at ?? "",
    ) &&
    /^[0-9a-f]{40}$/.test(row.activated_source_sha ?? "") &&
    /^sha256:[0-9a-f]{64}$/.test(row.drain_evidence_digest ?? "")
  ) {
    return { productReady: true, cutover: "V3_ACTIVE" };
  }
  return { productReady: false, cutover: "INVALID" };
}

export async function requireV3CutoverActive(
  db: JsdaWorkerEnv["DB"],
): Promise<void> {
  try {
    const status = await loadV3CutoverStatus(db);
    if (status.productReady) return;
  } catch {
    // A missing/malformed migration surface is never product-ready.
  }
  throw new Error("JSDA_V3_CUTOVER_PENDING");
}
