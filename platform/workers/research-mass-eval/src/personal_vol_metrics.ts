export type PersonalVolDailyPoint = {
  date: string;
  gross_return?: number;
  cost_return?: number;
  turnover_one_way?: number;
  invalid_equity_observations?: number;
  fill_count?: number;
  net_return: number;
  equity: number;
};

export type PersonalVolPerformance = {
  schema_version: "personal-performance/v1";
  periods_per_year: 252;
  series_contiguity: "contiguous_window" | "non_contiguous_window_stitch";
  cagr_applicable: boolean;
  sessions: number;
  active_sessions: number;
  n_sessions: number;
  n_nonzero_sessions: number;
  n_months: number;
  net_total_return: number | null;
  total_return_net: number | null;
  cagr: number | null;
  annualized_volatility: number | null;
  annualized_downside_deviation: number | null;
  annualized_sharpe: number | null;
  annualized_sortino: number | null;
  max_drawdown: number | null;
  max_drawdown_duration_sessions: number | null;
  recovery_sessions: number | null;
  max_drawdown_recovery_sessions: number | null;
  recovered: boolean | null;
  max_drawdown_recovered: boolean | null;
  calmar: number | null;
  calmar_ratio: number | null;
  daily_hit_rate: number | null;
  positive_day_rate: number | null;
  positive_active_day_rate: number | null;
  flat_day_rate: number | null;
  monthly_hit_rate: number | null;
  positive_month_rate: number | null;
  best_day: number | null;
  best_day_return: number | null;
  worst_day: number | null;
  worst_day_return: number | null;
  best_month_return: number | null;
  worst_month_return: number | null;
  historical_var_95_loss: number | null;
  daily_value_at_risk_95: number | null;
  historical_cvar_95_loss: number | null;
  daily_conditional_value_at_risk_95: number | null;
  monthly_observations: number;
  starting_capital: 1;
  estimated_total_return_pre_cost_additive: number | null;
  pre_cost_estimate_basis: string;
  cost_amount: number;
  cost_return: number;
  turnover_one_way_amount: number;
  turnover_one_way_ratio: number;
  turnover_one_way_annualized_ratio: number | null;
  fill_count: number | null;
  round_trip_trade_metrics: {
    status: "UNAVAILABLE";
    trade_win_rate: null;
    profit_factor: null;
    reason: string;
  };
  invalid_equity_observations: number;
  year_metrics: Array<Record<string, unknown>>;
  hit_rate_basis: "strictly_positive_among_nonzero_returns";
  var_convention: "positive_loss_from_empirical_left_tail";
};

function finite(values: number[]): number[] {
  return values.filter((value) => Number.isFinite(value));
}

function mean(values: number[]): number | null {
  const clean = finite(values);
  if (!clean.length) return null;
  return clean.reduce((total, value) => total + value, 0) / clean.length;
}

function sampleStd(values: number[]): number | null {
  const clean = finite(values);
  if (clean.length < 2) return null;
  const average = mean(clean);
  if (average === null) return null;
  const variance =
    clean.reduce((total, value) => total + (value - average) ** 2, 0) /
    (clean.length - 1);
  return Math.sqrt(Math.max(0, variance));
}

function quantile(values: number[], probability: number): number | null {
  const sorted = finite(values).sort((left, right) => left - right);
  if (!sorted.length) return null;
  if (sorted.length === 1) return sorted[0];
  const index = Math.max(0, Math.min(1, probability)) * (sorted.length - 1);
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  if (lower === upper) return sorted[lower];
  const weight = index - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function compoundedReturn(values: number[]): number | null {
  const clean = finite(values);
  if (!clean.length) return null;
  let wealth = 1;
  for (const value of clean) wealth *= 1 + value;
  return wealth - 1;
}

function monthlyReturns(points: PersonalVolDailyPoint[]): number[] {
  const byMonth = new Map<string, number[]>();
  for (const point of points) {
    if (!Number.isFinite(point.net_return)) continue;
    const month = point.date.slice(0, 7);
    const values = byMonth.get(month) || [];
    values.push(point.net_return);
    byMonth.set(month, values);
  }
  const out: number[] = [];
  for (const values of byMonth.values()) {
    const compounded = compoundedReturn(values);
    if (compounded !== null) out.push(compounded);
  }
  return out;
}

function drawdown(values: number[]): {
  maxDrawdown: number | null;
  duration: number | null;
  recovery: number | null;
  recovered: boolean | null;
} {
  const clean = finite(values);
  if (!clean.length) {
    return {
      maxDrawdown: null,
      duration: null,
      recovery: null,
      recovered: null,
    };
  }
  const equity = [1];
  for (const value of clean) equity.push(equity[equity.length - 1] * (1 + value));
  let peak = equity[0];
  let peakIndex = 0;
  let worst = 0;
  let troughIndex = 0;
  let worstPeakIndex = 0;
  for (let index = 1; index < equity.length; index += 1) {
    if (equity[index] > peak) {
      peak = equity[index];
      peakIndex = index;
    }
    if (peak <= 0) continue;
    const current = equity[index] / peak - 1;
    if (current < worst) {
      worst = current;
      troughIndex = index;
      worstPeakIndex = peakIndex;
    }
  }
  if (worst === 0) {
    return { maxDrawdown: 0, duration: 0, recovery: 0, recovered: true };
  }
  const peakEquity = equity[worstPeakIndex];
  let recovery: number | null = null;
  for (let index = troughIndex + 1; index < equity.length; index += 1) {
    if (equity[index] >= peakEquity) {
      recovery = index - troughIndex;
      break;
    }
  }
  return {
    maxDrawdown: worst,
    duration: troughIndex - worstPeakIndex,
    recovery,
    recovered: recovery !== null,
  };
}

export function personalVolPerformance(
  points: PersonalVolDailyPoint[],
  contiguous: boolean,
  includeYearMetrics = true,
): PersonalVolPerformance {
  const returns = finite(points.map((point) => point.net_return));
  const nonzero = returns.filter((value) => value !== 0);
  const months = monthlyReturns(points);
  const totalReturn = compoundedReturn(returns);
  const average = mean(returns);
  const standardDeviation = sampleStd(returns);
  const annualizedVolatility =
    standardDeviation === null ? null : standardDeviation * Math.sqrt(252);
  const annualizedSharpe =
    average === null || standardDeviation === null || standardDeviation === 0
      ? null
      : (average / standardDeviation) * Math.sqrt(252);
  const downsideDeviation = returns.length
    ? Math.sqrt(
        returns.reduce(
          (total, value) => total + Math.min(0, value) ** 2,
          0,
        ) / returns.length,
      )
    : null;
  const annualizedDownsideDeviation =
    downsideDeviation === null ? null : downsideDeviation * Math.sqrt(252);
  const annualizedSortino =
    average === null || downsideDeviation === null || downsideDeviation === 0
      ? null
      : (average / downsideDeviation) * Math.sqrt(252);
  const dd = drawdown(returns);
  let cagr: number | null = null;
  if (contiguous && totalReturn !== null && totalReturn > -1 && returns.length) {
    cagr = (1 + totalReturn) ** (252 / returns.length) - 1;
  }
  const calmar =
    cagr === null || dd.maxDrawdown === null || dd.maxDrawdown === 0
      ? null
      : cagr / Math.abs(dd.maxDrawdown);
  const q05 = quantile(returns, 0.05);
  const tail = q05 === null ? [] : returns.filter((value) => value <= q05);
  const tailMean = mean(tail);
  const positiveDayRate = returns.length
    ? returns.filter((value) => value > 0).length / returns.length
    : null;
  const positiveActiveDayRate = nonzero.length
    ? nonzero.filter((value) => value > 0).length / nonzero.length
    : null;
  const positiveMonthRate = months.length
    ? months.filter((value) => value > 0).length / months.length
    : null;
  const bestDay = returns.length ? Math.max(...returns) : null;
  const worstDay = returns.length ? Math.min(...returns) : null;
  const bestMonth = months.length ? Math.max(...months) : null;
  const worstMonth = months.length ? Math.min(...months) : null;
  const var95 = q05 === null ? null : Math.max(0, -q05);
  const cvar95 = tailMean === null ? null : Math.max(0, -tailMean);
  const costReturn = points.reduce(
    (total, point) =>
      total + (Number.isFinite(point.cost_return) ? Number(point.cost_return) : 0),
    0,
  );
  const turnoverRatio = points.reduce(
    (total, point) =>
      total +
      (Number.isFinite(point.turnover_one_way)
        ? Number(point.turnover_one_way)
        : 0),
    0,
  );
  const invalidEquityObservations = points.reduce((total, point) => {
    const count = point.invalid_equity_observations;
    return total +
      (Number.isFinite(count) && Number(count) > 0
        ? Math.trunc(Number(count))
        : 0);
  }, 0);
  const fillCount = points.reduce((total, point) => {
    const count = point.fill_count;
    return total +
      (Number.isFinite(count) && Number(count) > 0
        ? Math.trunc(Number(count))
        : 0);
  }, 0);
  const reportedFillCount = points.some((point) => Number.isFinite(point.fill_count))
    ? fillCount
    : null;
  const yearMetrics: Array<Record<string, unknown>> = [];
  if (includeYearMetrics) {
    const byYear = new Map<string, PersonalVolDailyPoint[]>();
    for (const point of points) {
      const year = point.date.slice(0, 4);
      if (!/^\d{4}$/.test(year)) continue;
      const values = byYear.get(year) || [];
      values.push(point);
      byYear.set(year, values);
    }
    for (const [year, values] of [...byYear.entries()].sort()) {
      yearMetrics.push({
        year: Number(year),
        ...personalVolPerformance(values, true, false),
      });
    }
  }
  return {
    schema_version: "personal-performance/v1",
    periods_per_year: 252,
    series_contiguity: contiguous
      ? "contiguous_window"
      : "non_contiguous_window_stitch",
    cagr_applicable: contiguous,
    sessions: returns.length,
    active_sessions: nonzero.length,
    n_sessions: returns.length,
    n_nonzero_sessions: nonzero.length,
    n_months: months.length,
    net_total_return: totalReturn,
    total_return_net: totalReturn,
    cagr,
    annualized_volatility: annualizedVolatility,
    annualized_downside_deviation: annualizedDownsideDeviation,
    annualized_sharpe: annualizedSharpe,
    annualized_sortino: annualizedSortino,
    max_drawdown:
      dd.maxDrawdown === null ? null : Math.abs(dd.maxDrawdown),
    max_drawdown_duration_sessions: dd.duration,
    recovery_sessions: dd.recovery,
    max_drawdown_recovery_sessions: dd.recovery,
    recovered: dd.recovered,
    max_drawdown_recovered: dd.recovered,
    calmar,
    calmar_ratio: calmar,
    daily_hit_rate: positiveActiveDayRate,
    positive_day_rate: positiveDayRate,
    positive_active_day_rate: positiveActiveDayRate,
    flat_day_rate:
      returns.length
        ? returns.filter((value) => value === 0).length / returns.length
        : null,
    monthly_hit_rate: positiveMonthRate,
    positive_month_rate: positiveMonthRate,
    best_day: bestDay,
    best_day_return: bestDay,
    worst_day: worstDay,
    worst_day_return: worstDay,
    best_month_return: bestMonth,
    worst_month_return: worstMonth,
    historical_var_95_loss: var95,
    daily_value_at_risk_95: var95,
    historical_cvar_95_loss: cvar95,
    daily_conditional_value_at_risk_95: cvar95,
    monthly_observations: months.length,
    starting_capital: 1,
    estimated_total_return_pre_cost_additive:
      totalReturn === null ? null : totalReturn + costReturn,
    pre_cost_estimate_basis:
      "net total return plus additive amortized cost; descriptive, not a counterfactual zero-cost equity path",
    cost_amount: costReturn,
    cost_return: costReturn,
    turnover_one_way_amount: turnoverRatio,
    turnover_one_way_ratio: turnoverRatio,
    turnover_one_way_annualized_ratio:
      returns.length === 0 ? null : (turnoverRatio * 252) / returns.length,
    fill_count: reportedFillCount,
    round_trip_trade_metrics: {
      status: "UNAVAILABLE",
      trade_win_rate: null,
      profit_factor: null,
      reason:
        "the bar-native screen records a portfolio path, not immutable execution fills or closed round trips",
    },
    invalid_equity_observations: invalidEquityObservations,
    year_metrics: yearMetrics,
    hit_rate_basis: "strictly_positive_among_nonzero_returns",
    var_convention: "positive_loss_from_empirical_left_tail",
  };
}
