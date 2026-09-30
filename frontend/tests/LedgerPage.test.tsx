import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { LedgerPage } from '../src/pages/LedgerPage';
import { renderWithProviders } from './testProviders';

describe('long-term ledger', () => {
  it('shows currency groups separately and leaves reference CNY pending', async () => {
    renderWithProviders(<LedgerPage />, {handlers: [
      http.get('/api/ledger/statistics', () => HttpResponse.json({period: {id: 'p', opened_on: '2026-10-01'}, currencies: [
        {currency: 'USD', unrealized: '10', realized: '3', dividends: '2', opening_unrealized: '4', period_pnl: '11', complete: true, incomplete_reasons: []},
        {currency: 'CNY', unrealized: '20', realized: '0', dividends: '1', opening_unrealized: '0', period_pnl: '21', complete: true, incomplete_reasons: []}],
        reference_pnl_cny: null, incomplete_reasons: ['SPY 人民币参考折算待补全'], holdings: []})),
      http.get('/api/ledger/entries', () => HttpResponse.json([])),
      http.get('/api/holdings', () => HttpResponse.json([])),
    ]});
    expect(await screen.findByRole('heading', {name: '投资记录与期间损益'})).toBeInTheDocument();
    expect(await screen.findByText('USD')).toBeInTheDocument();
    expect(screen.getByText('CNY')).toBeInTheDocument();
    expect(screen.getByText('人民币参考：待补全')).toBeInTheDocument();
    expect(screen.getByText('启用日期 2026-10-01')).toBeInTheDocument();
  });
});
