from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from html import escape
import json
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.db.decision_models import DecisionPolicy, DecisionObservation, NotificationOutbox
from app.db.models import AssetClass, Setting, RebalancePlan
from app.domain.decision import advance_streaks, decision_status, next_review, evidence_current
from app.services.analytics import get_portfolio_analytics
from app.services.errors import ServiceError
from app.services.email_settings import load_email_config
from app.services.email_sender import send_email

async def load_policy(session, *, lock=False):
    await session.execute(insert(DecisionPolicy).values(id=1, review_day=1, notification_mode='daily', monthly_email=False, streaks={}, anomalies={}).on_conflict_do_nothing())
    query = select(DecisionPolicy).where(DecisionPolicy.id == 1)
    return await session.scalar(query.with_for_update() if lock else query)

async def fingerprint(session):
    targets = (await session.execute(select(AssetClass.id, AssetClass.target_weight).where(AssetClass.is_active.is_(True)).order_by(AssetClass.id))).all()
    tolerance = await session.scalar(select(Setting.default_tolerance).limit(1))
    return sha256(json.dumps([[(str(i), str(w)) for i,w in targets], str(tolerance)], sort_keys=True).encode()).hexdigest()

async def reset_changed_rules(session, policy):
    current = await fingerprint(session)
    if policy.rule_fingerprint != current:
        policy.rule_fingerprint = current
        policy.streaks = {}
        policy.anomalies = {}
    return current

async def expire_old_evidence(session, policy, now):
    latest = await session.scalar(select(DecisionObservation.local_date).order_by(DecisionObservation.local_date.desc()).limit(1))
    if not evidence_current(now.astimezone(ZoneInfo('Asia/Shanghai')).date(), latest):
        policy.streaks = {}
        policy.anomalies = {}

async def current_inputs(session):
    try:
        analytics = await get_portfolio_analytics(session)
    except ServiceError as exc:
        if exc.code != 'PORTFOLIO_DATA_INCOMPLETE': raise
        return None, exc.extra.get('items', [])
    issues = [item.model_dump(mode='json') for item in analytics.data_inputs if item.status not in {'valid', 'manual'}]
    return analytics, issues

async def get_decision(session, *, now=None):
    now = now or datetime.now(UTC)
    policy = await load_policy(session, lock=True)
    await reset_changed_rules(session, policy)
    await expire_old_evidence(session, policy, now)
    analytics, issues = await current_inputs(session)
    plan = await session.scalar(select(RebalancePlan).where(RebalancePlan.status == 'in_progress').order_by(RebalancePlan.created_at.desc()).limit(1))
    classes = []
    for item in analytics.asset_classes if analytics else []:
        direction = 1 if item.drift > analytics.tolerance else -1 if item.drift < -analytics.tolerance else 0
        state = policy.streaks.get(str(item.id), {})
        count = state.get('count', 0) if state.get('direction') == direction and direction else 0
        classes.append({'id': str(item.id), 'name': item.name, 'target_weight': str(item.target_weight), 'actual_weight': str(item.actual_weight), 'drift': str(item.drift), 'direction': direction, 'observations': count})
    status = decision_status(bool(analytics and analytics.data_status == 'setup'), not issues and analytics is not None, plan is not None, any(c['observations'] >= 3 for c in classes), any(c['direction'] for c in classes))
    title, reason = {
        'setup': ('开始建立组合', '添加第一个持仓后查看配置。'),
        'data_issue': ('检查组合数据', '必要行情或汇率缺失或过期，暂不提供配置行动结论。'),
        'in_progress': ('再平衡进行中', '返回现有方案继续手动维护。'),
        'sustained': ('持续越界，值得复核', '同一类别同一方向已连续三次有效日终观察越界，可先测算新增资金。'),
        'observing': ('刚刚越界，继续观察', '当前偏离超出允许区间，可观察或随月度新增资金复核。'),
        'normal': ('配置正常', '全部类别在允许偏离区间内。'),
    }[status]
    due, overdue = next_review(now.astimezone(ZoneInfo('Asia/Shanghai')).date(), policy.review_day, policy.acknowledged_month)
    return {'status': status, 'title': title, 'reason': reason, 'classes': classes, 'issues': issues, 'has_manual_data': bool(analytics and analytics.has_manual_data), 'latest_valid_date': policy.latest_valid_date, 'last_checked_at': policy.last_checked_at, 'active_plan_id': str(plan.id) if plan else None, 'review_date': due, 'review_due': overdue, 'last_reviewed_at': policy.last_reviewed_at}

async def queue_event(session, key, subject, html):
    await session.execute(insert(NotificationOutbox).values(event_key=key, subject=subject, html=html, status='pending', attempts=0).on_conflict_do_nothing())

async def queue_monthly_review(session, policy, now):
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    _, due = next_review(today, policy.review_day, policy.acknowledged_month)
    if policy.monthly_email and due:
        await queue_event(session, 'review:' + today.strftime('%Y-%m'), '本月配置待复核', '<p>本月配置待复核。复核是提醒，不要求交易；完成后请在首页点击已复核。</p>')

async def record_scheduled_observation(session, *, now=None, snapshot_complete=True):
    now = now or datetime.now(UTC)
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
    policy = await load_policy(session, lock=True)
    rule = await reset_changed_rules(session, policy)
    policy.last_checked_at = now
    await queue_monthly_review(session, policy, now)
    if await session.get(DecisionObservation, today): return False
    last_date = await session.scalar(select(DecisionObservation.local_date).order_by(DecisionObservation.local_date.desc()).limit(1))
    if last_date and (today - last_date).days > 1:
        policy.streaks = {}
        policy.anomalies = {}
    analytics, issues = await current_inputs(session)
    valid = bool(snapshot_complete and analytics and analytics.data_status != 'setup' and not issues)
    classes = [{'id': str(c.id), 'name': c.name, 'target_weight': str(c.target_weight), 'actual_weight': str(c.actual_weight), 'drift': str(c.drift)} for c in analytics.asset_classes] if analytics else []
    directions = {c['id']: 1 if Decimal(c['drift']) > analytics.tolerance else -1 if Decimal(c['drift']) < -analytics.tolerance else 0 for c in classes} if analytics else {}
    policy.streaks = advance_streaks(policy.streaks, directions, valid, today.isoformat())
    keys = sorted({str(i.get('key') or i.get('symbol')) for i in issues})
    old_anomalies = policy.anomalies
    policy.anomalies = {key: {'count': old_anomalies.get(key, {}).get('count', 0) + 1, 'started': old_anomalies.get(key, {}).get('started', today.isoformat())} for key in keys}
    if valid: policy.latest_valid_date = today
    session.add(DecisionObservation(local_date=today, valid=valid, has_manual_data=bool(analytics and analytics.has_manual_data), rule_fingerprint=rule, classes=classes, anomaly_keys=keys, captured_at=now))
    if policy.notification_mode == 'attention':
        for c in classes:
            state = policy.streaks.get(c['id'], {})
            if state.get('count', 0) >= 3:
                key = f"drift:{rule}:{c['id']}:{state['direction']}:{state['started']}"
                html = '<p>持续越界，值得复核；可先测算新增资金。</p><p>' + escape(f"{c['name']}：目标 {Decimal(c['target_weight']):.1%}，实际 {Decimal(c['actual_weight']):.1%}，偏离 {Decimal(c['drift'])*100:+.1f} 个百分点，连续 {state['count']} 次有效日终观察。") + '</p>'
                await queue_event(session, key, '投资组合持续越界提醒', html)
        for key, state in policy.anomalies.items():
            if state['count'] >= 2:
                await queue_event(session, f"anomaly:{key}:{state['started']}", '投资组合数据异常提醒', '<p>连续两次不同日期的定时检查仍存在数据异常：' + escape(key) + '。请检查数据源。</p>')
    return True

async def deliver_pending_notifications(session, *, now=None):
    now = now or datetime.now(UTC)
    policy = await load_policy(session, lock=True)
    await reset_changed_rules(session, policy)
    await expire_old_evidence(session, policy, now)
    config = await load_email_config(session)
    if config is None: return
    await queue_monthly_review(session, policy, now)
    rows = list(await session.scalars(select(NotificationOutbox).where(NotificationOutbox.status == 'pending').order_by(NotificationOutbox.created_at).with_for_update(skip_locked=True)))
    live_analytics, live_issues = await current_inputs(session) if any(r.event_key.startswith(('drift:', 'anomaly:')) for r in rows) else (None, [])
    active_plan = await session.scalar(select(RebalancePlan.id).where(RebalancePlan.status == 'in_progress').limit(1))
    live_directions = {str(c.id): 1 if c.drift > live_analytics.tolerance else -1 if c.drift < -live_analytics.tolerance else 0 for c in live_analytics.asset_classes} if live_analytics and not live_issues else {}
    live_anomalies = {str(i.get('key') or i.get('symbol')) for i in live_issues}
    for row in rows:
        if row.event_key.startswith('drift:') or row.event_key.startswith('anomaly:'):
            if policy.notification_mode != 'attention': continue
            active_keys = {f"drift:{policy.rule_fingerprint}:{key}:{state['direction']}:{state['started']}" for key, state in policy.streaks.items() if state.get('count', 0) >= 3 and live_directions.get(key) == state.get('direction') and active_plan is None}
            active_keys.update(f"anomaly:{key}:{state['started']}" for key, state in policy.anomalies.items() if state.get('count', 0) >= 2 and key in live_anomalies)
            if row.event_key not in active_keys: continue
        elif row.event_key.startswith('review:'):
            today = now.astimezone(ZoneInfo('Asia/Shanghai')).date()
            month = today.strftime('%Y-%m')
            _, due = next_review(today, policy.review_day, policy.acknowledged_month)
            if not due: continue
            if not policy.monthly_email or row.event_key != 'review:' + month or policy.acknowledged_month == month: continue
        row.attempts += 1
        try:
            await send_email(config, subject=row.subject, html=row.html)
        except Exception:
            row.last_error = '邮件发送失败，可重试。'
        else:
            row.status = 'sent'
            row.sent_at = now
            row.last_error = None
