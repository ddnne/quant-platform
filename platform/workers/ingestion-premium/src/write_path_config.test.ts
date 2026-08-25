import { describe, expect, it } from "vitest";
import contractDocument from "../../../../packages/data_plane/data_contracts/jquants_premium_core.json";
import { PREMIUM_CORE_DATASETS } from "./catalog";
import { PREMIUM_CORE_DATASET_IDS, isR2Only } from "./write_path_config";

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
