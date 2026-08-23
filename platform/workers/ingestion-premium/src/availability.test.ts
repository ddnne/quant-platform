import { describe, expect, it } from "vitest";
import { pickAvailableAt, policyForDataset } from "./availability";
import { datasetById } from "./catalog";
import { pickAvailableAt as pickFromContract } from "./identity";

const INGESTED = "2025-04-02T09:00:00+09:00";

describe("policyForDataset", () => {
  it("returns ingest_time_conservative when the dataset is not in the contract", () => {
    expect(policyForDataset("not_a_dataset")).toBe("ingest_time_conservative");
  });

  it("returns the contract policy for known datasets", () => {
    expect(policyForDataset("equities_bars_daily")).toBe("session_close");
    expect(policyForDataset("markets_breakdown")).toBe("ingest_time_conservative");
    expect(policyForDataset("markets_calendar")).toBe("calendar_prepublished");
  });
});

describe("pickAvailableAt wrapper", () => {
  it("fails safe to ingestedAt when the dataset is not in the contract", () => {
    expect(pickAvailableAt({ Date: "2025-04-01" }, "not_a_dataset", INGESTED)).toBe(
      INGESTED,
    );
  });

  it("delegates to pickFromContract for a known dataset", () => {
    const row = { Code: "8697", Date: "2025-04-01" };
    const spec = datasetById("equities_bars_daily");
    expect(spec).toBeDefined();
    expect(pickAvailableAt(row, "equities_bars_daily", INGESTED)).toBe(
      pickFromContract(row, spec!, INGESTED),
    );
    expect(pickAvailableAt(row, "equities_bars_daily", INGESTED)).toBe(
      "2025-04-01T15:30:00+09:00",
    );
  });

  it("falls back to ingestedAt when the contract availability field is missing on the row", () => {
    expect(
      pickAvailableAt(
        { Code: "8697", DisclosedDate: "2025-04-05" },
        "equities_bars_daily",
        INGESTED,
      ),
    ).toBe(INGESTED);
    expect(
      pickAvailableAt(
        { Code: "8697", DiscDate: "2025-04-01", DiscNo: "1" },
        "fins_details",
        INGESTED,
      ),
    ).toBe(INGESTED);
  });

  it("keeps ingest time when publication instant is unknown", () => {
    const row = { Code: "8697", Date: "2025-04-01" };
    expect(pickAvailableAt(row, "markets_breakdown", INGESTED)).toBe(INGESTED);
    expect(pickAvailableAt(row, "markets_calendar", INGESTED)).toBe(INGESTED);
    expect(pickAvailableAt(row, "equities_master", INGESTED)).toBe(INGESTED);
  });
});

describe("pickFromContract", () => {
  it("returns ingestedAt when the contract availability field is missing", () => {
    const spec = datasetById("equities_bars_daily");
    expect(spec).toBeDefined();
    expect(
      pickFromContract(
        { Code: "8697", DisclosedDate: "2025-04-05" },
        spec!,
        INGESTED,
      ),
    ).toBe(INGESTED);
  });

  it("returns ingestedAt for ingest_time_conservative contracts even when Date is present", () => {
    const spec = datasetById("markets_breakdown");
    expect(spec).toBeDefined();
    expect(spec!.available_at_policy).toBe("ingest_time_conservative");
    expect(spec!.availability_field).toBeNull();
    expect(
      pickFromContract({ Code: "8697", Date: "2025-04-01" }, spec!, INGESTED),
    ).toBe(INGESTED);
  });
});
