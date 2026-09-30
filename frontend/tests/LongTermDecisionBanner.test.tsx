import { screen, fireEvent } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { LongTermDecisionBanner } from '../src/features/decision/LongTermDecisionBanner';
import { decisionFixture, renderWithProviders } from './testProviders';
import type { LongTermDecision } from '../src/features/decision/api';
it('keeps active plan accessible when data is invalid and acknowledges monthly review explicitly', async () => {
  let acknowledged = false;
  renderWithProviders(<LongTermDecisionBanner decision={{ ...decisionFixture, status: 'data_issue', title: '检查组合数据', active_plan_id: 'plan', review_due: true } as LongTermDecision} />, { handlers: [http.post('/api/decision/review', () => { acknowledged = true; return HttpResponse.json(decisionFixture); })] });
  expect(screen.getByRole('link', { name: '检查数据' })).toHaveAttribute('href', '/data-sources');
  expect(screen.getByRole('link', { name: '继续现有方案' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '已复核' }));
  await screen.findByRole('button', { name: '已复核' });
  await new Promise(resolve => setTimeout(resolve, 20));
  expect(acknowledged).toBe(true);
});
it('distinguishes current drift from the dated observation count', () => {
  renderWithProviders(<LongTermDecisionBanner decision={{ ...decisionFixture, status: 'observing', title: '刚刚越界，继续观察', has_manual_data: true, classes: [{ id: 'a', name: '股票', target_weight: '0.5', actual_weight: '0.6', drift: '0.1', direction: 1, observations: 1 }] } as LongTermDecision} />);
  expect(screen.getByText(/连续 1 次有效日终观察/)).toBeInTheDocument();
  expect(screen.getByText('包含有效手动行情')).toBeInTheDocument();
});
