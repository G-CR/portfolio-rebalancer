import { Link } from 'react-router-dom';
import { useLedgerStatistics } from './api';
import { formatSignedAmount } from '../analytics/format';
import styles from '../../pages/LedgerPage.module.css';

export function PeriodPnl() {
  const statistics = useLedgerStatistics();
  if (statistics.isPending) return <section className={styles.section} role="status">正在载入期间损益</section>;
  if (statistics.isError) return <section className={styles.section} role="alert">期间损益载入失败。<button onClick={() => void statistics.refetch()}>重试</button></section>;
  const data = statistics.data;
  if (!data.period) return <section className={styles.section}><h3>长期投资损益</h3><p>建立期初后，按币种追踪期间损益、已实现盈亏与分红。</p><Link to="/ledger">核对并建立今日期初</Link></section>;
  return <section className={styles.section} aria-labelledby="period-pnl-title"><h3 id="period-pnl-title">期间投资损益 · 原币口径</h3><p>启用日期 {data.period.opened_on}，已扣除期初浮动盈亏。</p>
    <div className={styles.tableWrap}><table><thead><tr><th>币种</th><th>当前浮动</th><th>已实现</th><th>分红净收入</th><th>期间损益</th></tr></thead><tbody>{data.currencies.map((item) => <tr key={item.currency}><th scope="row">{item.currency}</th><td>{formatSignedAmount(item.unrealized)}</td><td>{formatSignedAmount(item.realized)}</td><td>{formatSignedAmount(item.dividends)}</td><td>{item.period_pnl === null ? '不完整' : formatSignedAmount(item.period_pnl)}</td></tr>)}</tbody></table></div>
    <p>人民币参考期间损益：{data.reference_pnl_cny === null ? '待补全' : formatSignedAmount(data.reference_pnl_cny)}。采用冻结期初估值与逐笔参考现金流，不表示实际换汇盈亏或收益率。</p>
    {data.incomplete_reasons.length ? <ul>{data.incomplete_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : null}<Link to="/ledger">查看投资流水与记录操作</Link></section>;
}
