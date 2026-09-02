import { describe, expect, it } from "vitest";

import {
  PERSONAL_RESEARCH_AM_PM_COHORT_IDS,
  PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME,
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  PERSONAL_RESEARCH_RUNNER_SLOT,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_CONTAINER_NAME,
  PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES,
  PERSONAL_SNAPSHOT_SOURCE_RUNNER_VERSIONS,
  isPersonalSnapshotSourceRunnerVersion,
  parsePersonalResearchRequest,
  personalJobContainerName,
  personalResearchCohortDigest,
  personalResearchJobIdFromPath,
  personalResearchRequestDigest,
  personalResearchUniverseDecisionCutoff,
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
  it("separates 4 GiB compressed transport from 5 GiB expanded sqlite", () => {
    expect(PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES).toBe(4 * 1024 * 1024 * 1024);
    expect(PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES).toBe(5 * 1024 * 1024 * 1024);
  });

  it("pins the runner-bound Container identity", async () => {
    expect(PERSONAL_RESEARCH_RUNNER_VERSION).toBe("personal-cloud-runner/v15");
    expect(PERSONAL_RESEARCH_RUNNER_SLOT).toBe("v15");
    expect(PERSONAL_SNAPSHOT_CONTAINER_NAME).toBe("personal-snapshot-v16");
    expect(personalSnapshotContainerName()).toBe("personal-snapshot-v16");
    expect(PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME).toBe("personal-research-v12");
    expect([...PERSONAL_SNAPSHOT_SOURCE_RUNNER_VERSIONS]).toEqual([
      "personal-cloud-runner/v13",
      "personal-cloud-runner/v14",
      "personal-cloud-runner/v15",
    ]);
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v13")).toBe(
      true,
    );
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v14")).toBe(
      true,
    );
    expect(isPersonalSnapshotSourceRunnerVersion(PERSONAL_RESEARCH_RUNNER_VERSION)).toBe(
      true,
    );
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v12")).toBe(
      false,
    );
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v16")).toBe(
      false,
    );
    expect(
      isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/v15-extra"),
    ).toBe(false);
    expect(isPersonalSnapshotSourceRunnerVersion("personal-cloud-runner/")).toBe(
      false,
    );
    const first = await personalJobContainerName("research", VALID.job_id);
    const second = await personalJobContainerName("research", "other-job");
    expect(first).toMatch(/^personal-v15-research-[0-9a-f]{24}$/);
    expect(first).not.toBe(PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME);
    expect(second).not.toBe(first);
    expect(await personalJobContainerName("svi", VALID.job_id)).not.toBe(first);
    expect(await personalJobContainerName("vol-panel", VALID.job_id)).toMatch(
      /^personal-v15-vol-panel-[0-9a-f]{24}$/,
    );
    expect(await personalJobContainerName("vol-panel", VALID.job_id)).not.toBe(
      await personalJobContainerName("svi", VALID.job_id),
    );
    expect(await personalJobContainerName("option-sidecar", VALID.job_id)).toMatch(
      /^personal-v15-option-sidecar-[0-9a-f]{24}$/,
    );
    expect(await personalJobContainerName("option-sidecar", VALID.job_id)).not.toBe(
      await personalJobContainerName("vol-panel", VALID.job_id),
    );
  });

  it("accepts one content-addressed bounded draft four-candidate request", async () => {
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
      universe_rule_digest: personalResearchUniverseRuleDigest(
        VALID.universe_id,
        VALID.cohort_id,
      ),
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
        period_start: "2000-01-01",
      }).ok,
    ).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        universe_id: "prime" as never,
      }).ok,
    ).toBe(false);
    expect(personalResearchCohortDigest("sector-relative-ls-v1")).toBe(
      "sha256:6e4de725046c0b0e55416891d83580b9acb753c00a2beecfd3a26ee0c87a74f9",
    );
  });

  it("interprets the 7000-day cap as inclusive calendar dates", () => {
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        period_start: "2007-01-01",
        period_end: "2026-03-01",
      }).ok,
    ).toBe(true);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        period_start: "2007-01-01",
        period_end: "2026-03-02",
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

  it("selects morning_close universe rule digests for AM cohorts only", async () => {
    expect(personalResearchUniverseDecisionCutoff("diverse-core-v1")).toBe(
      "session_close",
    );
    expect(
      personalResearchUniverseDecisionCutoff("diverse-core-am-pm-v1"),
    ).toBe("morning_close");
    expect(
      personalResearchUniverseRuleDigest("topix_all", "diverse-core-v1"),
    ).toBe(
      "sha256:7b88c89520a7cf751e7b63f160c16130183dba3c7c7e9c3a56660f3149c2c048",
    );
    expect(
      personalResearchUniverseRuleDigest(
        "topix_all",
        "diverse-core-am-pm-v1",
      ),
    ).toBe(
      "sha256:ba0c9af6b51121e6c27d660ccd28ae3e1a7c8af1ae3ffcff4986bf3f31247fd9",
    );
    const am = parsePersonalResearchRequest({
      ...VALID,
      cohort_id: "diverse-core-am-pm-v1",
    });
    expect(am.ok).toBe(true);
    if (!am.ok) throw new Error(am.error);
    const digest = await personalResearchRequestDigest(am.value);
    const canonical = JSON.stringify({
      cohort_digest: personalResearchCohortDigest("diverse-core-am-pm-v1"),
      cohort_id: "diverse-core-am-pm-v1",
      job_id: VALID.job_id,
      period_end: VALID.period_end,
      period_start: VALID.period_start,
      runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
      snapshot_key: VALID.snapshot_key,
      snapshot_sha256: VALID.snapshot_sha256,
      universe_id: VALID.universe_id,
      universe_rule_digest: personalResearchUniverseRuleDigest(
        VALID.universe_id,
        "diverse-core-am-pm-v1",
      ),
    });
    const expected = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(canonical),
    );
    expect(digest).toBe(
      `sha256:${Array.from(new Uint8Array(expected), (v) => v.toString(16).padStart(2, "0")).join("")}`,
    );
    expect(
      personalResearchUniverseRuleDigest("topix_all", "diverse-core-am-pm-v1"),
    ).not.toBe(
      personalResearchUniverseRuleDigest("topix_all", "diverse-core-v1"),
    );
  });

  it("admits the five frozen AM cohorts with exact repo digests", async () => {
    const expected = {
      "price-relative-am-pm-v1":
        "sha256:f1ed5dda6f4b8afe502a2b71a8ae3e5d3157caa69e5380fc97c9e7447ab181ce",
      "fundamental-relative-am-pm-v1":
        "sha256:127d5558da094e0751a3d6c81d103d65d88e6549fe69bd3a9ef560dd6929248e",
      "diverse-core-am-pm-v1":
        "sha256:0c9fc5cba93c68cbfec3951a56f09949674c1a01cb4d4d4cf406082c01033c10",
      "compact-market-diverse-am-pm-v1":
        "sha256:f8c7e7aa76663f9e9b73d5835ce3e3b45b5dd31935e5d00ec5684c22b3b3ad95",
      "sector-relative-ls-am-pm-v1":
        "sha256:9d4135b9b78ad16d071f8a0b26a88b29d315c4d53eace3cb7600aaccf450b73c",
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
