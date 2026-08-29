import { describe, expect, it } from "vitest";

import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  parsePersonalResearchRequest,
  personalResearchCohortDigest,
  personalResearchJobIdFromPath,
  personalResearchRequestDigest,
  personalResearchUniverseRuleDigest,
} from "./personal_research_contract";

const SHA = "a".repeat(64);
const VALID = {
  cohort_id: "diverse-core-v1" as const,
  job_id: "exact-four-20260829",
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite`,
  snapshot_sha256: SHA,
  period_start: "2022-04-19",
  period_end: "2026-08-27",
  universe_id: "topix_all" as const,
};
const VALID_GZIP = {
  ...VALID,
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite.gz`,
};

describe("personal research request contract", () => {
  it("accepts one content-addressed bounded exact-four request", async () => {
    const parsed = parsePersonalResearchRequest(VALID);
    expect(parsed).toEqual({ ok: true, value: VALID });
    if (!parsed.ok) throw new Error(parsed.error);
    const digest = await personalResearchRequestDigest(parsed.value);
    const canonical = JSON.stringify({
      cohort_digest: personalResearchCohortDigest(VALID.cohort_id),
      cohort_id: VALID.cohort_id,
      job_id: VALID.job_id,
      period_end: VALID.period_end,
      period_start: VALID.period_start,
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      snapshot_key: VALID.snapshot_key,
      snapshot_sha256: VALID.snapshot_sha256,
      universe_id: VALID.universe_id,
      universe_rule_digest: personalResearchUniverseRuleDigest(VALID.universe_id),
    });
    const expected = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(canonical),
    );
    expect(digest).toBe(
      `sha256:${Array.from(new Uint8Array(expected), (v) => v.toString(16).padStart(2, "0")).join("")}`,
    );
  });

  it("accepts gzip transport while keeping raw SQLite digest identity", () => {
    expect(parsePersonalResearchRequest(VALID_GZIP)).toEqual({
      ok: true,
      value: VALID_GZIP,
    });
  });

  it("rejects field, digest, and date-range drift", () => {
    expect(parsePersonalResearchRequest({ ...VALID, extra: true }).ok).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "not-a-closed-cohort" as never,
      }).ok,
    ).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        snapshot_key: `research/personal/snapshots/sha256=${"b".repeat(64)}.sqlite`,
      }).ok,
    ).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        period_start: "2010-01-01",
      }).ok,
    ).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        universe_id: "prime" as never,
      }).ok,
    ).toBe(false);
    expect(personalResearchCohortDigest("sector-relative-ls-v1")).toBe(
      "sha256:584bbf0052ad1eee6ec31cacdf1298c13c8a59b9eb6928267935fc17e34289be",
    );
  });

  it("admits fixed long-short sensitivity only on broad universes", () => {
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "sector-relative-ls-v1",
      }).ok,
    ).toBe(true);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "sector-relative-ls-v1",
        universe_id: "topix_core30",
      }).ok,
    ).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "sector-relative-ls-v1",
        short_financing_rates: [0, 0.03, 0.1],
      }).ok,
    ).toBe(false);
  });

  it("pairs compact universes only with the compact market cohort", () => {
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "compact-market-diverse-v1",
        universe_id: "topix_core30",
      }).ok,
    ).toBe(true);
    expect(
      parsePersonalResearchRequest({ ...VALID, universe_id: "topix_large70" })
        .ok,
    ).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "compact-market-diverse-v1",
      }).ok,
    ).toBe(false);
  });

  it("accepts only one safe status path segment", () => {
    expect(
      personalResearchJobIdFromPath(
        "/v1/personal-research/jobs/exact-four-20260829",
      ),
    ).toBe("exact-four-20260829");
    expect(
      personalResearchJobIdFromPath("/v1/personal-research/jobs/../secret"),
    ).toBeNull();
  });
});
