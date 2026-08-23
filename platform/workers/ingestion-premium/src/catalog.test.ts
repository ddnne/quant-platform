import { describe, expect, it } from "vitest";
import contractDocument from "../../../../packages/data_plane/data_contracts/jquants_premium_core.json";
import { PREMIUM_CORE_DATASETS } from "./catalog";

describe("premium catalog identity", () => {
  it("exposes the JSON contract dataset_id set, not a second hardcoded catalog", () => {
    const contractIds = contractDocument.datasets.map((row) => row.dataset_id);
    const workerIds = PREMIUM_CORE_DATASETS.map((spec) => spec.id);

    expect(workerIds).toHaveLength(23);
    expect(contractIds).toHaveLength(23);
    expect(new Set(workerIds)).toEqual(new Set(contractIds));
    expect(workerIds).toEqual(contractIds);
    expect(PREMIUM_CORE_DATASETS.map((spec) => spec.dataset_id)).toEqual(contractIds);
  });
});

describe("premium catalog dateMode", () => {
  it("maps every JSON date_mode onto Worker spec.dateMode, and day_param onto dayParam when present", () => {
    expect(PREMIUM_CORE_DATASETS).toHaveLength(contractDocument.datasets.length);

    for (const json of contractDocument.datasets) {
      const spec = PREMIUM_CORE_DATASETS.find((row) => row.id === json.dataset_id);
      expect(spec).toBeDefined();
      expect(spec!.dateMode).toBe(json.date_mode);
      if (json.day_param !== undefined) {
        expect(spec!.dayParam).toBe(json.day_param);
      }
    }
  });
});
