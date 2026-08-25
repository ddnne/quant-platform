import { describe, expect, it } from "vitest";
import {
  LOW_VARIANCE_MAX_ABS_T,
  LOW_VARIANCE_MIN_REL_STD,
  hasPairwiseLowVarianceArtifact,
  invertNets,
  isLowVarianceTArtifact,
  sampleMean,
  sampleStd,
  sharpePeriod,
  tStatVsZeroDetail,
} from "./metrics";

/** W95 fund 2017: near-identical 2-period nets inflate |t|. */
const GIANT_PAIR = [0.008229283197313041, 0.008337431738535494];
const GIANT_TRIPLE = [0.01, 0.0101, 0.01005];
const SPREAD_NETS = [0.1, -0.05, 0.2];

function expectLowVarianceArtifact(nets: number[]): void {
  const d = tStatVsZeroDetail(nets);
  expect(d.n).toBe(nets.length);
  expect(d.t_stat).toBeNull();
  expect(d.reason).toBe("low_variance_artifact");
  expect(d.raw_t_stat).not.toBeNull();
  expect(Math.abs(d.raw_t_stat as number)).toBeGreaterThan(LOW_VARIANCE_MAX_ABS_T);
  expect(d.cv).not.toBeNull();
  expect(d.cv as number).toBeLessThan(LOW_VARIANCE_MIN_REL_STD);
  expect(isLowVarianceTArtifact(d.n, d.mean, d.std, d.raw_t_stat)).toBe(true);
}

describe("sampleMean", () => {
  it("empty is null; [1,2,3] is 2; skips null/undefined/NaN", () => {
    expect(sampleMean([])).toBeNull();
    expect(sampleMean([1, 2, 3])).toBe(2);
    expect(sampleMean([1, null, 2, undefined, Number.NaN, 3])).toBe(2);
  });
});

describe("sampleStd", () => {
  it("n=1 is 0; n=0 is null", () => {
    expect(sampleStd([7])).toBe(0);
    expect(sampleStd([])).toBeNull();
    expect(sampleStd([null, Number.NaN])).toBeNull();
  });
});

describe("tStatVsZeroDetail n<2", () => {
  it("empty is no_values; n=1 is n_lt_2; t_stat is null", () => {
    const empty = tStatVsZeroDetail([]);
    expect(empty.n).toBe(0);
    expect(empty.reason).toBe("no_values");
    expect(empty.t_stat).toBeNull();
    expect(empty.raw_t_stat).toBeNull();

    const one = tStatVsZeroDetail([1]);
    expect(one.n).toBe(1);
    expect(one.reason).toBe("n_lt_2");
    expect(one.t_stat).toBeNull();
    expect(one.raw_t_stat).toBeNull();
  });
});

describe("tStatVsZeroDetail zero std", () => {
  it("mean 0 is zero_std; t_stat is null", () => {
    const d = tStatVsZeroDetail([0, 0]);
    expect(d.reason).toBe("zero_std");
    expect(d.t_stat).toBeNull();
    expect(d.raw_t_stat).toBeNull();
    expect(d.std).toBe(0);
    expect(d.mean).toBe(0);
  });

  it("nonzero mean is low_variance_artifact; t_stat is null", () => {
    const d = tStatVsZeroDetail([1, 1]);
    expect(d.reason).toBe("low_variance_artifact");
    expect(d.t_stat).toBeNull();
    expect(d.raw_t_stat).toBeNull();
    expect(d.std).toBe(0);
    expect(d.mean).toBe(1);
  });
});

describe("W95 low-variance inflated-t", () => {
  it("small-n near-identical nets null t_stat and keep raw_t_stat", () => {
    expectLowVarianceArtifact(GIANT_PAIR);
    expectLowVarianceArtifact(GIANT_TRIPLE);
  });
});

describe("hasPairwiseLowVarianceArtifact", () => {
  it("true when a 2-period subset is the artifact; false for well-spread nets", () => {
    expect(hasPairwiseLowVarianceArtifact([...GIANT_PAIR, -0.02])).toBe(true);
    expect(hasPairwiseLowVarianceArtifact(SPREAD_NETS)).toBe(false);
  });
});

describe("sharpePeriod", () => {
  it("n<2 is null; low-variance artifact is null", () => {
    expect(sharpePeriod([])).toBeNull();
    expect(sharpePeriod([0.01])).toBeNull();
    expect(sharpePeriod(GIANT_PAIR)).toBeNull();
    expect(sharpePeriod(GIANT_TRIPLE)).toBeNull();
  });
});

describe("invertNets", () => {
  it("without costs is -net; with amortized cost uses -gross - cost", () => {
    expect(invertNets([0.5, -0.25])).toEqual([-0.5, 0.25]);
    // gross = net + cost; inverted net = -gross - cost
    expect(invertNets([0.5, -0.25], [0.125, 0.125])).toEqual([-0.75, 0]);
  });
});
