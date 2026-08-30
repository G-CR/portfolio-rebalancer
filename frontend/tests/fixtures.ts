import type { Holding, HoldingReplacementRequest, HoldingReplacementResponse } from "../src/api/types";

export const assetClassFixtures = [
  {
    id: "10000000-0000-4000-8000-000000000001",
    name: "红利低波",
    target_weight: "0.20000000",
    display_order: 1,
    notes: null,
    is_active: true,
  },
  {
    id: "10000000-0000-4000-8000-000000000002",
    name: "红利质量",
    target_weight: "0.20000000",
    display_order: 2,
    notes: null,
    is_active: true,
  },
  {
    id: "10000000-0000-4000-8000-000000000003",
    name: "标普 500",
    target_weight: "0.30000000",
    display_order: 3,
    notes: null,
    is_active: true,
  },
  {
    id: "10000000-0000-4000-8000-000000000004",
    name: "纳斯达克 100",
    target_weight: "0.20000000",
    display_order: 4,
    notes: null,
    is_active: true,
  },
  {
    id: "10000000-0000-4000-8000-000000000005",
    name: "黄金",
    target_weight: "0.10000000",
    display_order: 5,
    notes: null,
    is_active: true,
  },
] as const;

export const holdingFixture = {
  id: "20000000-0000-4000-8000-000000000001",
  asset_class_id: assetClassFixtures[2].id,
  symbol: "SPY",
  name: "SPDR S&P 500 ETF Trust",
  market: "US",
  account_name: "长期账户",
  trade_currency: "USD",
  quantity: "12.0000",
  average_cost_price: "510.25",
  cost_fx_to_cny: "7.18",
  baseline_fx_to_cny: "7.2",
  lot_size: "1",
  quantity_precision: 4,
  preferred_data_source: null,
  is_rebalance_preferred: true,
  is_active: true,
  version: 1,
} as const;

export const marketDataFixture = {
  key: "SPY",
  data_type: "price",
  value: "590.42",
  currency: "USD",
  source: "Yahoo Finance",
  market_time: "2026-07-13T20:00:00Z",
  fetched_at: "2026-07-14T00:00:08Z",
  status: "valid",
  is_override: false,
  error_summary: null,
} as const;

export const portfolioFixture = {
  as_of: "2026-07-14T00:00:08Z",
  data_status: "valid",
  has_stale_data: false,
  has_manual_data: false,
  tolerance: "0.020000000000",
  cost_cny: "1196630.00",
  market_value_cny: "1268420.00",
  fx_neutral_value_cny: "1257340.00",
  unrealized_pnl: "71790.00",
  unrealized_return: "0.059991811",
  price_effect: "65710.00",
  fx_effect: "6080.00",
  overseas_weight: "0.524000000000",
  decision: {
    status: "hold",
    title: "保持现状",
    reason: "全部资产仍在 ±2.0 个百分点策略区间内。",
    max_drift: "0.01800000",
    fx_contribution: "0.01100000",
    primary_action: "simulate_contribution",
  },
  asset_classes: assetClassFixtures.map((assetClass, index) => ({
    id: assetClass.id,
    name: assetClass.name,
    target_weight: assetClass.target_weight,
    display_order: assetClass.display_order,
    actual_weight: ["0.186000000000", "0.192000000000", "0.318000000000", "0.206000000000", "0.098000000000"][index],
    fx_neutral_weight: ["0.188000000000", "0.194000000000", "0.307000000000", "0.211000000000", "0.100000000000"][index],
    drift: ["-0.014", "-0.008", "0.018", "0.006", "-0.002"][index],
    fx_weight_contribution: ["-0.002", "-0.002", "0.011", "-0.005", "-0.002"][index],
    cost_cny: ["220000", "224000", "360000", "260000", "132630"][index],
    market_value_cny: ["235930", "243540", "403376", "261294", "124280"][index],
    fx_neutral_value_cny: ["236380", "243923", "386151", "265307", "125579"][index],
    unrealized_pnl: ["15930", "19540", "43376", "1294", "-8350"][index],
    price_effect: ["15930", "19540", "37300", "3200", "-260"][index],
    fx_effect: ["0", "0", "6076", "-1906", "-8090"][index],
  })),
  holdings: [
    {
      holding_id: holdingFixture.id,
      asset_class_id: holdingFixture.asset_class_id,
      symbol: "SPY",
      name: "SPDR S&P 500 ETF Trust",
      trade_currency: "USD",
      current_price: "590.42",
      current_fx_to_cny: "7.2",
      price_status: "valid",
      fx_status: "manual",
      cost_trade_currency: "6123.00",
      market_value_trade_currency: "7085.04",
      unrealized_pnl_trade_currency: "+962.04",
      cost_cny: "43963.14",
      market_value_cny: "51012.29",
      fx_neutral_value_cny: "51012.29",
      unrealized_pnl: "+7049.15",
      unrealized_return: "0.160342",
      price_effect: "+6900.00",
      fx_effect: "+149.15",
    },
  ],
  data_inputs: [
    { key: "price:SPY", input: "price", value: "590.420000000000", status: "valid", source: "yahoo", market_time: "2026-07-13T20:00:00Z", fetched_at: "2026-07-14T00:00:08Z", error_summary: null, note: null },
    { key: "fx:USD/CNY", input: "fx", value: "7.2", status: "manual", source: "manual", market_time: "2026-07-14T00:00:00Z", fetched_at: "2026-07-14T00:00:00Z", error_summary: null, note: "券商结算汇率" },
  ],
} as const;

export const snapshotFixture = {
  id: "30000000-0000-4000-8000-000000000001",
  snapshot_type: "manual",
  captured_at: "2026-07-14T00:10:00Z",
  note: "再平衡测算前",
  data_complete: true,
  has_stale_data: false,
  total_market_value_cny: "684220.00",
  items: portfolioFixture.asset_classes,
} as const;

export const rebalanceFixture = {
  id: "40000000-0000-4000-8000-000000000001",
  status: "draft",
  feasible: true,
  generated_at: "2026-07-14T00:12:00Z",
  inputs: {
    cny_cash: "20000.00",
    usd_cash: "1000.00",
    tolerance: "0.0200",
    minimum_trade_cny: "1000.00",
    allow_sell: false,
    allow_fx: true,
    weight_basis: "actual",
  },
  remaining_cash: { cny: "86.00", usd: "12.00" },
  trades: [
    {
      holding_id: holdingFixture.id,
      symbol: "SPY",
      side: "buy",
      quantity: "1",
      reference_amount_cny: "4251.00",
      reason: "实际占比低于目标区间",
    },
  ],
  projected_weights: portfolioFixture.asset_classes.map((item) => ({
    asset_class_id: item.id,
    weight: item.target_weight,
  })),
} as const;

const projectedWeights = assetClassFixtures.map((item, index) => ({
  asset_class_id: item.id,
  before: ["0.180000000000", "0.190000000000", "0.340000000000", "0.210000000000", "0.080000000000"][index],
  after: ["0.198000000000", "0.199000000000", "0.302000000000", "0.201000000000", "0.100000000000"][index],
  target: item.target_weight,
}));

export const rebalancePreviewFixture = {
  session_token: "test-browser-session",
  request_token: "test-request",
  status: "ok",
  data_status: "valid",
  acknowledge_stale_data: false,
  refresh_attempted: true,
  valuation_basis: "actual",
  result: {
    feasible: true,
    max_drift_before: "0.040000000000",
    max_drift_after: "0.002000000000",
    buy_only_max_drift: "0.006000000000",
    optimization_precision: "0.000100000000",
    optimization_certified: true,
    optimality_gap: "0",
    sell_phase_used: true,
    net_fx_direction: "cny_to_usd",
    net_fx_amount_cny: "7200.000000000000",
    fx_required_cny: "7200.000000000000",
    remaining_cny: "86.000000000000",
    remaining_usd: "12.000000000000",
    projected_weights: projectedWeights,
    trades: [
      {
        symbol: "510880",
        action: "buy",
        quantity: "1200.000000000000",
        amount_cny: "3600.000000000000",
        amount_trade_currency: "3600.000000000000",
        reason_code: "REDUCE_MAX_DRIFT",
        reason: "该交易用于降低投资组合的最大配置偏离。",
      },
      {
        symbol: "159758",
        action: "buy",
        quantity: "3000.000000000000",
        amount_cny: "3600.000000000000",
        amount_trade_currency: "3600.000000000000",
        reason_code: "REDUCE_TOTAL_DRIFT",
        reason: "在最佳最大偏离范围内，该交易进一步降低整体配置偏离。",
      },
      {
        symbol: "SPY",
        action: "sell",
        quantity: "2.000000000000",
        amount_cny: "8500.000000000000",
        amount_trade_currency: "1180.000000000000",
        reason_code: "REALLOCATE_OUTSIDE_TOLERANCE",
        reason: "新增资金不足以消除高配",
      },
      {
        symbol: "518880",
        action: "buy",
        quantity: "1500.000000000000",
        amount_cny: "8700.000000000000",
        amount_trade_currency: "8700.000000000000",
        reason_code: "REDUCE_MAX_DRIFT",
        reason: "该交易用于降低投资组合的最大配置偏离。",
      },
    ],
  },
  fx_comparison: {
    valuation_basis: "fx_neutral",
    result: {
      feasible: true,
      max_drift_before: "0.022000000000",
      max_drift_after: "0.003000000000",
      buy_only_max_drift: "0.003000000000",
      optimization_precision: "0.000100000000",
      optimization_certified: true,
      optimality_gap: "0",
      sell_phase_used: false,
      net_fx_direction: "none",
      net_fx_amount_cny: "0",
      fx_required_cny: "0",
      remaining_cny: "420.000000000000",
      remaining_usd: "38.000000000000",
      projected_weights: projectedWeights,
      trades: [],
    },
  },
} as const;

export const rebalancePlanFixture = {
  id: "40000000-0000-4000-8000-000000000099",
  status: "draft",
  valuation_basis: "actual",
  available_cny: "0",
  available_usd: "0",
  minimum_trade_cny: null,
  allow_sell: true,
  allow_fx: true,
  acknowledge_stale_data: false,
  tolerance: "0.02",
  data_version: "fixture-data-version",
  data_status: "valid",
  market_data_record_ids: {},
  holding_versions: {},
  asset_class_targets: Object.fromEntries(assetClassFixtures.map((item) => [item.id, item.target_weight])),
  result: rebalancePreviewFixture.result,
  fx_comparison: rebalancePreviewFixture.fx_comparison,
  before_snapshot_id: null,
  after_snapshot_id: null,
  baseline_reset_at: null,
  created_at: "2026-07-14T00:12:00+00:00",
  updated_at: "2026-07-14T00:12:00+00:00",
} as const;

export const marketDataCollectionFixture = {
  items: [
    {
      key: "price:SPY",
      data_type: "price",
      symbol: "SPY",
      currency: "USD",
      effective_value: "651.28",
      source: "yahoo",
      status: "stale",
      market_time: "2026-07-10T20:00:00Z",
      fetched_at: "2026-07-14T00:00:00Z",
      error_summary: "Yahoo 请求超时，当前使用 07/10 收盘值",
      note: null,
    },
    {
      key: "fx:USD/CNY",
      data_type: "fx",
      symbol: "USD/CNY",
      currency: "CNY",
      effective_value: "7.18",
      source: "manual",
      status: "manual",
      market_time: "2026-07-14T00:00:00Z",
      fetched_at: "2026-07-14T00:00:00Z",
      error_summary: null,
      note: "券商结算参考",
    },
  ],
  diagnostics: [],
} as const;

export const providerSettingsFixture = [
  { provider: "akshare", display_name: "AKShare", requires_key: false, enabled: true, priority: 1, key_status: "not_required", masked_key: null, validation_status: null, validation_message: null, last_validated_at: null },
  { provider: "yahoo", display_name: "Yahoo Finance", requires_key: false, enabled: true, priority: 2, key_status: "not_required", masked_key: null, validation_status: null, validation_message: null, last_validated_at: null },
  { provider: "sina", display_name: "新浪财经", requires_key: false, enabled: true, priority: 3, key_status: "not_required", masked_key: null, validation_status: null, validation_message: null, last_validated_at: null },
  { provider: "tushare", display_name: "Tushare", requires_key: true, enabled: false, priority: 4, key_status: "not_configured", masked_key: null, validation_status: null, validation_message: null, last_validated_at: null },
  { provider: "alpha_vantage", display_name: "Alpha Vantage", requires_key: true, enabled: true, priority: 5, key_status: "configured", masked_key: "****alue", validation_status: "valid", validation_message: "Credential validation succeeded.", last_validated_at: "2026-07-14T00:00:00Z" },
] as const;

export const generalSettingsFixture = {
  refresh_time: "08:00",
  provider_priority: ["akshare", "yahoo", "sina", "tushare", "alpha_vantage"],
  default_tolerance: "0.02",
  minimum_trade_amount_cny: "500",
  allow_sell: true,
  allow_fx: true,
  updated_at: "2026-07-14T00:00:00Z",
} as const;

export const rebalanceDefaultsFixture = {
  available_cny: "0",
  available_usd: "0",
  valuation_basis: "actual",
  tolerance: "0.02",
  minimum_trade_cny: "500",
  allow_sell: true,
  allow_fx: true,
  updated_at: "2026-07-14T00:00:00Z",
} as const;

export function holdingReplacementRequestFixture(
  source: Holding,
  overrides: Partial<HoldingReplacementRequest> = {},
): HoldingReplacementRequest {
  return {
    source_version: source.version,
    symbol: "VOO",
    name: "Vanguard S&P 500 ETF",
    market: source.market,
    account_name: source.account_name,
    trade_currency: source.trade_currency,
    quantity: "8",
    average_cost_price: "625.40",
    cost_fx_to_cny: source.cost_fx_to_cny,
    baseline_fx_to_cny: source.baseline_fx_to_cny,
    lot_size: source.lot_size,
    quantity_precision: source.quantity_precision,
    preferred_data_source: source.preferred_data_source,
    note: null,
    ...overrides,
  };
}

function scaleDecimalString(value: string, precision: number): string {
  const match = value.trim().match(/^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))$/);
  if (!match) throw new Error(`Invalid decimal fixture value: ${value}`);

  const scale = Math.max(precision, 0);
  const fraction = match[3] ?? match[4] ?? "";
  const units = BigInt(`${match[2] ?? "0"}${fraction}`);
  let scaledUnits: bigint;
  if (fraction.length <= scale) {
    scaledUnits = units * 10n ** BigInt(scale - fraction.length);
  } else {
    const divisor = 10n ** BigInt(fraction.length - scale);
    const quotient = units / divisor;
    const remainder = units % divisor;
    const comparison = remainder * 2n - divisor;
    const roundUp = comparison > 0n || (comparison === 0n && quotient % 2n !== 0n);
    scaledUnits = quotient + (roundUp ? 1n : 0n);
  }

  const sign = match[1] === "-" ? "-" : "";
  const digits = scaledUnits.toString().padStart(scale + 1, "0");
  if (scale === 0) return `${sign}${digits}`;
  return `${sign}${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
}

export function holdingReplacementResponseFixture(
  source: Holding,
  payload: HoldingReplacementRequest,
  targetId = "20000000-0000-4000-8000-000000000099",
): HoldingReplacementResponse {
  const zeroQuantity = source.quantity_precision > 0
    ? `0.${"0".repeat(source.quantity_precision)}`
    : "0";
  const targetQuantity = scaleDecimalString(payload.quantity, payload.quantity_precision);
  return {
    source: {
      ...source,
      quantity: zeroQuantity,
      average_cost_price: "0",
      cost_fx_to_cny: "0",
      is_active: false,
      is_rebalance_preferred: false,
      version: source.version + 1,
    },
    target: {
      id: targetId,
      asset_class_id: source.asset_class_id,
      symbol: payload.symbol,
      name: payload.name,
      market: payload.market,
      account_name: payload.account_name,
      trade_currency: payload.trade_currency,
      quantity: targetQuantity,
      average_cost_price: payload.average_cost_price,
      cost_fx_to_cny: payload.trade_currency === "CNY" ? "1" : payload.cost_fx_to_cny,
      baseline_fx_to_cny: payload.trade_currency === "CNY" ? "1" : payload.baseline_fx_to_cny,
      lot_size: payload.lot_size,
      quantity_precision: payload.quantity_precision,
      preferred_data_source: payload.preferred_data_source,
      is_rebalance_preferred: true,
      is_active: true,
      version: 1,
    },
  };
}

export const emailSettingsFixture = {
  enabled: false,
  recipient: null,
  smtp_host: null,
  smtp_port: 465,
  smtp_security: "ssl",
  smtp_username: null,
  from_address: null,
  password_masked: null,
  updated_at: "2026-07-15T08:00:00Z",
} as const;
