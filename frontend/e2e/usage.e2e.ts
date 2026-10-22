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
  if (!isPhone()) {
    // Prompt-cache read share per feature (hidden at phone width, like the token column).
    await expect(byFeature.getByText('64% cached')).toBeVisible(); // tutor: 36k of 56k
    await expect(byFeature.getByText('0% cached').first()).toBeVisible();
  }

  const byModel = page.getByTestId('usage-by-model');
  await expect(byModel.getByText('claude-sonnet-4-6')).toBeVisible();
  await expect(byModel.getByText('price unknown')).toBeVisible();

  await expect(page.getByText('No limit set.')).toBeVisible();
  await expect(page.getByText('AA_DAILY_BUDGET_USD=5')).toBeVisible();
});

test('feature labels show in full at desktop width', async ({ page }) => {
  test.skip(isPhone(), 'desktop layout (1440px)');
  await page.goto('/usage');
  const labels = page.getByTestId('usage-by-feature').getByTestId('feature-label');
  await expect(labels.filter({ hasText: 'Research' })).toHaveText('Research');
  for (const label of await labels.all()) {
    await expect(label).toBeVisible();
    // Not clipped: the whole label fits in its box (no ellipsis, no hidden overflow).
    const clipped = await label.evaluate((el) => el.scrollWidth > el.clientWidth);
    expect(clipped).toBe(false);
  }
});

test('the quality scorecard shows each number from the seeded events', async ({ page }) => {
  await page.goto('/usage');
  const card = page.getByTestId('usage-quality');
  await expect(card.getByRole('heading', { name: 'Is each model doing its job?' })).toBeVisible();
  const windows = card.getByRole('group', { name: 'Scorecard time window' });
  await expect(windows.getByRole('button', { name: 'Last 30 days' })).toHaveAttribute('aria-pressed', 'true');

  // Cost per grade: $0.06 of priced teach spend over the four seeded assessments.
  await expect(page.getByTestId('quality-cost-per-grade')).toContainText('$0.015');
  // The unpriced assess call is left out of that figure, and the card says so.
  await expect(page.getByTestId('quality-unpriced-note')).toHaveText(
    'Leaves out 1 grading call with no known price.'
  );
  await expect(card).toContainText('A grade in the wrong format is counted under Grade checks above');
  const grading = page.getByTestId('quality-grading');
  await expect(grading).toContainText('0.50');
  await expect(grading).toContainText('2 of 4 grades failed a check');
  await expect(grading).toContainText('1 failed the checks twice (25% of grades)');
  await expect(grading.getByRole('list', { name: 'Most failed checks' })).toContainText('G13 · 3');
  const guard = page.getByTestId('quality-guard');
  await expect(guard).toContainText('1 of 5 replies gave the answer away');
  await expect(guard).toContainText('1 check where the model check failed');

  const byFeature = page.getByTestId('quality-by-feature');
  await expect(byFeature.getByRole('row', { name: /Research/ })).toContainText('1 wrong format (100%)');
  await expect(byFeature.getByRole('row', { name: /Curriculum/ })).toContainText('1 cut off (100%)');
  await expect(byFeature.getByRole('row', { name: /Tutor/ })).toContainText('none');
  const byModel = page.getByTestId('quality-by-model');
  await expect(byModel.getByRole('row', { name: /claude-custom-finetune/ })).toContainText('price unknown');

  // Today: the 3-day-old curriculum call drops out; all-time brings it back.
  await windows.getByRole('button', { name: 'Today' }).click();
  await expect(windows.getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'true');
  await expect(byFeature.getByRole('row', { name: /Curriculum/ })).toHaveCount(0);
  await windows.getByRole('button', { name: 'All time' }).click();
  await expect(byFeature.getByRole('row', { name: /Curriculum/ })).toHaveCount(1);
});

test('the footnote names where calls are sent on each backend', async ({ page }) => {
  await page.goto('/usage');
  const footnote = page.getByTestId('usage-footnote');
  await expect(footnote).toContainText('Each model call itself is still sent to Anthropic.');
  await expect(footnote).not.toContainText('OpenRouter');
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
  // The scorecard's tables (long model ids included) are the widest part of the page.
  await expect(page.getByTestId('quality-by-model')).toBeVisible();
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
});
