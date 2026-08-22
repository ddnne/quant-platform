export function isMdhCollapseSignal(signalId: unknown): boolean {
  return String(signalId || "").startsWith("c21_lite_fallback_mdh:");
}

export function isPathCollapsedRow(row: {
  path_collapsed?: boolean;
  status?: string;
  signal_id?: string;
  skip_reason?: string;
}): boolean {
  if (row.path_collapsed || row.status === "path_collapsed") return true;
  if (isMdhCollapseSignal(row.signal_id)) return true;
  const reason = String(row.skip_reason || "");
  return (
    reason.startsWith("unique_unsupported") || reason.startsWith("path_collapsed")
  );
}
