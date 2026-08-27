import { describe, expect, it } from "vitest";
import {
  FILE_ROUTING_VERSION,
  JSDA_FILE_ROUTING,
  classifyFetchFreshness,
  observationEpoch,
} from "./source_routing";

describe("JSDA file routing metadata", () => {
  it("keeps dataset locator policies explicit", () => {
    expect(FILE_ROUTING_VERSION).toBe("jsda-official-file-routing/v2");
    expect(JSDA_FILE_ROUTING.jsda_tokyo_repo_rates.locator_policy).toBe(
      "rolling_current_file",
    );
    expect(JSDA_FILE_ROUTING.jsda_corporate_bond_transactions.locator_policy).toBe(
      "annual_file_current_year_rolling",
    );
    expect(JSDA_FILE_ROUTING.jsda_otc_bond_reference_prices.locator_policy).toBe(
      "dated_publication_archive",
    );
  });

  it("scopes rolling observations to the run and archives to a stable epoch", () => {
    expect(observationEpoch("rolling", "jsda:v2:root:example:cron:2026-08-25")).toBe(
      "jsda:v2:root:example:cron:2026-08-25",
    );
    expect(observationEpoch("archive", "jsda:v2:root:example:cron:2026-08-25")).toBe(
      "archive",
    );
  });

  it("treats a current-year annual file as rolling and a prior year as archive", () => {
    const url2026 =
      "https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/torihiki2026.csv";
    expect(
      classifyFetchFreshness(
        "jsda_corporate_bond_transactions",
        url2026,
        "2026-12-31T23:59:59.000Z",
      ),
    ).toBe("rolling");
    expect(
      classifyFetchFreshness(
        "jsda_corporate_bond_transactions",
        url2026,
        "2027-01-01T00:00:00.000Z",
      ),
    ).toBe("archive");
  });
});
