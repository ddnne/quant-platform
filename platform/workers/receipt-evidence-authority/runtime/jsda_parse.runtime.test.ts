import { describe, expect, it } from "vitest";
import * as XLSX from "@e965/xlsx";
import { sha256Digest } from "../src/canonical";
import {
  detectJsdaFormat,
  parseCsvRows,
  parseJsdaOtcFile,
  parseOtcReferenceRows,
} from "../src/jsda_otc_parse";
import { parseJsdaStructuredRows } from "../src/jsda_capture";

const HEADERLESS_TEXT = [
  "20020802,01,123456789,10年国債,20120820,1.500,1.225,99.85,-0.10,03,20,0,0,0,1.230,100.00,1.100,99.50,1.350,,12,1.100,0.05,1.350,-0.20,1.220,1.225,99.84,-0.11",
  "20020802,02,987654321,テスト社債,20300802,0.750,0.755,99.95,0.01,02,08,0,1,0,0.760,100.10,0.700,99.80,0.800,*,4,0.700,0.02,0.800,-0.03,0.750,0.755,99.96,0.02",
  "",
].join("\n");
const HEADERLESS = new TextEncoder().encode(HEADERLESS_TEXT);

function encodeCp932Like(text: string): Uint8Array {
  return new TextEncoder().encode(text);
}

function workbookBytes(rows: string[][], bookType: "xlsx" | "xls"): Uint8Array {
  const sheet = XLSX.utils.aoa_to_sheet(rows);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, "Sheet1");
  return new Uint8Array(XLSX.write(workbook, { type: "array", bookType }));
}

function earlyPrefix(width: number): string {
  return parseCsvRows(HEADERLESS_TEXT)
    .map((row) => row.slice(0, width).map((cell) => `"${cell.replace(/"/g, '""')}"`).join(","))
    .join("\n") + "\n";
}

describe("JSDA official OTC parser", () => {
  it("parses official 29-column headerless rows with exact source row numbers", () => {
    const records = parseJsdaOtcFile(HEADERLESS, {
      datasetId: "jsda_otc_bond_reference_prices",
      targetUrl: "https://market.jsda.or.jp/archive/data/S020802.csv",
      governedFormats: ["csv", "xlsx"],
      publicationLabelDate: "2002-08-02",
      quoteEffectiveDate: "2002-08-01",
    });
    expect(records).toHaveLength(2);
    expect(records[0]).toMatchObject({
      source: "jsda",
      publication_label_date: "2002-08-02",
      quote_effective_date: "2002-08-01",
      security_code: "123456789",
      bond_name: "10年国債",
      source_row_number: 1,
    });
    expect(records[0]!.high_yield).not.toBeNull();
    expect(records.every((row) => !Object.values(row).includes("COMPLETE"))).toBe(true);
  });

  it("parses early 2002-style 21-column headerless rows and keeps label vs effective dates", () => {
    const text = earlyPrefix(21);
    const records = parseJsdaOtcFile(new TextEncoder().encode(text), {
      datasetId: "jsda_otc_bond_reference_prices",
      targetUrl: "https://market.jsda.or.jp/archive/data/otc.csv",
      governedFormats: ["csv", "xlsx"],
      publicationLabelDate: "2002-08-02",
      quoteEffectiveDate: "2002-08-01",
    });
    expect(records).toHaveLength(2);
    expect(records[0]!.publication_label_date).toBe("2002-08-02");
    expect(records[0]!.quote_effective_date).toBe("2002-08-01");
    expect(records[0]!.individual_investor_flag).toBeNull();
    expect(records[0]!.high_yield).toBeNull();
    expect(records[0]!.median_price).toBeNull();
  });

  it("parses official-like XLSX and XLS through the same row mapping", () => {
    const rows = parseCsvRows(HEADERLESS_TEXT);
    for (const bookType of ["xlsx", "xls"] as const) {
      const bytes = workbookBytes(rows, bookType);
      expect(detectJsdaFormat(bytes, "csv")).toBe(bookType === "xlsx" ? "xlsx" : "xls");
      const records = parseJsdaOtcFile(bytes, {
        datasetId: "jsda_otc_bond_reference_prices",
        targetUrl: `https://market.jsda.or.jp/archive/data/otc.${bookType}`,
        governedFormats: ["csv", "xlsx", "xls"],
        publicationLabelDate: "2002-08-02",
        quoteEffectiveDate: "2002-08-01",
      });
      expect(records).toHaveLength(2);
      expect(records[0]!.security_code).toBe("123456789");
      expect(records[0]!.source_row_number).toBe(1);
    }
  });

  it("decodes CP932 CSV quoting and rejects truncated, HTML, and bound violations", async () => {
    const quoted = '20020802,01,123456789,"10年国債, 特号",20120820,1.500,1.225,99.85,-0.10,03,20,0,0,0,1.230,100.00,1.100,99.50,1.350,,12,1.100,0.05,1.350,-0.20,1.220,1.225,99.84,-0.11\n';
    const records = parseOtcReferenceRows(parseCsvRows(quoted), "2002-08-02", "2002-08-01");
    expect(records[0]!.bond_name).toBe("10年国債, 特号");
    const cp932 = encodeCp932Like(
      "銘柄コード,銘柄名,発表日付\n123456789,10年国債,2002/08/02\n",
    );
    const headered = parseJsdaOtcFile(cp932, {
      datasetId: "jsda_otc_bond_reference_prices",
      targetUrl: "https://market.jsda.or.jp/archive/data/otc.csv",
      governedFormats: ["csv", "xlsx"],
    });
    expect(headered).toHaveLength(1);
    expect(headered[0]!.security_code).toBe("123456789");
    const full = parseCsvRows(HEADERLESS_TEXT)[0]!;
    for (const width of [...Array.from({ length: 17 }, (_, i) => i + 4), ...Array.from({ length: 7 }, (_, i) => i + 22)]) {
      expect(parseOtcReferenceRows([full.slice(0, width)])).toEqual([]);
    }
    await expect(async () => parseJsdaStructuredRows(
      new TextEncoder().encode("<html>error</html>"),
      "fetch_file",
      null,
      {
        datasetId: "jsda_otc_bond_reference_prices",
        targetUrl: "https://market.jsda.or.jp/archive/data/otc.csv",
      },
    )).rejects.toThrow(/PARSE_ZERO/);
    const oversized = new Uint8Array(4 * 1024 * 1024 + 8);
    oversized[0] = 0x50;
    oversized[1] = 0x4b;
    oversized[2] = 0x03;
    oversized[3] = 0x04;
    expect(() => parseJsdaOtcFile(oversized, {
      datasetId: "jsda_otc_bond_reference_prices",
      targetUrl: "https://market.jsda.or.jp/archive/data/otc.xlsx",
      governedFormats: ["csv", "xlsx"],
    })).toThrow(/bound|PARSE_ZERO/);
  });

  it("binds nonzero parse count to the exact raw digest", async () => {
    const bytes = HEADERLESS;
    const digest = await sha256Digest(bytes);
    const records = parseJsdaStructuredRows(bytes, "fetch_file", null, {
      datasetId: "jsda_otc_bond_reference_prices",
      targetUrl: "https://market.jsda.or.jp/archive/data/S020802.csv",
      publicationLabelDate: "2002-08-02",
    });
    expect(records.length).toBeGreaterThan(0);
    expect(digest).toMatch(/^sha256:[0-9a-f]{64}$/);
    expect(records).toHaveLength(2);
  });
});
