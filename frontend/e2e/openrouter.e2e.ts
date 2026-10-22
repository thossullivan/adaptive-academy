import { expect, test, type Page } from '@playwright/test';
import {
  EXPERIMENTAL,
  SLUGS,
  agentSdkInContainer,
  mistypedBackend,
  mockOpenRouterUsage,
  mockSetup,
  openrouterExperimental,
  openrouterMissingKey
} from './openrouter-mocks';

// The OpenRouter backend (AA_LLM_BACKEND=openrouter), with /api/setup and /api/usage mocked:
// the e2e API itself runs keyless on the default backend, and no test makes a model call.

const isPhone = () => test.info().project.name === 'phone';

async function noSidewaysScroll(page: Page) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
}

test('the setup card names the OpenRouter key when it is missing', async ({ page }) => {
  await mockSetup(page, openrouterMissingKey);
  await page.goto('/topics/new');
  const notice = page.getByTestId('setup-notice');
  await expect(notice).toBeVisible();
  await expect(notice.getByRole('heading', { name: 'Add your OpenRouter API key to run the agents' })).toBeVisible();
  await expect(notice).toContainText('OPENROUTER_API_KEY=sk-or-');
  await expect(notice).toContainText('passes through OpenRouter');
  await expect(notice).not.toContainText('ANTHROPIC_API_KEY=');
  await expect(page.getByRole('button', { name: /Research this topic/ })).toBeDisabled();
  if (isPhone()) await noSidewaysScroll(page);
});

test('the setup card marks an experimental model with a text label', async ({ page }) => {
  await mockSetup(page, openrouterExperimental);
  await page.goto('/topics/new');
  const card = page.getByTestId('setup-experimental');
  await expect(card).toBeVisible();
  await expect(card).toContainText('It is not a Claude model');
  const models = card.getByRole('list', { name: 'Configured models' });
  const flagged = models.getByRole('listitem').filter({ hasText: EXPERIMENTAL });
  await expect(flagged.getByText('Experimental', { exact: true })).toBeVisible();
  const claude = models.getByRole('listitem').filter({ hasText: SLUGS.copy });
  await expect(claude.getByText('Experimental', { exact: true })).toHaveCount(0);
  // An experimental model is allowed: research still runs.
  await expect(page.getByTestId('setup-notice')).toHaveCount(0);
  await page.getByPlaceholder('e.g. Build LLMs from scratch').fill('Linear algebra');
  await page.getByPlaceholder("By the end I'll have…").fill('Derive SVD');
  await expect(page.getByRole('button', { name: /Research this topic/ })).toBeEnabled();
  if (isPhone()) await noSidewaysScroll(page);
});

test('the dashboard shows the experimental card beside the topic', async ({ page }) => {
  await mockSetup(page, openrouterExperimental);
  await page.goto('/');
  await expect(page.getByTestId('setup-experimental')).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Build LLMs from Scratch including the math' })
  ).toBeVisible();
  if (isPhone()) await noSidewaysScroll(page);
});

test('the usage page labels experimental models and explains OpenRouter costs', async ({ page }) => {
  await mockOpenRouterUsage(page);
  await page.goto('/usage');
  await expect(page.getByTestId('usage-report')).toBeVisible();
  await expect(page.getByTestId('usage-openrouter')).toContainText('what OpenRouter reported');
  const byModel = page.getByTestId('usage-by-model');
  const flagged = byModel.getByRole('listitem').filter({ hasText: EXPERIMENTAL });
  await expect(flagged.getByText('Experimental', { exact: true })).toBeVisible();
  const claude = byModel.getByRole('listitem').filter({ hasText: 'claude-sonnet-4-6' });
  await expect(claude.getByText('Experimental', { exact: true })).toHaveCount(0);
  if (isPhone()) await noSidewaysScroll(page);
});

test('no experimental label on the default backend', async ({ page }) => {
  await page.goto('/usage');
  await expect(page.getByTestId('usage-report')).toBeVisible();
  await page.waitForLoadState('networkidle');
  await expect(page.getByTestId('experimental-label')).toHaveCount(0);
  await expect(page.getByTestId('setup-experimental')).toHaveCount(0);
});

test('agent_sdk in the container says what to change and blocks research', async ({ page }) => {
  await mockSetup(page, agentSdkInContainer);
  await page.goto('/topics/new');
  const notice = page.getByTestId('setup-notice');
  await expect(notice.getByRole('heading', { name: "The Claude subscription backend can't run here" })).toBeVisible();
  await expect(notice).toContainText('this container');
  await expect(notice).not.toContainText('cp .env.example .env');
  await expect(page.getByRole('button', { name: /Research this topic/ })).toBeDisabled();
  if (isPhone()) await noSidewaysScroll(page);
});

test('a mistyped AA_LLM_BACKEND gets its own setup card', async ({ page }) => {
  await mockSetup(page, mistypedBackend);
  await page.goto('/topics/new');
  const card = page.getByTestId('setup-check');
  await expect(card).toBeVisible();
  await expect(card.getByTestId('setup-warning')).toContainText("'openroutr'");
  await expect(page.getByTestId('setup-notice')).toHaveCount(0);
  if (isPhone()) await noSidewaysScroll(page);
});
