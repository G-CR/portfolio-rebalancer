export type DecimalString = string;

export type BackupOperationStatus = "pending" | "running" | "succeeded" | "failed" | "interrupted";
export type BackupStage = "validated" | "locking_data" | "creating_safety_backup" | "writing_data" | "verifying_integrity" | "completed";

export interface BackupOperation {
  id: string;
  kind: "export" | "restore";
  status: BackupOperationStatus;
  stage: BackupStage;
  error: { code: string; message: string } | null;
  download_ready: boolean;
  safety_backup_id: string | null;
}

export interface BackupCountComparison {
  backup: number;
  current: number;
  delta: number;
}

export interface BackupPreview {
  exported_at: string;
  source_application_version: string;
  source_format_version: number;
  current_format_version: number;
  record_counts: Record<string, number>;
  current_record_counts: Record<string, number>;
  count_comparison: Record<string, BackupCountComparison>;
  warnings: string[];
  credential_categories: string[];
  restore_token: string;
  expires_at: string;
}

export interface SafetyBackup {
  id: string;
  exported_at: string;
  source_application_version: string;
  format_version: number;
  size_bytes: number;
  record_counts: Record<string, number>;
}

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
  preferred_data_source: ProviderName | null;
  is_rebalance_preferred: boolean;
  is_active: boolean;
  version: number;
}

export interface HoldingReplacementRequest {
  source_version: number;
  symbol: string;
  name: string;
  market: string;
  account_name: string;
  trade_currency: string;
  quantity: DecimalString;
  average_cost_price: DecimalString;
  cost_fx_to_cny: DecimalString;
  baseline_fx_to_cny: DecimalString;
  lot_size: DecimalString;
  quantity_precision: number;
  preferred_data_source: ProviderName | null;
  note: string | null;
}

export interface HoldingReplacementResponse {
  source: Holding;
  target: Holding;
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

export type SnapshotType = "daily" | "manual" | "rebalance_before" | "rebalance_after";

export interface SnapshotSummary {
  id: string;
  snapshot_type: SnapshotType;
  local_date: string;
  captured_at: string;
  note: string | null;
  data_complete: boolean;
  has_stale_data: boolean;
  has_manual_data: boolean;
  total_market_value_cny: DecimalString;
  total_fx_neutral_value_cny: DecimalString;
  total_cost_value_cny: DecimalString;
  total_unrealized_pnl_cny: DecimalString;
  total_price_effect_cny: DecimalString;
  total_fx_effect_cny: DecimalString;
  actual_weight: DecimalString;
  fx_neutral_weight: DecimalString;
  target_weight: DecimalString | null;
}

export interface SnapshotItem {
  id: string;
  holding_id: string | null;
  asset_class_name: string;
  holding_name: string;
  symbol: string;
  account_name: string;
  trade_currency: string;
  quantity: DecimalString;
  market_price: DecimalString | null;
  current_fx_to_cny: DecimalString | null;
  baseline_fx_to_cny: DecimalString;
  average_cost_price: DecimalString;
  cost_fx_to_cny: DecimalString;
  target_weight: DecimalString;
  market_value_cny: DecimalString | null;
  fx_neutral_value_cny: DecimalString | null;
  cost_value_cny: DecimalString | null;
  unrealized_pnl_amount_cny: DecimalString | null;
  unrealized_pnl_rate: DecimalString | null;
  price_effect_cny: DecimalString | null;
  fx_effect_cny: DecimalString | null;
  actual_weight: DecimalString | null;
  fx_neutral_weight: DecimalString | null;
  price_status: AnalyticsDataStatus;
  fx_status: AnalyticsDataStatus;
}

export interface SnapshotDetail extends SnapshotSummary {
  items: SnapshotItem[];
}

export interface SnapshotCollection {
  items: SnapshotSummary[];
  page: number;
  page_size: number;
  total: number;
}

export type HoldingCreate = Omit<Holding, "id" | "is_active" | "version">;
export type HoldingUpdate = Partial<HoldingCreate>;

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

export type RebalanceValuationBasis = "actual" | "fx_neutral";
export type RebalanceDataStatus = "valid" | "stale" | "manual";

export interface RebalancePreviewPayload {
  session_token: string;
  request_token: string;
  available_cny: DecimalString;
  available_usd: DecimalString;
  valuation_basis: RebalanceValuationBasis;
  allow_sell: boolean;
  allow_fx: boolean;
  tolerance: DecimalString;
  acknowledge_stale_data: boolean;
}

export interface RebalanceTradeSuggestion {
  symbol: string;
  action: "buy" | "sell";
  quantity: DecimalString;
  amount_cny: DecimalString;
  amount_trade_currency: DecimalString;
  reason_code: string;
  reason: string;
}

export interface RebalanceProjectedWeight {
  asset_class_id: string;
  before: DecimalString;
  after: DecimalString;
  target: DecimalString;
}

export type RebalanceNetFxDirection = "cny_to_usd" | "usd_to_cny" | "none";

export interface RebalanceResult {
  feasible: boolean;
  max_drift_before: DecimalString;
  max_drift_after: DecimalString;
  buy_only_max_drift: DecimalString;
  optimization_precision: DecimalString;
  optimization_certified: boolean;
  optimality_gap: DecimalString;
  sell_phase_used: boolean;
  net_fx_direction: RebalanceNetFxDirection;
  net_fx_amount_cny: DecimalString;
  fx_required_cny: DecimalString;
  remaining_cny: DecimalString;
  remaining_usd: DecimalString;
  projected_weights: RebalanceProjectedWeight[];
  trades: RebalanceTradeSuggestion[];
}

export interface RebalanceComparison {
  valuation_basis: RebalanceValuationBasis;
  result: RebalanceResult;
}

export interface RebalancePreview {
  session_token: string;
  request_token: string;
  status: "ok";
  data_status: RebalanceDataStatus;
  acknowledge_stale_data: boolean;
  refresh_attempted: boolean;
  valuation_basis: RebalanceValuationBasis;
  result: RebalanceResult;
  fx_comparison: RebalanceComparison;
  input_signature?: string | null;
}

export type RebalancePreviewJobStatus = "queued" | "refreshing" | "calculating" | "succeeded" | "failed";

export interface RebalancePreviewJob {
  id: string;
  status: RebalancePreviewJobStatus;
  result: RebalancePreview | null;
  error: ApiErrorDetail | null;
  payload?: RebalancePreviewPayload | null;
  created_at?: string | null;
  finished_at?: string | null;
  is_current?: boolean | null;
}

export interface RebalancePlan extends Omit<RebalancePreview, "session_token" | "request_token" | "status" | "refresh_attempted" | "acknowledge_stale_data"> {
  id: string;
  status: "draft" | "in_progress" | "completed" | "cancelled";
  available_cny: DecimalString;
  available_usd: DecimalString;
  minimum_trade_cny: DecimalString | null;
  allow_sell: boolean;
  allow_fx: boolean;
  acknowledge_stale_data: boolean;
  tolerance: DecimalString;
  data_version: string;
  market_data_record_ids: Record<string, string>;
  holding_versions: Record<string, number>;
  asset_class_targets: Record<string, string>;
  before_snapshot_id: string | null;
  after_snapshot_id: string | null;
  baseline_reset_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MarketDataStatus {
  key: string;
  data_type: "price" | "fx" | string;
  symbol: string;
  currency: string;
  effective_value: DecimalString | null;
  source: string | null;
  status: AnalyticsDataStatus;
  market_time: string | null;
  fetched_at: string | null;
  error_summary: string | null;
  note: string | null;
}

export interface MarketDataCollection {
  items: MarketDataStatus[];
  diagnostics: Array<{ code: string; message: string; holding_id: string; symbol: string; fields: string[] }>;
}

export type ProviderName = "yahoo" | "sina" | "akshare" | "tushare" | "alpha_vantage";

export interface ProviderSetting {
  provider: ProviderName;
  display_name: string;
  requires_key: boolean;
  enabled: boolean;
  priority: number;
  key_status: "not_required" | "not_configured" | "configured";
  masked_key: string | null;
  validation_status: "valid" | "failed" | null;
  validation_message: string | null;
  last_validated_at: string | null;
}

export interface GeneralSettings {
  refresh_time: string;
  provider_priority: ProviderName[];
  default_tolerance: DecimalString;
  minimum_trade_amount_cny: DecimalString;
  allow_sell: boolean;
  allow_fx: boolean;
  updated_at: string;
}

export interface GeneralSettingsUpdate {
  refresh_time: string;
  provider_priority: ProviderName[];
  default_tolerance: DecimalString;
  allow_sell: boolean;
  allow_fx: boolean;
}

export interface RebalanceDefaults {
  available_cny: DecimalString;
  available_usd: DecimalString;
  valuation_basis: RebalanceValuationBasis;
  tolerance: DecimalString;
  minimum_trade_cny: DecimalString;
  allow_sell: boolean;
  allow_fx: boolean;
  updated_at: string;
}

export interface RebalanceDefaultsUpdate {
  available_cny: DecimalString;
  available_usd: DecimalString;
  valuation_basis: RebalanceValuationBasis;
  tolerance: DecimalString;
  allow_sell: boolean;
  allow_fx: boolean;
}

export type EmailSecurity = "ssl" | "starttls";

export interface EmailSettings {
  enabled: boolean;
  recipient: string | null;
  smtp_host: string | null;
  smtp_port: number;
  smtp_security: EmailSecurity;
  smtp_username: string | null;
  from_address: string | null;
  password_masked: string | null;
  updated_at: string;
}

export interface EmailTestResult {
  status: "ok" | "failed";
  error_category:
    | "not_configured"
    | "smtp_connect_failed"
    | "smtp_auth_failed"
    | "smtp_recipient_rejected"
    | "smtp_timeout"
    | "smtp_send_failed"
    | null;
}

export type EmailDigestTriggerStatus = "sent" | "anomaly_sent" | "skipped_empty" | "not_configured";

export interface EmailDigestTriggerResult {
  status: EmailDigestTriggerStatus;
  sent_at: string | null;
}
