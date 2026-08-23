import { describe, expect, it } from "vitest";
import contractDocument from "../../../../packages/data_plane/data_contracts/jquants_premium_core.json";
import { PREMIUM_CORE_DATASETS } from "./catalog";
import {
  PREMIUM_CORE_DATASET_IDS,
  isR2Only,
  r2DatasetSegment,
  r2DateSegment,
  wantsSummaryChangeLog,
} from "./write_path_config";

describe("premium write-path ids", () => {
  it("exposes the JSON contract dataset_id set, not a second hardcoded catalog", () => {
    const contractIds = contractDocument.datasets.map((row) => row.dataset_id);

    expect(PREMIUM_CORE_DATASET_IDS).toHaveLength(23);
    expect(contractIds).toHaveLength(23);
    expect(new Set(PREMIUM_CORE_DATASET_IDS)).toEqual(new Set(contractIds));
    expect(PREMIUM_CORE_DATASET_IDS).toEqual(contractIds);
    expect(PREMIUM_CORE_DATASETS.map((spec) => spec.id)).toEqual(contractIds);
  });
});

describe("isR2Only", () => {
  it("defaults a premium-core dataset to R2-only", () => {
    expect(isR2Only("equities_bars_daily")).toBe(true);
  });

  it("lets ALLOW_D1_STRUCTURED_DATASETS opt a dataset back to D1", () => {
    expect(
      isR2Only("markets_calendar", {
        ALLOW_D1_STRUCTURED_DATASETS: "markets_calendar",
      }),
    ).toBe(false);
  });

  it("keeps an unknown jsda_ dataset R2-only", () => {
    expect(isR2Only("jsda_unknown")).toBe(true);
  });
});

describe("wantsSummaryChangeLog", () => {
  it("equals isR2Only for one r2-only id and one calendar id without D1 allow-list", () => {
    expect(wantsSummaryChangeLog("equities_bars_daily")).toBe(
      isR2Only("equities_bars_daily"),
    );
    expect(wantsSummaryChangeLog("equities_bars_daily")).toBe(true);

    expect(wantsSummaryChangeLog("markets_calendar")).toBe(
      isR2Only("markets_calendar"),
    );
    expect(wantsSummaryChangeLog("markets_calendar")).toBe(true);
  });
});

describe("r2DateSegment", () => {
  it("takes the calendar prefix from a JST timestamp and does not invent today when empty", () => {
    expect(r2DateSegment("2024-06-03T00:00:00+09:00")).toBe("2024-06-03");
    expect(r2DateSegment(null)).toBe("0000-01-01");
    expect(r2DateSegment(undefined)).toBe("0000-01-01");
    expect(r2DateSegment("")).toBe("0000-01-01");
  });
});

describe("r2DatasetSegment", () => {
  it("strips characters that are unsafe in an R2 key segment", () => {
    expect(r2DatasetSegment("foo/bar:baz")).toBe("foo_bar_baz");
  });
});
