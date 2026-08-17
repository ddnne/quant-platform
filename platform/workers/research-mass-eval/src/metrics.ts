/**
 * Pure TS lite stats for multi-period nets (mirrors research.stats_metrics).
 * Research-only · no significance / edge claim.
 */

export function finiteFloats(values: Array<number | null | undefined>): number[] {
  const out: number[] = [];
  for (const v of values) {
    if (v === null || v === undefined) continue;
    const x = Number(v);
    if (Number.isFinite(x)) out.push(x);
  }
  return out;
}

export function sampleMean(values: Array<number | null | undefined>): number | null {
  const vals = finiteFloats(values);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

export function sampleStd(
  values: Array<number | null | undefined>,
  ddof = 1,
): number | null {
  const vals = finiteFloats(values);
  const n = vals.length;
  if (n === 0) return null;
  if (n === 1) return 0;
  const m = vals.reduce((a, b) => a + b, 0) / n;
  let acc = 0;
  for (const x of vals) acc += (x - m) ** 2;
  const denom = ddof <= 0 ? n : n - 1;
  if (denom <= 0) return 0;
  return Math.sqrt(acc / denom);
}

/** One-sample t vs 0: t = mean / (s / sqrt(n)). */
export function tStatVsZero(values: Array<number | null | undefined>): number | null {
  const vals = finiteFloats(values);
  const n = vals.length;
  if (n < 2) return null;
  const m = sampleMean(vals);
  const s = sampleStd(vals, 1);
  if (m === null || s === null || s === 0) return null;
  return m / (s / Math.sqrt(n));
}

/** Period Sharpe = mean / std of period nets (no extra sqrt(N)). */
export function sharpePeriod(values: Array<number | null | undefined>): number | null {
  const vals = finiteFloats(values);
  if (vals.length < 2) return null;
  const m = sampleMean(vals);
  const s = sampleStd(vals, 1);
  if (m === null || s === null || s === 0) return null;
  return m / s;
}

export function invertNets(
  values: Array<number | null | undefined>,
  amortizedCosts: Array<number | null | undefined> | null = null,
): Array<number | null> {
  // inverted gross = -gross; net_inv ≈ -gross - cost = -(gross - cost) - 2*cost
  // When only nets provided: approximate as -net (cost already in net).
  // Prefer gross-based when costs given.
  return values.map((v, i) => {
    if (v === null || v === undefined || !Number.isFinite(Number(v))) return null;
    if (amortizedCosts && amortizedCosts[i] != null && Number.isFinite(Number(amortizedCosts[i]))) {
      // v is net = gross - cost → gross = net + cost; inv_net = -gross - cost
      const cost = Number(amortizedCosts[i]);
      const gross = Number(v) + cost;
      return -gross - cost;
    }
    return -Number(v);
  });
}

export function sha256HexSync(input: string): Promise<string> {
  const enc = new TextEncoder();
  return crypto.subtle.digest("SHA-256", enc.encode(input)).then((buf) => {
    const bytes = new Uint8Array(buf);
    return Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  });
}
