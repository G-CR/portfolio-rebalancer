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
  "id" | "name" | "target_weight" | "display_order" | "notes"
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
