import { expect, test } from '@playwright/test';

// The Usage page against the e2e seed's LLMUsage fixtures (no real model calls): today =
// $0.0495 + $0.284 (tutor + research) plus one call on a model with no known price.

const isPhone = () => test.info().project.name === 'phone';

test('usage page shows recorded spend, breakdowns, and the unset limit', async ({ page }) => {
  await page.goto('/usage');
  const report = page.getByTestId('usage-report');
  await expect(report).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Usage & cost' })).toBeVisible();

  await expect(report.getByText('$0.33').first()).toBeVisible();
  await expect(report.getByText(/3 calls · .* tokens · 5 searches · 1 price unknown/).first()).toBeVisible();

  const byFeature = page.getByTestId('usage-by-feature');
  await expect(byFeature.getByText('Research')).toBeVisible();
  await expect(byFeature.getByText('Curriculum')).toBeVisible();
  await expect(byFeature.getByText('price unknown')).toBeVisible(); // the assess row

  const byModel = page.getByTestId('usage-by-model');
  await expect(byModel.getByText('claude-sonnet-4-6')).toBeVisible();
  await expect(byModel.getByText('price unknown')).toBeVisible();

  await expect(page.getByText('No limit set.')).toBeVisible();
  await expect(page.getByText('AA_DAILY_BUDGET_USD=5')).toBeVisible();
});

test('a setup warning about the limit is shown on the usage page', async ({ page }) => {
  const warning =
    "A daily spending limit is set (AA_DAILY_BUDGET_USD) but the model 'claude-opus-5-5' has no known price, so its spend can't be capped.";
  await page.route('**/api/setup', (route) =>
    route.fulfill({
      json: {
        llm_backend: 'anthropic',
        llm_ready: true,
        message: 'ok',
        models: { reasoning: 'claude-opus-5-5', copy: 'claude-haiku-5-5' },
        warnings: [warning]
      }
    })
  );
  await page.goto('/usage');
  await expect(page.getByTestId('usage-report')).toBeVisible();
  await expect(page.getByTestId('budget-warning')).toContainText("has no known price");
});

test('no budget warning without one from setup', async ({ page }) => {
  await page.goto('/usage');
  await expect(page.getByTestId('usage-report')).toBeVisible();
  await page.waitForLoadState('networkidle');
  await expect(page.getByTestId('budget-warning')).toHaveCount(0);
});

test('the nav links to the usage page', async ({ page }) => {
  await page.goto('/fleet');
  await page.waitForLoadState('networkidle');
  if (isPhone()) {
    await page.getByRole('button', { name: 'Open navigation' }).click();
  }
  await page.getByRole('link', { name: 'Usage' }).filter({ visible: true }).first().click();
  await expect(page).toHaveURL(/\/usage$/);
  await expect(page.getByTestId('usage-report')).toBeVisible();
});

test('usage page does not scroll sideways at 390px', async ({ page }) => {
  test.skip(!isPhone(), 'phone-only layout');
  await page.goto('/usage');
  await expect(page.getByTestId('usage-report')).toBeVisible();
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
});
