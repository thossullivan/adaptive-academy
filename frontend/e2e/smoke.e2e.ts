import { expect, test } from '@playwright/test';

// Proves the harness: the seeded topic loads through the proxied throwaway API.
test('dashboard renders the seeded topic', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Build LLMs from Scratch including the math' })
  ).toBeVisible();
});
