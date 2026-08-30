import { sha256Hex } from "./sha256";
import type { Opt225RegimeBundle } from "./types";

export const PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION =
  "personal-vol-ratio-am-pm-panel/v1" as const;
export const PERSONAL_VOL_AM_PM_PANELS_PREFIX =
  "research/personal/vol-ratio-am-pm-v1/panels" as const;
export const PERSONAL_VOL_AM_PM_SESSION_DATES_DIGEST_SCHEMA =
  "ordered-trading-session-dates/v1" as const;

export const PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY = {
  dataset: "markets_calendar",
  source: "jquants_premium_core",
  upstream_locator: "/v2/markets/calendar",
  policy_version: "source-capability/v3",
  holiday_division: "1",
  holiday_division_meaning: "trading_session",
  dates_digest_schema: PERSONAL_VOL_AM_PM_SESSION_DATES_DIGEST_SCHEMA,
  role: "canonical_jquants_trading_session_calendar",
  predecessor_rule: "previous_element_of_pinned_ordered_dates",
} as const;

export const PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT = {
  non_price_cutoff_jst: "11:30:00+09:00",
  am_equity_admission_jst: "12:30:00+09:00",
  am_equity_admission_widens_non_price_cutoff: false,
  option_observations_asof: "native_session",
  signal_option_lag_sessions: 1,
  equity_cross_section: "D_MAdjC_with_prior_history",
  order_sizing_price: "D_MAdjC",
  fill: "D_AAdjC",
  eod_valuation: "D_AAdjC",
  first_pnl: "D_AAdjC_to_next_AAdjC",
  no_adjc_fallback: true,
  no_ffill: true,
  no_signal_date_option_values: true,
} as const;

export const PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY = {
  required: true,
  producer_id: "personal-vol-ratio-am-pm-panel-writer/v1",
  panel_schema: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
  panels_prefix: PERSONAL_VOL_AM_PM_PANELS_PREFIX,
  ineligible_source: {
    schema: "PeriodPanel",
    prefix: "research/mass_eval/panels_cache/527c1065afe14601/panels",
    loader: "loadR2Panels",
    reason:
      "PeriodPanel carries one close per code and cannot host MAdjC/AAdjC or the D-1 option as-of contract",
  },
  required_session_calendar: PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
  required_equity_fields: {
    MAdjC: "preserve_when_finite_even_if_AAdjC_missing",
    AAdjC: "preserve_when_finite_even_if_MAdjC_missing",
    AdjC: "never_used_as_fallback",
  },
  required_option_observations: "native_session_including_predecessor",
  predecessor_rule: PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY.predecessor_rule,
  source_preservation:
    "packages/data_plane/ingestion/personal_history.py MorningAdjustmentClose/AfternoonAdjustmentClose",
  forbidden: [
    "AdjC_fallback",
    "ffill",
    "signal_date_option_values",
    "legacy_PeriodPanel_reinterpretation",
    "single_stock_iv",
    "cash_index_executable_fill",
    "hold_clock_compressed_to_fillable_dates",
    "morning_signal_gated_on_AAdjC",
  ],
} as const;

const CASH_INDEX_FILL_ALIASES = new Set([
  "TOPIX",
  "NKY",
  "NK225",
  "N225",
  "NIKKEI",
  "NIKKEI225",
  "__NKY_PROXY__",
  "__TOPIX__",
  "__NK225F__",
  "__INDEX__",
]);

export type AmPmEquityBar = {
  date: string;
  MAdjC: number | null;
  AAdjC: number | null;
};

export type PersonalVolAmPmSessionCalendar =
  typeof PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY & {
    dates: string[];
    dates_digest: string;
  };

export type PersonalVolAmPmTradableHedge = {
  etf_code: string;
  dataset: string;
  bars: AmPmEquityBar[];
};

export type PersonalVolAmPmPanel = {
  schema_version: typeof PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION;
  period_id: string;
  year: number;
  period_start: string;
  period_end: string;
  status: "ok" | "data_missing";
  source: string;
  temporal_contract: typeof PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT;
  session_calendar: PersonalVolAmPmSessionCalendar;
  codes: string[];
  bars: Record<string, AmPmEquityBar[]>;
  opt225_regime: Opt225RegimeBundle | null;
  tradable_hedge: PersonalVolAmPmTradableHedge | null;
};

export type PersonalVolAmPmPanelParseFailure = {
  ok: false;
  error: string;
  legacy: boolean;
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isIsoDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function sameTemporalContract(value: unknown): boolean {
  if (!isObject(value)) return false;
  const expected = PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT;
  const keys = Object.keys(expected) as Array<keyof typeof expected>;
  if (Object.keys(value).sort().join(",") !== keys.slice().sort().join(",")) {
    return false;
  }
  return keys.every((key) => value[key] === expected[key]);
}

function looksLikeCloseTuple(point: unknown): boolean {
  return (
    Array.isArray(point) &&
    point.length >= 2 &&
    (typeof point[1] === "number" || typeof point[1] === "string")
  );
}

export function isLegacyPersonalVolPanel(raw: unknown): boolean {
  if (!isObject(raw)) return false;
  if (raw.schema_version === PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION) {
    return false;
  }
  const bars = raw.bars;
  if (isObject(bars)) {
    for (const series of Object.values(bars)) {
      if (!Array.isArray(series) || series.length === 0) continue;
      if (series.some((point) => looksLikeCloseTuple(point))) return true;
    }
  }
  return (
    typeof raw.period_id === "string" &&
    isObject(raw.bars) &&
    raw.schema_version !== PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION
  );
}

function finitePositivePrice(value: unknown): number | null {
  const price = Number(value);
  return Number.isFinite(price) && price > 0 ? price : null;
}

function parseAmPmBar(point: unknown): AmPmEquityBar | "legacy" | null {
  if (looksLikeCloseTuple(point)) return "legacy";
  if (!isObject(point)) return null;
  const date = typeof point.date === "string" ? point.date : String(point.Date ?? "");
  if (!isIsoDate(date)) return null;
  const morning = finitePositivePrice(
    point.MAdjC ?? point.MorningAdjustmentClose,
  );
  const afternoon = finitePositivePrice(
    point.AAdjC ?? point.AfternoonAdjustmentClose,
  );
  if (morning === null && afternoon === null) return null;
  return { date, MAdjC: morning, AAdjC: afternoon };
}

function parseMembershipCodes(raw: unknown): string[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const codes: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string" || !item || item.startsWith("__")) return null;
    codes.push(item);
  }
  const unique = [...new Set(codes)].sort();
  return unique.length === codes.length ? unique : null;
}

function parseAmPmBars(
  raw: unknown,
): { bars: Record<string, AmPmEquityBar[]>; legacy: boolean } {
  if (!isObject(raw)) return { bars: {}, legacy: false };
  const bars: Record<string, AmPmEquityBar[]> = {};
  for (const [code, series] of Object.entries(raw)) {
    if (!Array.isArray(series)) continue;
    const points: AmPmEquityBar[] = [];
    for (const point of series) {
      const parsed = parseAmPmBar(point);
      if (parsed === "legacy") return { bars: {}, legacy: true };
      if (parsed) points.push(parsed);
    }
    points.sort((left, right) => (left.date < right.date ? -1 : 1));
    bars[code] = points;
  }
  return { bars, legacy: false };
}

const SESSION_CALENDAR_KEYS = new Set([
  ...Object.keys(PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY),
  "dates",
  "dates_digest",
]);

export function personalVolAmPmSessionDatesPayload(dates: string[]): string {
  return `{"ordered_session_dates":${JSON.stringify(dates)},"schema_version":"${PERSONAL_VOL_AM_PM_SESSION_DATES_DIGEST_SCHEMA}"}`;
}

export async function personalVolAmPmSessionDatesDigest(
  dates: string[],
): Promise<`sha256:${string}`> {
  return `sha256:${await sha256Hex(
    new TextEncoder().encode(personalVolAmPmSessionDatesPayload(dates)),
  )}`;
}

function strictlyIncreasingIsoDates(raw: unknown): string[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null;
  const dates: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string" || !isIsoDate(item)) return null;
    if (dates.length && item <= dates[dates.length - 1]) return null;
    dates.push(item);
  }
  return dates;
}

function parseSessionCalendar(
  raw: unknown,
): PersonalVolAmPmSessionCalendar | null {
  if (!isObject(raw)) return null;
  if (Object.keys(raw).some((key) => !SESSION_CALENDAR_KEYS.has(key))) {
    return null;
  }
  const identity = PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY;
  for (const key of Object.keys(identity) as Array<keyof typeof identity>) {
    if (raw[key] !== identity[key]) return null;
  }
  const dates = strictlyIncreasingIsoDates(raw.dates);
  const digest = typeof raw.dates_digest === "string" ? raw.dates_digest : "";
  if (!dates || !/^sha256:[0-9a-f]{64}$/.test(digest)) return null;
  return {
    ...identity,
    dates,
    dates_digest: digest,
  };
}

export async function personalVolAmPmSessionCalendarDigestMatches(
  calendar: PersonalVolAmPmSessionCalendar,
): Promise<boolean> {
  if (!calendar.dates.length) return false;
  return (
    calendar.dates_digest ===
    (await personalVolAmPmSessionDatesDigest(calendar.dates))
  );
}

function parseTradableHedge(
  raw: unknown,
): PersonalVolAmPmTradableHedge | null | "invalid" {
  if (raw === null || raw === undefined) return null;
  if (!isObject(raw)) return "invalid";
  const etfCode = String(raw.etf_code ?? "").trim();
  const dataset = typeof raw.dataset === "string" ? raw.dataset : "";
  if (
    !etfCode ||
    CASH_INDEX_FILL_ALIASES.has(etfCode.toUpperCase()) ||
    etfCode.startsWith("__") ||
    !dataset ||
    /indices_bars_daily/.test(dataset)
  ) {
    return "invalid";
  }
  const parsedBars = parseAmPmBars(raw.bars ? { [etfCode]: raw.bars } : {});
  if (parsedBars.legacy) return "invalid";
  const bars = parsedBars.bars[etfCode] || [];
  if (!bars.length) return "invalid";
  return { etf_code: etfCode, dataset, bars };
}

export function parsePersonalVolAmPmPanel(
  raw: unknown,
  membership?: readonly string[],
): { ok: true; value: PersonalVolAmPmPanel } | PersonalVolAmPmPanelParseFailure {
  if (!isObject(raw)) {
    return { ok: false, error: "panel must be a JSON object", legacy: false };
  }
  if (isLegacyPersonalVolPanel(raw)) {
    return {
      ok: false,
      error: "legacy_period_panel_rejected",
      legacy: true,
    };
  }
  if (raw.schema_version !== PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION) {
    return {
      ok: false,
      error: "am_pm_panel_schema_missing_or_mismatch",
      legacy: false,
    };
  }
  if (!sameTemporalContract(raw.temporal_contract)) {
    return {
      ok: false,
      error: "am_pm_temporal_contract_missing_or_mismatch",
      legacy: false,
    };
  }
  const sessionCalendar = parseSessionCalendar(raw.session_calendar);
  if (!sessionCalendar) {
    return {
      ok: false,
      error: "session_calendar_missing_or_invalid",
      legacy: false,
    };
  }
  const parsedBars = parseAmPmBars(raw.bars);
  if (parsedBars.legacy) {
    return {
      ok: false,
      error: "legacy_period_panel_rejected",
      legacy: true,
    };
  }
  const declared = parseMembershipCodes(membership ?? raw.codes);
  if ((membership || raw.codes !== undefined) && !declared) {
    return { ok: false, error: "equity_membership_invalid", legacy: false };
  }
  const observed = Object.keys(parsedBars.bars)
    .filter((code) => !code.startsWith("__"))
    .sort();
  const codes = declared ?? observed;
  if (declared) {
    const allowed = new Set(declared);
    for (const code of observed) {
      if (!allowed.has(code)) {
        return { ok: false, error: "equity_membership_mismatch", legacy: false };
      }
    }
  }
  const bars: Record<string, AmPmEquityBar[]> = {};
  for (const code of codes) bars[code] = parsedBars.bars[code] || [];
  const hedge = parseTradableHedge(raw.tradable_hedge);
  if (hedge === "invalid") {
    return {
      ok: false,
      error: "cash_index_executable_fill_rejected",
      legacy: false,
    };
  }
  const periodId = typeof raw.period_id === "string" ? raw.period_id : "";
  const periodStart =
    typeof raw.period_start === "string" ? raw.period_start.slice(0, 10) : "";
  const periodEnd =
    typeof raw.period_end === "string" ? raw.period_end.slice(0, 10) : "";
  if (!periodId || !isIsoDate(periodStart) || !isIsoDate(periodEnd)) {
    return { ok: false, error: "period_bounds_invalid", legacy: false };
  }
  const status = raw.status === "data_missing" ? "data_missing" : "ok";
  const opt225 = isObject(raw.opt225_regime)
    ? (raw.opt225_regime as Opt225RegimeBundle)
    : null;
  return {
    ok: true,
    value: {
      schema_version: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
      period_id: periodId,
      year: Number(raw.year ?? 0),
      period_start: periodStart,
      period_end: periodEnd,
      status,
      source: typeof raw.source === "string" ? raw.source : "am_pm_panel",
      temporal_contract: PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT,
      session_calendar: sessionCalendar,
      codes,
      bars,
      opt225_regime: opt225,
      tradable_hedge: hedge,
    },
  };
}

export function equityCodes(panel: PersonalVolAmPmPanel): string[] {
  const source = panel.codes.length
    ? panel.codes
    : Object.keys(panel.bars);
  return [...new Set(source.filter((code) => !code.startsWith("__")))].sort();
}

export function barMaps(panel: PersonalVolAmPmPanel): {
  morning: Record<string, Record<string, number>>;
  afternoon: Record<string, Record<string, number>>;
} {
  const morning: Record<string, Record<string, number>> = {};
  const afternoon: Record<string, Record<string, number>> = {};
  for (const code of equityCodes(panel)) {
    morning[code] = {};
    afternoon[code] = {};
    for (const point of panel.bars[code] || []) {
      if (typeof point.MAdjC === "number" && Number.isFinite(point.MAdjC) && point.MAdjC > 0) {
        morning[code][point.date] = point.MAdjC;
      }
      if (typeof point.AAdjC === "number" && Number.isFinite(point.AAdjC) && point.AAdjC > 0) {
        afternoon[code][point.date] = point.AAdjC;
      }
    }
  }
  return { morning, afternoon };
}
