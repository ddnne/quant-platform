import { describe, expect, it } from "vitest";

import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  parsePersonalResearchRequest,
  personalResearchCohortDigest,
  personalResearchJobIdFromPath,
  personalResearchRequestDigest,
} from "./personal_research_contract";

const SHA = "a".repeat(64);
const VALID = {
  cohort_id: "diverse-core-v1" as const,
  job_id: "exact-four-20260829",
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite`,
  snapshot_sha256: SHA,
  period_start: "2022-04-19",
  period_end: "2026-08-27",
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
    });
    const expected = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(canonical),
    );
    expect(digest).toBe(
      `sha256:${Array.from(new Uint8Array(expected), (v) => v.toString(16).padStart(2, "0")).join("")}`,
    );
  });

  it("rejects field, digest, and date-range drift", () => {
    expect(parsePersonalResearchRequest({ ...VALID, extra: true }).ok).toBe(false);
    expect(
      parsePersonalResearchRequest({
        ...VALID,
        cohort_id: "sector-relative-ls-v1",
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
