import { ArrowRight, Check, ChevronDown } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import type { Holding, ProviderName } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { useReplaceHolding } from "./api";
import styles from "./Holdings.module.css";

type Props = {
  holding: Holding;
  assetClassName: string;
  open: boolean;
  onClose: () => void;
  onReplaced: (target: Holding) => void;
};

type ReplacementField =
  | "symbol"
  | "name"
  | "quantity"
  | "averageCost"
  | "accountName"
  | "market"
  | "costFx"
  | "baselineFx"
  | "lotSize"
  | "precision";

type FieldErrors = Partial<Record<ReplacementField, string>>;

const providers: Array<{ value: ProviderName; label: string }> = [
  { value: "yahoo", label: "Yahoo Finance" },
  { value: "sina", label: "新浪财经" },
  { value: "akshare", label: "AKShare" },
  { value: "tushare", label: "Tushare" },
  { value: "alpha_vantage", label: "Alpha Vantage" },
];

const markets = [
  { value: "US", label: "美股" },
  { value: "SH", label: "上海 A 股" },
  { value: "SZ", label: "深圳 A 股" },
] as const;

const decimalPattern = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;

function decimalSign(value: string): -1 | 0 | 1 | null {
  const trimmed = value.trim();
  if (!decimalPattern.test(trimmed)) return null;
  if (!/[1-9]/.test(trimmed)) return 0;
  return trimmed.startsWith("-") ? -1 : 1;
}

export function ReplacementDrawer({ holding, assetClassName, open, onClose, onReplaced }: Props) {
  const replace = useReplaceHolding();
  const [symbol, setSymbol] = useState("");
  const [name, setName] = useState("");
  const [quantity, setQuantity] = useState(holding.quantity);
  const [averageCost, setAverageCost] = useState(holding.average_cost_price);
  const [accountName, setAccountName] = useState(holding.account_name);
  const [market, setMarket] = useState(
    markets.some((option) => option.value === holding.market) ? holding.market : "US",
  );
  const [currency, setCurrency] = useState(holding.trade_currency);
  const [costFx, setCostFx] = useState(holding.cost_fx_to_cny);
  const [baselineFx, setBaselineFx] = useState(holding.baseline_fx_to_cny);
  const [lotSize, setLotSize] = useState(holding.lot_size);
  const [precision, setPrecision] = useState(String(holding.quantity_precision));
  const [preferredDataSource, setPreferredDataSource] = useState<ProviderName | "">(holding.preferred_data_source ?? "");
  const [note, setNote] = useState("");
  const [advanced, setAdvanced] = useState(true);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);

  const targetLabel = symbol.trim().toUpperCase() || "新标的";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setServerError(null);
    const errors: FieldErrors = {};
    if (!symbol.trim()) errors.symbol = "请输入目标代码。";
    if (!name.trim()) errors.name = "请输入目标名称。";
    if (!accountName.trim()) errors.accountName = "请输入账户名称。";
    if (!markets.some((option) => option.value === market)) errors.market = "请选择有效上市市场。";
    if (decimalSign(quantity) !== 1) errors.quantity = "请输入大于 0 的有效目标份额。";
    const averageCostSign = decimalSign(averageCost);
    if (averageCostSign === null || averageCostSign < 0) errors.averageCost = "请输入大于或等于 0 的有效平均成本价。";
    if (currency !== "CNY") {
      if (decimalSign(costFx) !== 1) errors.costFx = "请输入大于 0 的有效成本汇率。";
      if (decimalSign(baselineFx) !== 1) errors.baselineFx = "请输入大于 0 的有效基准汇率。";
    }
    const lotSizeSign = decimalSign(lotSize);
    if (lotSizeSign === null || lotSizeSign < 0) errors.lotSize = "请输入大于或等于 0 的有效最小交易单位。";
    const trimmedPrecision = precision.trim();
    const parsedPrecision = /^\d+$/.test(trimmedPrecision) ? Number(trimmedPrecision) : Number.NaN;
    if (!Number.isInteger(parsedPrecision) || parsedPrecision < 0 || parsedPrecision > 12) {
      errors.precision = "份额精度必须是 0 到 12 的整数。";
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      return;
    }

    try {
      const result = await replace.mutateAsync({
        holdingId: holding.id,
        payload: {
          source_version: holding.version,
          symbol: symbol.trim().toUpperCase(),
          name: name.trim(),
          market,
          account_name: accountName,
          trade_currency: currency,
          quantity,
          average_cost_price: averageCost,
          cost_fx_to_cny: currency === "CNY" ? "1" : costFx,
          baseline_fx_to_cny: currency === "CNY" ? "1" : baselineFx,
          lot_size: lotSize,
          quantity_precision: parsedPrecision,
          preferred_data_source: preferredDataSource || null,
          note: note.trim() || null,
        },
      });
      onReplaced(result.target);
    } catch (caught) {
      setServerError(caught instanceof ApiError ? caught.message : "标的替换失败，请检查输入后重试。");
    }
  }

  const footer = (
    <div className={styles.drawerFooter}>
      <button className={styles.secondaryButton} type="button" disabled={replace.isPending} onClick={onClose}>取消</button>
      <button className={styles.primaryButton} type="submit" form="replacement-form" disabled={replace.isPending}>
        {replace.isPending ? "正在替换" : `确认替换为 ${targetLabel}`}<Check size={15} aria-hidden="true" />
      </button>
    </div>
  );

  return (
    <WorkDrawer open={open} title={`替换标的 · ${holding.symbol}`} onClose={onClose} footer={footer} closeDisabled={replace.isPending}>
      <form id="replacement-form" className={styles.drawerContent} onSubmit={(event) => void submit(event)}>
        <section className={styles.replacementTransition} aria-labelledby="replacement-transition-title">
          <div className={styles.transitionHeading}>
            <span>{holding.symbol}</span>
            <ArrowRight size={18} aria-hidden="true" />
            <span>{targetLabel}</span>
          </div>
          <h3 id="replacement-transition-title" className={styles.srOnly}>{holding.symbol} → {targetLabel}</h3>
          <p>{holding.name} · {assetClassName} · {holding.account_name} · {holding.quantity} 份</p>
          <ul className={styles.replacementOutcomes}>
            <li>原标的将按当前份额全部卖出并归档</li>
            <li>新标的将创建到“{assetClassName}”并成为该资产类别的默认调整标的</li>
            <li>已有历史快照保持不变</li>
            <li>本次替换不记录已实现盈亏</li>
          </ul>
        </section>

        {serverError ? <div className={styles.alert} role="alert">{serverError}</div> : null}

        <section className={styles.drawerSection} aria-labelledby="replacement-target-title">
          <div className={styles.sectionHeading}>
            <div><h3 id="replacement-target-title">新标的信息</h3><p>记录替换后的代码、名称和起始成本状态。</p></div>
          </div>
          <div className={styles.fieldGrid}>
            <FormField label="目标代码" required error={fieldErrors.symbol}><input value={symbol} onChange={(event) => setSymbol(event.target.value)} autoCapitalize="characters" /></FormField>
            <FormField label="目标名称" required error={fieldErrors.name}><input value={name} onChange={(event) => setName(event.target.value)} /></FormField>
            <FormField label="目标份额" required error={fieldErrors.quantity}><input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></FormField>
            <FormField label="平均成本价" required error={fieldErrors.averageCost}><input inputMode="decimal" value={averageCost} onChange={(event) => setAverageCost(event.target.value)} /></FormField>
          </div>
        </section>

        <section className={styles.drawerSection} aria-labelledby="replacement-settings-title">
          <button
            className={styles.advancedToggle}
            type="button"
            aria-expanded={advanced}
            aria-controls="replacement-inherited-settings"
            onClick={() => setAdvanced((value) => !value)}
          >
            <span><strong id="replacement-settings-title">继承设置</strong><small>已从 {holding.symbol} 带入，可在替换前调整</small></span>
            <ChevronDown size={16} aria-hidden="true" />
          </button>
          {advanced ? (
            <div id="replacement-inherited-settings" className={styles.fieldGrid}>
              <FormField label="账户名称" required error={fieldErrors.accountName}><input value={accountName} onChange={(event) => setAccountName(event.target.value)} /></FormField>
              <FormField label="上市市场" required error={fieldErrors.market}>
                <select value={market} onChange={(event) => setMarket(event.target.value)}>
                  {markets.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </FormField>
              <FormField label="交易币种" required>
                <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
                  {!(["CNY", "USD"] as string[]).includes(currency) ? <option value={currency}>{currency}</option> : null}
                  <option value="CNY">CNY</option><option value="USD">USD</option>
                </select>
              </FormField>
              <FormField label="成本汇率" error={fieldErrors.costFx}><input inputMode="decimal" value={currency === "CNY" ? "1" : costFx} disabled={currency === "CNY"} onChange={(event) => setCostFx(event.target.value)} /></FormField>
              <FormField label="基准汇率" error={fieldErrors.baselineFx}><input inputMode="decimal" value={currency === "CNY" ? "1" : baselineFx} disabled={currency === "CNY"} onChange={(event) => setBaselineFx(event.target.value)} /></FormField>
              <FormField label="最小交易单位" error={fieldErrors.lotSize}><input inputMode="decimal" value={lotSize} onChange={(event) => setLotSize(event.target.value)} /></FormField>
              <FormField label="份额精度" error={fieldErrors.precision}><input inputMode="numeric" value={precision} onChange={(event) => setPrecision(event.target.value)} /></FormField>
              <FormField label="首选行情来源">
                <select value={preferredDataSource} onChange={(event) => setPreferredDataSource(event.target.value as ProviderName | "")}>
                  <option value="">跟随系统优先级</option>
                  {providers.map((provider) => <option key={provider.value} value={provider.value}>{provider.label}</option>)}
                </select>
              </FormField>
            </div>
          ) : null}
        </section>

        <FormField label="替换备注" hint="可选，记录这次标的迁移的原因。"><textarea value={note} onChange={(event) => setNote(event.target.value)} /></FormField>
      </form>
    </WorkDrawer>
  );
}
