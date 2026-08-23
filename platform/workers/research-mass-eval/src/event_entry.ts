/** PIT event entry. Missing DiscTime is not same-day. Not GO. */

function discClock(discTime: string): string {
  const t = discTime.trim();
  if (t.includes("T")) return (t.split("T")[1] || "").slice(0, 8);
  return t.slice(0, 8);
}

export function discTimeKnown(discTime: string | null | undefined): boolean {
  const t = String(discTime || "").trim();
  if (t.length < 4) return false;
  const clock = discClock(t);
  // Date-start invent is not a print clock (Python: T00:00:00 without DiscTime).
  if (clock === "00:00:00" || clock === "00:00") return false;
  const hh = Number(clock.slice(0, 2));
  return Number.isFinite(hh);
}

export function afterClose(discTime: string | null | undefined): boolean {
  const t = String(discTime || "").trim();
  if (!discTimeKnown(t)) return false;
  const hh = Number(discClock(t).slice(0, 2));
  return hh >= 15;
}

/** Shift +1 when after close or time unknown. Same-day only if pre-close time known. */
export function pitEventEntryShift(discTime: string | null | undefined): 0 | 1 {
  if (!discTimeKnown(discTime)) return 1;
  return afterClose(discTime) ? 1 : 0;
}
