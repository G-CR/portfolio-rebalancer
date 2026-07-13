export type DecimalString = string;

export type ApiErrorDetail = {
  code: string;
  message: string;
  [key: string]: unknown;
};

export interface AssetClass {
  id: string;
  name: string;
  target_weight: DecimalString;
  display_order: number;
  notes: string | null;
  is_active: boolean;
}

export type AssetClassUpdate = Pick<
  AssetClass,
  "id" | "name" | "target_weight" | "display_order" | "notes" | "is_active"
>;

export interface Holding {
  id: string;
  asset_class_id: string;
  symbol: string;
  name: string;
  market: string;
  account_name: string;
  trade_currency: "CNY" | "USD" | string;
  quantity: DecimalString;
  average_cost_price: DecimalString;
  cost_fx_to_cny: DecimalString;
  baseline_fx_to_cny: DecimalString;
  lot_size: DecimalString;
  quantity_precision: number;
  is_rebalance_preferred: boolean;
  is_active: boolean;
  version: number;
}

export type AnalyticsDataStatus = "valid" | "stale" | "manual" | "missing" | "failed" | string;

export interface PortfolioDataInput {
  key: string;
  input: "price" | "fx";
  value: DecimalString | null;
  status: AnalyticsDataStatus;
  source: string | null;
  market_time: string | null;
  fetched_at: string | null;
  error_summary: string | null;
  note: string | null;
}

export interface HoldingAnalytics {
  holding_id: string;
  asset_class_id: string;
  symbol: string;
  name: string;
  trade_currency: string;
  current_price: DecimalString;
  current_fx_to_cny: DecimalString;
  price_status: AnalyticsDataStatus;
  fx_status: AnalyticsDataStatus;
  cost_trade_currency: DecimalString;
  market_value_trade_currency: DecimalString;
  unrealized_pnl_trade_currency: DecimalString;
  cost_cny: DecimalString;
  market_value_cny: DecimalString;
  fx_neutral_value_cny: DecimalString;
  unrealized_pnl: DecimalString;
  unrealized_return: DecimalString;
  price_effect: DecimalString;
  fx_effect: DecimalString;
}

export interface AssetClassAnalytics {
  id: string;
  name: string;
  target_weight: DecimalString;
  display_order: number;
  actual_weight: DecimalString;
  fx_neutral_weight: DecimalString;
  drift: DecimalString;
  fx_weight_contribution: DecimalString;
  cost_cny: DecimalString;
  market_value_cny: DecimalString;
  fx_neutral_value_cny: DecimalString;
  unrealized_pnl: DecimalString;
  price_effect: DecimalString;
  fx_effect: DecimalString;
}

export interface PortfolioDecision {
  status: "setup" | "hold" | "contribute" | "rebalance";
  title: string;
  reason: string;
  max_drift: DecimalString;
  fx_contribution: DecimalString;
  primary_action: "add_holding" | "simulate_contribution" | "view_rebalance";
}

export interface PortfolioAnalytics {
  as_of: string | null;
  data_status: string;
  has_stale_data: boolean;
  has_manual_data: boolean;
  tolerance: DecimalString;
  cost_cny: DecimalString;
  market_value_cny: DecimalString;
  fx_neutral_value_cny: DecimalString;
  unrealized_pnl: DecimalString;
  unrealized_return: DecimalString;
  price_effect: DecimalString;
  fx_effect: DecimalString;
  overseas_weight: DecimalString;
  decision: PortfolioDecision;
  asset_classes: AssetClassAnalytics[];
  holdings: HoldingAnalytics[];
  data_inputs: PortfolioDataInput[];
}

export interface PortfolioIncompleteItem {
  holding_id: string;
  symbol: string;
  input: "price" | "fx";
  key: string;
  status: string;
  value: null;
  market_time?: string | null;
  source?: string | null;
  error_summary?: string | null;
}

export type HoldingCreate = Omit<Holding, "id" | "is_active" | "version">;

export interface HoldingDefaults {
  fee_currency: string;
  commission_rate: DecimalString;
  minimum_commission: DecimalString;
  per_share_fee: DecimalString;
  fixed_fee: DecimalString;
}

export interface CostBasisState {
  quantity: DecimalString;
  average_cost_price: DecimalString;
  cost_fx_to_cny: DecimalString;
  total_cost_cny: DecimalString;
}

export interface FeePreview {
  mode: "estimated" | "actual";
  currency: string;
  amount: DecimalString;
  amount_cny: DecimalString;
}

export type CostOperation = "purchase" | "sell" | "manual_correction" | "restore";

export interface CostAdjustmentPreview {
  holding_id: string;
  holding_version: number;
  operation: CostOperation;
  before: CostBasisState;
  after: CostBasisState;
  fee: FeePreview | null;
  note: string | null;
  adjustment_id: string | null;
}

export interface CostAdjustmentHistoryItem {
  id: string;
  operation_type: string;
  before: CostBasisState;
  after: CostBasisState;
  input_summary: Record<string, unknown>;
  note: string | null;
  created_at: string;
}

export interface CostAdjustmentCollection {
  holding_id: string;
  holding_version: number;
  defaults: HoldingDefaults | null;
  items: CostAdjustmentHistoryItem[];
}

export interface PurchasePayload {
  quantity: DecimalString;
  price: DecimalString;
  fx: DecimalString;
  fee_currency: string | null;
  commission_rate: DecimalString | null;
  minimum_commission: DecimalString | null;
  per_share_fee: DecimalString | null;
  fixed_fee: DecimalString | null;
  actual_fee: DecimalString | null;
  save_fee_defaults: boolean;
  note: string | null;
}

export interface SellPayload {
  quantity: DecimalString;
  note: string | null;
}

export interface CorrectionPayload {
  quantity: DecimalString;
  average_cost_price: DecimalString;
  cost_fx_to_cny: DecimalString;
  note: string;
}

export interface RestorePayload {
  adjustment_id: string;
  note: string | null;
}

export interface ConfirmAdjustmentRequest<TPayload> {
  expected_version: number;
  operation: CostOperation;
  payload: TPayload;
}
