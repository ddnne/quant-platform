/**
 * Phase 3.5 (P0-4) — Promise-based minimum-interval rate limiter.
 *
 * The limiter serializes state mutation through a Promise chain so that
 * concurrent ``acquire()`` callers each receive a slot at least
 * ``min_interval_ms`` apart — even though JavaScript is single-threaded, the
 * event loop interleaves ``fetch`` resolutions, so a shared reservation
 * variable must be guarded.
 *
 * Behavior:
 *   * First call never waits (reserves the next slot at now + interval).
 *   * Subsequent calls either take the reserved slot immediately or sleep
 *     until it is their turn, then advance the reservation by one interval.
 *   * ``min_interval_ms <= 0`` disables the limiter (``acquire`` is a no-op).
 *
 * The Premium budget is ~500 req/min → a 125 ms floor leaves headroom for
 * bursty parallel ingest without throttling at the upstream.
 */
export class RateLimiter {
  private readonly minIntervalMs: number;
  private nextAllowedMs = 0;
  private tail: Promise<void> = Promise.resolve();

  constructor(minIntervalMs: number) {
    this.minIntervalMs = Math.max(0, Math.floor(minIntervalMs));
  }

  get minIntervalMsValue(): number {
    return this.minIntervalMs;
  }

  async acquire(): Promise<void> {
    if (this.minIntervalMs <= 0) return;
    // Chain a reservation: each caller waits for the previous to finish
    // (which has already advanced nextAllowedMs past its own slot).
    const slot = this.tail.then(async () => {
      const now = Date.now();
      const wait = Math.max(0, this.nextAllowedMs - now);
      if (wait > 0) {
        await new Promise<void>((resolve) => setTimeout(resolve, wait));
      }
      this.nextAllowedMs = Date.now() + this.minIntervalMs;
    });
    // Keep the chain ordered; do not let a thrown rejection break later slots.
    this.tail = slot.then(
      () => undefined,
      () => undefined,
    );
    await slot;
  }
}
