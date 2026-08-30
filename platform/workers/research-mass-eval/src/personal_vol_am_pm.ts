import { putChildrenThenManifest, putImmutableJson } from "./http";
import {
  PERSONAL_VOL_EXCLUDED_LOOKAHEAD_WINDOWS,
  PERSONAL_VOL_HOLD_SESSIONS,
  PERSONAL_VOL_INCOMPLETE_INTERVAL_SAMPLE_LIMIT,
  PERSONAL_VOL_IV_AVAILABLE_FROM,
  PERSONAL_VOL_ONE_WAY_COST,
  PERSONAL_VOL_PERIODS,
  PERSONAL_VOL_SOURCE_IDENTITY,
  PERSONAL_VOL_STRATEGIES,
  PERSONAL_VOL_SUPPORTED_SOURCE_VERSIONS,
  PERSONAL_VOL_UNIVERSE_PROVENANCE,
  type PersonalVolStrategyId,
} from "./personal_vol_research";
import {
  barMaps,
  equityCodes,
  loadPersonalVolAmPmPanels,
  PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
  PERSONAL_VOL_AM_PM_PANELS_PREFIX,
  PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY,
  PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT,
  parsePersonalVolAmPmPanel,
  type PersonalVolAmPmPanel,
} from "./personal_vol_am_pm_panel";
import {
  personalVolPerformance,
  type PersonalVolDailyPoint,
} from "./personal_vol_metrics";
import { sha256Hex } from "./sha256";
import type { Env, NkyVolSeries, Opt225RegimeBundle } from "./types";

export const PERSONAL_VOL_AM_PM_COHORT_ID = "personal-vol-ratio-am-pm-v1" as const;
export const PERSONAL_VOL_AM_PM_REPORT_SCHEMA =
  "personal-vol-ratio-am-pm-report/v1" as const;
export const PERSONAL_VOL_AM_PM_MANIFEST_SCHEMA =
  "personal-vol-ratio-am-pm-manifest/v1" as const;
export const PERSONAL_VOL_AM_PM_ARTIFACT_PLANE =
  "research/personal/vol-ratio-am-pm-v1/artifacts" as const;
export const PERSONAL_VOL_AM_PM_JOB_ROOT =
  "research/personal/vol-ratio-am-pm-v1" as const;
export const PERSONAL_VOL_AM_PM_MOMENTUM_SESSIONS = 5;
export const PERSONAL_VOL_AM_PM_LONG_FRAC = 0.3;
export const PERSONAL_VOL_AM_PM_SHORT_FRAC = 0.3;
export const PERSONAL_VOL_AM_PM_EXPAND_RATIO = 1.2;
export const PERSONAL_VOL_AM_PM_COMPRESS_RATIO = 0.8;
export const PERSONAL_VOL_AM_PM_CM_HIGH = 0.1;
export const PERSONAL_VOL_AM_PM_CM_LOW = -0.1;

export const PERSONAL_VOL_AM_PM_CONTROL = {
  control_id: "equity_momentum_keep_common_calendar_control_v1",
  role: "COMMON_VALID_CALENDAR_MOMENTUM_KEEP_CONTROL",
  ranking_role: "DIAGNOSTIC_CONTROL_NOT_RANKED",
  thesis:
    "Always keep the balanced 30/30 MAdjC momentum rank on the same common-valid calendar, hold, and cost as the four index-vol ratio candidates.",
  mechanics:
    "Ignore the option-ratio switch. Flatten with the four candidates when any required D-1 vol signal or required M/A equity fact is missing.",
  return_source:
    "Relative equity momentum filled at D AAdjC, not an option premium trade and not a cash-index fill.",
} as const;

export const PERSONAL_VOL_AM_PM_CONTRACT = {
  cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID,
  panel_schema: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
  report_schema: PERSONAL_VOL_AM_PM_REPORT_SCHEMA,
  manifest_schema: PERSONAL_VOL_AM_PM_MANIFEST_SCHEMA,
  panels_prefix: PERSONAL_VOL_AM_PM_PANELS_PREFIX,
  artifact_plane: PERSONAL_VOL_AM_PM_ARTIFACT_PLANE,
  job_root: PERSONAL_VOL_AM_PM_JOB_ROOT,
  ...PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT,
  hold_sessions: PERSONAL_VOL_HOLD_SESSIONS,
  one_way_cost: PERSONAL_VOL_ONE_WAY_COST,
  exact_four: true,
  individual_stock_option_volatility_used: false,
  volatility_signal_scope: "nikkei_225_index_options",
  cash_index_executable_fill: false,
  live_orders: false,
  automatic_promotion: false,
  go: false,
} as const;

export type PersonalVolAmPmResearchRequest = {
  job_id: string;
  cohort_id: typeof PERSONAL_VOL_AM_PM_COHORT_ID;
};

type HeldBook = Record<string, Record<string, number>>;

export type PersonalVolAmPmValidityRow = {
  date: string;
  predecessor: string | null;
  common_valid: boolean;
  reasons: string[];
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSupportedPersonalVolSource(
  source: Opt225RegimeBundle["source"],
): source is { dataset: string; version: string } {
  return (
    source?.dataset === PERSONAL_VOL_SOURCE_IDENTITY.dataset &&
    typeof source.version === "string" &&
    PERSONAL_VOL_SUPPORTED_SOURCE_VERSIONS.some(
      (version) => version === source.version,
    )
  );
}

export function parsePersonalVolAmPmResearchRequest(
  body: unknown,
):
  | { ok: true; value: PersonalVolAmPmResearchRequest }
  | { ok: false; error: string } {
  if (!isObject(body)) return { ok: false, error: "body must be a JSON object" };
  const allowed = new Set(["job_id", "cohort_id"]);
  const unknown = Object.keys(body).filter((key) => !allowed.has(key));
  if (unknown.length) {
    return { ok: false, error: `unknown fields: ${unknown.sort().join(",")}` };
  }
  const jobId = typeof body.job_id === "string" ? body.job_id.trim() : "";
  if (!jobId) return { ok: false, error: "job_id required" };
  if (
    jobId === "." ||
    jobId === ".." ||
    !/^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(jobId)
  ) {
    return { ok: false, error: "job_id is invalid" };
  }
  const cohort = body.cohort_id ?? PERSONAL_VOL_AM_PM_COHORT_ID;
  if (cohort !== PERSONAL_VOL_AM_PM_COHORT_ID) {
    return {
      ok: false,
      error: `cohort_id must be ${PERSONAL_VOL_AM_PM_COHORT_ID}`,
    };
  }
  return {
    ok: true,
    value: { job_id: jobId, cohort_id: PERSONAL_VOL_AM_PM_COHORT_ID },
  };
}

export async function personalVolAmPmContractDigest(): Promise<`sha256:${string}`> {
  const bytes = new TextEncoder().encode(JSON.stringify(PERSONAL_VOL_AM_PM_CONTRACT));
  return `sha256:${await sha256Hex(bytes)}`;
}

function finitePositive(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function predecessorOf(dates: string[], date: string): string | null {
  const index = dates.indexOf(date);
  if (index <= 0) return null;
  return dates[index - 1];
}

function lookupSeries(
  series: NkyVolSeries | null | undefined,
  date: string,
): { short: number | null; long: number | null; abs: number | null } {
  const short = series?.rv_short_by_date?.[date];
  const long = series?.rv_long_by_date?.[date];
  const abs = series?.rv_abs_by_date?.[date];
  return {
    short: finiteNumber(short) ? short : null,
    long: finiteNumber(long) && long > 1e-12 ? long : null,
    abs: finiteNumber(abs) ? abs : null,
  };
}

function rollingRatioAt(
  series: NkyVolSeries | null | undefined,
  date: string,
): number | null {
  const found = lookupSeries(series, date);
  if (found.short === null || found.long === null) return null;
  return found.short / found.long;
}

function fourSignalReasons(
  bundle: Opt225RegimeBundle | null | undefined,
  observationDate: string,
): string[] {
  const reasons: string[] = [];
  if (!bundle) {
    return ["opt225_regime_missing"];
  }
  if (rollingRatioAt(bundle.basevol, observationDate) === null) {
    reasons.push("d_minus_1_basevol_missing");
  }
  if (rollingRatioAt(bundle.atm_iv, observationDate) === null) {
    reasons.push("d_minus_1_atm_iv_missing");
  }
  if (rollingRatioAt(bundle.skew, observationDate) === null) {
    reasons.push("d_minus_1_skew_missing");
  }
  const cm = lookupSeries(bundle.cm_term_ratio, observationDate).abs;
  if (observationDate < PERSONAL_VOL_IV_AVAILABLE_FROM || cm === null) {
    reasons.push("d_minus_1_cm_term_ratio_missing");
  }
  return reasons;
}

function equityFactReasons(
  morning: Record<string, Record<string, number>>,
  afternoon: Record<string, Record<string, number>>,
  codes: string[],
  date: string,
): string[] {
  const reasons: string[] = [];
  for (const code of codes) {
    if (!finitePositive(morning[code]?.[date])) {
      reasons.push(`missing_MAdjC:${code}:${date}`);
    }
    if (!finitePositive(afternoon[code]?.[date])) {
      reasons.push(`missing_AAdjC:${code}:${date}`);
    }
  }
  return reasons;
}

export function personalVolAmPmCommonValidity(
  panel: PersonalVolAmPmPanel,
): PersonalVolAmPmValidityRow[] {
  const dates = panel.session_calendar.dates;
  const codes = equityCodes(panel);
  const { morning, afternoon } = barMaps(panel);
  return dates.map((date) => {
    const predecessor = predecessorOf(dates, date);
    const reasons: string[] = [];
    if (!predecessor) reasons.push("predecessor_session_missing");
    else reasons.push(...fourSignalReasons(panel.opt225_regime, predecessor));
    if (!codes.length) reasons.push("equity_universe_empty");
    reasons.push(...equityFactReasons(morning, afternoon, codes, date));
    const unique: string[] = [];
    for (const reason of reasons) {
      if (!unique.includes(reason)) unique.push(reason);
    }
    return {
      date,
      predecessor,
      common_valid: unique.length === 0,
      reasons: unique,
    };
  });
}

function momentumAt(
  dates: string[],
  morning: Record<string, number>,
  index: number,
): number | null {
  if (index < PERSONAL_VOL_AM_PM_MOMENTUM_SESSIONS) return null;
  const lastDate = dates[index];
  const baseDate = dates[index - PERSONAL_VOL_AM_PM_MOMENTUM_SESSIONS];
  const last = morning[lastDate];
  const base = morning[baseDate];
  if (!finitePositive(base) || !finitePositive(last)) return null;
  for (let step = index - PERSONAL_VOL_AM_PM_MOMENTUM_SESSIONS; step <= index; step += 1) {
    if (!finitePositive(morning[dates[step]])) return null;
  }
  return (last - base) / base;
}

function rankSigns(
  scores: Record<string, number | null>,
): Record<string, number> {
  const items = Object.entries(scores)
    .filter(([, value]) => value !== null && Number.isFinite(value))
    .map(([code, value]) => [code, value as number] as [string, number])
    .sort((left, right) => right[1] - left[1]);
  const out: Record<string, number> = {};
  for (const code of Object.keys(scores)) out[code] = 0;
  if (!items.length) return out;
  const nLong = Math.max(1, Math.floor(items.length * PERSONAL_VOL_AM_PM_LONG_FRAC));
  const nShort = Math.max(1, Math.floor(items.length * PERSONAL_VOL_AM_PM_SHORT_FRAC));
  for (let index = 0; index < items.length; index += 1) {
    const code = items[index][0];
    if (index < nLong) out[code] = 1;
    else if (index >= items.length - nShort) out[code] = -1;
    else out[code] = 0;
  }
  return out;
}

function stickyFixedHorizon(
  entries: Array<number | null>,
  hold: number,
): Array<number | null> {
  const out: Array<number | null> = new Array(entries.length).fill(null);
  let held: number | null = null;
  let since = 0;
  for (let index = 0; index < entries.length; index += 1) {
    const raw = entries[index];
    const entry =
      raw === null || !Number.isFinite(raw) ? null : Math.sign(raw);
    if (index === 0 || since >= hold) {
      if (entry !== null && entry !== 0) held = entry;
      else if (entry === 0) held = 0;
      since = 1;
    } else {
      since += 1;
    }
    out[index] = held;
  }
  return out;
}

function regimeAt(
  strategyId: PersonalVolStrategyId | "control",
  bundle: Opt225RegimeBundle | null | undefined,
  observationDate: string,
): "keep" | "reverse" | "flat" | null {
  if (strategyId === "control") return "keep";
  if (!bundle) return null;
  if (strategyId === "near_next_cm_atm_iv_ratio") {
    const value = lookupSeries(bundle.cm_term_ratio, observationDate).abs;
    if (value === null || observationDate < PERSONAL_VOL_IV_AVAILABLE_FROM) {
      return null;
    }
    if (value >= PERSONAL_VOL_AM_PM_CM_HIGH) return "reverse";
    if (value <= PERSONAL_VOL_AM_PM_CM_LOW) return "keep";
    return "flat";
  }
  const series =
    strategyId === "basevol_short_long_ratio"
      ? bundle.basevol
      : strategyId === "atm_iv_short_long_ratio"
        ? bundle.atm_iv
        : bundle.skew;
  const ratio = rollingRatioAt(series, observationDate);
  if (ratio === null) return null;
  if (ratio >= PERSONAL_VOL_AM_PM_EXPAND_RATIO) return "reverse";
  if (ratio <= PERSONAL_VOL_AM_PM_COMPRESS_RATIO) return "keep";
  return "flat";
}

export function personalVolAmPmEntrySigns(
  panel: PersonalVolAmPmPanel,
  strategyId: PersonalVolStrategyId | "control",
  signalDate: string,
): Record<string, number> {
  const dates = panel.session_calendar.dates;
  const index = dates.indexOf(signalDate);
  const empty: Record<string, number> = {};
  for (const code of equityCodes(panel)) empty[code] = 0;
  if (index < 0) return empty;
  const validity = personalVolAmPmCommonValidity(panel);
  const row = validity[index];
  if (!row?.common_valid) return empty;
  const { morning } = barMaps(panel);
  const scores: Record<string, number | null> = {};
  for (const code of equityCodes(panel)) {
    scores[code] = momentumAt(dates, morning[code] || {}, index);
  }
  const ranks = rankSigns(scores);
  const regime = regimeAt(
    strategyId,
    panel.opt225_regime,
    row.predecessor || "",
  );
  const out: Record<string, number> = {};
  for (const code of equityCodes(panel)) {
    const rank = ranks[code] ?? 0;
    if (!rank || regime === null || regime === "flat") out[code] = 0;
    else if (regime === "reverse") out[code] = -rank;
    else out[code] = rank;
  }
  return out;
}

function heldBookFor(
  panel: PersonalVolAmPmPanel,
  strategyId: PersonalVolStrategyId | "control",
): HeldBook {
  const dates = panel.session_calendar.dates;
  const validity = personalVolAmPmCommonValidity(panel);
  const validDates = dates.filter((_, index) => validity[index]?.common_valid);
  const codes = equityCodes(panel);
  const held: HeldBook = {};
  for (const code of codes) held[code] = {};
  if (!validDates.length) return held;
  const entriesByCode: Record<string, number[]> = {};
  for (const code of codes) entriesByCode[code] = [];
  for (const date of validDates) {
    const signs = personalVolAmPmEntrySigns(panel, strategyId, date);
    for (const code of codes) {
      entriesByCode[code].push(signs[code] ?? 0);
    }
  }
  for (const code of codes) {
    const sticky = stickyFixedHorizon(
      entriesByCode[code],
      PERSONAL_VOL_HOLD_SESSIONS,
    );
    for (let index = 0; index < validDates.length; index += 1) {
      const position = sticky[index];
      if (position !== null && position !== 0) {
        held[code][validDates[index]] = position;
      }
    }
  }
  return held;
}

export function personalVolAmPmDailyPath(
  held: HeldBook,
  panel: PersonalVolAmPmPanel,
): {
  points: PersonalVolDailyPoint[];
  active_sessions: number;
  short_sessions: number;
  occupancy: number | null;
  incomplete_intervals: number;
  invalid_equity_observations: number;
  fill_count: number;
  incomplete_interval_samples: Array<{
    signal_date: string;
    fill_date: string;
    return_start_date: string;
    return_end_date: string;
    missing_leg_count: number;
  }>;
  incomplete_interval_samples_omitted: number;
} {
  const dates = panel.session_calendar.dates;
  const validity = personalVolAmPmCommonValidity(panel);
  const validityByDate = new Map(validity.map((row) => [row.date, row]));
  const { afternoon } = barMaps(panel);
  const codes = equityCodes(panel);
  const points: PersonalVolDailyPoint[] = [];
  let equity = 1;
  let activeSessions = 0;
  let shortSessions = 0;
  let incompleteIntervals = 0;
  let invalidEquityObservations = 0;
  let fillCount = 0;
  const incompleteIntervalSamples: Array<{
    signal_date: string;
    fill_date: string;
    return_start_date: string;
    return_end_date: string;
    missing_leg_count: number;
  }> = [];
  const amortizedRoundTripCost =
    (2 * PERSONAL_VOL_ONE_WAY_COST) / PERSONAL_VOL_HOLD_SESSIONS;
  for (let index = 1; index < dates.length; index += 1) {
    const signalDate = dates[index - 1];
    const current = dates[index];
    if (current < panel.period_start) continue;
    if (current > panel.period_end) break;
    const signalValid = validityByDate.get(signalDate)?.common_valid === true;
    const contributions: number[] = [];
    let hasShort = false;
    let intendedLegs = 0;
    let missingLegs = 0;
    if (signalValid) {
      missingLegs = codes.filter(
        (code) => !finitePositive(afternoon[code]?.[current]),
      ).length;
      for (const code of codes) {
        const position = held[code]?.[signalDate];
        if (position === undefined || position === 0) continue;
        intendedLegs += 1;
        const fill = afternoon[code]?.[signalDate];
        const next = afternoon[code]?.[current];
        const legReturn =
          Number.isFinite(position) &&
          finitePositive(fill) &&
          finitePositive(next)
            ? position * (Number(next) / Number(fill) - 1)
            : Number.NaN;
        if (Number.isFinite(legReturn)) {
          contributions.push(legReturn);
          if (position < 0) hasShort = true;
        }
      }
    }
    let grossReturn = 0;
    let costReturn = 0;
    let turnoverOneWay = 0;
    let netReturn = 0;
    let sessionFills = 0;
    if (signalValid && missingLegs > 0) {
      incompleteIntervals += 1;
      invalidEquityObservations += missingLegs;
      if (
        incompleteIntervalSamples.length <
        PERSONAL_VOL_INCOMPLETE_INTERVAL_SAMPLE_LIMIT
      ) {
        incompleteIntervalSamples.push({
          signal_date: signalDate,
          fill_date: signalDate,
          return_start_date: signalDate,
          return_end_date: current,
          missing_leg_count: missingLegs,
        });
      }
    } else if (signalValid && contributions.length === intendedLegs && intendedLegs > 0) {
      grossReturn =
        contributions.reduce((total, value) => total + value, 0) /
        contributions.length;
      costReturn = amortizedRoundTripCost;
      turnoverOneWay = 2 / PERSONAL_VOL_HOLD_SESSIONS;
      netReturn = grossReturn - costReturn;
      activeSessions += 1;
      sessionFills = intendedLegs;
      fillCount += intendedLegs;
      if (hasShort) shortSessions += 1;
    }
    equity *= 1 + netReturn;
    points.push({
      date: current,
      gross_return: grossReturn,
      cost_return: costReturn,
      turnover_one_way: turnoverOneWay,
      invalid_equity_observations: missingLegs,
      fill_count: sessionFills,
      net_return: netReturn,
      equity,
    });
  }
  return {
    points,
    active_sessions: activeSessions,
    short_sessions: shortSessions,
    occupancy: points.length ? activeSessions / points.length : null,
    incomplete_intervals: incompleteIntervals,
    invalid_equity_observations: invalidEquityObservations,
    fill_count: fillCount,
    incomplete_interval_samples: incompleteIntervalSamples,
    incomplete_interval_samples_omitted:
      incompleteIntervals - incompleteIntervalSamples.length,
  };
}

function unavailableWindow(
  panel: PersonalVolAmPmPanel,
  reason: string,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  const diagnosticMetrics = personalVolPerformance([], true);
  return {
    period_id: panel.period_id,
    year: panel.year,
    status: reason === "panel_missing_or_empty" ? "data_missing" : "incomplete",
    reason,
    daily_path: [],
    performance_status: "UNAVAILABLE",
    performance_unavailable_reason: reason,
    metrics: null,
    diagnostic_metrics: diagnosticMetrics,
    ...extra,
  };
}

function ratioKind(
  strategyId: PersonalVolStrategyId | "control",
): "rolling_short_long" | "near_next_zero_centered" | "control_no_ratio" {
  if (strategyId === "control") return "control_no_ratio";
  if (strategyId === "near_next_cm_atm_iv_ratio") return "near_next_zero_centered";
  return "rolling_short_long";
}

export function evaluatePersonalVolAmPmWindow(
  definition: (typeof PERSONAL_VOL_STRATEGIES)[number] | typeof PERSONAL_VOL_AM_PM_CONTROL,
  panel: PersonalVolAmPmPanel,
): Record<string, unknown> {
  const parsed = parsePersonalVolAmPmPanel(panel);
  if (!parsed.ok) {
    return unavailableWindow(
      panel,
      parsed.legacy
        ? "legacy_period_panel_rejected"
        : parsed.error,
    );
  }
  if (panel.status !== "ok" || equityCodes(panel).length === 0) {
    return unavailableWindow(panel, "panel_missing_or_empty");
  }
  if (!panel.session_calendar.dates.length) {
    return unavailableWindow(panel, "session_calendar_missing_or_invalid");
  }
  const source = panel.opt225_regime?.source;
  if (!isSupportedPersonalVolSource(source)) {
    return unavailableWindow(panel, "opt225_source_identity_missing_or_mismatch", {
      expected_source: {
        dataset: PERSONAL_VOL_SOURCE_IDENTITY.dataset,
        supported_versions: PERSONAL_VOL_SUPPORTED_SOURCE_VERSIONS,
      },
      observed_source: source ?? null,
    });
  }
  const strategyId =
    "strategy_id" in definition ? definition.strategy_id : "control";
  const validity = personalVolAmPmCommonValidity(panel);
  const requiredDates = validity.filter(
    (row) => row.date >= panel.period_start && row.date <= panel.period_end,
  );
  const held = heldBookFor(panel, strategyId);
  const path = personalVolAmPmDailyPath(held, panel);
  const status =
    path.incomplete_intervals > 0
      ? "incomplete"
      : path.active_sessions > 0
        ? "ok"
        : requiredDates.every((row) => !row.common_valid)
          ? "incomplete"
          : "no_active_positions";
  const reason =
    status === "ok"
      ? null
      : status === "incomplete"
        ? path.incomplete_intervals > 0
          ? "one_or_more_active_intervals_missing_complete_equity_legs"
          : "common_validity_empty"
        : "ratio_never_crossed_fixed_thresholds";
  const diagnosticMetrics = personalVolPerformance(path.points, true);
  return {
    period_id: panel.period_id,
    year: panel.year,
    period_start: panel.period_start,
    period_end: panel.period_end,
    status,
    reason,
    volatility_source: source,
    ratio_kind: ratioKind(strategyId),
    canonical_trading_sessions: panel.session_calendar.dates.length,
    required_trading_sessions: requiredDates.length,
    common_valid_sessions: requiredDates.filter((row) => row.common_valid).length,
    common_validity: requiredDates,
    eval_path: `personal_draft:am_pm:${strategyId}`,
    option_signal_lag_sessions: 1,
    fill_lag_sessions: 0,
    first_pnl_lag_sessions: 1,
    execution_timing: "signal_d_morning_d_minus_1_vol_fill_d_aadjc",
    order_sizing_price: "D_MAdjC",
    fill: "D_AAdjC",
    eod_valuation: "D_AAdjC",
    first_pnl: "D_AAdjC_to_next_AAdjC",
    active_sessions: path.active_sessions,
    short_sessions: path.short_sessions,
    occupancy: path.occupancy,
    complete_leg_policy: "flat_entire_interval_without_cost",
    incomplete_intervals: path.incomplete_intervals,
    missing_leg_count: path.invalid_equity_observations,
    invalid_equity_observations: path.invalid_equity_observations,
    fill_count: path.fill_count,
    incomplete_interval_samples: path.incomplete_interval_samples,
    incomplete_interval_samples_omitted:
      path.incomplete_interval_samples_omitted,
    daily_path: path.points,
    performance_status: status === "ok" ? "AVAILABLE" : "UNAVAILABLE",
    performance_unavailable_reason: reason,
    metrics: status === "ok" ? diagnosticMetrics : null,
    ...(status === "ok" ? {} : { diagnostic_metrics: diagnosticMetrics }),
    individual_stock_option_volatility_used: false,
    cash_index_executable_fill: false,
  };
}

function stitchWindows(
  windows: Record<string, unknown>[],
  commonPeriodIds: string[],
): {
  stitched_non_contiguous: Record<string, unknown>;
  common_window_comparison: Record<string, unknown>;
} {
  const stitchedPoints = windows.flatMap((window) =>
    Array.isArray(window.daily_path)
      ? (window.daily_path as PersonalVolDailyPoint[])
      : [],
  );
  const unavailablePeriodIds = windows
    .filter((window) => window.status !== "ok")
    .map((window) => String(window.period_id));
  const stitchedMetrics = personalVolPerformance(stitchedPoints, false);
  const stitchedAvailable = unavailablePeriodIds.length === 0;
  const comparable = commonPeriodIds.length === PERSONAL_VOL_PERIODS.length;
  const commonSet = new Set(comparable ? commonPeriodIds : []);
  const commonPoints = windows.flatMap((window) =>
    commonSet.has(String(window.period_id)) && Array.isArray(window.daily_path)
      ? (window.daily_path as PersonalVolDailyPoint[])
      : [],
  );
  return {
    stitched_non_contiguous: {
      label: "three fixed post-selection windows stitched for descriptive comparison",
      warning:
        "The gaps between windows are omitted. CAGR is intentionally null and this stitch is not a continuous backtest.",
      performance_status: stitchedAvailable ? "AVAILABLE" : "UNAVAILABLE",
      performance_unavailable_reason: stitchedAvailable
        ? null
        : "one_or_more_windows_not_ok",
      unavailable_period_ids: unavailablePeriodIds,
      metrics: stitchedAvailable ? stitchedMetrics : null,
      ...(stitchedAvailable ? {} : { diagnostic_metrics: stitchedMetrics }),
    },
    common_window_comparison: {
      period_ids: comparable ? commonPeriodIds : [],
      comparable,
      performance_status: comparable ? "AVAILABLE" : "UNAVAILABLE",
      performance_unavailable_reason: comparable
        ? null
        : "all_required_windows_must_be_ok",
      metrics: comparable ? personalVolPerformance(commonPoints, false) : null,
    },
  };
}

function executionSummary(
  rows: Array<{
    strategy_id?: string;
    control_id?: string;
    windows: Record<string, unknown>[];
  }>,
): Record<string, unknown>[] {
  return rows.map((row) => {
    const successfulWindows = row.windows.filter((window) => window.status === "ok").length;
    const incompleteWindows = row.windows.filter(
      (window) => window.status === "incomplete",
    ).length;
    const nonOkWindows = row.windows.filter((window) => window.status !== "ok").length;
    const incompleteIntervals = row.windows.reduce(
      (total, window) =>
        total +
        (typeof window.incomplete_intervals === "number"
          ? window.incomplete_intervals
          : 0),
      0,
    );
    const missingLegCount = row.windows.reduce(
      (total, window) =>
        total +
        (typeof window.missing_leg_count === "number" ? window.missing_leg_count : 0),
      0,
    );
    const fillCount = row.windows.reduce(
      (total, window) =>
        total + (typeof window.fill_count === "number" ? window.fill_count : 0),
      0,
    );
    return {
      strategy_id: row.strategy_id ?? null,
      control_id: row.control_id ?? null,
      requested_windows: row.windows.length,
      successful_windows: successfulWindows,
      incomplete_windows: incompleteWindows,
      non_ok_windows: nonOkWindows,
      incomplete_intervals: incompleteIntervals,
      missing_leg_count: missingLegCount,
      fill_count: fillCount,
      candidate_status:
        successfulWindows === PERSONAL_VOL_PERIODS.length && nonOkWindows === 0
          ? "evaluated"
          : "not_evaluated",
    };
  });
}

export async function runPersonalVolAmPmResearch(
  env: Env,
  request: PersonalVolAmPmResearchRequest,
): Promise<Record<string, unknown>> {
  const digest = await personalVolAmPmContractDigest();
  const panelNotes: string[] = [];
  const observedVolatilitySources = new Map<
    string,
    { dataset: string; version: string }
  >();
  const windowsByStrategy = new Map<string, Record<string, unknown>[]>(
    PERSONAL_VOL_STRATEGIES.map((row) => [row.strategy_id, []]),
  );
  const controlWindows: Record<string, unknown>[] = [];

  for (const period of PERSONAL_VOL_PERIODS) {
    const loaded = await loadPersonalVolAmPmPanels(env.STRUCTURED_BUCKET, [period]);
    panelNotes.push(...loaded.notes);
    const panel = loaded.panels[0];
    const observedSource = panel.opt225_regime?.source;
    if (
      typeof observedSource?.dataset === "string" &&
      typeof observedSource.version === "string"
    ) {
      observedVolatilitySources.set(
        `${observedSource.dataset}\n${observedSource.version}`,
        {
          dataset: observedSource.dataset,
          version: observedSource.version,
        },
      );
    }
    for (const definition of PERSONAL_VOL_STRATEGIES) {
      windowsByStrategy
        .get(definition.strategy_id)!
        .push(evaluatePersonalVolAmPmWindow(definition, panel));
    }
    controlWindows.push(evaluatePersonalVolAmPmWindow(PERSONAL_VOL_AM_PM_CONTROL, panel));
  }

  const commonSuccessfulWindows = PERSONAL_VOL_PERIODS.map(
    (period) => period.period_id,
  ).filter((periodId) =>
    PERSONAL_VOL_STRATEGIES.every((definition) =>
      windowsByStrategy
        .get(definition.strategy_id)!
        .some((window) => window.period_id === periodId && window.status === "ok"),
    ),
  );
  const strategies = PERSONAL_VOL_STRATEGIES.map((definition) => ({
    ...definition,
    am_pm_contract: PERSONAL_VOL_AM_PM_CONTRACT,
    am_pm_contract_digest: digest,
    windows: windowsByStrategy.get(definition.strategy_id)!,
    ...stitchWindows(
      windowsByStrategy.get(definition.strategy_id)!,
      commonSuccessfulWindows,
    ),
  }));
  const control = {
    ...PERSONAL_VOL_AM_PM_CONTROL,
    am_pm_contract: PERSONAL_VOL_AM_PM_CONTRACT,
    am_pm_contract_digest: digest,
    windows: controlWindows,
    ...stitchWindows(controlWindows, commonSuccessfulWindows),
  };
  const allRequiredWindowsComparable =
    commonSuccessfulWindows.length === PERSONAL_VOL_PERIODS.length;
  const exactFourEvaluationComplete = allRequiredWindowsComparable;
  const report = {
    schema_version: PERSONAL_VOL_AM_PM_REPORT_SCHEMA,
    worker_version: env.MASS_EVAL_VERSION,
    job_id: request.job_id,
    cohort_id: request.cohort_id,
    research_mode: "personal_draft_screening",
    am_pm_contract: PERSONAL_VOL_AM_PM_CONTRACT,
    am_pm_contract_digest: digest,
    execution_contract: {
      exact_four: true,
      exact_four_evaluation_complete: exactFourEvaluationComplete,
      exact_four_common_window_comparable: allRequiredWindowsComparable,
      common_successful_windows: allRequiredWindowsComparable
        ? commonSuccessfulWindows
        : [],
      strategy_count: PERSONAL_VOL_STRATEGIES.length,
      hold_sessions: PERSONAL_VOL_HOLD_SESSIONS,
      one_way_cost: PERSONAL_VOL_ONE_WAY_COST,
      cost_method: "two_one_way_costs_amortized_over_fixed_hold",
      option_signal_lag_sessions: 1,
      fill_lag_sessions: 0,
      first_pnl_lag_sessions: 1,
      execution_timing: "signal_d_morning_d_minus_1_vol_fill_d_aadjc",
      incomplete_equity_leg_policy: "flat_entire_interval_without_cost",
      short_financing: "not_modelled",
      short_financing_limitation: "screening_only",
      market_neutrality: "dollar_balanced_rank_long_short_not_beta_neutral",
      index_etf_hedge: "not_applied_in_this_screen",
      individual_stock_option_volatility_used: false,
      volatility_signal_scope: "nikkei_225_index_options",
      cash_index_executable_fill: false,
      live_orders: false,
      automatic_promotion: false,
      go: false,
      ...PERSONAL_VOL_AM_PM_TEMPORAL_CONTRACT,
    },
    execution_summary: executionSummary([
      ...strategies.map((strategy) => ({
        strategy_id: strategy.strategy_id,
        windows: strategy.windows,
      })),
      {
        control_id: PERSONAL_VOL_AM_PM_CONTROL.control_id,
        windows: controlWindows,
      },
    ]),
    data_contract: {
      panels_prefix: PERSONAL_VOL_AM_PM_PANELS_PREFIX,
      panel_schema: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
      producer_dependency: PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY,
      periods: PERSONAL_VOL_PERIODS,
      period_count: PERSONAL_VOL_PERIODS.length,
      iv_fields_available_from: PERSONAL_VOL_IV_AVAILABLE_FROM,
      panel_notes: panelNotes,
      source: "closed AM/PM panel bundle; never a PeriodPanel reinterpretation",
      volatility_source: {
        dataset: PERSONAL_VOL_SOURCE_IDENTITY.dataset,
        current_staging_version: PERSONAL_VOL_SOURCE_IDENTITY.version,
        supported_versions: PERSONAL_VOL_SUPPORTED_SOURCE_VERSIONS,
        observed: [...observedVolatilitySources.values()],
      },
      equity_universe: PERSONAL_VOL_UNIVERSE_PROVENANCE,
      excluded_lookahead_windows: PERSONAL_VOL_EXCLUDED_LOOKAHEAD_WINDOWS,
      exclusion_reason:
        "The fixed equity codes were selected with 2019 information, so 2015, 2017, and the in-sample 2019 window are not valid out-of-sample performance evidence.",
    },
    result_authority: {
      draft_only: true,
      screening_only: true,
      verified_pilot_readiness: false,
      verified_mass_readiness: false,
      usable_as_pilot_readiness: false,
      usable_as_mass_readiness: false,
      connected_to_ready: false,
      connected_to_mass: false,
      go: false,
    },
    strategies,
    control,
    automatic_promotion: false,
    live_orders: false,
    go: false,
    not_a_pass: true,
  };
  const artifact = await putImmutableJson(
    env.STRUCTURED_BUCKET,
    PERSONAL_VOL_AM_PM_ARTIFACT_PLANE,
    report,
  );
  const prefix = `${PERSONAL_VOL_AM_PM_JOB_ROOT}/job=${request.job_id}`;
  const reportKey = `${prefix}/report.json`;
  const manifestKey = `${prefix}/manifest.json`;
  const manifest = {
    schema_version: PERSONAL_VOL_AM_PM_MANIFEST_SCHEMA,
    job_id: request.job_id,
    cohort_id: request.cohort_id,
    am_pm_contract_digest: digest,
    report_key: reportKey,
    artifact_key: artifact.key,
    artifact_digest: artifact.digest,
    go: false,
    not_a_pass: true,
  };
  const commit = await putChildrenThenManifest(
    env.STRUCTURED_BUCKET,
    [{ key: reportKey, data: report }],
    { key: manifestKey, data: manifest },
    artifact.digest,
  );
  if (!commit.ok) {
    throw Object.assign(new Error("artifact_conflict"), {
      code: "artifact_conflict",
    });
  }
  return {
    ...report,
    r2_keys: {
      report: reportKey,
      manifest: manifestKey,
      artifact: artifact.key,
      digest: artifact.digest,
    },
    artifact_created: artifact.created,
    report_created: commit.children[0]?.created ?? false,
    manifest_created: commit.manifest.created,
  };
}
