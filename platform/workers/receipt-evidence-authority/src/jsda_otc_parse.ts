/** Canonical JSDA OTC-reference parser for the Receipt Evidence Authority. */

import * as XLSX from "@e965/xlsx";

export const JSDA_PARSE_ZERO = "PARSE_ZERO: empty JSDA structured product cannot mint COMPLETE";

const MAX_WORKBOOK_BYTES = 4 * 1024 * 1024;
const MAX_SHEETS = 8;
const MAX_ROWS = 20_000;
const MAX_COLS = 64;
const MAX_CELLS = 200_000;

const OTC_REFERENCE_ALIASES: Record<string, string[]> = {
  publication_label_date: ["発表日付", "発表日", "publicationdate"],
  quote_effective_date: ["気配基準日", "基準日", "実効日", "quotedate"],
  security_code: ["銘柄コード", "証券コード", "isinコード", "isin", "code"],
  bond_name: ["銘柄名", "債券名", "name"],
  coupon_rate: ["表面利率", "利率", "coupon"],
  maturity_date: ["償還期日", "償還年月日", "償還日", "maturity"],
  average_price: ["平均値単価", "平均単価", "平均値価格"],
  average_yield: ["平均値複利", "平均利回り", "平均値利回り"],
  median_price: ["中央値単価", "中央単価", "中央値価格"],
  median_yield: ["中央値複利", "中央利回り", "中央値利回り"],
  high_price: ["最高値単価", "最高単価", "最高値価格"],
  high_yield: ["最高値複利", "最高利回り"],
  low_price: ["最低値単価", "最低単価", "最低値価格"],
  low_yield: ["最低値複利", "最低利回り"],
  individual_investor_flag: ["個人向け社債等", "個人向け", "individualinvestor"],
};

const OTC_HEADER_MARKERS = ["銘柄コード", "証券コード", "銘柄名", "債券名"] as const;

const OTC_POSITIONAL_COLUMNS: Record<string, number> = {
  publication_label_date: 0,
  security_code: 2,
  bond_name: 3,
  maturity_date: 4,
  coupon_rate: 5,
  average_yield: 6,
  average_price: 7,
  individual_investor_flag: 12,
  high_price: 15,
  low_price: 17,
  high_yield: 21,
  low_yield: 23,
  median_yield: 25,
  median_price: 27,
};
const OTC_POSITIONAL_MIN_COLUMNS = 29;
const OTC_EARLY_LAYOUT_COLUMN_COUNT = 21;
const OTC_EARLY_POSITIONAL_COLUMNS: Record<string, number> = {
  publication_label_date: 0,
  security_code: 2,
  bond_name: 3,
  maturity_date: 4,
  coupon_rate: 5,
  average_yield: 6,
  average_price: 7,
  high_price: 15,
  low_price: 17,
};
const OTC_POSITIONAL_IDENTITY_MIN_COLUMNS = OTC_POSITIONAL_COLUMNS.bond_name! + 1;

const OLE_MAGIC = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1] as const;

export type JsdaDetectedFormat = "csv" | "xlsx" | "xls" | "html" | "unknown";

export type JsdaOtcRecord = {
  source: "jsda";
  publication_label_date: string | null;
  quote_effective_date: string | null;
  security_code: string;
  bond_name: string;
  coupon_rate: number | null;
  maturity_date: string | null;
  average_price: number | null;
  average_yield: number | null;
  median_price: number | null;
  median_yield: number | null;
  high_price: number | null;
  high_yield: number | null;
  low_price: number | null;
  low_yield: number | null;
  individual_investor_flag: string | null;
  source_row_number: number;
};

export type JsdaParseContext = {
  datasetId: string;
  targetUrl: string;
  governedFormats: readonly string[];
  publicationLabelDate?: string | null;
  quoteEffectiveDate?: string | null;
};

function startsWithBytes(bytes: Uint8Array, magic: readonly number[]): boolean {
  if (bytes.byteLength < magic.length) return false;
  return magic.every((value, index) => bytes[index] === value);
}

function asciiPrefix(bytes: Uint8Array, limit = 256): string {
  const slice = bytes.subarray(0, Math.min(bytes.byteLength, limit));
  let text = "";
  for (const byte of slice) {
    if (byte === 0) break;
    text += String.fromCharCode(byte);
  }
  return text.trimStart().toLowerCase();
}

export function detectJsdaFormat(
  bytes: Uint8Array,
  governedUrlFormat?: string | null,
): JsdaDetectedFormat {
  if (bytes.byteLength >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b &&
    (bytes[2] === 0x03 || bytes[2] === 0x05 || bytes[2] === 0x07) &&
    (bytes[3] === 0x04 || bytes[3] === 0x06 || bytes[3] === 0x08)
  ) {
    return "xlsx";
  }
  if (startsWithBytes(bytes, OLE_MAGIC)) return "xls";
  const head = asciiPrefix(bytes);
  if (head.startsWith("<!doctype") || head.startsWith("<html") || head.startsWith("<?xml")) {
    return "html";
  }
  if (governedUrlFormat === "xlsx" || governedUrlFormat === "xls" || governedUrlFormat === "csv") {
    // Extension is not authority; text bodies remain CSV even when the URL
    // advertises a spreadsheet, and spreadsheet magic already returned above.
    return "csv";
  }
  return bytes.byteLength > 0 ? "csv" : "unknown";
}

export function governedUrlFormat(targetUrl: string): string | null {
  const match = /\.([A-Za-z0-9]+)(?:\?|#|$)/.exec(targetUrl);
  if (match === null) return null;
  const ext = match[1]!.toLowerCase();
  if (ext === "xlsx" || ext === "xls" || ext === "csv") return ext;
  return null;
}

function decodeText(bytes: Uint8Array): string {
  if (bytes.byteLength >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(
      bytes.subarray(3),
    );
  }
  for (const encoding of ["utf-8", "shift_jis"] as const) {
    try {
      return new TextDecoder(encoding, { fatal: true, ignoreBOM: false }).decode(bytes);
    } catch {
      continue;
    }
  }
  return new TextDecoder("latin1").decode(bytes);
}

export function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  const input = text.replace(/^\uFEFF/, "");
  for (let index = 0; index < input.length; index += 1) {
    const ch = input[index]!;
    if (inQuotes) {
      if (ch === '"') {
        if (input[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
      continue;
    }
    if (ch === ",") {
      row.push(field);
      field = "";
      continue;
    }
    if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && input[index + 1] === "\n") index += 1;
      row.push(field);
      field = "";
      if (row.some((cell) => cell.trim() !== "")) rows.push(row);
      row = [];
      continue;
    }
    field += ch;
  }
  row.push(field);
  if (row.some((cell) => cell.trim() !== "")) rows.push(row);
  return rows;
}

function otcHeaderText(cell: unknown): string {
  return String(cell ?? "").replace(/[\s()（）［］[\]・_%％]/g, "").toLowerCase();
}

function findOtcHeader(rows: string[][]): { index: number; headers: string[] } {
  for (let index = 0; index < rows.length; index += 1) {
    const normalized = rows[index]!.map(otcHeaderText);
    if (normalized.some((cell) => OTC_HEADER_MARKERS.some((marker) => cell.includes(marker)))) {
      return { index, headers: normalized };
    }
  }
  return { index: -1, headers: [] };
}

function otcColumns(headers: string[]): Record<string, number> {
  const columns: Record<string, number> = {};
  const claimed = new Set<number>();
  const aliases = Object.fromEntries(
    Object.entries(OTC_REFERENCE_ALIASES).map(([field, names]) => [
      field,
      names.map((alias) => otcHeaderText(alias)),
    ]),
  ) as Record<string, string[]>;
  for (const exact of [true, false]) {
    for (let index = 0; index < headers.length; index += 1) {
      if (claimed.has(index)) continue;
      const header = headers[index]!;
      for (const [field, names] of Object.entries(aliases)) {
        if (field in columns) continue;
        const match = exact
          ? names.includes(header)
          : names.some((alias) => header.includes(alias));
        if (match) {
          columns[field] = index;
          claimed.add(index);
          break;
        }
      }
    }
  }
  return columns;
}

function cell(row: string[], index: number | undefined): string {
  if (index === undefined || index >= row.length) return "";
  return (row[index] ?? "").trim();
}

function looksLikeOtcPositionalRow(row: string[]): boolean {
  if (row.length < OTC_POSITIONAL_IDENTITY_MIN_COLUMNS) return false;
  const sourceDate = cell(row, 0).replace(/\D/g, "");
  const code = cell(row, OTC_POSITIONAL_COLUMNS.security_code);
  const name = cell(row, OTC_POSITIONAL_COLUMNS.bond_name);
  return sourceDate.length === 8 && /^\d{8}$/.test(sourceDate) && Boolean(code && name);
}

function positionalOtcColumnMap(row: string[]): Record<string, number> | null {
  const width = row.length;
  if (width >= OTC_POSITIONAL_MIN_COLUMNS) return { ...OTC_POSITIONAL_COLUMNS };
  if (width === OTC_EARLY_LAYOUT_COLUMN_COUNT) return { ...OTC_EARLY_POSITIONAL_COLUMNS };
  return null;
}

function parseDate(value: string): string | null {
  const raw = value.trim();
  if (!raw) return null;
  const formats: Array<RegExp> = [
    /^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/,
    /^(\d{4})(\d{2})(\d{2})$/,
    /^(\d{4})年(\d{1,2})月(\d{1,2})日$/,
  ];
  for (const pattern of formats) {
    const match = pattern.exec(raw);
    if (match === null) continue;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const iso = `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const parsed = Date.parse(`${iso}T00:00:00Z`);
    if (!Number.isFinite(parsed)) continue;
    if (new Date(parsed).toISOString().slice(0, 10) !== iso) continue;
    return iso;
  }
  const loose = /^\s*(\d{4})\D(\d{1,2})\D(\d{1,2})/.exec(raw);
  if (loose === null) return null;
  const iso = `${String(Number(loose[1])).padStart(4, "0")}-${String(Number(loose[2])).padStart(2, "0")}-${String(Number(loose[3])).padStart(2, "0")}`;
  const parsed = Date.parse(`${iso}T00:00:00Z`);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 10) !== iso) {
    return null;
  }
  return iso;
}

function parseNumber(value: string): number | null {
  const raw = value.replace(/,/g, "").replace(/%/g, "").replace(/　/g, "").trim();
  if (!raw || raw === "-" || raw === "－" || raw === "―") return null;
  const number = Number(raw);
  return Number.isFinite(number) ? number : null;
}

export function parseOtcReferenceRows(
  rows: string[][],
  publicationLabelDate?: string | null,
  quoteEffectiveDate?: string | null,
): JsdaOtcRecord[] {
  if (rows.length === 0) return [];
  const header = findOtcHeader(rows);
  let headerColumns: Record<string, number> | null = null;
  let firstDataIndex = 0;
  if (header.index < 0) {
    if (!looksLikeOtcPositionalRow(rows[0]!)) return [];
  } else {
    headerColumns = otcColumns(header.headers);
    firstDataIndex = header.index + 1;
  }
  const out: JsdaOtcRecord[] = [];
  for (let rowIndex = firstDataIndex; rowIndex < rows.length; rowIndex += 1) {
    const row = rows[rowIndex]!;
    const columns = headerColumns ?? positionalOtcColumnMap(row);
    if (columns === null) continue;
    const code = cell(row, columns.security_code);
    const name = cell(row, columns.bond_name);
    if (!code && !name) continue;
    const label = parseDate(cell(row, columns.publication_label_date))
      ?? parseDate(publicationLabelDate ?? "");
    const effective = parseDate(cell(row, columns.quote_effective_date))
      ?? parseDate(quoteEffectiveDate ?? "");
    out.push({
      source: "jsda",
      publication_label_date: label,
      quote_effective_date: effective,
      security_code: code,
      bond_name: name,
      coupon_rate: parseNumber(cell(row, columns.coupon_rate)),
      maturity_date: parseDate(cell(row, columns.maturity_date)),
      average_price: parseNumber(cell(row, columns.average_price)),
      average_yield: parseNumber(cell(row, columns.average_yield)),
      median_price: parseNumber(cell(row, columns.median_price)),
      median_yield: parseNumber(cell(row, columns.median_yield)),
      high_price: parseNumber(cell(row, columns.high_price)),
      high_yield: parseNumber(cell(row, columns.high_yield)),
      low_price: parseNumber(cell(row, columns.low_price)),
      low_yield: parseNumber(cell(row, columns.low_yield)),
      individual_investor_flag: cell(row, columns.individual_investor_flag) || null,
      source_row_number: rowIndex + 1,
    });
  }
  return out;
}

function cellDisplay(value: unknown): string {
  if (value == null) return "";
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toISOString().slice(0, 10).replace(/-/g, "");
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return Number.isInteger(value) ? String(value) : String(value);
  }
  return String(value);
}

function workbookToRows(bytes: Uint8Array): string[][] {
  if (bytes.byteLength < 1 || bytes.byteLength > MAX_WORKBOOK_BYTES) {
    throw new Error("PARSE_ZERO: JSDA workbook exceeds the closed size bound");
  }
  let workbook: XLSX.WorkBook;
  try {
    workbook = XLSX.read(bytes, {
      type: "array",
      raw: true,
      cellFormula: true,
      cellHTML: false,
      cellStyles: false,
      sheetStubs: false,
      dense: false,
    });
  } catch {
    throw new Error("PARSE_ZERO: JSDA workbook is not a closed XLS/XLSX body");
  }
  const names = workbook.SheetNames ?? [];
  if (names.length < 1 || names.length > MAX_SHEETS) {
    throw new Error("PARSE_ZERO: JSDA workbook sheet bound violated");
  }
  const sheet = workbook.Sheets[names[0]!];
  if (sheet === undefined) {
    throw new Error("PARSE_ZERO: JSDA workbook sheet bound violated");
  }
  const ref = sheet["!ref"];
  if (typeof ref !== "string" || ref.length === 0) {
    throw new Error(JSDA_PARSE_ZERO);
  }
  const range = XLSX.utils.decode_range(ref);
  const rowCount = range.e.r - range.s.r + 1;
  const colCount = range.e.c - range.s.c + 1;
  if (rowCount < 1 || rowCount > MAX_ROWS || colCount < 1 || colCount > MAX_COLS) {
    throw new Error("PARSE_ZERO: JSDA workbook row/column bound violated");
  }
  if (rowCount * colCount > MAX_CELLS) {
    throw new Error("PARSE_ZERO: JSDA workbook cell bound violated");
  }
  const rows: string[][] = [];
  for (let rowIndex = range.s.r; rowIndex <= range.e.r; rowIndex += 1) {
    const row: string[] = [];
    let nonempty = false;
    for (let colIndex = range.s.c; colIndex <= range.e.c; colIndex += 1) {
      const address = XLSX.utils.encode_cell({ r: rowIndex, c: colIndex });
      const item = sheet[address] as XLSX.CellObject | undefined;
      if (item && (item.f || item.t === "e")) {
        throw new Error("PARSE_ZERO: JSDA workbook formulas/errors are not admitted");
      }
      const displayed = cellDisplay(item?.v);
      if (displayed.trim() !== "") nonempty = true;
      row.push(displayed);
    }
    if (nonempty) rows.push(row);
  }
  return rows;
}

export function parseJsdaOtcFile(
  bytes: Uint8Array,
  context: JsdaParseContext,
): JsdaOtcRecord[] {
  const advertised = governedUrlFormat(context.targetUrl);
  const detected = detectJsdaFormat(bytes, advertised);
  if (detected === "html" || detected === "unknown") {
    throw new Error(JSDA_PARSE_ZERO);
  }
  if (!context.governedFormats.includes(detected)) {
    throw new Error(`PARSE_ZERO: JSDA ${detected} is outside the governed format set`);
  }
  const rows = detected === "csv"
    ? parseCsvRows(decodeText(bytes))
    : workbookToRows(bytes);
  return parseOtcReferenceRows(
    rows,
    context.publicationLabelDate,
    context.quoteEffectiveDate,
  );
}
