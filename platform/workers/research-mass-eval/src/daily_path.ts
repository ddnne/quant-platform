import { classifyControlledStrategy } from "./controlled_strategy_policy";
import { barNativeHeldBook } from "./eval";
import { pitEventEntryShift } from "./event_entry";
import { sharpePeriod, tStatVsZero } from "./metrics";
import { isPathBroken } from "./path_broken";
import type { BarsByCode, LogicSpec, PeriodPanel } from "./types";

type HeldBook = Record<string, Record<string, number>>;

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function positiveInt(value: unknown, fallback: number): number {
  if (!finite(value)) return fallback;
  return Math.max(1, Math.floor(value));
}

function unionDates(bars: BarsByCode): string[] {
  const dates = new Set<string>();
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__")) continue;
    for (const [date] of pairs || []) dates.add(String(date).slice(0, 10));
  }
  return Array.from(dates).sort();
}

function closeByMap(bars: BarsByCode): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const [code, pairs] of Object.entries(bars || {})) {
    if (code.startsWith("__")) continue;
    out[code] = {};
    for (const [date, close] of pairs || []) {
      if (finite(close)) out[code][String(date).slice(0, 10)] = close;
    }
  }
  return out;
}

export function equityPathDrawdown(
  equities: number[],
  dates: string[],
): {
  max_dd: number | null;
  abs_max_dd: number | null;
  dd_duration_days: number | null;
  recovery_days: number | null;
  recovered: boolean | null;
  total_return: number | null;
  n: number;
  method: string;
} {
  if (!equities.length || equities.length !== dates.length) {
    return {
      max_dd: null,
      abs_max_dd: null,
      dd_duration_days: null,
      recovery_days: null,
      recovered: null,
      total_return: null,
      n: 0,
      method: "daily_equity_level_peak_to_trough",
    };
  }
  let peak = equities[0];
  let peakIndex = 0;
  let maxDrawdown = 0;
  let troughIndex = 0;
  let peakAtDrawdown = 0;
  for (let index = 0; index < equities.length; index += 1) {
    const equity = equities[index];
    if (equity > peak) {
      peak = equity;
      peakIndex = index;
    }
    if (peak <= 0) continue;
    const drawdown = equity / peak - 1;
    if (drawdown < maxDrawdown) {
      maxDrawdown = drawdown;
      troughIndex = index;
      peakAtDrawdown = peakIndex;
    }
  }
  const duration = maxDrawdown < 0 ? troughIndex - peakAtDrawdown : 0;
  let recoveryDays: number | null = null;
  let recovered = maxDrawdown >= 0;
  if (maxDrawdown < 0) {
    const priorPeak = equities[peakAtDrawdown];
    for (let index = troughIndex + 1; index < equities.length; index += 1) {
      if (equities[index] >= priorPeak - 1e-15) {
        recoveryDays = index - troughIndex;
        recovered = true;
        break;
      }
    }
  }
  return {
    max_dd: maxDrawdown,
    abs_max_dd: Math.abs(maxDrawdown),
    dd_duration_days: duration,
    recovery_days: recoveryDays,
    recovered,
    total_return:
      equities[0] !== 0 ? equities[equities.length - 1] / equities[0] - 1 : null,
    n: equities.length,
    method: "daily_equity_level_peak_to_trough",
  };
}

function disclosureEventHeld(
  panel: PeriodPanel,
  holdDays: number,
): { held: HeldBook; fallback?: string } {
  const eventsByCode = panel.fund_regime?.events_by_code;
  if (!eventsByCode || !Object.keys(eventsByCode).length) {
    return { held: {}, fallback: "path_broken_missing_disclosure_events" };
  }
  const held: HeldBook = {};
  let entries = 0;
  for (const [code, pairs] of Object.entries(panel.bars || {})) {
    if (code.startsWith("__") || !pairs?.length) continue;
    const dates = pairs.map(([date]) => String(date).slice(0, 10));
    held[code] = {};
    for (const event of eventsByCode[code] || []) {
      const disclosureDate = String(event.disc_date || "").slice(0, 10);
      if (!disclosureDate) continue;
      const firstAvailable = dates.findIndex((date) => date >= disclosureDate);
      if (firstAvailable < 0) continue;
      const sameSession = dates[firstAvailable] === disclosureDate;
      const entryIndex =
        firstAvailable +
        (sameSession ? pitEventEntryShift(event.disc_time) : 0);
      if (entryIndex >= dates.length) continue;
      entries += 1;
      for (
        let index = entryIndex;
        index < Math.min(dates.length, entryIndex + holdDays);
        index += 1
      ) {
        held[code][dates[index]] = 1;
      }
    }
  }
  if (entries === 0) {
    return { held, fallback: "path_broken_no_pit_disclosure_entries" };
  }
  return { held };
}

function heldBookDailyMtm(
  held: HeldBook,
  closeBy: Record<string, Record<string, number>>,
  dates: string[],
  holdDays: number,
  oneWay: number,
  repoByDate?: Record<string, number>,
  advByCode?: Record<string, number>,
): {
  dates: string[];
  net_daily: number[];
  occupancy: number | null;
  n_gate_on: number;
  cost_adv_incomplete: boolean;
} {
  if (dates.length < 2) {
    return {
      dates: [],
      net_daily: [],
      occupancy: null,
      n_gate_on: 0,
      cost_adv_incomplete: false,
    };
  }
  const amortizedRoundTripCost = (2 * oneWay) / Math.max(1, holdDays);
  const netDaily: number[] = [0];
  let activeDays = 0;
  let costAdvIncomplete = false;
  for (let index = 1; index < dates.length; index += 1) {
    const previous = dates[index - 1];
    const current = dates[index];
    const contributions: number[] = [];
    const liquidityMultipliers: number[] = [];
    let shortPositions = 0;
    for (const [code, positions] of Object.entries(held)) {
      const position = positions[previous];
      if (!position) continue;
      const adv = advByCode?.[code];
      if (!finite(adv)) {
        costAdvIncomplete = true;
        continue;
      }
      const before = closeBy[code]?.[previous];
      const after = closeBy[code]?.[current];
      if (!finite(before) || !finite(after) || before === 0) continue;
      contributions.push(position * (after / before - 1));
      if (position < 0) shortPositions += 1;
      liquidityMultipliers.push(adv >= 1e9 ? 1 : adv >= 1e8 ? 1.5 : 2.5);
    }
    if (!contributions.length) {
      netDaily.push(0);
      continue;
    }
    const gross =
      contributions.reduce((total, value) => total + value, 0) /
      contributions.length;
    const liquidity =
      liquidityMultipliers.reduce((total, value) => total + value, 0) /
      liquidityMultipliers.length;
    const repo = repoByDate?.[previous];
    const shortDrag =
      shortPositions > 0 && finite(repo)
        ? (shortPositions / contributions.length) * (repo / 100 / 252) * liquidity
        : 0;
    netDaily.push(gross - amortizedRoundTripCost * liquidity - shortDrag);
    activeDays += 1;
  }
  return {
    dates,
    net_daily: netDaily,
    occupancy: activeDays / (dates.length - 1),
    n_gate_on: activeDays,
    cost_adv_incomplete: costAdvIncomplete,
  };
}

function incompletePack(
  panel: PeriodPanel,
  reason: string,
): Record<string, unknown> {
  return {
    period_id: panel.period_id,
    year: panel.year,
    status: "unsupported_strategy",
    daily_path_complete: false,
    skip_reason: reason,
    eval_path: "controlled_exact_four",
    path_fallback: `path_broken_${reason}`,
  };
}

export function evalLogicDailyPathOnPanel(
  logic: LogicSpec,
  panel: PeriodPanel,
  oneWay: number,
): Record<string, unknown> {
  const classification = classifyControlledStrategy(logic);
  if (!classification.ok) return incompletePack(panel, classification.reason);
  if (panel.status !== "ok" || !panel.bars || !Object.keys(panel.bars).length) {
    return {
      period_id: panel.period_id,
      year: panel.year,
      status: "data_missing",
      daily_path_complete: false,
      skip_reason: "empty_or_missing_bars",
      eval_path: `controlled:${classification.kind}`,
      path_fallback: "path_broken_empty_or_missing_bars",
    };
  }

  const params = logic.params || {};
  const defaultHold = classification.kind === "event" ? 5 : 10;
  const holdDays = positiveInt(
    params.hold_days ?? params.post_hold_days,
    defaultHold,
  );
  let held: HeldBook;
  let evalPath: string;
  let pathFallback: string | undefined;
  if (classification.kind === "event") {
    const event = disclosureEventHeld(panel, holdDays);
    held = event.held;
    evalPath = "controlled:event_post";
    pathFallback = event.fallback;
  } else {
    const native = barNativeHeldBook(
      { ...logic, family_id: classification.family_id },
      panel,
    );
    if (!native) return incompletePack(panel, "closed_interpreter_unavailable");
    held = native.held;
    evalPath = `controlled:${classification.kind}:${native.path}`;
    pathFallback = native.fallback;
  }

  const dates = unionDates(panel.bars);
  const path = heldBookDailyMtm(
    held,
    closeByMap(panel.bars),
    dates,
    holdDays,
    oneWay,
    panel.repo_rate_regime?.rates_by_date ||
      panel.repo_rate_regime?.rate_by_date ||
      panel.repo_rate_by_date ||
      undefined,
    panel.adv_by_code || undefined,
  );
  if (path.net_daily.length < 2) {
    return {
      period_id: panel.period_id,
      year: panel.year,
      status: "insufficient_dates",
      daily_path_complete: false,
      skip_reason: "insufficient_dates",
      eval_path: evalPath,
      path_fallback: pathFallback || "path_broken_insufficient_dates",
    };
  }

  if (!pathFallback && path.cost_adv_incomplete) {
    pathFallback = "path_broken_missing_adv";
  }
  if (!pathFallback && path.n_gate_on === 0) {
    pathFallback = "path_broken_no_positions";
  }
  let equity = 1;
  const equities = path.net_daily.map((daily, index) => {
    if (index === 0) return equity;
    equity *= 1 + daily;
    return equity;
  });
  const drawdown = equityPathDrawdown(equities, path.dates);
  const complete =
    !isPathBroken(evalPath, pathFallback) &&
    !path.cost_adv_incomplete &&
    path.n_gate_on > 0 &&
    drawdown.max_dd !== null &&
    drawdown.dd_duration_days !== null &&
    drawdown.recovered !== null &&
    drawdown.total_return !== null;
  const nets = path.net_daily.slice(1);
  return {
    period_id: panel.period_id,
    year: panel.year,
    status: "ok",
    logic_id: classification.logic_id,
    window_id: panel.period_id,
    dates: path.dates,
    net_daily: path.net_daily,
    occupancy_frac: path.occupancy,
    occupancy: path.occupancy,
    n_gate_on_days: path.n_gate_on,
    cost_adv_incomplete: path.cost_adv_incomplete,
    n_days: path.dates.length,
    daily_path_DD: drawdown.max_dd,
    total_ret_net: drawdown.total_return,
    dd_duration: drawdown.dd_duration_days,
    recovered: drawdown.recovered,
    recovery_days: drawdown.recovery_days,
    t_stat: tStatVsZero(nets),
    sharpe_daily: sharpePeriod(nets),
    eval_path: evalPath,
    path_fallback: pathFallback || null,
    daily_path_complete: complete,
    method: drawdown.method,
    survived: false,
    promote_as_main: false,
    go: false,
    candidate_grade: false,
    period_net_dd_only_pass_forbidden: true,
  };
}

export function cellsFromPeriodPacks(
  logicId: string,
  packs: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  return packs.map((pack) => {
    if (pack.status !== "ok") {
      return {
        logic_id: logicId,
        window: pack.period_id || pack.window_id,
        window_id: pack.period_id || pack.window_id,
        daily_path_complete: false,
        survived: false,
        promote_as_main: false,
        go: false,
        incomplete_reason: pack.skip_reason || pack.status,
        eval_path: pack.eval_path || "controlled_exact_four",
        path_fallback: pack.path_fallback || "path_broken_incomplete",
        period_net_dd_only_pass_forbidden: true,
      };
    }
    return {
      logic_id: logicId,
      window: pack.window_id || pack.period_id,
      window_id: pack.window_id || pack.period_id,
      daily_path_DD: pack.daily_path_DD,
      total_ret_net: pack.total_ret_net,
      occupancy_frac: pack.occupancy_frac,
      occupancy: pack.occupancy_frac,
      dates: pack.dates,
      net_daily: pack.net_daily,
      dd_duration: pack.dd_duration,
      recovered: pack.recovered,
      recovery_days: pack.recovery_days,
      n_days: pack.n_days,
      t_stat: pack.t_stat,
      sharpe_daily: pack.sharpe_daily,
      eval_path: pack.eval_path,
      path_fallback: pack.path_fallback ?? null,
      cost_adv_incomplete: pack.cost_adv_incomplete,
      daily_path_complete:
        Boolean(pack.daily_path_complete) &&
        !isPathBroken(pack.eval_path, pack.path_fallback),
      survived: false,
      promote_as_main: false,
      go: false,
      candidate_grade: false,
      period_net_dd_only_pass_forbidden: true,
      method: pack.method,
    };
  });
}
