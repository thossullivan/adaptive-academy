import { fileURLToPath } from 'node:url';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { createDemo, replayTutor, reportKeyConfigured, settle } from './demo';

// README screenshots: `npm run screenshots` (playwright.screenshots.config.ts). Not part of
// `npm run test:e2e`. Writes docs/images/*.png from the demo topic, created through the real
// POST /api/demo on a fresh throwaway db. What the run fakes, and why, is noted in ./demo.ts;
// the Usage page reads rows from screenshots/seed_screenshots.py (see the note there).

const OUT = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

async function shoot(target: Page | Locator, name: string) {
  const page = 'page' in target ? target.page() : target;
  // Nothing focused or hovered, and the current page's link scrolled into view in the rail
  // (a no-op while the whole rail fits, kept in case it ever has to scroll again).
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.mouse.move(0, 0);
  await page.evaluate(() => {
    // The phone drawer holds a second, hidden copy of the rail: take the visible one.
    const active = [...document.querySelectorAll('aside nav a')].find(
      (a) => a.classList.contains('bg-surface-2') && a.getClientRects().length > 0
    );
    active?.scrollIntoView({ block: 'nearest' });
  });
  await target.screenshot({ path: `${OUT}${name}.png`, animations: 'disabled' });
}

test('README screenshots', async ({ page }) => {
  await reportKeyConfigured(page);
  const demo = await createDemo(page);
  const id = demo.id;

  await page.setViewportSize(DESKTOP);

  // 1. Dashboard (the README hero).
  await page.goto('/');
  await settle(page);
  await expect(page.getByRole('heading', { name: 'Build LLMs from scratch (demo)' })).toBeVisible();
  await expect(page.getByText('Where you stand')).toBeVisible();
  await shoot(page, 'dashboard');

  // 2. Competence triangulation: two knowledge-map rows opened to say why.
  for (const name of ['Causal Self-Attention', 'Token Embeddings']) {
    await page.getByRole('button', { name: new RegExp(`^Why is ${name} `) }).click();
  }
  await expect(page.getByText(/^Shaky: /).first()).toBeVisible();
  const map = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Where you stand' }) });
  await shoot(map, 'competence');

  // 3. Today: the daily loop.
  await page.goto(`/topics/${id}/today`);
  await settle(page);
  await expect(page.getByText('Your next steps on the track:')).toBeVisible();
  await shoot(page, 'today');

  // 4. Tutor: the demo's conversation in which the reveal came only after a logged attempt.
  await replayTutor(page, demo);
  await page.evaluate(() => document.querySelectorAll('.overflow-y-auto').forEach((el) => el.scrollTo(0, 0)));
  await shoot(page, 'tutor');

  // 5. Constellation, with one concept focused (its prerequisite chain highlighted).
  await page.goto(`/topics/${id}/map`);
  await settle(page);
  const graph = page.locator('[data-settled]');
  await expect(graph).toHaveAttribute('data-settled', 'true', { timeout: 30_000 });
  // A star's accessible name is "<concept>: <verdict>"; target the star, not the list entry.
  await page.locator('g[role="button"][aria-label^="Causal Self-Attention:"]').click();
  // Also announced in a screen-reader live region, so match the visible copy.
  await expect(page.getByText(/prerequisite ancestors? highlighted/).first()).toBeVisible();
  await expect(graph).toHaveAttribute('data-settled', 'true');
  await shoot(page, 'constellation');

  // 6. Usage & cost.
  await page.goto('/usage');
  await settle(page);
  await expect(page.getByText('Daily spending limit')).toBeVisible();
  await shoot(page, 'usage');

  // 7. Phone width: Today.
  await page.setViewportSize(PHONE);
  await page.goto(`/topics/${id}/today`);
  await settle(page);
  await expect(page.getByText('Your next steps on the track:')).toBeVisible();
  await shoot(page, 'phone-today');
});
