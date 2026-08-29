import { barNativeHeldBook } from "./eval";
import { putChildrenThenManifest, putImmutableJson } from "./http";
import { loadR2Panels } from "./panels";
import {
  personalVolPerformance,
  type PersonalVolDailyPoint,
} from "./personal_vol_metrics";
import type {
  BarsByCode,
  Env,
  LogicSpec,
  NkyVolSeries,
  Opt225RegimeBundle,
  PeriodPanel,
  PeriodSpec,
} from "./types";

export const PERSONAL_VOL_COHORT_ID = "personal-vol-ratio-v2" as const;
export const PERSONAL_VOL_PANELS_PREFIX =
  "research/mass_eval/panels_cache/527c1065afe14601/panels" as const;
export const PERSONAL_VOL_ONE_WAY_COST = 0.001;
export const PERSONAL_VOL_HOLD_SESSIONS = 10;
export const PERSONAL_VOL_IV_AVAILABLE_FROM = "2016-07-19";
export const PERSONAL_VOL_INCOMPLETE_INTERVAL_SAMPLE_LIMIT = 20;
export const PERSONAL_VOL_SOURCE_IDENTITY = {
  dataset: "derivatives_bars_daily_options_225",
  version: "research-options-225-vol-series/v1.3",
} as const;
export const PERSONAL_VOL_SUPPORTED_SOURCE_VERSIONS = [
  "research-options-225-vol-series/v1.2",
  PERSONAL_VOL_SOURCE_IDENTITY.version,
] as const;

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

export const PERSONAL_VOL_UNIVERSE_PROVENANCE = {
  scope_id: "legacy-liq-large-adv100-2019-v1",
  selection_rule: "adv_desc_skip_missing_bars_and_fins",
  selection_reference_start: "2019-01-01",
  selection_reference_end: "2019-10-21",
  maximum_codes: 100,
  membership: "static_fixed_panel_codes",
  daily_pit_reconstitution: false,
  topix_scale_bound: false,
  comparable_to_personal_topix_factor_runs: false,
} as const;

export const PERSONAL_VOL_EXCLUDED_LOOKAHEAD_WINDOWS = [
  "y2015_full",
  "y2017_q4",
  "y2019_full",
] as const;

export const PERSONAL_VOL_PERIODS: readonly PeriodSpec[] = [
  {
    period_id: "y2021_full",
    year: 2021,
    period_start: "2021-01-04",
    period_end: "2021-10-15",
  },
  {
    period_id: "y2023_full",
    year: 2023,
    period_start: "2023-01-04",
    period_end: "2023-10-13",
  },
  {
    period_id: "y2025_q4",
    year: 2025,
    period_start: "2025-09-01",
    period_end: "2025-12-29",
  },
] as const;

export type PersonalVolStrategyId =
  | "basevol_short_long_ratio"
  | "atm_iv_short_long_ratio"
  | "skew_short_long_ratio"
  | "near_next_cm_atm_iv_ratio";

export type PersonalVolResearchRequest = {
  job_id: string;
  cohort_id: typeof PERSONAL_VOL_COHORT_ID;
};

type PersonalVolStrategyDefinition = {
  strategy_id: PersonalVolStrategyId;
  signal_source: "basevol" | "atm_iv" | "skew" | "cm_term_ratio";
  ratio_definition: string;
  thesis: string;
  mechanics: string;
  return_source: string;
  works_when: string;
  fails_when: string;
};

export const PERSONAL_VOL_STRATEGIES: readonly PersonalVolStrategyDefinition[] = [
  {
    strategy_id: "basevol_short_long_ratio",
    signal_source: "basevol",
    ratio_definition: "BaseVol 10-session mean / BaseVol 60-session mean",
    thesis:
      "Fast exchange BaseVol above its slow baseline marks accelerating stress; below it marks normalization. The ratio is used instead of an absolute volatility level.",
    mechanics:
      "Rank equities by 5-session momentum. Keep the balanced 30/30 long-short rank when the ratio is at most 0.80, reverse it when the ratio is at least 1.20, otherwise stay flat; hold each decision for 10 sessions.",
    return_source:
      "Relative equity momentum or reversal conditional on the speed of the options volatility regime, not an option premium trade.",
    works_when:
      "BaseVol acceleration reliably separates stress/reversal regimes from calm/trend regimes.",
    fails_when:
      "The ratio oscillates near thresholds, volatility changes without affecting equity cross-section leadership, or short borrow costs dominate.",
  },
  {
    strategy_id: "atm_iv_short_long_ratio",
    signal_source: "atm_iv",
    ratio_definition: "ATM IV 10-session mean / ATM IV 60-session mean",
    thesis:
      "A fast/slow ATM-IV ratio measures repricing speed without comparing unlike absolute IV regimes across years.",
    mechanics:
      "Apply the same fixed equity momentum rank and 0.80/1.20 calm/stress ratio switch, with a 10-session hold and no caller-tunable parameters.",
    return_source:
      "Cross-sectional equity returns captured when reconstructed ATM-IV acceleration predicts whether momentum persists or reverses.",
    works_when:
      "Front implied volatility reprices before broad changes in equity leadership.",
    fails_when:
      "ATM reconstruction is noisy, the ratio is stale, or implied-vol repricing is disconnected from equity ranking returns.",
  },
  {
    strategy_id: "skew_short_long_ratio",
    signal_source: "skew",
    ratio_definition: "95%-put skew 10-session mean / skew 60-session mean",
    thesis:
      "The relative acceleration of downside-insurance demand is more portable than the absolute skew level.",
    mechanics:
      "Condition the same balanced momentum book on the skew fast/slow ratio: keep below 0.80, reverse above 1.20, flat in between, fixed 10-session hold.",
    return_source:
      "Changes in equity cross-section leadership following unusually fast expansion or compression of downside protection demand.",
    works_when:
      "Skew acceleration precedes de-risking and factor reversals, while skew compression accompanies stable trends.",
    fails_when:
      "Skew moves for supply/technical reasons, sparse strikes distort the series, or the equity universe does not transmit index-option demand.",
  },
  {
    strategy_id: "near_next_cm_atm_iv_ratio",
    signal_source: "cm_term_ratio",
    ratio_definition: "near-CM ATM IV / next-CM ATM IV - 1",
    thesis:
      "A zero-centred maturity ratio distinguishes front-end inversion from longer-dated concern without relying on absolute IV.",
    mechanics:
      "Keep the equity momentum rank when the centred ratio is at most -0.10, reverse it when it is at least +0.10, otherwise stay flat; hold 10 sessions.",
    return_source:
      "Relative equity returns around changes in the slope of the index-option volatility term structure.",
    works_when:
      "Front-end inversion is an early stress signal and contango is associated with stable cross-sectional trends.",
    fails_when:
      "Expiry rolls, sparse quotes, or event-specific front premium move the ratio without a durable equity regime change.",
  },
] as const;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parsePersonalVolResearchRequest(
  body: unknown,
):
  | { ok: true; value: PersonalVolResearchRequest }
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
  const cohort = body.cohort_id ?? PERSONAL_VOL_COHORT_ID;
  if (cohort !== PERSONAL_VOL_COHORT_ID) {
    return {
      ok: false,
      error: `cohort_id must be ${PERSONAL_VOL_COHORT_ID}`,
    };
  }
  return {
    ok: true,
    value: { job_id: jobId, cohort_id: PERSONAL_VOL_COHORT_ID },
  };
}

function unionDates(bars: BarsByCode): string[] {
  const dates = new Set<string>();
  for (const [code, pairs] of Object.entries(bars)) {
    if (code.startsWith("__")) continue;
    for (const [date] of pairs) dates.add(date.slice(0, 10));
  }
  return [...dates].sort();
}

function closeByCode(bars: BarsByCode): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const [code, pairs] of Object.entries(bars)) {
    if (code.startsWith("__")) continue;
    out[code] = {};
    for (const [date, close] of pairs) {
      if (Number.isFinite(close) && close > 0) out[code][date.slice(0, 10)] = close;
    }
  }
  return out;
}

export function ratioSeriesForStrategy(
  strategyId: PersonalVolStrategyId,
  panel: PeriodPanel,
): {
  kind: "rolling_short_long" | "near_next_zero_centered";
  series: NkyVolSeries | null;
  n_observations: number;
} {
  const bundle = panel.opt225_regime;
  const panelDates = new Set(unionDates(panel.bars));
  if (strategyId === "near_next_cm_atm_iv_ratio") {
    const level =
      panel.cm_term_ratio_series || bundle?.cm_term_ratio?.rv_abs_by_date || null;
    const pinned = level
      ? Object.fromEntries(
          Object.entries(level).filter(
            ([date, value]) =>
              date.slice(0, 10) >= PERSONAL_VOL_IV_AVAILABLE_FROM &&
              panelDates.has(date.slice(0, 10)) &&
              Number.isFinite(value),
          ),
        )
      : null;
    return {
      kind: "near_next_zero_centered",
      series: pinned ? { rv_abs_by_date: pinned } : null,
      n_observations: pinned ? Object.keys(pinned).length : 0,
    };
  }
  const source =
    strategyId === "basevol_short_long_ratio"
      ? bundle?.basevol
      : strategyId === "atm_iv_short_long_ratio"
        ? bundle?.atm_iv
        : bundle?.skew;
  const short = source?.rv_short_by_date;
  const long = source?.rv_long_by_date;
  if (!short || !long) {
    return { kind: "rolling_short_long", series: null, n_observations: 0 };
  }
  const ratioDates = Object.keys(short).filter(
    (date) =>
      panelDates.has(date.slice(0, 10)) &&
      Number.isFinite(short[date]) &&
      Number.isFinite(long[date]) &&
      long[date] > 1e-12,
  );
  const shortInPanel = Object.fromEntries(
    ratioDates.map((date) => [date, short[date]]),
  );
  const longInPanel = Object.fromEntries(
    ratioDates.map((date) => [date, long[date]]),
  );
  return {
    kind: "rolling_short_long",
    series: {
      rv_short_by_date: shortInPanel,
      rv_long_by_date: longInPanel,
    },
    n_observations: ratioDates.length,
  };
}

function logicForStrategy(
  strategyId: PersonalVolStrategyId,
): LogicSpec {
  if (strategyId === "near_next_cm_atm_iv_ratio") {
    return {
      logic_id: "opt225_cm_term_ratio",
      family_id: "options_vol_regime",
      params: {
        mode: "opt225_cm_term_ratio",
        series_kind: "cm_term_ratio",
        momentum_n: 5,
        hold_days: PERSONAL_VOL_HOLD_SESSIONS,
        long_frac: 0.3,
        short_frac: 0.3,
        high_threshold: 0.1,
        low_threshold: -0.1,
        neutral_policy: "flat_at_rebalance",
      },
    };
  }
  return {
    logic_id: "nky_vol_term_ratio",
    family_id: "index_vol_regime",
    params: {
      mode: "nky_vol_term_ratio",
      momentum_n: 5,
      hold_days: PERSONAL_VOL_HOLD_SESSIONS,
      long_frac: 0.3,
      short_frac: 0.3,
      expand_ratio: 1.2,
      compress_ratio: 0.8,
      neutral_policy: "flat_at_rebalance",
    },
  };
}

export function personalVolDailyPath(
  held: Record<string, Record<string, number>>,
  panel: PeriodPanel,
): {
  points: PersonalVolDailyPoint[];
  active_sessions: number;
  short_sessions: number;
  occupancy: number | null;
  incomplete_intervals: number;
  invalid_equity_observations: number;
  incomplete_interval_samples: Array<{
    signal_date: string;
    return_start_date: string;
    return_end_date: string;
    missing_leg_count: number;
  }>;
  incomplete_interval_samples_omitted: number;
} {
  const dates = unionDates(panel.bars);
  const closes = closeByCode(panel.bars);
  const points: PersonalVolDailyPoint[] = [];
  let equity = 1;
  let activeSessions = 0;
  let shortSessions = 0;
  let incompleteIntervals = 0;
  let invalidEquityObservations = 0;
  const incompleteIntervalSamples: Array<{
    signal_date: string;
    return_start_date: string;
    return_end_date: string;
    missing_leg_count: number;
  }> = [];
  const amortizedRoundTripCost =
    (2 * PERSONAL_VOL_ONE_WAY_COST) / PERSONAL_VOL_HOLD_SESSIONS;
  // A signal observed at close d cannot be filled at that same close.  It is
  // entered at the next close and first earns the following close-to-close
  // return, hence signal[d-2] applies to return[d-1 -> d].  Earlier bars remain
  // available solely as warm-up; reported P&L is cropped to the declared
  // evaluation window.
  for (let index = 2; index < dates.length; index += 1) {
    const signalDate = dates[index - 2];
    const previous = dates[index - 1];
    const current = dates[index];
    if (current < panel.period_start) continue;
    if (current > panel.period_end) break;
    const contributions: number[] = [];
    let hasShort = false;
    let intendedLegs = 0;
    let missingLegs = 0;
    for (const [code, positions] of Object.entries(held)) {
      const position = positions[signalDate];
      if (position === undefined || position === 0) continue;
      intendedLegs += 1;
      const before = closes[code]?.[previous];
      const after = closes[code]?.[current];
      const legReturn =
        Number.isFinite(position) &&
        Number.isFinite(before) &&
        Number(before) > 0 &&
        Number.isFinite(after) &&
        Number(after) > 0
          ? position * (Number(after) / Number(before) - 1)
          : Number.NaN;
      if (!Number.isFinite(legReturn)) {
        missingLegs += 1;
        continue;
      }
      contributions.push(legReturn);
      if (position < 0) hasShort = true;
    }
    let grossReturn = 0;
    let costReturn = 0;
    let turnoverOneWay = 0;
    let netReturn = 0;
    if (intendedLegs > 0 && missingLegs > 0) {
      incompleteIntervals += 1;
      invalidEquityObservations += missingLegs;
      if (
        incompleteIntervalSamples.length <
        PERSONAL_VOL_INCOMPLETE_INTERVAL_SAMPLE_LIMIT
      ) {
        incompleteIntervalSamples.push({
          signal_date: signalDate,
          return_start_date: previous,
          return_end_date: current,
          missing_leg_count: missingLegs,
        });
      }
    } else if (contributions.length === intendedLegs && intendedLegs > 0) {
      grossReturn =
        contributions.reduce((total, value) => total + value, 0) /
        contributions.length;
      costReturn = amortizedRoundTripCost;
      turnoverOneWay = 2 / PERSONAL_VOL_HOLD_SESSIONS;
      netReturn = grossReturn - costReturn;
      activeSessions += 1;
      if (hasShort) shortSessions += 1;
    }
    equity *= 1 + netReturn;
    points.push({
      date: current,
      gross_return: grossReturn,
      cost_return: costReturn,
      turnover_one_way: turnoverOneWay,
      invalid_equity_observations: missingLegs,
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
    incomplete_interval_samples: incompleteIntervalSamples,
    incomplete_interval_samples_omitted:
      incompleteIntervals - incompleteIntervalSamples.length,
  };
}

export function evaluatePersonalVolWindow(
  definition: PersonalVolStrategyDefinition,
  panel: PeriodPanel,
): Record<string, unknown> {
  if (panel.status !== "ok" || !Object.keys(panel.bars).length) {
    const diagnosticMetrics = personalVolPerformance([], true);
    return {
      period_id: panel.period_id,
      year: panel.year,
      status: "data_missing",
      reason: "panel_missing_or_empty",
      daily_path: [],
      performance_status: "UNAVAILABLE",
      performance_unavailable_reason: "panel_missing_or_empty",
      metrics: null,
      diagnostic_metrics: diagnosticMetrics,
    };
  }
  const source = panel.opt225_regime?.source;
  if (!isSupportedPersonalVolSource(source)) {
    const diagnosticMetrics = personalVolPerformance([], true);
    return {
      period_id: panel.period_id,
      year: panel.year,
      status: "incomplete",
      reason: "opt225_source_identity_missing_or_mismatch",
      expected_source: {
        dataset: PERSONAL_VOL_SOURCE_IDENTITY.dataset,
        supported_versions: PERSONAL_VOL_SUPPORTED_SOURCE_VERSIONS,
      },
      observed_source: source ?? null,
      daily_path: [],
      performance_status: "UNAVAILABLE",
      performance_unavailable_reason:
        "opt225_source_identity_missing_or_mismatch",
      metrics: null,
      diagnostic_metrics: diagnosticMetrics,
    };
  }
  const selected = ratioSeriesForStrategy(definition.strategy_id, panel);
  if (!selected.series || selected.n_observations === 0) {
    const diagnosticMetrics = personalVolPerformance([], true);
    return {
      period_id: panel.period_id,
      year: panel.year,
      status: "data_missing",
      reason: "required_ratio_series_missing",
      volatility_source: source,
      ratio_kind: selected.kind,
      ratio_observations: selected.n_observations,
      daily_path: [],
      performance_status: "UNAVAILABLE",
      performance_unavailable_reason: "required_ratio_series_missing",
      metrics: null,
      diagnostic_metrics: diagnosticMetrics,
    };
  }
  const logic = logicForStrategy(definition.strategy_id);
  const evaluationPanel =
    selected.kind === "rolling_short_long"
      ? { ...panel, nky_vol_series: selected.series }
      : {
          ...panel,
          cm_term_ratio_series: selected.series.rv_abs_by_date || {},
        };
  const native = barNativeHeldBook(logic, evaluationPanel);
  if (!native || native.fallback) {
    const unavailableReason =
      native?.fallback || "closed_bar_native_interpreter_unavailable";
    const diagnosticMetrics = personalVolPerformance([], true);
    return {
      period_id: panel.period_id,
      year: panel.year,
      status: "incomplete",
      reason: unavailableReason,
      volatility_source: source,
      ratio_kind: selected.kind,
      ratio_observations: selected.n_observations,
      daily_path: [],
      performance_status: "UNAVAILABLE",
      performance_unavailable_reason: unavailableReason,
      metrics: null,
      diagnostic_metrics: diagnosticMetrics,
    };
  }
  const path = personalVolDailyPath(native.held, panel);
  const status =
    path.incomplete_intervals > 0
      ? "incomplete"
      : path.active_sessions > 0
        ? "ok"
        : "no_active_positions";
  const reason =
    status === "ok"
      ? null
      : status === "incomplete"
        ? "one_or_more_active_intervals_missing_complete_equity_legs"
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
    ratio_kind: selected.kind,
    ratio_observations: selected.n_observations,
    eval_path: `personal_draft:${native.path}`,
    signal_lag_sessions: 1,
    execution_timing: "signal_close_d_fill_close_d_plus_1",
    active_sessions: path.active_sessions,
    short_sessions: path.short_sessions,
    occupancy: path.occupancy,
    complete_leg_policy: "flat_entire_interval_without_cost",
    incomplete_intervals: path.incomplete_intervals,
    missing_leg_count: path.invalid_equity_observations,
    invalid_equity_observations: path.invalid_equity_observations,
    incomplete_interval_samples: path.incomplete_interval_samples,
    incomplete_interval_samples_omitted:
      path.incomplete_interval_samples_omitted,
    daily_path: path.points,
    performance_status: status === "ok" ? "AVAILABLE" : "UNAVAILABLE",
    performance_unavailable_reason: reason,
    metrics: status === "ok" ? diagnosticMetrics : null,
    ...(status === "ok" ? {} : { diagnostic_metrics: diagnosticMetrics }),
  };
}

export async function runPersonalVolResearch(
  env: Env,
  request: PersonalVolResearchRequest,
): Promise<Record<string, unknown>> {
  const panelNotes: string[] = [];
  const fixedPrefixNotes: string[] = [];
  const observedVolatilitySources = new Map<
    string,
    { dataset: string; version: string }
  >();
  const windowsByStrategy = new Map<
    PersonalVolStrategyId,
    Record<string, unknown>[]
  >(PERSONAL_VOL_STRATEGIES.map((row) => [row.strategy_id, []]));

  // Keep peak isolate memory bounded: load one historical panel, evaluate all
  // four closed definitions, then release that panel before reading the next.
  // The fixed cache totals tens of megabytes on disk and must not be retained
  // as six expanded JSON object graphs in a 128 MiB Worker isolate.
  for (const period of PERSONAL_VOL_PERIODS) {
    const loaded = await loadR2Panels(
      env.STRUCTURED_BUCKET,
      [period],
      PERSONAL_VOL_PANELS_PREFIX,
    );
    panelNotes.push(...loaded.notes);
    const expectedKey = `${PERSONAL_VOL_PANELS_PREFIX}/${period.period_id}.json`;
    const loadedFromFixedKey = loaded.notes.some((note) =>
      note.startsWith(`loaded:${expectedKey}:`),
    );
    const panel = loadedFromFixedKey
      ? loaded.panels[0]
      : (() => {
          fixedPrefixNotes.push(`fixed_prefix_missing_or_invalid:${expectedKey}`);
          return {
            period_id: period.period_id,
            year: Number(period.year ?? 0),
            period_start: period.period_start || "",
            period_end: period.period_end || "",
            status: "data_missing" as const,
            bars: {},
            source: "fixed_personal_vol_panel_missing",
          };
        })();
    const observedSource =
      "opt225_regime" in panel ? panel.opt225_regime?.source : undefined;
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
        .push(evaluatePersonalVolWindow(definition, panel));
    }
  }
  const strategiesBeforeCommonWindow = PERSONAL_VOL_STRATEGIES.map((definition) => {
    const windows = windowsByStrategy.get(definition.strategy_id)!;
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
    return {
      ...definition,
      windows,
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
    };
  });
  const commonSuccessfulWindows = PERSONAL_VOL_PERIODS.map(
    (period) => period.period_id,
  ).filter((periodId) =>
    strategiesBeforeCommonWindow.every((strategy) =>
      strategy.windows.some(
        (window) => window.period_id === periodId && window.status === "ok",
      ),
    ),
  );
  const commonWindowSet = new Set(commonSuccessfulWindows);
  const strategies = strategiesBeforeCommonWindow.map((strategy) => {
    const commonPoints = strategy.windows.flatMap((window) =>
      commonWindowSet.has(String(window.period_id)) &&
      Array.isArray(window.daily_path)
        ? (window.daily_path as PersonalVolDailyPoint[])
        : [],
    );
    return {
      ...strategy,
      common_window_comparison: {
        period_ids: commonSuccessfulWindows,
        comparable: commonSuccessfulWindows.length > 0,
        metrics: personalVolPerformance(commonPoints, false),
      },
    };
  });
  const executionSummary = strategies.map((strategy) => {
    const successfulWindows = strategy.windows.filter(
      (window) => window.status === "ok",
    ).length;
    const incompleteWindows = strategy.windows.filter(
      (window) => window.status === "incomplete",
    ).length;
    const incompleteIntervals = strategy.windows.reduce(
      (total, window) =>
        total +
        (typeof window.incomplete_intervals === "number"
          ? window.incomplete_intervals
          : 0),
      0,
    );
    const missingLegCount = strategy.windows.reduce(
      (total, window) =>
        total +
        (typeof window.missing_leg_count === "number"
          ? window.missing_leg_count
          : 0),
      0,
    );
    return {
      strategy_id: strategy.strategy_id,
      requested_windows: strategy.windows.length,
      successful_windows: successfulWindows,
      incomplete_windows: incompleteWindows,
      incomplete_intervals: incompleteIntervals,
      missing_leg_count: missingLegCount,
      candidate_status:
        incompleteWindows > 0
          ? "not_evaluated_incomplete_equity_legs"
          : successfulWindows > 0
            ? "evaluated"
            : "not_evaluated",
    };
  });
  const exactFourEvaluationComplete =
    commonSuccessfulWindows.length === PERSONAL_VOL_PERIODS.length;
  const report = {
    schema_version: "personal-vol-ratio-report/v2",
    worker_version: env.MASS_EVAL_VERSION,
    job_id: request.job_id,
    cohort_id: request.cohort_id,
    research_mode: "personal_draft_screening",
    execution_contract: {
      exact_four: true,
      exact_four_evaluation_complete: exactFourEvaluationComplete,
      exact_four_common_window_comparable:
        commonSuccessfulWindows.length > 0,
      common_successful_windows: commonSuccessfulWindows,
      strategy_count: PERSONAL_VOL_STRATEGIES.length,
      hold_sessions: PERSONAL_VOL_HOLD_SESSIONS,
      one_way_cost: PERSONAL_VOL_ONE_WAY_COST,
      cost_method: "two_one_way_costs_amortized_over_fixed_hold",
      signal_lag_sessions: 1,
      execution_timing: "signal_close_d_fill_close_d_plus_1",
      incomplete_equity_leg_policy: "flat_entire_interval_without_cost",
      short_financing: "not_modelled",
      short_financing_limitation: "screening_only",
      market_neutrality: "dollar_balanced_rank_long_short_not_beta_neutral",
      index_etf_hedge: "not_applied_in_this_screen",
      individual_stock_option_volatility_used: false,
      volatility_signal_scope: "nikkei_225_index_options",
      live_orders: false,
      automatic_promotion: false,
      go: false,
    },
    execution_summary: executionSummary,
    data_contract: {
      panels_prefix: PERSONAL_VOL_PANELS_PREFIX,
      periods: PERSONAL_VOL_PERIODS,
      period_count: PERSONAL_VOL_PERIODS.length,
      iv_fields_available_from: PERSONAL_VOL_IV_AVAILABLE_FROM,
      panel_notes: [...panelNotes, ...fixedPrefixNotes],
      source: "existing immutable R2 panel bundle",
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
    automatic_promotion: false,
    live_orders: false,
    go: false,
    not_a_pass: true,
  };
  const artifact = await putImmutableJson(
    env.STRUCTURED_BUCKET,
    "research/personal/vol-ratio-v2/artifacts",
    report,
  );
  const prefix = `research/personal/vol-ratio-v2/job=${request.job_id}`;
  const reportKey = `${prefix}/report.json`;
  const manifestKey = `${prefix}/manifest.json`;
  const manifest = {
    schema_version: "personal-vol-ratio-manifest/v2",
    job_id: request.job_id,
    cohort_id: request.cohort_id,
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
