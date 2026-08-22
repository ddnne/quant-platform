export interface Env {
  STRUCTURED_BUCKET: R2Bucket;
  DB?: D1Database;
  MASS_EVAL_TOKEN?: string;
  MASS_EVAL_VERSION?: string;
  MASS_EVAL_WAVE?: string;
  MASS_RESEARCH?: string;
  PHASE7?: string;
  READY_DECLARED?: string;
  OPERATIONAL_GO?: string;
  CONTINUOUS_PAPER?: string;
}

export interface LogicSpec {
  logic_id: string;
  family_id?: string;
  strategy_id?: string;
  params?: Record<string, unknown>;
  /** Pre-baked period nets skip the bar path when present. */
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
  mode?: "synthetic" | "r2_panels" | "d1_bars" | "nets_only";
  eval_kind?: "screen" | "daily_path";
  /** Fan-out shards skip R2 writes; the driver aggregates. */
  write_artifacts?: boolean;
  panels_prefix?: string;
  one_way_cost?: number;
  max_codes?: number;
  max_days?: number;
  near_zero_abs?: number;
  min_activation?: number;
}

export type BarSeries = Array<[string, number]>; // [date, close]
export type BarsByCode = Record<string, BarSeries>;

export interface NkyVolSeries {
  source?: string;
  short_n?: number;
  long_n?: number;
  rv_short_by_date?: Record<string, number>;
  rv_long_by_date?: Record<string, number>;
  rv_abs_by_date?: Record<string, number>;
  rv_ratio_by_date?: Record<string, number>;
}

export interface Opt225RegimeSeries extends NkyVolSeries {
  series_kind?: string;
  units?: string;
  dataset?: string;
}

export interface Opt225RegimeBundle {
  spread_convention?: string;
  skew_convention?: string;
  cm_term_convention?: string;
  basevol_delta_convention?: string;
  units?: string;
  dataset?: string;
  version?: string;
  basevol?: Opt225RegimeSeries | null;
  atm_iv?: Opt225RegimeSeries | null;
  spread?: Opt225RegimeSeries | null;
  spread_change?: Opt225RegimeSeries | null;
  skew?: Opt225RegimeSeries | null;
  cm_term?: Opt225RegimeSeries | null;
  basevol_delta?: Opt225RegimeSeries | null;
}

export interface RepoRateRegime {
  dataset?: string;
  status?: string;
  units?: string;
  rates_by_date?: Record<string, number>;
  rate_by_date?: Record<string, number>;
  spread_by_date?: Record<string, number>;
  n_rates?: number;
  n_obs?: number;
  short_tenor?: string;
  long_tenor?: string;
}

export interface CalendarSideCar {
  dataset?: string;
  hol_div_by_date?: Record<string, string>;
  n_dates?: number;
  n_trading_dates?: number;
  dates?: string[];
}

export interface FlowRegime {
  dataset_margin?: string;
  dataset_short?: string;
  status?: string;
  margin_level_by_code?: Record<string, Record<string, number>>;
  margin_change_by_code?: Record<string, Record<string, number>>;
  short_ratio_by_date?: Record<string, number>;
  short_section?: string;
  n_codes?: number;
  n_obs?: number;
  n_short_obs?: number;
}

export interface FundRegime {
  dataset?: string;
  status?: string;
  events_by_code?: Record<
    string,
    Array<{
      disc_date?: string;
      disc_time?: string | null;
      eps?: number | null;
      feps?: number | null;
      prior_eps?: number | null;
      bps?: number | null;
      roe?: number | null;
      div_ann?: number | null;
      np?: number | null;
      sales?: number | null;
      eq?: number | null;
      ta?: number | null;
      eq_ar?: number | null;
      prior_ta?: number | null;
    }>
  >;
  n_codes?: number;
  n_events?: number;
}

export interface PeriodPanel {
  period_id: string;
  year: number;
  period_start: string;
  period_end: string;
  status: "ok" | "data_missing";
  bars: BarsByCode;
  source: string;
  nky_vol_series?: NkyVolSeries | null;
  opt225_regime?: Opt225RegimeBundle | null;
  base_vol_series?: Record<string, number> | null;
  atm_iv_series?: Record<string, number> | null;
  iv_base_spread?: Record<string, number> | null;
  skew_series?: Record<string, number> | null;
  cm_term_series?: Record<string, number> | null;
  basevol_delta_series?: Record<string, number> | null;
  repo_rate_regime?: RepoRateRegime | null;
  repo_rate_by_date?: Record<string, number> | null;
  calendar?: CalendarSideCar | null;
  flow_regime?: FlowRegime | null;
  fund_regime?: FundRegime | null;
  /** Missing ADV → tx+repo only. */
  adv_by_code?: Record<string, number> | null;
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
  path_collapsed?: boolean;
  error?: string;
}

export interface LogicEvalResult {
  strategy_id: string;
  logic_id: string;
  family_id: string;
  params: Record<string, unknown>;
  status: string;
  n_periods_ok: number;
  n_periods_total: number;
  period_rows: PeriodEvalRow[];
  mean_gross: number | null;
  mean_net: number | null;
  mean_net_inverted: number | null;
  t_stat: number | null;
  t_stat_inverted: number | null;
  t_stat_reason?: string;
  raw_t_stat?: number | null;
  low_variance_artifact?: boolean;
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
    low_variance_artifact?: boolean;
    t_stat_reason?: string;
    raw_t_stat?: number | null;
    screen_kind?: string;
    daily_path_complete?: boolean;
    candidate_grade?: boolean;
    n_survivors_are_not_a_pass?: boolean;
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
  n_survivors_are_not_a_pass?: boolean;
  screen_kind?: string;
  daily_path_complete?: boolean;
  candidate_grade?: boolean;
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
