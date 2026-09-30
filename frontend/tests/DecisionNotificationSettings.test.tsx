import { fireEvent, screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { DecisionNotificationSettings } from '../src/features/decision/DecisionNotificationSettings';
import { renderWithProviders } from './testProviders';
it('preserves daily default and saves attention mode with monthly review opt-in', async () => {
  let payload: unknown;
  renderWithProviders(<DecisionNotificationSettings />, { handlers: [http.put('/api/decision/settings', async ({ request }) => { payload = await request.json(); return HttpResponse.json({ ...payload as object, last_checked_at: null, last_reviewed_at: null }); })] });
  expect(await screen.findByRole('combobox', { name: '自动邮件模式' })).toHaveValue('daily');
  expect(screen.getByRole('checkbox', { name: '月度复核到期邮件' })).not.toBeChecked();
  fireEvent.change(screen.getByRole('combobox', { name: '自动邮件模式' }), { target: { value: 'attention' } });
  fireEvent.change(screen.getByRole('spinbutton', { name: '每月复核日' }), { target: { value: '31' } });
  fireEvent.click(screen.getByRole('checkbox', { name: '月度复核到期邮件' }));
  fireEvent.click(screen.getByRole('button', { name: '保存提醒设置' }));
  await waitFor(() => expect(payload).toEqual({ notification_mode: 'attention', review_day: 31, monthly_email: true }));
});
