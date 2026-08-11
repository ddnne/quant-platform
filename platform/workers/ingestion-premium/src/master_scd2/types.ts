/** equities_master SCD2 event types (GLM W3). Migration ops not auto-run. */

export const MASTER_EVENT_TYPES = {
  LISTED: "LISTED",
  DELISTED: "DELISTED",
  NAME_CHANGE: "NAME_CHANGE",
  SECTOR_33_CHANGE: "SECTOR_33_CHANGE",
  SECTOR_17_CHANGE: "SECTOR_17_CHANGE",
  SCALE_CHANGE: "SCALE_CHANGE",
  MARKET_CHANGE: "MARKET_CHANGE",
  MERGER: "MERGER",
  ABSORBED: "ABSORBED",
  SPLIT: "SPLIT",
  SYMBOL_CHANGE: "SYMBOL_CHANGE",
  ATTRIBUTE_CORRECT: "ATTRIBUTE_CORRECT",
  CORP_ACTION: "CORP_ACTION",
} as const;

export type MasterEventType =
  (typeof MASTER_EVENT_TYPES)[keyof typeof MASTER_EVENT_TYPES];

export interface MasterRecord {
  local_code: string;
  code_name: string;
  sector_33_code?: string;
  sector_33_name?: string;
  sector_17_code?: string;
  sector_17_name?: string;
  scale_code?: string;
  scale_name?: string;
  listing_date?: string;
  market_code?: string;
  market_name?: string;
}

export async function computeVersionHash(rec: MasterRecord): Promise<string> {
  const stable = [
    rec.code_name,
    rec.sector_33_code ?? "",
    rec.sector_33_name ?? "",
    rec.sector_17_code ?? "",
    rec.sector_17_name ?? "",
    rec.scale_code ?? "",
    rec.scale_name ?? "",
    rec.listing_date ?? "",
    rec.market_code ?? "",
    rec.market_name ?? "",
  ].join("|");
  const buf = new TextEncoder().encode(stable);
  const dig = await crypto.subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(dig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
