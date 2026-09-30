import { Link } from 'react-router-dom';
import { CircleCheck, TriangleAlert, ArrowRight } from 'lucide-react';
import type { LongTermDecision } from './api';
import { useReviewDecision } from './api';
import { formatSignedPercentagePoints, formatDataTime } from '../analytics/format';
import styles from '../analytics/Analytics.module.css';
export function LongTermDecisionBanner({ decision }: { decision: LongTermDecision }) {
  const review = useReviewDecision();
  const Icon = decision.status === 'normal' ? CircleCheck : TriangleAlert;
  const action = decision.status === 'setup' ? { to: '/holdings', label: '添加第一个持仓' } : decision.status === 'data_issue' ? { to: '/data-sources', label: '检查数据' } : decision.status === 'in_progress' ? { to: '/rebalance', label: '继续现有方案' } : { to: '/rebalance', label: '测算本月新增资金' };
  return <div>
    <section className={styles.decision} data-status={decision.status} aria-labelledby="decision-title">
      <Icon size={22} aria-hidden="true" /><div className={styles.decisionCopy}><p>当前配置判断</p><h2 id="decision-title">{decision.title}</h2><span>{decision.reason}</span>
        {decision.has_manual_data ? <small>包含有效手动行情</small> : null}
        {decision.classes.filter(c => c.direction !== 0).map(c => <p key={c.id}>{c.name} · 当前偏离 {formatSignedPercentagePoints(c.drift)} · 连续 {c.observations} 次有效日终观察</p>)}
        <small>最近有效观察：{decision.latest_valid_date ?? '尚无'} · 日终观察仅由定时刷新记录</small>
        {decision.issues.map((i, index) => <p key={index}>{i.key ?? i.symbol} · {i.status}</p>)}
      </div><Link className={styles.decisionAction} to={action.to}>{action.label}<ArrowRight size={15} /></Link>
      {decision.active_plan_id && decision.status === 'data_issue' ? <Link to="/rebalance">继续现有方案</Link> : null}
    </section>
    {decision.status !== 'setup' ? <section className={styles.monthlyReview} aria-label="月度配置复核"><div><p>{decision.review_due ? '本月配置待复核' : '下次月度复核'} · {decision.review_date}</p><small>上次复核：{formatDataTime(decision.last_reviewed_at)}。完成测算后仍需手动确认复核。</small></div>{decision.review_due ? <button type="button" onClick={() => review.mutate()} disabled={review.isPending}>已复核</button> : null}{review.isError ? <p role="alert">复核确认失败，请重试。</p> : null}</section> : null}
  </div>;
}
