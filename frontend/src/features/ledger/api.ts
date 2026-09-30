import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiRequest, jsonBody } from '../../api/client';
import { portfolioAnalyticsKey } from '../../api/queryKeys';

export type LedgerKind = 'purchase' | 'sale' | 'dividend' | 'split' | 'manual_correction';
export type LedgerEntry = {
  id: string; holding_id: string; symbol: string; name: string; account_name: string;
  kind: LedgerKind | 'reversal'; occurred_on: string; created_at: string; currency: string;
  quantity: string; price: string; amount: string; fee: string; fee_currency: string;
  ratio: string; note: string | null; reference_cash_flow_cny: string | null;
  replaces_id: string | null; reverses_id: string | null; linked_entry_id: string | null;
  reference_details: { trade?: {status: string; reference_date?: string}; fee?: {status: string}; dividend_gross_amount?: string; dividend_tax?: string };
};
export type LedgerStatistics = {
  period: {id: string; opened_on: string} | null;
  currencies: {currency: string; unrealized: string; realized: string; dividends: string; opening_unrealized: string; period_pnl: string | null; complete: boolean; incomplete_reasons: string[]}[];
  reference_pnl_cny: string | null; incomplete_reasons: string[];
};
export type EntryPayload = {
  holding_id: string; kind: LedgerKind; occurred_on: string; quantity?: string; price?: string;
  amount?: string; fee?: string; fee_currency?: string; currency?: string; ratio?: string;
  gross_amount?: string; tax?: string; note?: string; idempotency_key: string;
  preview_token?: string; replaces_id?: string; linked_entry_id?: string;
};
export type EntryPreview = {
  preview_token: string; before: {quantity: string; average_cost_price: string};
  after: {quantity: string; average_cost_price: string; original_cost: string};
  reference_cash_flow_cny: string | null; original_fee_pending: boolean; incomplete_reasons: string[];
};
export type OpeningPreview = {
  opened_on: string; preview_token: string;
  items: {holding_id: string; symbol: string; currency: string; quantity: string; original_cost: string; market_price: string | null; reference_value_cny: string | null}[];
};
export const ledgerRoot = ['ledger'] as const;
export function useLedgerStatistics() {
  return useQuery({queryKey: [...ledgerRoot, 'statistics'], queryFn: () => apiRequest<LedgerStatistics>('/api/ledger/statistics')});
}
export function useLedgerEntries(filters: Record<string, string>) {
  const query = new URLSearchParams(Object.entries(filters).filter(([,value]) => value)).toString();
  return useQuery({queryKey: [...ledgerRoot, 'entries', filters], queryFn: () => apiRequest<LedgerEntry[]>(`/api/ledger/entries?${query}`)});
}
export function useLedgerWrite<T>(path: string, refresh = false) {
  const client = useQueryClient();
  return useMutation({mutationFn: (payload: object) => apiRequest<T>(`/api/ledger/${path}`, {method: 'POST', body: jsonBody(payload)}),
    onSuccess: () => { if (refresh) { void client.invalidateQueries({queryKey: ledgerRoot}); void client.invalidateQueries({queryKey: ['holdings']}); void client.invalidateQueries({queryKey: portfolioAnalyticsKey}); void client.invalidateQueries({queryKey: ['cost-adjustments']}); }} });
}
export function shanghaiDate() {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date());
  return ['year', 'month', 'day'].map((key) => parts.find((part) => part.type === key)?.value).join('-');
}
