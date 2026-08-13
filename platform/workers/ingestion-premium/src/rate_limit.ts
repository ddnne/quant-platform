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
 *   * On 429: ``notify429()`` applies a short cooldown and temporarily widens
 *     the interval; subsequent successes via ``notifyOk()`` restore the base
 *     floor quickly so we return to near-ceiling throughput.
 *
 * Premium budget ~500 req/min → 120 ms base floor (exactly 500/min).
 */
export class RateLimiter {
  private readonly baseIntervalMs: number;
  private currentIntervalMs: number;
  private nextAllowedMs = 0;
  private tail: Promise<void> = Promise.resolve();
  private consecutiveOk = 0;
  private rateLimitHits = 0;

  constructor(minIntervalMs: number) {
    this.baseIntervalMs = Math.max(0, Math.floor(minIntervalMs));
    this.currentIntervalMs = this.baseIntervalMs;
  }

  get minIntervalMsValue(): number {
    return this.currentIntervalMs;
  }

  get baseIntervalMsValue(): number {
    return this.baseIntervalMs;
  }

  get rateLimitHitCount(): number {
    return this.rateLimitHits;
  }

  /**
   * Short 429 recovery: push next slot ~1.2s out and briefly run at 2× interval.
   * Does not park at a low long-term rate — ``notifyOk`` restores base quickly.
   */
  notify429(cooldownMs = 1_200): void {
    this.rateLimitHits += 1;
    this.consecutiveOk = 0;
    if (this.baseIntervalMs > 0) {
      // 2× base (e.g. 240 ms) — still near the Premium class, not a deep park.
      this.currentIntervalMs = Math.max(this.baseIntervalMs * 2, this.baseIntervalMs);
    }
    const now = Date.now();
    this.nextAllowedMs = Math.max(this.nextAllowedMs, now + Math.max(0, cooldownMs));
  }

  /** After a successful upstream response, decay back toward the base floor. */
  notifyOk(): void {
    this.consecutiveOk += 1;
    if (this.consecutiveOk >= 2 && this.currentIntervalMs > this.baseIntervalMs) {
      this.currentIntervalMs = this.baseIntervalMs;
    }
  }

  async acquire(): Promise<void> {
    if (this.baseIntervalMs <= 0) return;
    // Chain a reservation: each caller waits for the previous to finish
    // (which has already advanced nextAllowedMs past its own slot).
    const slot = this.tail.then(async () => {
      const now = Date.now();
      const wait = Math.max(0, this.nextAllowedMs - now);
      if (wait > 0) {
        await new Promise<void>((resolve) => setTimeout(resolve, wait));
      }
      const interval = this.currentIntervalMs > 0 ? this.currentIntervalMs : this.baseIntervalMs;
      this.nextAllowedMs = Date.now() + interval;
    });
    // Keep the chain ordered; do not let a thrown rejection break later slots.
    this.tail = slot.then(
      () => undefined,
      () => undefined,
    );
    await slot;
  }
}
