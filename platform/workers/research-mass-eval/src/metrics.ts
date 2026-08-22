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

/** W95: small-n near-identical nets inflate |t|; null instead of emitting giant t. */
export const LOW_VARIANCE_SMALL_N_MAX = 3;
export const LOW_VARIANCE_MIN_REL_STD = 0.05;
export const LOW_VARIANCE_MAX_ABS_T = 12.0;

export function isLowVarianceTArtifact(
  n: number,
  meanNet: number | null,
  stdNet: number | null,
  tStat: number | null,
): boolean {
  if (n < 2 || n > LOW_VARIANCE_SMALL_N_MAX) return false;
  if (meanNet === null || stdNet === null || tStat === null) return false;
  if (![meanNet, stdNet, tStat].every((x) => Number.isFinite(x))) return false;
  const absM = Math.abs(meanNet);
  if (absM <= 0) return false;
  const cv = stdNet / absM;
  // Strict: CV below floor AND implausibly large |t| (no 2× CV looseness).
  return cv < LOW_VARIANCE_MIN_REL_STD && Math.abs(tStat) > LOW_VARIANCE_MAX_ABS_T;
}

/**
 * One-sample t vs 0: t = mean / (s / sqrt(n)).
 * W95: returns null on zero-std or low-variance artifact (raw available via detail).
 */
export function tStatVsZero(values: Array<number | null | undefined>): number | null {
  return tStatVsZeroDetail(values).t_stat;
}

export function tStatVsZeroDetail(
  values: Array<number | null | undefined>,
): {
  t_stat: number | null;
  raw_t_stat: number | null;
  mean: number | null;
  std: number | null;
  n: number;
  reason: string;
  cv: number | null;
} {
  const vals = finiteFloats(values);
  const n = vals.length;
  if (n < 2) {
    return {
      t_stat: null,
      raw_t_stat: null,
      mean: sampleMean(vals),
      std: n === 1 ? 0 : null,
      n,
      reason: n === 0 ? "no_values" : "n_lt_2",
      cv: null,
    };
  }
  const m = sampleMean(vals);
  const s = sampleStd(vals, 1);
  if (m === null || s === null) {
    return {
      t_stat: null,
      raw_t_stat: null,
      mean: m,
      std: s,
      n,
      reason: "no_values",
      cv: null,
    };
  }
  if (s === 0) {
    return {
      t_stat: null,
      raw_t_stat: null,
      mean: m,
      std: 0,
      n,
      reason: m === 0 ? "zero_std" : "low_variance_artifact",
      cv: 0,
    };
  }
  const t = m / (s / Math.sqrt(n));
  const cv = m === 0 ? null : s / Math.abs(m);
  if (isLowVarianceTArtifact(n, m, s, t)) {
    return {
      t_stat: null,
      raw_t_stat: t,
      mean: m,
      std: s,
      n,
      reason: "low_variance_artifact",
      cv,
    };
  }
  return {
    t_stat: t,
    raw_t_stat: t,
    mean: m,
    std: s,
    n,
    reason: "ok",
    cv,
  };
}

/** True if any 2-period subset is a low-variance inflated-t artifact. */
export function hasPairwiseLowVarianceArtifact(
  values: Array<number | null | undefined>,
): boolean {
  const vals = finiteFloats(values);
  if (vals.length < 2) return false;
  for (let i = 0; i < vals.length; i++) {
    for (let j = i + 1; j < vals.length; j++) {
      const detail = tStatVsZeroDetail([vals[i], vals[j]]);
      if (detail.reason === "low_variance_artifact") return true;
    }
  }
  return false;
}

/** Period Sharpe = mean / std of period nets (no extra sqrt(N)). */
export function sharpePeriod(values: Array<number | null | undefined>): number | null {
  const vals = finiteFloats(values);
  if (vals.length < 2) return null;
  const detail = tStatVsZeroDetail(vals);
  if (detail.reason === "low_variance_artifact") return null;
  const m = detail.mean;
  const s = detail.std;
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
