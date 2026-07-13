import { Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import type { AssetClass, HoldingCreate } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { WorkDrawer } from "../../components/WorkDrawer/WorkDrawer";
import { useCreateHolding } from "./api";
import styles from "./Holdings.module.css";

type Props = {
  assetClasses: AssetClass[];
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
};

const decimalPattern = /^\d+(?:\.\d+)?$/;

export function AddHoldingDrawer({ assetClasses, open, onClose, onCreated }: Props) {
  const activeClasses = assetClasses.filter((item) => item.is_active);
  const create = useCreateHolding();
  const [assetClassId, setAssetClassId] = useState(activeClasses[0]?.id ?? "");
  const [symbol, setSymbol] = useState("");
  const [name, setName] = useState("");
  const [market, setMarket] = useState("");
  const [accountName, setAccountName] = useState("");
  const [currency, setCurrency] = useState("CNY");
  const [quantity, setQuantity] = useState("0");
  const [averageCost, setAverageCost] = useState("0");
  const [costFx, setCostFx] = useState("1");
  const [baselineFx, setBaselineFx] = useState("1");
  const [lotSize, setLotSize] = useState("1");
  const [precision, setPrecision] = useState("0");
  const [preferred, setPreferred] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => () => { mounted.current = false; }, []);

  useEffect(() => {
    if (!assetClassId && activeClasses[0]) setAssetClassId(activeClasses[0].id);
  }, [activeClasses, assetClassId]);

  const missingIdentity = submitted && (!symbol.trim() || !name.trim() || !market.trim() || !accountName.trim());
  const invalidDecimals = submitted && [quantity, averageCost, costFx, baselineFx, lotSize]
    .some((value) => !decimalPattern.test(value));
  const invalidPrecision = submitted && !/^\d+$/.test(precision);
  const canSubmit = Boolean(
    assetClassId && symbol.trim() && name.trim() && market.trim() && accountName.trim()
    && [quantity, averageCost, costFx, baselineFx, lotSize].every((value) => decimalPattern.test(value))
    && /^\d+$/.test(precision),
  );

  async function submit() {
    setSubmitted(true);
    setServerError(null);
    if (!canSubmit) return;
    const payload: HoldingCreate = {
      asset_class_id: assetClassId,
      symbol: symbol.trim(),
      name: name.trim(),
      market: market.trim(),
      account_name: accountName.trim(),
      trade_currency: currency,
      quantity,
      average_cost_price: averageCost,
      cost_fx_to_cny: costFx,
      baseline_fx_to_cny: baselineFx,
      lot_size: lotSize,
      quantity_precision: Number.parseInt(precision, 10),
      is_rebalance_preferred: preferred,
    };
    try {
      await create.mutateAsync(payload);
      if (mounted.current) onCreated();
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : "持仓创建失败，请检查输入后重试。");
    }
  }

  return (
    <WorkDrawer
      open={open}
      title="添加持仓"
      onClose={onClose}
      footer={<div className={styles.drawerFooter}><button className={styles.secondaryButton} type="button" onClick={onClose}>取消</button><button className={styles.primaryButton} type="button" disabled={create.isPending} onClick={() => void submit()}><Check size={16} aria-hidden="true" />{create.isPending ? "正在创建" : "创建持仓"}</button></div>}
    >
      <div className={styles.drawerContent}>
        {serverError ? <div className={styles.alert} role="alert">{serverError}</div> : null}
        {missingIdentity ? <div className={styles.alert} role="alert">请完整填写标的代码、名称、市场和账户。</div> : null}
        {invalidDecimals || invalidPrecision ? <div className={styles.alert} role="alert">成本与份额字段必须是非负十进制，份额小数位必须是整数。</div> : null}
        <section className={styles.drawerSection}>
          <div className={styles.sectionHeading}><span className={styles.step}>01</span><div><h3>标的身份</h3><p>选择资产类别并记录券商账户中的标的信息。</p></div></div>
          <FormField label="所属资产类别" required><select value={assetClassId} onChange={(event) => setAssetClassId(event.target.value)}>{activeClasses.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></FormField>
          <div className={styles.fieldGrid}>
            <FormField label="标的代码" required><input type="text" value={symbol} onChange={(event) => setSymbol(event.target.value)} /></FormField>
            <FormField label="标的名称" required><input type="text" value={name} onChange={(event) => setName(event.target.value)} /></FormField>
            <FormField label="上市市场" required><input type="text" value={market} onChange={(event) => setMarket(event.target.value)} /></FormField>
            <FormField label="账户名称" required><input type="text" value={accountName} onChange={(event) => setAccountName(event.target.value)} /></FormField>
            <FormField label="交易币种" required><select value={currency} onChange={(event) => { const next = event.target.value; setCurrency(next); if (next === "CNY") { setCostFx("1"); setBaselineFx("1"); } }}><option value="CNY">CNY</option><option value="USD">USD</option></select></FormField>
          </div>
        </section>
        <section className={styles.drawerSection}>
          <div className={styles.sectionHeading}><span className={styles.step}>02</span><div><h3>初始成本状态</h3><p>新持仓默认从零份额、零成本开始；所有输入按十进制字符串提交。</p></div></div>
          <div className={styles.fieldGrid}>
            <FormField label="初始份额" required><input type="text" inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></FormField>
            <FormField label="平均成本价" required><input type="text" inputMode="decimal" value={averageCost} onChange={(event) => setAverageCost(event.target.value)} /></FormField>
            <FormField label="成本汇率" required><input type="text" inputMode="decimal" value={costFx} onChange={(event) => setCostFx(event.target.value)} /></FormField>
            <FormField label="基准汇率" required><input type="text" inputMode="decimal" value={baselineFx} onChange={(event) => setBaselineFx(event.target.value)} /></FormField>
            <FormField label="最小交易单位" required><input type="text" inputMode="decimal" value={lotSize} onChange={(event) => setLotSize(event.target.value)} /></FormField>
            <FormField label="份额小数位" required><input type="text" inputMode="numeric" value={precision} onChange={(event) => setPrecision(event.target.value)} /></FormField>
          </div>
          <label className={styles.checkboxRow}><input type="checkbox" checked={preferred} onChange={(event) => setPreferred(event.target.checked)} />设为该资产类别的默认调整标的</label>
        </section>
      </div>
    </WorkDrawer>
  );
}
