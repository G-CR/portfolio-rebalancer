import { useEffect, useState } from 'react';
import { useDecisionSettings, useSaveDecisionSettings } from './api';
import { formatDataTime } from '../analytics/format';
export function DecisionNotificationSettings() {
  const settings = useDecisionSettings(); const save = useSaveDecisionSettings();
  const [day, setDay] = useState(1); const [mode, setMode] = useState<'daily' | 'attention'>('daily'); const [monthly, setMonthly] = useState(false);
  useEffect(() => { if (settings.data) { setDay(settings.data.review_day); setMode(settings.data.notification_mode); setMonthly(settings.data.monthly_email); } }, [settings.data]);
  if (settings.isPending) return <p role="status">正在载入提醒设置...</p>;
  if (settings.isError) return <p role="alert">提醒设置无法载入。<button type="button" onClick={() => void settings.refetch()}>重试</button></p>;
  return <fieldset><legend>配置复核与通知频率</legend>
    <label>自动邮件模式<select value={mode} onChange={event => setMode(event.target.value as 'daily' | 'attention')}><option value="daily">每日邮件</option><option value="attention">仅需关注时通知</option></select></label>
    <label>每月复核日<input type="number" min={1} max={31} value={day} onChange={event => setDay(Number(event.target.value))} /></label>
    <label><input type="checkbox" checked={monthly} onChange={event => setMonthly(event.target.checked)} />月度复核到期邮件</label>
    <p>短月份按月底复核，使用上海时间。提醒需要 worker 运行；邮件总开关关闭时不发送。</p>
    <small>最近检查：{formatDataTime(settings.data?.last_checked_at ?? null)}</small>
    <button type="button" disabled={save.isPending || day < 1 || day > 31 || !Number.isInteger(day)} onClick={() => save.mutate({ review_day: day, notification_mode: mode, monthly_email: monthly })}>保存提醒设置</button>
    {save.isError ? <p role="alert">提醒设置保存失败，请重试。</p> : save.isSuccess ? <p role="status">提醒设置已保存</p> : null}
  </fieldset>;
}
