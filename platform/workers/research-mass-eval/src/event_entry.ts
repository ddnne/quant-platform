/** PIT event entry. Missing DiscTime is not same-day. Not GO. */

export function discTimeKnown(discTime: string | null | undefined): boolean {
  const t = String(discTime || "").trim();
  if (t.length < 4) return false;
  const hh = Number(t.slice(0, 2));
  return Number.isFinite(hh);
}

export function afterClose(discTime: string | null | undefined): boolean {
  const t = String(discTime || "").trim();
  if (!discTimeKnown(t)) return false;
  const hh = Number(t.slice(0, 2));
  return hh >= 15;
}

/** Shift +1 when after close or time unknown. Same-day only if pre-close time known. */
export function pitEventEntryShift(discTime: string | null | undefined): 0 | 1 {
  if (!discTimeKnown(discTime)) return 1;
  return afterClose(discTime) ? 1 : 0;
}
