/** Retry delay jitter. crypto.getRandomValues, not Math.random. */

function unitInterval(): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] / 2 ** 32;
}

/** Full jitter in [0, base). */
export function fullJitterMs(base: number): number {
  return Math.floor(unitInterval() * base);
}

/** Half-to-full jitter in [base / 2, base). */
export function halfToFullJitterMs(base: number): number {
  return Math.floor(base / 2 + unitInterval() * (base / 2));
}

function exponentialCapMs(attempt: number, baseMs: number, maxMs: number): number {
  return Math.min(maxMs, baseMs * 2 ** (attempt - 1));
}

/** Exponential backoff + full jitter. Callers own baseMs/maxMs. */
export function exponentialBackoffFullJitterMs(
  attempt: number,
  baseMs: number,
  maxMs: number,
): number {
  return fullJitterMs(exponentialCapMs(attempt, baseMs, maxMs));
}

/** Exponential backoff + half-to-full jitter. Callers own baseMs/maxMs. */
export function exponentialBackoffHalfToFullJitterMs(
  attempt: number,
  baseMs: number,
  maxMs: number,
): number {
  return halfToFullJitterMs(exponentialCapMs(attempt, baseMs, maxMs));
}
