import { expect, test, type Locator, type Page } from '@playwright/test';

// The left rail has to fit a laptop screen without scrolling once a topic is selected, with
// every destination on it, and it must say where the daily loop starts. The phone drawer
// renders the same rail with roomier, touch-sized rows, and fades its edge where it scrolls.

const isPhone = () => test.info().project.name === 'phone';

// Every destination the rail offers with a topic selected (nothing may drop off).
const LINKS = [
  'Today',
  'Dashboard',
  'Tutor',
  'Practice',
  'Assess',
  'Teach',
  'Track',
  'Wayfinder',
  'Constellation',
  'Retention',
  'Sources',
  'Notebook',
  'Vault',
  'Story',
  'Fleet',
  'Programs',
  'Usage',
  'Your data'
];

const HINT = /Start at Today/;

async function seededTopicId(page: Page): Promise<number> {
  const res = await page.request.get('/api/topics');
  expect(res.ok()).toBeTruthy();
  const topics = (await res.json()) as { id: number; title: string }[];
  return topics.find((t) => t.title === 'Build LLMs from Scratch including the math')!.id;
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}

/** Heights of the visible rail and its nav, and whether either has to scroll. */
async function railMetrics(rail: Locator) {
  return rail.evaluate((aside) => {
    const nav = aside.querySelector('nav')!;
    return {
      railScroll: aside.scrollHeight,
      railClient: aside.clientHeight,
      navScroll: nav.scrollHeight,
      navClient: nav.clientHeight
    };
  });
}

test.describe('desktop rail', () => {
  test.beforeEach(() => {
    test.skip(isPhone(), 'desktop-only layout');
  });

  for (const vp of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 1366, height: 768 }
  ]) {
    test(`fits without scrolling at ${vp.width}x${vp.height} with a topic selected`, async ({ page }) => {
      const id = await seededTopicId(page);
      await page.setViewportSize(vp);
      await page.goto(`/topics/${id}/today`);
      await settle(page);

      const rail = page.locator('aside:visible');
      await expect(rail).toHaveCount(1);
      // The first-run hint is showing (fresh browser), the tallest the rail gets.
      await expect(rail.getByText(HINT)).toBeVisible();

      const m = await railMetrics(rail);
      test.info().annotations.push({ type: 'rail', description: `${vp.width}x${vp.height}: ${JSON.stringify(m)}` });
      expect(m.navScroll, 'the nav does not scroll').toBeLessThanOrEqual(m.navClient);
      expect(m.railScroll, 'the rail does not scroll').toBeLessThanOrEqual(m.railClient);

      for (const name of LINKS) {
        const link = rail.getByRole('link', { name, exact: true });
        await expect(link, `${name} is on the rail`).toBeVisible();
        const box = (await link.boundingBox())!;
        expect(box.y, `${name} is on screen`).toBeGreaterThanOrEqual(0);
        expect(box.y + box.height, `${name} is above the fold`).toBeLessThanOrEqual(vp.height);
      }
    });
  }

  test('the current page is marked in the rail', async ({ page }) => {
    const id = await seededTopicId(page);
    await page.goto(`/topics/${id}/tutor`);
    await settle(page);
    const rail = page.locator('aside:visible');
    await expect(rail.getByRole('link', { name: 'Tutor', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(rail.locator('a[aria-current="page"]')).toHaveCount(1);
  });

  test('the daily-loop hint can be dismissed and stays dismissed', async ({ page }) => {
    const id = await seededTopicId(page);
    await page.goto(`/topics/${id}/today`);
    await settle(page);
    const rail = page.locator('aside:visible');
    await expect(rail.getByText(HINT)).toBeVisible();
    await rail.getByRole('button', { name: 'Dismiss hint' }).click();
    await expect(rail.getByText(HINT)).toHaveCount(0);
    await page.reload();
    await settle(page);
    await expect(page.locator('aside:visible').getByRole('link', { name: 'Today', exact: true })).toBeVisible();
    await expect(page.locator('aside:visible').getByText(HINT)).toHaveCount(0);
  });
});

test.describe('phone drawer', () => {
  test.beforeEach(() => {
    test.skip(!isPhone(), 'phone-only layout');
  });

  test('every destination is in the drawer with touch-sized rows', async ({ page }) => {
    const id = await seededTopicId(page);
    await page.goto(`/topics/${id}/today`);
    await settle(page);
    await page.getByRole('button', { name: 'Open navigation' }).click();
    const drawer = page.locator('#mobile-nav-drawer');
    await expect(drawer).toBeVisible();
    for (const name of LINKS) {
      const link = drawer.getByRole('link', { name, exact: true });
      await link.scrollIntoViewIfNeeded();
      await expect(link, `${name} is in the drawer`).toBeVisible();
      const box = (await link.boundingBox())!;
      expect(box.height, `${name} is at least 40px tall`).toBeGreaterThanOrEqual(40);
    }
  });

  test('fades where the nav is cut, and every link scrolls clear of the footer', async ({ page }) => {
    const id = await seededTopicId(page);
    await page.goto(`/topics/${id}/today`);
    await settle(page);
    await page.getByRole('button', { name: 'Open navigation' }).click();
    const drawer = page.locator('#mobile-nav-drawer');
    const nav = drawer.getByRole('navigation', { name: 'Main' });
    const fade = drawer.getByTestId('rail-fade-below');

    const scrolls = await nav.evaluate((n) => n.scrollHeight > n.clientHeight + 1);
    test.skip(!scrolls, 'the whole nav fits this screen');
    await expect(nav).toHaveAttribute('data-more-below', 'true');
    await expect(fade).toHaveCSS('opacity', '1');

    await nav.evaluate((n) => n.scrollTo(0, n.scrollHeight));
    await expect(nav).not.toHaveAttribute('data-more-below', 'true');
    await expect(fade).toHaveCSS('opacity', '0');
    // Scrolled to the end, the last links sit fully above the pinned footer.
    const footerTop = (await drawer.getByRole('navigation', { name: 'Usage and data' }).boundingBox())!.y;
    for (const name of ['Story', 'Fleet', 'Programs']) {
      const box = (await nav.getByRole('link', { name, exact: true }).boundingBox())!;
      expect(box.y + box.height, `${name} clears the footer`).toBeLessThanOrEqual(footerTop);
    }
  });
});
