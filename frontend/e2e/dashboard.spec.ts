import { test, expect, type Request } from '@playwright/test';

test('real browser: healthy → slow → failing → healthy, policy windows and negative budget', async ({ page }) => {
  const errors: string[] = [];
  const inflight = new Set<Request>();
  let peak = 0;
  page.on('request', request => { if (request.url().includes('/api/')) { inflight.add(request); peak = Math.max(peak, inflight.size); } });
  page.on('requestfinished', request => inflight.delete(request));
  page.on('requestfailed', request => inflight.delete(request));
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByTestId('demo-mode')).toHaveText('Healthy');
  await page.getByLabel('Slow delay (seconds)').fill('0.8');
  for (const [mode, outcome, status] of [['Healthy', 'GOOD', '200'], ['Slow', 'BAD', '200'], ['Failing', 'BAD', '500'], ['Healthy', 'GOOD', '200']]) {
    const changed = Date.now();
    await page.getByRole('button', { name: mode, exact: true }).click();
    await expect(page.getByTestId('demo-mode')).toHaveText(mode);
    await expect.poll(async () => {
      const row = page.getByTestId('result-row').first();
      if (!await row.count()) return false;
      const slot = await row.getAttribute('data-scheduled-at');
      return !!slot && Date.parse(slot) >= changed && (await row.innerText()).includes(outcome);
    }, { timeout: 20000 }).toBe(true);
    await expect(page.getByTestId('result-row').first().locator('td').nth(3)).toHaveText(status);
    if (mode === 'Slow') await expect(page.getByTestId('result-row').first()).toContainText('latency');
  }
  await expect(page.getByRole('article', { name: 'Error budget remaining' }).locator('.metric-value')).toHaveText(/-/);
  await expect(page.getByRole('article', { name: 'Monitoring coverage' })).toBeVisible();
  await expect(page.getByRole('article', { name: 'SLI', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/dashboard-desktop.png', fullPage: true });
  await page.getByLabel('Reliability policy').selectOption('thirty_day');
  await expect(page.getByRole('heading', { name: 'Thirty-day reporting · 30 days' })).toBeVisible();
  await expect(page.getByTestId('alert-state')).toHaveText('Insufficient data');
  await page.getByLabel('Reliability policy').selectOption('demo');
  await expect(page.getByRole('heading', { name: 'Demo policy · 5 minutes' })).toBeVisible();
  expect(errors).toEqual([]);
  expect(peak).toBe(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/dashboard-mobile-results.png', fullPage: true });
});

test('empty real check, null metrics, validation, selection, offline recovery and mobile layout', async ({ page, request, context }) => {
  const response = await request.post('/api/checks', { data: { name: 'Paused empty check', enabled: false } });
  expect(response.ok()).toBe(true);
  const check = await response.json();
  await page.goto('/');
  await expect(page.getByLabel('Monitoring check')).toBeEnabled();
  await page.getByLabel('Monitoring check').selectOption(String(check.id));
  await expect(page.getByRole('article', { name: 'SLI', exact: true }).locator('.metric-value')).toHaveText('No data');
  await expect(page.getByRole('article', { name: 'Burn rate' }).locator('.metric-value')).toHaveText('No data');
  await expect(page.getByText('No data. Start or resume the monitoring worker to collect results.')).toBeVisible();
  await page.getByLabel('Timeout (seconds)').fill('6');
  await page.getByRole('button', { name: 'Save configuration' }).click();
  await expect(page.getByRole('alert')).toContainText('Timeout must be less than interval');
  await page.getByLabel('Timeout (seconds)').fill('2');
  await page.getByLabel('Latency threshold (ms)').fill('450');
  await page.getByRole('button', { name: 'Save configuration' }).click();
  await expect(page.getByText('Configuration saved. Schedule history is preserved.')).toBeVisible();
  expect((await (await request.get(`/api/checks`)).json()).find((item: { id: number }) => item.id === check.id).latency_threshold_ms).toBe(450);
  await context.setOffline(true);
  await expect(page.getByRole('alert').filter({ hasText: 'Connection error' })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('Showing the last successful response. Values may be stale.')).toBeVisible();
  await context.setOffline(false);
  await page.getByRole('button', { name: 'Retry connection' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Connection error' })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'SRE Operations Cockpit' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true });
});

test('real missed slots appear as UNKNOWN and latency gaps', async ({ page, request }) => {
  // Real workload causes missed dispatches; never insert fabricated result rows.
  await request.put('/api/demo', { data: { mode: 'Slow', delay_seconds: 3 } });
  const config = { name: 'Gap verification', interval_seconds: 1, timeout_seconds: 0.8, latency_threshold_ms: 500 };
  await request.put('/api/checks/1', { data: config });
  const extraIds: number[] = [];
  try {
    for (let index = 0; index < 2; index++) {
      const created = await request.post('/api/checks', { data: { ...config, name: `Real load ${index}` } });
      expect(created.ok()).toBe(true);
      extraIds.push((await created.json()).id);
    }
    await page.goto('/');
    await expect(page.getByLabel('Monitoring check')).toBeEnabled();
    await page.getByLabel('Monitoring check').selectOption(String(extraIds[0]));
    await expect.poll(async () => (await page.getByTestId('result-row').allTextContents()).some(text => text.includes('UNKNOWN') && text.includes('No data')), { timeout: 25000 }).toBe(true);
    await expect.poll(() => page.getByTestId('latency-segment').count(), { timeout: 25000 }).toBeGreaterThan(1);
  } finally {
    await request.put('/api/demo', { data: { mode: 'Healthy', delay_seconds: 1 } });
    await request.put('/api/checks/1', { data: {} });
    for (const id of extraIds) await request.put(`/api/checks/${id}`, { data: { enabled: false } });
  }
});
