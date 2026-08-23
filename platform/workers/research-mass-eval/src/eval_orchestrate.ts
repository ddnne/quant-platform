import {
  hasPairwiseLowVarianceArtifact,
  invertNets,
  sampleMean,
  sharpePeriod,
  tStatVsZeroDetail,
} from "./metrics";
import { isPathCollapsedRow } from "./mdh_collapse";
import { evalLogicOnPanel } from "./eval";
import type {
  LogicEvalResult,
  LogicSpec,
  PeriodEvalRow,
  PeriodPanel,
} from "./types";

const DEFAULT_ONE_WAY = 0.001;
const DEFAULT_NEAR_ZERO = 1e-6;
const DEFAULT_MIN_ACTIVATION = 0.02;

function freezeFields() {
  return {
    mass_research: "NO-GO",
    phase7: "OFF",
    ready_declared: false,
    operational_go: false,
    continuous_paper: "UNARMED",
    frozen_defaults_retuned: false,
  };
}

export function evaluateLogicAcrossPeriods(
  logic: LogicSpec,
  panels: PeriodPanel[],
  opts: {
    oneWayCost?: number;
    nearZeroAbs?: number;
    minActivation?: number;
    seed?: number;
    index?: number;
  } = {},
): LogicEvalResult {
  const oneWay = opts.oneWayCost ?? DEFAULT_ONE_WAY;
  const nearZero = opts.nearZeroAbs ?? DEFAULT_NEAR_ZERO;
  const minAct = opts.minActivation ?? DEFAULT_MIN_ACTIVATION;
  const family = String(logic.family_id || logic.logic_id || "multi_day_hold");
  const logicId = String(logic.logic_id || family);
  const sid =
    String(logic.strategy_id || "").trim() ||
    `msf_cf_${String(opts.seed ?? 0).padStart(8, "0")}_${String(opts.index ?? 0).padStart(4, "0")}_${logicId}`;

  const periodRows: PeriodEvalRow[] = [];
  const errors: string[] = [];

  if (
    Array.isArray(logic.period_nets) &&
    logic.period_nets.length > 0 &&
    panels.length === 0
  ) {
    for (let i = 0; i < logic.period_nets.length; i++) {
      const net = logic.period_nets[i];
      const gross = Array.isArray(logic.period_grosses)
        ? logic.period_grosses[i] ?? null
        : net;
      periodRows.push({
        period_id: `p${i}`,
        status: net === null || net === undefined ? "data_missing" : "ok",
        gross_signed_mean_active:
          gross === null || gross === undefined ? null : Number(gross),
        net_one_way_mean_active:
          net === null || net === undefined ? null : Number(net),
        amortized_one_way_cost: oneWay,
      });
    }
  } else {
    for (const panel of panels) {
      const row = evalLogicOnPanel(logic, panel, oneWay);
      if (row.status === "error" && row.error) errors.push(row.error);
      periodRows.push(row);
    }
  }

  const okRows = periodRows.filter((r) => r.status === "ok");
  const grosses = okRows.map((r) => r.gross_signed_mean_active);
  const nets = okRows.map((r) => r.net_one_way_mean_active);
  const costs = okRows.map((r) => r.amortized_one_way_cost ?? null);
  const actRates = okRows
    .map((r) => r.activation_rate)
    .filter((x): x is number => x !== null && x !== undefined && Number.isFinite(x));

  const meanGross = sampleMean(grosses);
  const meanNetOrig = sampleMean(nets);
  const tOrigDetail = tStatVsZeroDetail(nets);
  const tOrig = tOrigDetail.t_stat;
  const sharpeOrig = sharpePeriod(nets);
  const lowVarArtifact =
    tOrigDetail.reason === "low_variance_artifact" ||
    hasPairwiseLowVarianceArtifact(nets);

  const netsInv = invertNets(nets, costs);
  const meanNetInv = sampleMean(netsInv);
  const tInvDetail = tStatVsZeroDetail(netsInv);
  const tInv = tInvDetail.t_stat;
  const sharpeInv = sharpePeriod(netsInv);

  let chosen: "original" | "inverted" | "reject" = "reject";
  const origOk =
    meanNetOrig !== null &&
    Math.abs(meanNetOrig) > nearZero &&
    meanNetOrig > 0 &&
    tOrig !== null;
  const invOk =
    meanNetInv !== null &&
    Math.abs(meanNetInv) > nearZero &&
    meanNetInv > 0 &&
    tInv !== null;
  if (origOk && invOk) {
    chosen = Math.abs(tOrig!) >= Math.abs(tInv!) ? "original" : "inverted";
  } else if (origOk) {
    chosen = "original";
  } else if (invOk) {
    chosen = "inverted";
  } else if (
    meanNetOrig !== null &&
    Math.abs(meanNetOrig) > nearZero &&
    tOrig !== null
  ) {
    chosen = "reject";
  }

  const meanNet = chosen === "inverted" ? meanNetInv : meanNetOrig;
  const tStat = chosen === "inverted" ? tInv : tOrig;
  const sharpe = chosen === "inverted" ? sharpeInv : sharpeOrig;
  const meanActivation = sampleMean(actRates);

  const rejectReasons: string[] = [];
  if (okRows.length < 2) rejectReasons.push("insufficient_periods");
  if (meanNet === null || !Number.isFinite(meanNet) || meanNet <= nearZero) {
    rejectReasons.push("non_positive_mean_net");
  }
  if (tStat === null || !Number.isFinite(tStat) || Math.abs(tStat) < 0.5) {
    rejectReasons.push("weak_t_stat");
  }
  const eventLike =
    family === "event_post" ||
    family.includes("event") ||
    family.includes("surprise") ||
    logicId.startsWith("event_") ||
    logicId.startsWith("surprise_");
  if (
    meanActivation !== null &&
    meanActivation < minAct &&
    !eventLike
  ) {
    rejectReasons.push("low_activation");
  }
  if (chosen === "reject") rejectReasons.push("sign_selection_reject");
  if (lowVarArtifact) rejectReasons.push("inflated_t_low_variance");
  if (periodRows.some((r) => isPathCollapsedRow(r))) {
    rejectReasons.push("path_collapsed_unique_on_period_net");
  }

  const survived = rejectReasons.length === 0;
  const freezes = freezeFields();

  return {
    strategy_id: sid,
    logic_id: logicId,
    family_id: family,
    params: logic.params || {},
    status: errors.length && okRows.length === 0 ? "eval_error" : "ok",
    n_periods_ok: okRows.length,
    n_periods_total: periodRows.length,
    period_rows: periodRows,
    mean_gross: meanGross,
    mean_net: meanNet,
    mean_net_inverted: meanNetInv,
    t_stat: tStat,
    t_stat_inverted: tInv,
    t_stat_reason: tOrigDetail.reason,
    raw_t_stat: tOrigDetail.raw_t_stat,
    low_variance_artifact: lowVarArtifact,
    sharpe_period: sharpe,
    sharpe_period_inverted: sharpeInv,
    chosen_sign: chosen,
    mean_activation: meanActivation,
    screen: {
      survived,
      screen_kind: "period_net",
      daily_path_complete: false,
      candidate_grade: false,
      n_survivors_are_not_a_pass: true,
      reject_reasons: rejectReasons,
      mean_net: meanNet,
      t_stat: tStat,
      sharpe_period: sharpe,
      chosen_sign: chosen,
      family_id: family,
      logic_id: logicId,
      strategy_id: sid,
      low_variance_artifact: lowVarArtifact,
      t_stat_reason: tOrigDetail.reason,
      raw_t_stat: tOrigDetail.raw_t_stat,
    },
    errors,
    ...freezes,
  };
}

export function rankSurvivors(results: LogicEvalResult[]): Array<Record<string, unknown>> {
  const survivors = results.filter((r) => r.screen?.survived);
  survivors.sort((a, b) => {
    const ta = a.t_stat !== null && Number.isFinite(a.t_stat) ? Math.abs(a.t_stat) : -1;
    const tb = b.t_stat !== null && Number.isFinite(b.t_stat) ? Math.abs(b.t_stat) : -1;
    if (tb !== ta) return tb - ta;
    const ma = a.mean_net ?? -1e9;
    const mb = b.mean_net ?? -1e9;
    return mb - ma;
  });
  return survivors.map((s, i) => ({
    rank: i + 1,
    strategy_id: s.strategy_id,
    logic_id: s.logic_id,
    family_id: s.family_id,
    mean_net: s.mean_net,
    t_stat: s.t_stat,
    sharpe_period: s.sharpe_period,
    chosen_sign: s.chosen_sign,
    mean_activation: s.mean_activation,
    screen_kind: "period_net",
    daily_path_complete: false,
    candidate_grade: false,
    n_survivors_are_not_a_pass: true,
  }));
}
