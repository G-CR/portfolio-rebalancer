import { useState } from 'react';
import { ApiError } from '../api/client';
import { FormField } from '../components/FormField/FormField';
import { useHoldings } from '../features/holdings/api';
import { formatAmount } from '../features/analytics/format';
import { type EntryPayload, type EntryPreview, type LedgerEntry, type LedgerKind, type OpeningPreview, shanghaiDate, useLedgerEntries, useLedgerStatistics, useLedgerWrite } from '../features/ledger/api';
import styles from './LedgerPage.module.css';

const labels = {purchase: '买入', sale: '卖出', dividend: '现金分红', split: '份额折算', manual_correction: '人工修正', reversal: '冲销'};
const amount = (value: string | null) => value === null ? '待补全' : formatAmount(value);
const errorText = (error: unknown) => error instanceof ApiError ? error.message : '操作失败，请检查输入后重试。';

export function LedgerPage() {
  const summary = useLedgerStatistics();
  const holdings = useHoldings(true);
  const [filters, setFilters] = useState({holding_id: '', account: '', kind: '', date_from: '', date_to: ''});
  const entries = useLedgerEntries(filters);
  const openingPreview = useLedgerWrite<OpeningPreview>('opening/preview');
  const openingConfirm = useLedgerWrite('opening/confirm', true);
  const previewWrite = useLedgerWrite<EntryPreview>('entries/preview');
  const confirmWrite = useLedgerWrite('entries/confirm', true);
  const [openingKey] = useState(() => crypto.randomUUID());
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [holdingId, setHoldingId] = useState('');
  const [kind, setKind] = useState<LedgerKind>('purchase');
  const [on, setOn] = useState(shanghaiDate);
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const [fee, setFee] = useState('0');
  const [currency, setCurrency] = useState('');
  const [feeCurrency, setFeeCurrency] = useState('');
  const [net, setNet] = useState('');
  const [gross, setGross] = useState('');
  const [tax, setTax] = useState('');
  const [ratio, setRatio] = useState('');
  const [note, setNote] = useState('');
  const [replaces, setReplaces] = useState('');
  const [linked, setLinked] = useState('');
  const [previewFingerprint, setPreviewFingerprint] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const holding = holdings.data?.find((item) => item.id === holdingId);
  const payload: EntryPayload = {holding_id: holdingId, kind, occurred_on: on, idempotency_key: key,
    ...(note ? {note} : {}), ...(replaces ? {replaces_id: replaces} : {}),
    ...(kind === 'purchase' && linked ? {linked_entry_id: linked} : {}),
    ...(kind === 'purchase' || kind === 'sale' ? {quantity, price, fee, fee_currency: feeCurrency || holding?.trade_currency} : {}),
    ...(kind === 'dividend' ? {amount: net, currency: currency || holding?.trade_currency, ...(gross || tax ? {gross_amount: gross, tax} : {})} : {}),
    ...(kind === 'split' ? {ratio} : {}), ...(kind === 'manual_correction' ? {quantity, amount: net} : {})};
  const fingerprint = JSON.stringify(payload);
  const preview = fingerprint === previewFingerprint ? previewWrite.data : undefined;

  async function action(work: () => Promise<unknown>) {
    setError(''); setSuccess('');
    try { await work(); } catch (caught) { setError(errorText(caught)); }
  }
  function correct(item: LedgerEntry) {
    if (item.kind === 'reversal') return;
    setHoldingId(item.holding_id); setKind(item.kind); setOn(item.occurred_on);
    setQuantity(item.quantity); setPrice(item.price); setFee(item.fee); setFeeCurrency(item.fee_currency);
    setCurrency(item.currency); setNet(item.amount); setRatio(item.ratio); setReplaces(item.id);
    setGross(item.reference_details.dividend_gross_amount ?? ''); setTax(item.reference_details.dividend_tax ?? '');
    setLinked(item.linked_entry_id ?? ''); setNote(''); setPreviewFingerprint('');
    document.getElementById('ledger-entry-form')?.scrollIntoView({behavior: 'smooth'});
  }
  if (summary.isPending) return <section role="status">正在载入投资记录</section>;
  if (summary.isError) return <section role="alert"><p>{errorText(summary.error)}</p><button onClick={() => void summary.refetch()}>重试</button></section>;
  const data = summary.data;
  return <section className={styles.page} aria-labelledby="ledger-title">
    <header><p className={styles.eyebrow}>INVESTMENT LEDGER</p><h2 id="ledger-title">投资记录与期间损益</h2><p>{data.period ? `启用日期 ${data.period.opened_on}` : '核对今天的持仓，建立期初后开始记录。无需追溯过去交易。'}</p></header>
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
    {success ? <p role="status">{success}</p> : null}
    {!data.period ? <section className={styles.section} aria-label="启用长期账本"><h3>建立今日期初</h3><p>期初已有浮动盈亏不会计入启用后期间损益。原币成本保留，旧成本汇率标为历史估算。</p>
      <button disabled={openingPreview.isPending || openingConfirm.isPending} onClick={() => void action(() => openingPreview.mutateAsync({idempotency_key: openingKey}))}>预览今日期初</button>
      {openingPreview.data ? <><div className={styles.tableWrap}><table><thead><tr><th>标的</th><th>份额</th><th>原币成本</th><th>期初价格</th><th>人民币参考市值</th></tr></thead><tbody>{openingPreview.data.items.map((item) => <tr key={item.holding_id}><td>{item.symbol}</td><td>{item.quantity}</td><td>{item.currency} {amount(item.original_cost)}</td><td>{amount(item.market_price)}</td><td>{amount(item.reference_value_cny)}</td></tr>)}</tbody></table></div><p>启用日期 {openingPreview.data.opened_on}。缺失估值会使期间结果显示待补全。</p><button disabled={openingConfirm.isPending} onClick={() => void action(() => openingConfirm.mutateAsync({idempotency_key: openingKey, preview_token: openingPreview.data!.preview_token}))}>核对无误，确认启用</button></> : null}
    </section> : <>
      <section className={styles.section}><h3>按原币统计</h3><div className={styles.tableWrap}><table><thead><tr><th>币种</th><th>当前浮动盈亏</th><th>启用后已实现</th><th>分红净收入</th><th>期初浮动盈亏</th><th>期间损益</th></tr></thead><tbody>{data.currencies.map((item) => <tr key={item.currency}><th scope="row">{item.currency}</th><td>{amount(item.unrealized)}</td><td>{amount(item.realized)}</td><td>{amount(item.dividends)}</td><td>{amount(item.opening_unrealized)}</td><td>{item.complete ? amount(item.period_pnl) : '不完整'}</td></tr>)}</tbody></table></div><p>期间损益 = 当前浮动 + 启用后已实现 + 分红净收入 − 期初浮动。费用已计入，币种分别展示。</p><strong>{data.reference_pnl_cny === null ? '人民币参考：待补全' : `人民币参考期间损益 ${amount(data.reference_pnl_cny)}`}</strong><p>采用冻结期初参考市值与逐笔参考现金流，不代表实际换汇盈亏或收益率，不包含池外外币现金收益。</p>{data.incomplete_reasons.length ? <ul>{data.incomplete_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : null}</section>
      <section className={styles.section} id="ledger-entry-form"><h3>{replaces ? '更正流水' : '记录投资操作'}</h3>{replaces ? <p>原流水保留，通过冲销与替代重放成本链。<button onClick={() => {setReplaces(''); setKey(crypto.randomUUID());}}>取消更正</button></p> : null}
        <div className={styles.fields}>
          <FormField label="标的" required><select value={holdingId} onChange={(event) => setHoldingId(event.target.value)}><option value="">选择标的与账户</option>{holdings.data?.map((item) => <option key={item.id} value={item.id}>{item.symbol} · {item.account_name}{item.is_active ? '' : ' · 已归档'}</option>)}</select></FormField>
          <FormField label="操作类型"><select value={kind} onChange={(event) => setKind(event.target.value as LedgerKind)}>{Object.entries(labels).filter(([value]) => value !== 'reversal').map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>
          <FormField label="发生日期" required><input type="date" min={data.period.opened_on} max={shanghaiDate()} value={on} onChange={(event) => setOn(event.target.value)} /></FormField>
          {kind === 'purchase' || kind === 'sale' || kind === 'manual_correction' ? <FormField label="份额" required><input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></FormField> : null}
          {kind === 'purchase' || kind === 'sale' ? <><FormField label="成交价格" required suffix={holding?.trade_currency}><input inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} /></FormField><FormField label="实际费用"><input inputMode="decimal" value={fee} onChange={(event) => setFee(event.target.value)} /></FormField><FormField label="费用币种"><input value={feeCurrency} placeholder={holding?.trade_currency} onChange={(event) => setFeeCurrency(event.target.value.toUpperCase())} /></FormField></> : null}
          {kind === 'dividend' || kind === 'manual_correction' ? <FormField label={kind === 'dividend' ? '净到账金额' : '修正后原币总成本'} required><input inputMode="decimal" value={net} onChange={(event) => setNet(event.target.value)} /></FormField> : null}
          {kind === 'dividend' ? <><FormField label="到账币种"><input placeholder={holding?.trade_currency} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} /></FormField><FormField label="税前金额（选填）"><input inputMode="decimal" value={gross} onChange={(event) => setGross(event.target.value)} /></FormField><FormField label="扣税（选填）"><input inputMode="decimal" value={tax} onChange={(event) => setTax(event.target.value)} /></FormField></> : null}
          {kind === 'split' ? <FormField label="折算比例（新份额 ÷ 原份额）" required><input inputMode="decimal" value={ratio} onChange={(event) => setRatio(event.target.value)} /></FormField> : null}
          {kind === 'purchase' ? <FormField label="关联分红再投资"><select value={linked} onChange={(event) => setLinked(event.target.value)}><option value="">普通买入</option>{entries.data?.filter((item) => item.kind === 'dividend' && item.holding_id === holdingId && !entries.data?.some((other) => other.reverses_id === item.id)).map((item) => <option key={item.id} value={item.id}>{item.occurred_on} · {item.currency} {item.amount}</option>)}</select></FormField> : null}
          <FormField label="备注／更正原因" required={Boolean(replaces) || kind === 'manual_correction'}><textarea value={note} onChange={(event) => setNote(event.target.value)} /></FormField>
        </div>
        <p>系统自动引用发生日参考汇率。当日值暂估，日终定稿；外币参考缺失仍可记录原币操作。</p>
        <button disabled={!holdingId || previewWrite.isPending || confirmWrite.isPending} onClick={() => void action(async () => {await previewWrite.mutateAsync(payload); setPreviewFingerprint(fingerprint);})}>预览持仓与成本变化</button>
        {preview ? <div className={styles.preview}><p>份额 {preview.before.quantity} → {preview.after.quantity}</p><p>平均原币成本 {amount(preview.before.average_cost_price)} → {amount(preview.after.average_cost_price)}</p><p>原币总成本 {amount(preview.after.original_cost)} · 人民币参考现金流 {amount(preview.reference_cash_flow_cny)}</p>{preview.original_fee_pending ? <p>跨币种费用折算待补全，原币成本暂不完整。</p> : null}<button disabled={confirmWrite.isPending} onClick={() => void action(async () => {await confirmWrite.mutateAsync({...payload, preview_token: preview.preview_token}); setKey(crypto.randomUUID()); setPreviewFingerprint(''); setReplaces(''); setSuccess('流水已记录，持仓与成本已同步更新。');})}>确认记录</button></div> : null}
      </section>
    </>}
    <section className={styles.section}><h3>投资流水</h3><div className={styles.fields}>
      <FormField label="标的筛选"><select value={filters.holding_id} onChange={(event) => setFilters({...filters, holding_id: event.target.value})}><option value="">全部标的（含归档）</option>{holdings.data?.map((item) => <option key={item.id} value={item.id}>{item.symbol} · {item.account_name}</option>)}</select></FormField>
      <FormField label="账户筛选"><input value={filters.account} onChange={(event) => setFilters({...filters, account: event.target.value})} /></FormField>
      <FormField label="类型筛选"><select value={filters.kind} onChange={(event) => setFilters({...filters, kind: event.target.value})}><option value="">全部类型</option>{Object.entries(labels).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>
      <FormField label="开始日期"><input type="date" value={filters.date_from} onChange={(event) => setFilters({...filters, date_from: event.target.value})} /></FormField><FormField label="结束日期"><input type="date" value={filters.date_to} onChange={(event) => setFilters({...filters, date_to: event.target.value})} /></FormField>
    </div>{entries.isError ? <p role="alert">流水载入失败。<button onClick={() => void entries.refetch()}>重试</button></p> : entries.isPending ? <p role="status">正在载入流水</p> : entries.data.length === 0 ? <p>暂无匹配流水。记录一笔成交、分红或份额折算后可在这里追踪。</p> : <div className={styles.tableWrap}><table><thead><tr><th>发生日期</th><th>标的／账户</th><th>类型</th><th>份额／金额</th><th>费用</th><th>参考状态</th><th>审计</th></tr></thead><tbody>{entries.data.map((item) => <tr key={item.id}><td>{item.occurred_on}<small>录入 {new Date(item.created_at).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai'})}</small></td><td>{item.symbol}<small>{item.account_name}</small></td><td>{labels[item.kind]}</td><td>{item.kind === 'dividend' ? `${item.currency} ${amount(item.amount)}` : item.kind === 'split' ? `× ${item.ratio}` : `${item.quantity} × ${item.price} ${item.currency}`}</td><td>{item.fee} {item.fee_currency}</td><td>{item.reference_details.trade?.status === 'provisional' ? '当日暂估' : item.reference_details.trade?.status === 'fallback' ? `回退 ${item.reference_details.trade.reference_date}` : item.reference_cash_flow_cny === null ? '待补全' : '已定稿'}</td><td>{item.reverses_id ? '冲销原流水' : item.replaces_id ? '替代原流水' : item.linked_entry_id ? '分红再投资' : '原始记录'}<small>{item.note}</small>{item.kind !== 'reversal' && !entries.data.some((other) => other.reverses_id === item.id) ? <button onClick={() => correct(item)}>更正</button> : null}</td></tr>)}</tbody></table></div>}</section>
  </section>;
}
