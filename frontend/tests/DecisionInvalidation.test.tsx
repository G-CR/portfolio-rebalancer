import { QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { createQueryClient } from '../src/app/providers';
import { decisionQueryKey } from '../src/features/decision/api';
import { useRefreshMarketData, useSetMarketDataOverride } from '../src/features/marketData/api';
import { useStartRebalancePlan } from '../src/features/rebalance/api';
import { server } from './testProviders';
function hook<T>(useHook: () => T) {
  const client = createQueryClient(); client.setQueryData(decisionQueryKey, {});
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, ...renderHook(useHook, { wrapper }) };
}
it('invalidates current decision even when manual refresh retains incomplete required data', async () => {
  server.use(http.post('/api/market-data/refresh', () => HttpResponse.json({ items: [{ effective_value: null }], diagnostics: [] })));
  const refreshed = hook(useRefreshMarketData);
  await act(() => refreshed.result.current.mutateAsync());
  expect(refreshed.client.getQueryState(decisionQueryKey)?.isInvalidated).toBe(true);
});
it('invalidates current decision after manual data override and active-plan transition', async () => {
  server.use(http.post('/api/market-data/price:SPY/override', () => HttpResponse.json({})), http.post('/api/rebalance/plans/plan/start', () => HttpResponse.json({})));
  const override = hook(useSetMarketDataOverride);
  await act(() => override.result.current.mutateAsync({ key: 'price:SPY', payload: { value: '100', note: 'manual', expires_at: null } }));
  expect(override.client.getQueryState(decisionQueryKey)?.isInvalidated).toBe(true);
  const started = hook(useStartRebalancePlan);
  await act(() => started.result.current.mutateAsync({ planId: 'plan', idempotencyKey: 'key' }));
  expect(started.client.getQueryState(decisionQueryKey)?.isInvalidated).toBe(true);
});
