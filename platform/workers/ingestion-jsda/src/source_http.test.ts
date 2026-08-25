import { describe, expect, it } from "vitest";
import {
  absolutize,
  extractLinks,
  fetchAllowed,
  hostAllowed,
  isDataUrl,
  selectDatasetDataUrls,
} from "./source_http";

describe("JSDA outbound allowlist", () => {
  it("requires HTTPS and rejects non-official or lookalike hosts", () => {
    expect(hostAllowed("https://www.jsda.or.jp/path")).toBe(true);
    expect(hostAllowed("https://market.jsda.or.jp/path")).toBe(true);
    expect(hostAllowed("http://www.jsda.or.jp/path")).toBe(false);
    expect(hostAllowed("https://www.jsda.or.jp.evil.test/path")).toBe(false);
    expect(hostAllowed("https://www.jsda.or.jp:8443/path")).toBe(false);
    expect(hostAllowed("https://evil@www.jsda.or.jp/path")).toBe(false);
  });

  it("rejects a redirect whose resolved host leaves the allowlist", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(null, {
        status: 302,
        headers: { Location: "https://evil.test/payload.csv" },
      })) as typeof fetch;
    try {
      await expect(
        fetchAllowed("https://www.jsda.or.jp/start.csv", "test-agent"),
      ).rejects.toMatchObject({ reasonCode: "redirect_host_not_allowlisted" });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("drops off-allowlist links before creating child jobs", () => {
    const base = "https://www.jsda.or.jp/archive/index.html";
    const links = extractLinks(
      [
        '<a href="archive2024.html">year</a>',
        '<a href="https://evil.test/payload.csv">evil</a>',
        '<a href="files/data.csv">data</a>',
      ].join("\n"),
      base,
    );
    expect(links).toEqual([
      "https://www.jsda.or.jp/archive/archive2024.html",
      "https://www.jsda.or.jp/archive/files/data.csv",
    ]);
    expect(links.filter(isDataUrl)).toEqual([
      "https://www.jsda.or.jp/archive/files/data.csv",
    ]);
    expect(absolutize(base, "https://evil.test/data.csv")).toBeNull();
  });

  it("keeps OTC reference files, rejects matrix files, and prefers CSV", () => {
    const links = [
      "https://market.jsda.or.jp/archive/files/20020802_reference.csv",
      "https://market.jsda.or.jp/archive/files/20020802_reference.xlsx",
      "https://market.jsda.or.jp/archive/files/20020802_matrix.csv",
      "https://market.jsda.or.jp/archive/files/R260825.csv",
    ];
    expect(selectDatasetDataUrls("jsda_otc_bond_reference_prices", links)).toEqual([
      "https://market.jsda.or.jp/archive/files/20020802_reference.csv",
    ]);
  });

  it("selects the governed Repo timeseries and annual corporate CSVs", () => {
    expect(
      selectDatasetDataUrls("jsda_tokyo_repo_rates", [
        "https://www.jsda.or.jp/trr/files/trr.xls",
        "https://www.jsda.or.jp/trr/files/trrts.xls",
        "https://www.jsda.or.jp/trr/bessi2-2025reference.xlsx",
      ]),
    ).toEqual(["https://www.jsda.or.jp/trr/files/trrts.xls"]);
    expect(
      selectDatasetDataUrls("jsda_corporate_bond_transactions", [
        "https://www.jsda.or.jp/toukei/TORIHIKI2026.csv",
        "https://www.jsda.or.jp/toukei/TORIHIKI2026.xlsx",
        "https://www.jsda.or.jp/toukei/TORIHIKI20260825.csv",
        "https://www.jsda.or.jp/toukei/ICHIRAN20260825.xls",
      ]),
    ).toEqual(["https://www.jsda.or.jp/toukei/TORIHIKI2026.csv"]);
  });
});
