import { CheckCircle2, KeyRound, Save, ShieldCheck } from "lucide-react";
import { useState } from "react";

import type { GeneralSettings, ProviderSetting } from "../../api/types";
import { FormField } from "../../components/FormField/FormField";
import { EmailSettingsForm } from "./EmailSettingsForm";
import {
  useGeneralSettings,
  useProviderSettings,
  useSaveGeneralSettings,
  useSaveProviderSetting,
  useTestProviderSetting,
} from "./api";
import styles from "../marketData/MarketData.module.css";

type ProviderDraft = { item: ProviderSetting; apiKey: string; enabled: boolean };

function ProviderList({ items }: { items: ProviderSetting[] }) {
  const save = useSaveProviderSetting();
  const test = useTestProviderSetting();
  const [draft, setDraft] = useState<ProviderDraft[]>(() => items.map((item) => ({ item, apiKey: "", enabled: item.enabled })));
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  function change(provider: ProviderSetting["provider"], patch: Partial<ProviderDraft>) {
    setMessage(null);
    setDraft((current) => current.map((row) => row.item.provider === provider ? { ...row, ...patch } : row));
  }
  function move(provider: ProviderSetting["provider"], position: number) {
    setMessage(null);
    setDraft((current) => {
      const next = [...current];
      const index = next.findIndex((row) => row.item.provider === provider);
      const [row] = next.splice(index, 1);
      next.splice(position - 1, 0, row);
      return next;
    });
  }
  async function submit() {
    setSaving(true);
    setMessage(null);
    try {
      // Saving in desired order makes each insert preserve the positions already saved.
      for (const [index, row] of draft.entries()) {
        await save.mutateAsync({ provider: row.item.provider, apiKey: row.apiKey || null, enabled: row.enabled, priority: index + 1 });
        setDraft((current) => current.map((item) => item.item.provider === row.item.provider ? { ...item, apiKey: "" } : item));
      }
      setMessage("数据源设置已保存。");
    } catch (error) {
      setMessage(`部分设置可能已保存，请检查后重试：${error instanceof Error ? error.message : "保存失败"}`);
    } finally {
      setSaving(false);
    }
  }

  return <>
    <div className={styles.providerList}>{draft.map((row, index) => {
      const item = items.find((value) => value.provider === row.item.provider) ?? row.item;
      return <fieldset className={styles.providerRow} aria-label={`${item.display_name} 设置`} key={item.provider} disabled={saving}>
        <div className={styles.providerIdentity}><strong>{item.display_name}</strong><span>{item.requires_key ? item.masked_key ?? "尚未配置密钥" : "无需密钥"}</span></div>
        <div data-provider-cell="priority"><FormField label="优先级"><select value={String(index + 1)} onChange={(event) => move(item.provider, Number(event.target.value))}>{draft.map((_, i) => <option value={i + 1} key={i + 1}>{i + 1}</option>)}</select></FormField></div>
        {item.requires_key ? <div data-provider-cell="credential"><FormField label="凭据"><input type="password" aria-label="API 密钥" autoComplete="new-password" value={row.apiKey} placeholder={item.masked_key ?? "输入新密钥"} onChange={(event) => change(item.provider, { apiKey: event.target.value })} /></FormField></div> : <div className={styles.providerField} data-provider-cell="credential"><span className={styles.providerFieldLabel}>凭据</span><div className={styles.noKey}><ShieldCheck size={16} aria-hidden="true" />公开数据源</div></div>}
        <div className={styles.providerField} data-provider-cell="status"><span className={styles.providerFieldLabel}>状态</span>{item.requires_key ? <label className={styles.enabled}><input type="checkbox" checked={row.enabled} onChange={(event) => change(item.provider, { enabled: event.target.checked })} />启用</label> : <span className={styles.enabled}><CheckCircle2 size={15} aria-hidden="true" />启用</span>}</div>
        <div className={styles.providerField} data-provider-cell="actions"><span className={styles.providerFieldLabel}>操作</span><div className={styles.providerActions}>{item.requires_key && item.key_status === "configured" ? <button type="button" className={styles.ghost} onClick={() => void test.mutateAsync(item.provider)} disabled={test.isPending}><KeyRound size={15} aria-hidden="true" />测试</button> : null}</div></div>
        {item.validation_status ? <small className={item.validation_status === "valid" ? styles.validationGood : styles.validationBad}>{item.validation_status === "valid" ? "最近验证成功" : "最近验证失败"}</small> : null}
      </fieldset>;
    })}</div>
    {message ? <p role="status">{message}</p> : null}
    <button type="button" className={styles.primary} disabled={saving} onClick={() => void submit()}><Save size={16} aria-hidden="true" />{saving ? "正在保存" : "保存数据源设置"}</button>
  </>;
}

function GeneralSettingsForm({ value }: { value: GeneralSettings }) {
  const save = useSaveGeneralSettings();
  const [refreshTime, setRefreshTime] = useState(value.refresh_time);
  const [tolerance, setTolerance] = useState(value.default_tolerance);
  const [allowSell, setAllowSell] = useState(value.allow_sell);
  const [allowFx, setAllowFx] = useState(value.allow_fx);

  return (
    <section className={styles.generalSettings} aria-labelledby="general-settings-title">
      <header className={styles.sectionHeading}><div><p>DEFAULT RULES</p><h2 id="general-settings-title">自动刷新与再平衡默认值</h2></div></header>
      <div className={styles.generalGrid}>
        <FormField label="每日刷新时间"><input type="time" value={refreshTime} onChange={(event) => setRefreshTime(event.target.value)} /></FormField>
        <FormField label="默认允许偏离" suffix="比例"><input inputMode="decimal" value={tolerance} onChange={(event) => setTolerance(event.target.value)} /></FormField>
        <div className={styles.defaultSwitches}><label><input type="checkbox" checked={allowSell} onChange={(event) => setAllowSell(event.target.checked)} />默认允许卖出</label><label><input type="checkbox" checked={allowFx} onChange={(event) => setAllowFx(event.target.checked)} />默认允许换汇</label></div>
      </div>
      <button type="button" className={styles.primary} disabled={save.isPending} onClick={() => void save.mutateAsync({ refresh_time: refreshTime, provider_priority: value.provider_priority, default_tolerance: tolerance, allow_sell: allowSell, allow_fx: allowFx })}><Save size={16} aria-hidden="true" />保存通用设置</button>
    </section>
  );
}

export function ProviderSettings() {
  const providers = useProviderSettings();
  const general = useGeneralSettings();
  return (
    <section className={styles.settings} aria-labelledby="provider-settings-title">
      <header className={styles.sectionHeading}><div><p>PROVIDER SETTINGS</p><h2 id="provider-settings-title">供应商与密钥</h2></div><span>密钥加密保存在本机数据卷</span></header>
      {providers.isPending ? <p className={styles.muted}>正在载入供应商设置</p> : providers.isError ? <p className={styles.error} role="alert">供应商设置载入失败。</p> : <ProviderList items={providers.data} />}
      {general.data ? <GeneralSettingsForm value={general.data} key={general.data.updated_at} /> : null}
      <EmailSettingsForm />
    </section>
  );
}
