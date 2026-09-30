import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { seedPortfolio } from './fixtures/portfolio';

test('original currency ledger remains usable with missing reference FX', async ({ page }) => {
  await seedPortfolio(page);
  await page.route('**/api/ledger/statistics', route => route.fulfill({json: {
    period: {id: 'period', opened_on: '2026-10-01'},
    currencies: [{currency: 'USD', unrealized: '10', realized: '3', dividends: '2', opening_unrealized: '4', period_pnl: '11', complete: true, incomplete_reasons: []}],
    reference_pnl_cny: null, incomplete_reasons: ['人民币参考折算待补全'], holdings: [],
  }}));
  await page.goto('/');
  await page.getByRole('link', {name: '投资记录', exact: true}).click();
  await expect(page.getByRole('heading', {name: '投资记录与期间损益'})).toBeVisible();
  await expect(page.getByText('人民币参考：待补全')).toBeVisible();
  await expect(page.getByRole('rowheader', {name: 'USD', exact: true})).toBeVisible();
  await page.getByLabel('操作类型', {exact: true}).selectOption('dividend');
  await expect(page.getByLabel('净到账金额')).toBeVisible();
  await expect(page.getByLabel('发生日期')).toBeVisible();
  await expect(page.getByRole('textbox', {name: /汇率/})).toHaveCount(0);
  expect((await new AxeBuilder({page}).analyze()).violations).toEqual([]);
  await page.screenshot({path: 'test-results/long-term-ledger.png', fullPage: true});
});

test('monthly review requires an explicit acknowledgement', async ({ page }) => {
  await seedPortfolio(page);
  let reviewed = false;
  const decision = () => ({status: 'normal', title: '配置正常', reason: '等待下次月度复核。', classes: [], issues: [], has_manual_data: false, latest_valid_date: '2026-09-30', last_checked_at: null, active_plan_id: null, review_date: reviewed ? '2026-11-01' : '2026-10-01', review_due: !reviewed, last_reviewed_at: reviewed ? '2026-10-01T02:00:00Z' : null});
  await page.route('**/api/decision', route => route.fulfill({json: decision()}));
  await page.route('**/api/decision/review', route => {reviewed = true; return route.fulfill({json: decision()});});
  await page.goto('/');
  await expect(page.getByText('本月配置待复核', {exact: false})).toBeVisible();
  await page.getByRole('button', {name: '已复核', exact: true}).click();
  await expect(page.getByText('下次月度复核', {exact: false})).toBeVisible();
  await expect(page.getByRole('button', {name: '已复核', exact: true})).toHaveCount(0);
  await page.screenshot({path: 'test-results/long-term-dashboard.png', fullPage: true});
});
