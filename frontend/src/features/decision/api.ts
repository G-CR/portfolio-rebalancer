import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiRequest, jsonBody } from '../../api/client';
import { portfolioAnalyticsKey } from '../../api/queryKeys';
export const decisionQueryKey = [...portfolioAnalyticsKey, 'decision'] as const;
export interface LongTermDecision {
  status: 'setup' | 'data_issue' | 'in_progress' | 'sustained' | 'observing' | 'normal';
  title: string; reason: string;
  classes: { id: string; name: string; target_weight: string; actual_weight: string; drift: string; direction: number; observations: number }[];
  issues: { key?: string; symbol?: string; status?: string }[];
  has_manual_data: boolean; latest_valid_date: string | null; last_checked_at: string | null;
  active_plan_id: string | null; review_date: string; review_due: boolean; last_reviewed_at: string | null;
}
export interface DecisionSettings {
  review_day: number; notification_mode: 'daily' | 'attention'; monthly_email: boolean;
  last_checked_at: string | null; last_reviewed_at: string | null;
}
export function useDecision() { return useQuery({ queryKey: decisionQueryKey, queryFn: () => apiRequest<LongTermDecision>('/api/decision') }); }
export function useDecisionSettings() { return useQuery({ queryKey: ['decision-settings'], queryFn: () => apiRequest<DecisionSettings>('/api/decision/settings') }); }
export function useSaveDecisionSettings() {
  const client = useQueryClient();
  return useMutation({ mutationFn: (value: Pick<DecisionSettings, 'review_day' | 'notification_mode' | 'monthly_email'>) => apiRequest<DecisionSettings>('/api/decision/settings', { method: 'PUT', body: jsonBody(value) }), onSuccess: () => { void client.invalidateQueries({ queryKey: ['decision-settings'] }); void client.invalidateQueries({ queryKey: decisionQueryKey }); } });
}
export function useReviewDecision() {
  const client = useQueryClient();
  return useMutation({ mutationFn: () => apiRequest<LongTermDecision>('/api/decision/review', { method: 'POST' }), onSuccess: (result) => client.setQueryData(decisionQueryKey, result) });
}
