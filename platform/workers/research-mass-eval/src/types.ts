/**
 * Shared types for research mass-eval worker (W90 / w0816y).
 *
 * Freezes: Mass=NO-GO · READY=false · ops GO=false · continuous paper UNARMED.
 * Does not retune frozen default-path representatives.
 */

export interface Env {
  STRUCTURED_BUCKET: R2Bucket;
  /** Optional D1 tip/history bind for mode=d1_bars (hot window only). */
  DB?: D1Database;
  /** Optional gate for POST /v1/mass-eval (X-Mass-Eval-Token). */
  MASS_EVAL_TOKEN?: string;
  MASS_EVAL_VERSION?: string;
  MASS_EVAL_WAVE?: string;
  MASS_RESEARCH?: string;
  PHASE7?: string;
  READY_DECLARED?: string;
  OPERATIONAL_GO?: string;
  CONTINUOUS_PAPER?: string;
}

/** One logic individual to evaluate (distinct economic thesis preferred). */
export interface LogicSpec {
  logic_id: string;
  family_id?: string;
  strategy_id?: string;
  params?: Record<string, unknown>;
  thesis?: string;
  signal_definition?: string;
  position_rule?: string;
  datasets?: string[];
  /** Optional pre-baked period nets (skip bar path when present). */
  period_nets?: Array<number | null>;
  period_grosses?: Array<number | null>;
}

export interface PeriodSpec {
  period_id: string;
  year?: number;
  period_start?: string;
  period_end?: string;
}

export interface MassEvalRequest {
  seed: number;
  logics: LogicSpec[];
  periods?: PeriodSpec[];
  job_id: string;
  /**
   * synthetic — deterministic PRNG panels (W90 default / smoke)
   * r2_panels — staged COMPLETE-backed panels under panels_prefix or default keys
   * d1_bars — live D1 jquants_records tip extract (hot window only; not multi-year)
   * nets_only — use pre-baked period_nets on each logic
   */
  mode?: "synthetic" | "r2_panels" | "d1_bars" | "nets_only";
  /** Override panel key prefix for r2_panels (default: research/mass_eval/panels). */
  panels_prefix?: string;
  one_way_cost?: number;
  max_codes?: number;
  max_days?: number;
  near_zero_abs?: number;
  min_activation?: number;
}

export type BarSeries = Array<[string, number]>; // [date, close]
export type BarsByCode = Record<string, BarSeries>;

/** Index-level realized-vol series for W91 nky_vol_* logics (date → ann. RV). */
export interface NkyVolSeries {
  source?: string;
  short_n?: number;
  long_n?: number;
  rv_short_by_date?: Record<string, number>;
  rv_long_by_date?: Record<string, number>;
  rv_abs_by_date?: Record<string, number>;
  rv_ratio_by_date?: Record<string, number>;
}

export interface PeriodPanel {
  period_id: string;
  year: number;
  period_start: string;
  period_end: string;
  status: "ok" | "data_missing";
  bars: BarsByCode;
  source: string;
  /** Optional W91 Nikkei/TOPIX realized-vol regime series. */
  nky_vol_series?: NkyVolSeries | null;
}

export interface PeriodEvalRow {
  period_id: string;
  year?: number;
  status: string;
  gross_signed_mean_active: number | null;
  net_one_way_mean_active: number | null;
  amortized_one_way_cost?: number | null;
  n_active_positions?: number | null;
  activation_rate?: number | null;
  hold_days?: number | null;
  signal_id?: string;
  skip_reason?: string;
  error?: string;
}

export interface LogicEvalResult {
  strategy_id: string;
  logic_id: string;
  family_id: string;
  params: Record<string, unknown>;
  thesis?: string;
  status: string;
  n_periods_ok: number;
  n_periods_total: number;
  period_rows: PeriodEvalRow[];
  mean_gross: number | null;
  mean_net: number | null;
  mean_net_inverted: number | null;
  t_stat: number | null;
  t_stat_inverted: number | null;
  sharpe_period: number | null;
  sharpe_period_inverted: number | null;
  chosen_sign: "original" | "inverted" | "reject" | null;
  mean_activation: number | null;
  screen: {
    survived: boolean;
    reject_reasons: string[];
    mean_net: number | null;
    t_stat: number | null;
    sharpe_period: number | null;
    chosen_sign: string | null;
    family_id: string;
    logic_id: string;
    strategy_id: string;
  };
  errors: string[];
  mass_research: string;
  phase7: string;
  ready_declared: boolean;
  operational_go: boolean;
  continuous_paper: string;
  frozen_defaults_retuned: boolean;
}

export interface MassEvalJobResult {
  version: string;
  wave: string;
  job_id: string;
  seed: number;
  mode: string;
  n_logics: number;
  n_periods: number;
  n_eval_ok: number;
  n_eval_fail: number;
  n_survivors: number;
  wall_time_ms: number;
  ranking: Array<Record<string, unknown>>;
  results: LogicEvalResult[];
  r2_keys: Record<string, string>;
  freezes: {
    mass_research: string;
    phase7: string;
    ready_declared: boolean;
    operational_go: boolean;
    continuous_paper: string;
    frozen_defaults_retuned: boolean;
    connected_to_ready: boolean;
    connected_to_mass: boolean;
  };
  note: string;
}
