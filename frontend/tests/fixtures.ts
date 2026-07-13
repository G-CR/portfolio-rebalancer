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
  totals: {
    cost_cny: "612430.00",
    market_value_cny: "684220.00",
    fx_neutral_value_cny: "678140.00",
    unrealized_pnl: "71790.00",
    unrealized_return: "0.11722",
    price_effect: "65710.00",
    fx_effect: "6080.00",
  },
  asset_classes: assetClassFixtures.map((assetClass, index) => ({
    ...assetClass,
    actual_weight: ["0.186", "0.192", "0.318", "0.206", "0.098"][index],
    fx_neutral_weight: ["0.188", "0.194", "0.307", "0.211", "0.100"][index],
    market_value_cny: ["127260", "131370", "217580", "140950", "67060"][index],
  })),
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
