import { CheckCircle2, KeyRound, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import type { GeneralSettings, ProviderSetting } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import {
  useGeneralSettings,
  useProviderSettings,
  useSaveGeneralSettings,
  useSaveProviderSetting,
  useTestProviderSetting,
} from "./api";
import styles from "../marketData/MarketData.module.css";

function ProviderRow({ item }: { item: ProviderSetting }) {
  const save = useSaveProviderSetting();
  const test = useTestProviderSetting();
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(item.enabled);
  const [priority, setPriority] = useState(String(item.priority));

  useEffect(() => {
    setEnabled(item.enabled);
    setPriority(String(item.priority));
  }, [item.enabled, item.priority]);

  async function submit() {
    await save.mutateAsync({
      provider: item.provider,
      apiKey: apiKey || null,
      enabled,
      priority: Number(priority),
    });
    setApiKey("");
  }

  return (
    <fieldset className={styles.providerRow} aria-label={`${item.display_name} 设置`}>
      <div className={styles.providerIdentity}><strong>{item.display_name}</strong><span>{item.requires_key ? item.masked_key ?? "尚未配置密钥" : "无需密钥"}</span></div>
      <div data-provider-cell="priority"><FormField label="优先级"><select value={priority} onChange={(event) => setPriority(event.target.value)}>{[1, 2, 3, 4, 5].map((value) => <option value={value} key={value}>{value}</option>)}</select></FormField></div>
      {item.requires_key ? <div data-provider-cell="credential"><FormField label="凭据"><input type="password" aria-label="API 密钥" autoComplete="new-password" value={apiKey} placeholder={item.masked_key ?? "输入新密钥"} onChange={(event) => setApiKey(event.target.value)} /></FormField></div> : <div className={styles.providerField} data-provider-cell="credential"><span className={styles.providerFieldLabel}>凭据</span><div className={styles.noKey}><ShieldCheck size={16} aria-hidden="true" />公开数据源</div></div>}
      <div className={styles.providerField} data-provider-cell="status"><span className={styles.providerFieldLabel}>状态</span>{item.requires_key ? <label className={styles.enabled}><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />启用</label> : <span className={styles.enabled}><CheckCircle2 size={15} aria-hidden="true" />启用</span>}</div>
      <div className={styles.providerField} data-provider-cell="actions"><span className={styles.providerFieldLabel}>操作</span><div className={styles.providerActions}><button type="button" className={styles.secondary} onClick={() => void submit()} disabled={save.isPending}><Save size={15} aria-hidden="true" />保存 {item.display_name}</button>{item.requires_key && item.key_status === "configured" ? <button type="button" className={styles.ghost} onClick={() => void test.mutateAsync(item.provider)} disabled={test.isPending}><KeyRound size={15} aria-hidden="true" />测试</button> : null}</div></div>
      {item.validation_status ? <small className={item.validation_status === "valid" ? styles.validationGood : styles.validationBad}>{item.validation_status === "valid" ? "最近验证成功" : "最近验证失败"}</small> : null}
    </fieldset>
  );
}

function GeneralSettingsForm({ value }: { value: GeneralSettings }) {
  const save = useSaveGeneralSettings();
  const [refreshTime, setRefreshTime] = useState(value.refresh_time);
  const [tolerance, setTolerance] = useState(value.default_tolerance);
  const [minimumTrade, setMinimumTrade] = useState(value.minimum_trade_amount_cny);
  const [allowSell, setAllowSell] = useState(value.allow_sell);
  const [allowFx, setAllowFx] = useState(value.allow_fx);

  return (
    <section className={styles.generalSettings} aria-labelledby="general-settings-title">
      <header className={styles.sectionHeading}><div><p>DEFAULT RULES</p><h2 id="general-settings-title">自动刷新与再平衡默认值</h2></div></header>
      <div className={styles.generalGrid}>
        <FormField label="每日刷新时间"><input type="time" value={refreshTime} onChange={(event) => setRefreshTime(event.target.value)} /></FormField>
        <FormField label="默认允许偏离" suffix="比例"><input inputMode="decimal" value={tolerance} onChange={(event) => setTolerance(event.target.value)} /></FormField>
        <FormField label="默认最小交易金额" suffix="CNY"><input inputMode="decimal" value={minimumTrade} onChange={(event) => setMinimumTrade(event.target.value)} /></FormField>
        <div className={styles.defaultSwitches}><label><input type="checkbox" checked={allowSell} onChange={(event) => setAllowSell(event.target.checked)} />默认允许卖出</label><label><input type="checkbox" checked={allowFx} onChange={(event) => setAllowFx(event.target.checked)} />默认允许换汇</label></div>
      </div>
      <button type="button" className={styles.primary} disabled={save.isPending} onClick={() => void save.mutateAsync({ refresh_time: refreshTime, provider_priority: value.provider_priority, default_tolerance: tolerance, minimum_trade_amount_cny: minimumTrade, allow_sell: allowSell, allow_fx: allowFx })}><Save size={16} aria-hidden="true" />保存通用设置</button>
    </section>
  );
}

export function ProviderSettings() {
  const providers = useProviderSettings();
  const general = useGeneralSettings();
  return (
    <section className={styles.settings} aria-labelledby="provider-settings-title">
      <header className={styles.sectionHeading}><div><p>PROVIDER SETTINGS</p><h2 id="provider-settings-title">供应商与密钥</h2></div><span>密钥加密保存在本机数据卷</span></header>
      {providers.isPending ? <p className={styles.muted}>正在载入供应商设置</p> : providers.isError ? <p className={styles.error} role="alert">供应商设置载入失败。</p> : <div className={styles.providerList}>{providers.data.map((item) => <ProviderRow item={item} key={item.provider} />)}</div>}
      {general.data ? <GeneralSettingsForm value={general.data} key={general.data.updated_at} /> : null}
    </section>
  );
}
