import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';

// "Your data": the learning record can be downloaded from the browser, which is the only easy
// way out of the Docker volume. Both links must produce a real attachment from the e2e API.

const isPhone = () => test.info().project.name === 'phone';

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.getByText('calibrating')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Your data', level: 1 })).toBeVisible();
}

async function download(page: Page, testId: string) {
  const [file] = await Promise.all([page.waitForEvent('download'), page.getByTestId(testId).click()]);
  const path = await file.path();
  return { name: file.suggestedFilename(), bytes: await readFile(path) };
}

test('the page explains where the data lives and how to restore it', async ({ page }) => {
  await page.goto('/data');
  await settle(page);
  await expect(page.getByText('adaptive-academy-data').first()).toBeVisible();
  await expect(page.getByText('Put a snapshot back')).toBeVisible();
  await expect(page.getByText('aa restore').first()).toBeVisible();
});

test('download backup gives a timestamped SQLite snapshot', async ({ page }) => {
  await page.goto('/data');
  await settle(page);
  const { name, bytes } = await download(page, 'download-backup');
  expect(name).toMatch(/^adaptive_academy-\d{8}-\d{6}\.db$/);
  expect(bytes.subarray(0, 16).toString('latin1')).toBe('SQLite format 3\u0000');
});

test('download full record gives the versioned JSON export', async ({ page }) => {
  await page.goto('/data');
  await settle(page);
  const { name, bytes } = await download(page, 'download-record');
  expect(name).toMatch(/^adaptive_academy-\d{8}-\d{6}\.json$/);
  const doc = JSON.parse(bytes.toString('utf-8'));
  expect(doc.format).toBe('adaptive-academy-export');
  expect(doc.version).toBe(1);
  expect(doc.tables.topic.length).toBeGreaterThan(0);
});

test('the rail links to the page', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('link', { name: 'Your data' }).click();
  await expect(page).toHaveURL(/\/data$/);
  await settle(page);
});

test('no horizontal scroll at 390px', async ({ page }) => {
  test.skip(!isPhone(), 'phone-only layout');
  await page.goto('/data');
  await settle(page);
  const width = page.viewportSize()!.width;
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));
  expect(scrollWidth).toBeLessThanOrEqual(Math.min(innerWidth, width));
});
