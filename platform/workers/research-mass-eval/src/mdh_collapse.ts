/** Period-net MDH fallback is not a unique/event/CS evaluation. */
export function isMdhCollapseSignal(signalId: unknown): boolean {
  return String(signalId || "").startsWith("c21_lite_fallback_mdh:");
}
