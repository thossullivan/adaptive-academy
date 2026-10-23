import { expect, test, type Page } from '@playwright/test';

// Phone layout: below `md` the rail collapses into an off-canvas drawer behind a top bar,
// and no route may scroll sideways. Desktop keeps the always-on rail.

const isPhone = () => test.info().project.name === 'phone';

async function seededTopicId(page: Page): Promise<number> {
  const res = await page.request.get('/api/topics');
  expect(res.ok()).toBeTruthy();
  const topics = (await res.json()) as { id: number }[];
  expect(topics.length).toBeGreaterThan(0);
  return topics[0].id;
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  // The layout shows a "calibrating" spinner until topics load; wait for real content.
  await expect(page.getByText('calibrating')).toHaveCount(0);
}

const TOPIC_SUBPAGES = [
  'today',
  'tutor',
  'track',
  'practice',
  'assess',
  'teach',
  'retention',
  'review',
  'notebook',
  'story',
  'vault',
  'wayfinder',
  'map'
];

test.describe('phone', () => {
  test.beforeEach(() => {
    test.skip(!isPhone(), 'phone-only layout');
  });

  test('no route scrolls horizontally at 390px', async ({ page }) => {
    test.setTimeout(120_000);
    const id = await seededTopicId(page);
    const routes = [
      '/',
      '/fleet',
      '/programs',
      '/programs/new',
      '/topics/new',
      ...TOPIC_SUBPAGES.map((s) => `/topics/${id}/${s}`)
    ];
    const width = page.viewportSize()!.width;
    const overflowing: string[] = [];
    for (const route of routes) {
      await page.goto(route);
      await settle(page);
      const { scrollWidth, innerWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth
      }));
      // Compare against the configured viewport too: mobile emulation can zoom out to fit
      // overflowing content, which would inflate innerWidth and hide the overflow.
      if (scrollWidth > innerWidth || scrollWidth > width) {
        overflowing.push(`${route}: scrollWidth ${scrollWidth} > ${Math.min(innerWidth, width)}`);
      }
    }
    expect(overflowing).toEqual([]);
  });

  test('rail is an off-canvas drawer behind the menu button', async ({ page }) => {
    await page.goto('/');
    await settle(page);

    const menu = page.getByRole('button', { name: 'Open navigation' });
    const fleetLink = page.getByRole('link', { name: 'Fleet', exact: true });
    await expect(menu).toBeVisible();
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(fleetLink).not.toBeVisible();

    const drawerId = await menu.getAttribute('aria-controls');
    expect(drawerId).toBeTruthy();
    const drawer = page.locator(`#${drawerId}`);

    // Open → nav link navigates and closes the drawer.
    await menu.click();
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
    await expect(drawer).toBeVisible();
    await expect(fleetLink).toBeVisible();
    // Focus moves into the drawer.
    await expect
      .poll(() => page.evaluate((id) => !!document.getElementById(id)?.contains(document.activeElement), drawerId))
      .toBe(true);
    // Body scroll is locked while open.
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe('hidden');

    await fleetLink.click();
    await expect(page).toHaveURL(/\/fleet$/);
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(fleetLink).not.toBeVisible();
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe('hidden');

    // Open → Escape closes and returns focus to the menu button.
    await menu.click();
    await expect(fleetLink).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(fleetLink).not.toBeVisible();
    await expect(menu).toBeFocused();

    // Open → backdrop click closes.
    await menu.click();
    await expect(fleetLink).toBeVisible();
    // Click the backdrop to the right of the drawer.
    await page.mouse.click(page.viewportSize()!.width - 10, 400);
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(fleetLink).not.toBeVisible();
    await expect(menu).toBeFocused();
  });

  test('switching topic on the dashboard closes the drawer', async ({ page }) => {
    // On "/" a topic switch re-renders in place without navigating.
    await page.goto('/');
    await settle(page);
    const menu = page.getByRole('button', { name: 'Open navigation' });
    await menu.click();
    const drawer = page.locator('#mobile-nav-drawer');
    await drawer.getByRole('button', { name: /Build LLMs from Scratch/ }).click();
    await drawer.getByRole('button', { name: /Linear Algebra Refresher/ }).click();
    await expect(menu).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByRole('heading', { name: 'Linear Algebra Refresher' })).toBeVisible();
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).not.toBe('hidden');
  });

  test('a drawer opened while topics load stays open when they arrive', async ({ page }) => {
    await page.route('**/api/topics', async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    await page.goto('/fleet');
    const menu = page.getByRole('button', { name: 'Open navigation' });
    await menu.click();
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
    await settle(page);
    await expect(menu).toHaveAttribute('aria-expanded', 'true');
  });

  test('Tab and Shift+Tab stay inside the open drawer', async ({ page }) => {
    await page.goto('/');
    await settle(page);
    await page.getByRole('button', { name: 'Open navigation' }).click();
    const inDrawer = () =>
      page.evaluate(() => !!document.getElementById('mobile-nav-drawer')?.contains(document.activeElement));
    await expect.poll(inDrawer).toBe(true);
    // Focus the drawer container itself, as a click on its blank space would.
    await page.evaluate(() => document.getElementById('mobile-nav-drawer')!.focus());
    await page.keyboard.press('Shift+Tab');
    expect(await inDrawer()).toBe(true);
    await page.keyboard.press('Tab');
    expect(await inDrawer()).toBe(true);
  });

  test('tutor composer is usable at 390px', async ({ page }) => {
    const id = await seededTopicId(page);
    await page.goto(`/topics/${id}/tutor`);
    await settle(page);

    const input = page.getByPlaceholder(/Ask the tutor/);
    const send = page.getByRole('button', { name: 'Send' });
    await expect(input).toBeVisible();
    await expect(send).toBeVisible();

    const attempt = page.getByRole('button', { name: 'Submit attempt' });
    await expect(attempt).toBeVisible();

    const vp = page.viewportSize()!;
    const inputBox = (await input.boundingBox())!;
    expect(inputBox.width).toBeGreaterThanOrEqual(200);
    for (const button of [send, attempt]) {
      const box = (await button.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
      expect(box.y + box.height).toBeLessThanOrEqual(vp.height);
      expect(box.height).toBeGreaterThanOrEqual(44); // a comfortable touch target
    }
    // The page never scrolls sideways.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(vp.width);
  });

  test('the tutor with a long conversation fits the screen, with a compact header', async ({ page }) => {
    const id = await seededTopicId(page);
    // A keyless tutor that answers every send with a long reply.
    await page.route('**/api/conversations', (r) =>
      r.request().method() === 'POST'
        ? r.fulfill({ json: { id: 998, concept_id: 1, attempt_logged: false, assistance_level: 'medium', challenge_level: 'medium', messages: [] } })
        : r.fallback()
    );
    await page.route('**/api/conversations/998/messages', (r) =>
      r.fulfill({
        json: {
          reply: 'Think about what each row must sum to. '.repeat(12),
          attempt_logged: true,
          attempt_outcome: 'accepted',
          reveals_solution: true,
          assistance_level: 'medium',
          challenge_level: 'medium',
          events: [],
          memory: []
        }
      })
    );
    await page.goto(`/topics/${id}/tutor`);
    await settle(page);
    const input = page.getByPlaceholder(/Ask the tutor/);
    for (let i = 0; i < 3; i++) {
      await input.fill(`attempt ${i}: \`scores.masked_fill(mask == 0, float("-inf"))\` before the softmax`);
      await page.getByRole('button', { name: 'Submit attempt' }).click();
      await expect(page.getByTestId('worked-solution')).toHaveCount(i + 1);
    }

    const vp = page.viewportSize()!;
    // The transcript scrolls inside its own region: no dead band under the composer.
    const { scrollHeight, scrollWidth } = await page.evaluate(() => ({
      scrollHeight: document.documentElement.scrollHeight,
      scrollWidth: document.documentElement.scrollWidth
    }));
    expect(scrollHeight).toBeLessThanOrEqual(vp.height);
    expect(scrollWidth).toBeLessThanOrEqual(vp.width);
    const send = (await page.getByRole('button', { name: 'Send' }).boundingBox())!;
    expect(send.y + send.height).toBeLessThanOrEqual(vp.height);

    // The session chips sit on one row (it scrolls sideways), and the header stays compact.
    const chips = page.getByTestId('tutor-chips');
    const boxes = await chips.locator(':scope > span').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().top));
    expect(new Set(boxes.map((t) => Math.round(t))).size).toBe(1);
    const header = (await page.locator('main header').first().boundingBox())!;
    expect(header.height).toBeLessThanOrEqual(110);
    // While the chips overflow, the row can be scrolled from the keyboard.
    const overflows = await chips.evaluate((el) => el.scrollWidth > el.clientWidth + 1);
    if (overflows) await expect(chips).toHaveAttribute('tabindex', '0');
    else await expect(chips).not.toHaveAttribute('tabindex', /.*/);

    // The gate chip comes first, so it is never the one cut off.
    const first = chips.locator(':scope > span').first();
    await expect(first).toHaveText('attempt logged');
    const firstBox = (await first.boundingBox())!;
    expect(firstBox.x + firstBox.width).toBeLessThanOrEqual(vp.width);
    // A fade marks the edge with more chips past it, and moves as the row scrolls.
    const right = page.getByTestId('chips-fade-right');
    const left = page.getByTestId('chips-fade-left');
    await expect(right).toHaveClass(overflows ? /opacity-100/ : /opacity-0/);
    await expect(left).toHaveClass(/opacity-0/);
    if (overflows) {
      await chips.focus();
      await page.keyboard.press('End');
      await chips.evaluate((el) => el.scrollTo({ left: el.scrollWidth }));
      await expect(left).toHaveClass(/opacity-100/);
      await expect(right).toHaveClass(/opacity-0/);
    }
  });
});

test.describe('desktop', () => {
  test.beforeEach(() => {
    test.skip(isPhone(), 'desktop-only layout');
  });

  test('rail is always visible and there is no menu button', async ({ page }) => {
    await page.goto('/');
    await settle(page);
    await expect(page.getByRole('link', { name: 'Fleet', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open navigation' })).not.toBeVisible();
  });
});
