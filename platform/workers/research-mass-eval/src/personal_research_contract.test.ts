import { describe, expect, it } from "vitest";

import {
  PERSONAL_RESEARCH_AM_PM_COHORT_IDS,
  PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME,
  PERSONAL_RESEARCH_RUNNER_SLOT,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_CONTAINER_NAME,
  PERSONAL_SNAPSHOT_SOURCE_RUNNER_VERSIONS,
  isPersonalSnapshotSourceRunnerVersion,
  parsePersonalResearchRequest,
  personalJobContainerName,
  personalResearchCohortDigest,
  personalResearchJobIdFromPath,
  personalResearchRequestDigest,
  personalResearchUniverseRuleDigest,
  personalSnapshotContainerName,
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
  it("pins the runner-bound Container identity", async () => {
    expect(PERSONAL_RESEARCH_RUNNER_VERSION).toBe("personal-cloud-runner/v14");
    expect(PERSONAL_RESEARCH_RUNNER_SLOT).toBe("v14");
    expect(PERSONAL_SNAPSHOT_CONTAINER_NAME).toBe("personal-snapshot-v14");
    expect(personalSnapshotContainerName()).toBe("personal-snapshot-v14");
    expect(PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME).toBe("personal-research-v12");
    expect([...PERSONAL_SNAPSHOT_SOURCE_RUNNER_VERSIONS]).toEqual([
      "personal-cloud-runner/v13",
      "personal-cloud-runner/v14",
    ]);
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v13")).toBe(
      true,
    );
    expect(isPersonalSnapshotSourceRunnerVersion(PERSONAL_RESEARCH_RUNNER_VERSION)).toBe(
      true,
    );
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v12")).toBe(
      false,
    );
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v15")).toBe(
      false,
    );
    expect(
      isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v14-extra"),
    ).toBe(false);
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/")).toBe(
      false,
    );
    const first = await personalJobContainerName("research", VALID.job_id);
    const second = await personalJobContainerName("research", "other-job");
    expect(first).toMatch(/^personal-v14-research-[0-9a-f]{24}$/);
    expect(first).not.toBe(PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME);
    expect(second).not.toBe(first);
    expect(await personalJobContainerName("svi", VALID.job_id)).not.toBe(first);
    expect(await personalJobContainerName("vol-panel", VALID.job_id)).toMatch(
      /^personal-v14-vol-panel-[0-9a-f]{24}$/,
    );
    expect(await personalJobContainerName("vol-panel", VALID.job_id)).not.toBe(
      await personalJobContainerName("svi", VALID.job_id),
    );
    expect(await personalJobContainerName("option-sidecar", VALID.job_id)).toMatch(
      /^personal-v14-option-sidecar-[0-9a-f]{24}$/,
    );
    expect(await personalJobContainerName("option-sidecar", VALID.job_id)).not.toBe(
      await personalJobContainerName("vol-panel", VALID.job_id),
    );
  });

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

  it("interprets the 2200-day cap as inclusive calendar dates", () => {
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        period_start: "2020-01-01",
        period_end: "2026-01-08",
      }).ok,
    ).toBe(true);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        period_start: "2020-01-01",
        period_end: "2026-01-09",
      }).ok,
    ).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        period_start: "2026-01-08",
        period_end: "2026-01-08",
      }).ok,
    ).toBe(false);
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
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "compact-market-diverse-am-pm-v1",
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
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "compact-market-diverse-am-pm-v1",
      }).ok,
    ).toBe(false);
  });

  it("admits the five frozen AM cohorts with exact repo digests", async () => {
    const expected = {
      "price-relative-am-pm-v1":
        "sha256:34e304efb8ff848a268a1e563985d1456316edf1b9ca874eba7262377e17db93",
      "fundamental-relative-am-pm-v1":
        "sha256:9bc404066d3e705e085380a3c2f15bac41c8a24a931b12518ab92abbddcaf67f",
      "diverse-core-am-pm-v1":
        "sha256:77136481d8a6b20fb8dc8188b8d6adb2837050b8185a8f8abac92ca10811adde",
      "compact-market-diverse-am-pm-v1":
        "sha256:b1c96581aa3f24a9f4df65126c4dd8c443ddb965e7105f9bbea392e72e383eb0",
      "sector-relative-ls-am-pm-v1":
        "sha256:e12e65393985ab8b7cc2b0b922a362a055404777a49fda7250f735d47f0b073b",
    } as const;
    expect([...PERSONAL_RESEARCH_AM_PM_COHORT_IDS]).toEqual(Object.keys(expected));
    for (const cohortId of PERSONAL_RESEARCH_AM_PM_COHORT_IDS) {
      const universeId =
        cohortId === "compact-market-diverse-am-pm-v1"
          ? ("topix_core30" as const)
          : VALID.universe_id;
      const parsed = parsePersonalResearchRequest({
        ...VALID,
        cohort_id: cohortId,
        universe_id: universeId,
      });
      expect(parsed.ok).toBe(true);
      if (!parsed.ok) throw new Error(parsed.error);
      expect(personalResearchCohortDigest(cohortId)).toBe(expected[cohortId]);
      const digest = await personalResearchRequestDigest(parsed.value);
      expect(digest.startsWith("sha256:")).toBe(true);
    }
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "not-a-closed-am-cohort" as never,
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
