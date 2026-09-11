import { afterEach, describe, expect, it, vi } from "vitest";
import {
  exponentialBackoffFullJitterMs,
  exponentialBackoffHalfToFullJitterMs,
  fullJitterMs,
  halfToFullJitterMs,
  sleepMs,
} from "./retry_jitter";

const UINT32_MAX = 0xffff_ffff;

function fillUint32(value: number) {
  return vi.spyOn(crypto, "getRandomValues").mockImplementation((array) => {
    (array as Uint32Array)[0] = value;
    return array;
  });
}

describe("retry jitter", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("maps unit interval 0 onto full and half-to-full ranges", () => {
    fillUint32(0);
    expect(fullJitterMs(1_000)).toBe(0);
    expect(halfToFullJitterMs(1_000)).toBe(500);
  });

  it("maps unit interval 0 and ~1 onto full and half-to-full ranges", () => {
    fillUint32(UINT32_MAX);
    expect(fullJitterMs(1_000)).toBe(999);
    expect(halfToFullJitterMs(1_000)).toBe(999);
  });

  it("exponential full jitter uses persist 500/8000 caps at unit 0", () => {
    fillUint32(0);
    expect(exponentialBackoffFullJitterMs(1, 500, 8_000)).toBe(0);
    expect(exponentialBackoffFullJitterMs(5, 500, 8_000)).toBe(0);
  });

  it("exponential full jitter uses persist 500/8000 caps at unit ~1", () => {
    fillUint32(UINT32_MAX);
    expect(exponentialBackoffFullJitterMs(1, 500, 8_000)).toBe(499);
    expect(exponentialBackoffFullJitterMs(2, 500, 8_000)).toBe(999);
    expect(exponentialBackoffFullJitterMs(4, 500, 8_000)).toBe(3_999);
    expect(exponentialBackoffFullJitterMs(5, 500, 8_000)).toBe(7_999);
    expect(exponentialBackoffFullJitterMs(6, 500, 8_000)).toBe(7_999);
  });

  it("exponential half-to-full jitter uses 429 1000/3000 caps at unit 0", () => {
    fillUint32(0);
    expect(exponentialBackoffHalfToFullJitterMs(1, 1_000, 3_000)).toBe(500);
    expect(exponentialBackoffHalfToFullJitterMs(2, 1_000, 3_000)).toBe(1_000);
    expect(exponentialBackoffHalfToFullJitterMs(3, 1_000, 3_000)).toBe(1_500);
    expect(exponentialBackoffHalfToFullJitterMs(4, 1_000, 3_000)).toBe(1_500);
  });

  it("exponential half-to-full jitter uses 429 1000/3000 caps at unit ~1", () => {
    fillUint32(UINT32_MAX);
    expect(exponentialBackoffHalfToFullJitterMs(1, 1_000, 3_000)).toBe(999);
    expect(exponentialBackoffHalfToFullJitterMs(2, 1_000, 3_000)).toBe(1_999);
    expect(exponentialBackoffHalfToFullJitterMs(3, 1_000, 3_000)).toBe(2_999);
  });

  it("sleepMs resolves", async () => {
    await expect(sleepMs(0)).resolves.toBeUndefined();
  });
});
