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
