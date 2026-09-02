import { describe, expect, it } from "vitest";

import {
  lastClosedMonthEnd,
  parsePersonalSnapshotBuildRequest,
  personalSnapshotObjectKey,
  personalSnapshotRequestDigest,
  verifySnapshotObservationEvidence,
} from "./personal_snapshot_contract";

const NOW = new Date("2026-08-30T03:00:00.000Z");

describe("personal snapshot request contract", () => {
  it("accepts a closed bounded request and is digest-stable", async () => {
    const parsed = parsePersonalSnapshotBuildRequest(
      {
        job_id: "shard-2022-2024",
        period_start: "2022-01-01",
        period_end: "2024-12-31",
      },
      NOW,
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) throw new Error(parsed.error);
    expect(parsed.value.lookback_sessions).toBe(10);
    const again = await personalSnapshotRequestDigest(parsed.value);
    expect(again).toBe(await personalSnapshotRequestDigest(parsed.value));
    expect(personalSnapshotObjectKey("a".repeat(64))).toBe(
      `research/personal/snapshots/sha256=${"a".repeat(64)}.sqlite.gz`,
    );
  });

  it("rejects future, overlong, conflicting, and extra fields", () => {
    expect(
      parsePersonalSnapshotBuildRequest(
        { job_id: "x", period_start: "2024-01-01", period_end: "2026-08-31" },
        NOW,
      ).ok,
    ).toBe(false);
    expect(
      parsePersonalSnapshotBuildRequest(
        { job_id: "x", period_start: "2000-01-01", period_end: "2024-12-31" },
        NOW,
      ).ok,
    ).toBe(false);
    expect(
      parsePersonalSnapshotBuildRequest(
        {
          job_id: "x",
          period_start: "2024-01-01",
          period_end: "2024-12-31",
          extra: true,
        },
        NOW,
      ).ok,
    ).toBe(false);
    expect(lastClosedMonthEnd(NOW)).toBe("2026-07-31");
  });

  it("interprets the 7000-day cap as inclusive calendar dates", () => {
    expect(
      parsePersonalSnapshotBuildRequest(
        { job_id: "bound-7000", period_start: "2007-01-01", period_end: "2026-03-01" },
        NOW,
      ).ok,
    ).toBe(true);
    expect(
      parsePersonalSnapshotBuildRequest(
        { job_id: "bound-7001", period_start: "2007-01-01", period_end: "2026-03-02" },
        NOW,
      ).ok,
    ).toBe(false);
    expect(
      parsePersonalSnapshotBuildRequest(
        { job_id: "one-day", period_start: "2026-07-31", period_end: "2026-07-31" },
        NOW,
      ).ok,
    ).toBe(true);
  });
});

describe("snapshot observation evidence", () => {
  const sqlite = {
    observed_through: "2025-01-02T16:00:00+09:00",
    revision_window_calendar_days: 40,
    revision_coverage: "BOUNDED_WINDOW",
  };

  it("accepts matching immutable observation evidence", () => {
    expect(
      verifySnapshotObservationEvidence(
        {
          status: "COMPLETED",
          observed_through: sqlite.observed_through,
          revision_window_calendar_days: 40,
          revision_coverage: "BOUNDED_WINDOW",
        },
        sqlite,
      ).ok,
    ).toBe(true);
  });

  it("rejects a broadened observed_through or missing revision evidence", () => {
    expect(
      verifySnapshotObservationEvidence(
        {
          status: "COMPLETED",
          observed_through: "2099-01-01T00:00:00+09:00",
          revision_window_calendar_days: 40,
          revision_coverage: "BOUNDED_WINDOW",
        },
        sqlite,
      ).ok,
    ).toBe(false);
    expect(
      verifySnapshotObservationEvidence(
        { status: "COMPLETED", observed_through: sqlite.observed_through },
        sqlite,
      ).ok,
    ).toBe(false);
  });
});
