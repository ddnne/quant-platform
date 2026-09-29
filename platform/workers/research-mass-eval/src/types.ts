import type { JquantsAcquisitionRpc } from "../../ingestion-secrets/src/jquants_acquisition_types";
import type { GatewayRpc } from "../../research-ai-gateway/src/gateway_rpc";
import type { ReceiptProductBytesRpc } from "../../ingestion-premium/src/receipt_product_bytes_rpc";
import type { PilotReadyPublicationRpc } from "../../ingestion-premium/src/pilot_ready_publication_rpc";
import type { PersonalResearchContainer } from "./personal_research_container";

/** Generated bindings with typed Gateway RPC; secrets stay string-only. */
export type Env = Omit<
  Cloudflare.Env,
  | "AI_GATEWAY"
  | "JQUANTS_ACQUISITION"
  | "INGESTION_PREMIUM"
  | "PILOT_READY_PUBLICATION"
> & {
  AI_GATEWAY?: GatewayRpc;
  JQUANTS_ACQUISITION?: JquantsAcquisitionRpc;
  INGESTION_PREMIUM?: ReceiptProductBytesRpc;
  PILOT_READY_PUBLICATION?: PilotReadyPublicationRpc;
  MASS_EVAL_TOKEN?: string;
  PERSONAL_RESEARCH_CONTAINER?: DurableObjectNamespace<PersonalResearchContainer>;
  D1_BACKUP_EXPORT_BUNDLE?: string;
  D1_BACKUP_KEY?: string;
};

export interface LogicSpec {
  logic_id: string;
  family_id?: string;
  strategy_id?: string;
  params?: Record<string, unknown>;
  period_nets?: Array<number | null>;
  period_grosses?: Array<number | null>;
}

export interface PeriodSpec {
  period_id: string;
  year?: number;
  period_start?: string;
  period_end?: string;
}

export type BarSeries = Array<[string, number]>;
export type BarsByCode = Record<string, BarSeries>;

export interface NkyVolSeries {
  rv_short_by_date?: Record<string, number>;
  rv_long_by_date?: Record<string, number>;
  rv_abs_by_date?: Record<string, number>;
  rv_ratio_by_date?: Record<string, number>;
}

export interface Opt225RegimeBundle {
  dataset?: string;
  version?: string;
  source?: {
    dataset?: string;
    version?: string;
  } | null;
  basevol?: NkyVolSeries | null;
  atm_iv?: NkyVolSeries | null;
  spread?: NkyVolSeries | null;
  spread_change?: NkyVolSeries | null;
  skew?: NkyVolSeries | null;
  cm_term?: NkyVolSeries | null;
  cm_term_ratio?: NkyVolSeries | null;
  basevol_delta?: NkyVolSeries | null;
}

export interface IndexProxyIdentity {
  dataset?: string;
  label?: string;
  role?: string;
  note?: string;
}

export interface RepoRateRegime {
  status?: string;
  rates_by_date?: Record<string, number>;
  rate_by_date?: Record<string, number>;
  spread_by_date?: Record<string, number>;
}

export interface CalendarSideCar {
  hol_div_by_date?: Record<string, string>;
}

export interface FlowRegime {
  status?: string;
  margin_level_by_code?: Record<string, Record<string, number>>;
  margin_change_by_code?: Record<string, Record<string, number>>;
  short_ratio_by_date?: Record<string, number>;
}

export interface FundRegime {
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
}

export interface PeriodPanel {
  period_id: string;
  year: number;
  period_start: string;
  period_end: string;
  status: "ok" | "data_missing";
  bars: BarsByCode;
  source: string;
  index_proxy?: IndexProxyIdentity | null;
  nky_vol_series?: NkyVolSeries | null;
  opt225_regime?: Opt225RegimeBundle | null;
  base_vol_series?: Record<string, number> | null;
  atm_iv_series?: Record<string, number> | null;
  iv_base_spread?: Record<string, number> | null;
  skew_series?: Record<string, number> | null;
  cm_term_series?: Record<string, number> | null;
  cm_term_ratio_series?: Record<string, number> | null;
  basevol_delta_series?: Record<string, number> | null;
  repo_rate_regime?: RepoRateRegime | null;
  repo_rate_by_date?: Record<string, number> | null;
  calendar?: CalendarSideCar | null;
  flow_regime?: FlowRegime | null;
  fund_regime?: FundRegime | null;
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
