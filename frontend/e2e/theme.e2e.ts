import { expect, test, type Page } from '@playwright/test';

// Theme follows the OS (`prefers-color-scheme`) unless the learner picks Light or Dark in the
// rail footer; a manual pick is remembered and wins over the OS.

const isPhone = () => test.info().project.name === 'phone';
const html = (page: Page) => page.locator('html');

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
}

/** The theme picker lives in the rail footer; on a phone the rail is inside the drawer. */
async function themeGroup(page: Page) {
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  const group = page.getByRole('radiogroup', { name: 'Theme' });
  await expect(group).toBeVisible();
  return group;
}

test('no stored choice + light OS → light theme, set before the app hydrates', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  // Record data-theme as soon as the document exists, before any app module runs.
  await page.addInitScript(() => {
    document.addEventListener('DOMContentLoaded', () => {
      (window as unknown as { __firstTheme: string | null }).__firstTheme =
        document.documentElement.getAttribute('data-theme');
    });
  });
  await page.goto('/');
  await settle(page);
  await expect(html(page)).toHaveAttribute('data-theme', 'light');
  expect(await page.evaluate(() => (window as unknown as { __firstTheme: string }).__firstTheme)).toBe('light');
  // The body really paints a light background.
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const [r, g, b] = bg.match(/\d+/g)!.map(Number);
  expect((r + g + b) / 3).toBeGreaterThan(200);
});

test('no stored choice + dark OS → dark theme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/');
  await settle(page);
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
});

test('in system mode the theme follows a live OS change', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/');
  await settle(page);
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(html(page)).toHaveAttribute('data-theme', 'light');
});

test('a manual choice persists across reload and beats the OS', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/');
  await settle(page);

  const group = await themeGroup(page);
  await expect(group.getByRole('radio', { name: 'System' })).toHaveAttribute('aria-checked', 'true');
  await group.getByRole('radio', { name: 'Light' }).click();
  await expect(html(page)).toHaveAttribute('data-theme', 'light');
  await expect(group.getByRole('radio', { name: 'Light' })).toHaveAttribute('aria-checked', 'true');

  await page.reload();
  await settle(page);
  await expect(html(page)).toHaveAttribute('data-theme', 'light');

  // The OS flipping no longer moves it.
  await page.emulateMedia({ colorScheme: 'light' });
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(html(page)).toHaveAttribute('data-theme', 'light');

  // Back to System: follows the (dark) OS again, and the override is gone after reload.
  const again = await themeGroup(page);
  await again.getByRole('radio', { name: 'System' }).click();
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await settle(page);
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(html(page)).toHaveAttribute('data-theme', 'light');
});

test('the theme radio group is keyboard operable', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/');
  await settle(page);
  const group = await themeGroup(page);
  const system = group.getByRole('radio', { name: 'System' });
  // Roving focus: only the checked option is in the tab order.
  await expect(system).toHaveAttribute('tabindex', '0');
  await expect(group.getByRole('radio', { name: 'Light' })).toHaveAttribute('tabindex', '-1');
  await system.focus();
  await page.keyboard.press('ArrowRight');
  await expect(group.getByRole('radio', { name: 'Light' })).toBeFocused();
  await expect(html(page)).toHaveAttribute('data-theme', 'light');
  await page.keyboard.press('ArrowRight');
  await expect(html(page)).toHaveAttribute('data-theme', 'dark');
  await page.keyboard.press('ArrowRight');
  await expect(system).toBeFocused();
  await expect(system).toHaveAttribute('aria-checked', 'true');
});

test('no horizontal scroll at 390px in light mode', async ({ page }) => {
  test.skip(!isPhone(), 'phone-only layout');
  await page.emulateMedia({ colorScheme: 'light' });
  const res = await page.request.get('/api/topics');
  const [{ id }] = (await res.json()) as { id: number }[];
  for (const route of ['/', `/topics/${id}/today`, `/topics/${id}/map`, '/usage']) {
    await page.goto(route);
    await settle(page);
    await expect(html(page)).toHaveAttribute('data-theme', 'light');
    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth
    }));
    expect(scrollWidth, route).toBeLessThanOrEqual(Math.min(innerWidth, 390));
  }
});
