import { afterEach, describe, expect, it, vi } from "vitest";
import { RateLimiter } from "./rate_limit";

describe("RateLimiter", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("acquire is a no-op when min interval is 0 or negative", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_700_000_000_000);

    for (const min of [0, -1, -120]) {
      const rl = new RateLimiter(min);
      expect(rl.baseIntervalMsValue).toBe(0);
      expect(rl.minIntervalMsValue).toBe(0);
      const t0 = Date.now();
      await Promise.all([rl.acquire(), rl.acquire()]);
      expect(Date.now()).toBe(t0);
      expect(vi.getTimerCount()).toBe(0);
    }
  });

  it("first acquire does not wait", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_700_000_000_000);
    const rl = new RateLimiter(40);
    const t0 = Date.now();
    await rl.acquire();
    expect(Date.now()).toBe(t0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("two acquires with interval > 0 are serialized at least interval apart", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_700_000_000_000);
    const interval = 40;
    const rl = new RateLimiter(interval);
    const times: number[] = [];
    const first = rl.acquire().then(() => {
      times.push(Date.now());
    });
    const second = rl.acquire().then(() => {
      times.push(Date.now());
    });
    await vi.runAllTimersAsync();
    await Promise.all([first, second]);
    expect(times).toHaveLength(2);
    expect(times[1]! - times[0]!).toBeGreaterThanOrEqual(interval);
  });

  it("notify429 widens the interval; notifyOk restores toward base", () => {
    const base = 120;
    const rl = new RateLimiter(base);
    expect(rl.baseIntervalMsValue).toBe(base);
    expect(rl.minIntervalMsValue).toBe(base);
    expect(rl.rateLimitHitCount).toBe(0);

    rl.notify429();
    expect(rl.rateLimitHitCount).toBe(1);
    expect(rl.minIntervalMsValue).toBe(base * 2);
    expect(rl.baseIntervalMsValue).toBe(base);

    rl.notifyOk();
    expect(rl.minIntervalMsValue).toBe(base * 2);

    rl.notifyOk();
    expect(rl.minIntervalMsValue).toBe(base);
    expect(rl.baseIntervalMsValue).toBe(base);
    expect(rl.rateLimitHitCount).toBe(1);
  });
});
