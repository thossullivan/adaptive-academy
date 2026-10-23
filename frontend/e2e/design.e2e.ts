import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

// Design-pass regressions: disabled buttons that looked live, a page edge that jumped between
// pages, misaligned "Where you stand" rows, raw event kinds on the dashboard, verdict marks
// that only a shade told apart, a stretched calibration card, an emoji-lit and mostly empty
// fleet. Desktop and phone both run. (The phone drawer's scroll fade is checked in rail.e2e.ts.)

const isPhone = () => test.info().project.name === 'phone';
const COLOUR_EMOJI = /[⛵⭐⚓\u{1F3AF}]/u;

async function seededTopicId(page: Page): Promise<number> {
  const topics = (await (await page.request.get('/api/topics')).json()) as { id: number; title: string }[];
  return topics.find((t) => t.title === 'Build LLMs from Scratch including the math')!.id;
}

async function selectTopic(page: Page, id: number) {
  await page.addInitScript((id) => localStorage.setItem('aa-current-topic', String(id)), id);
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}

async function expectNoSideScroll(page: Page) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));
  expect(scrollWidth, page.url()).toBeLessThanOrEqual(innerWidth);
}

/** A colour token resolved to the same rgb() string the browser reports for a computed style. */
async function tokenRgb(page: Page, token: string): Promise<string> {
  return page.evaluate((token) => {
    const probe = document.createElement('div');
    probe.style.background = `var(${token})`;
    document.body.append(probe);
    const rgb = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return rgb;
  }, token);
}

test('a disabled primary button is flat grey, not a faded brand button', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  await page.goto(`/topics/${id}/teach`);
  await settle(page);
  const submit = page.getByRole('button', { name: 'Submit for review' });
  await expect(submit).toBeDisabled();
  const style = await submit.evaluate((el) => {
    const s = getComputedStyle(el);
    return { opacity: s.opacity, bg: s.backgroundColor, color: s.color, shadow: s.boxShadow };
  });
  expect(style.opacity).toBe('1');
  // No shadow: none at all, or only fully transparent layers (how Tailwind writes shadow-none).
  expect(style.shadow.replace(/rgba\(0, 0, 0, 0\) 0px 0px 0px 0px(, )?/g, '').trim() || 'none').toBe('none');
  expect(style.bg).toBe(await tokenRgb(page, '--surface-3'));
  expect(style.bg).not.toBe(await tokenRgb(page, '--accent'));
  // And it comes back to the brand colour once there is something to submit.
  await page.getByRole('textbox').first().fill('Backprop applies the chain rule node by node.');
  await expect(submit).toBeEnabled();
  const accent = await tokenRgb(page, '--accent');
  // (The colour eases over 150ms, so wait for it to land.)
  await expect.poll(() => submit.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(accent);
});

test('every page starts at the same left edge', async ({ page }) => {
  test.skip(isPhone(), 'one column on a phone');
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  const routes = ['/', '/fleet', '/programs', '/topics/new', '/usage', `/topics/${id}/teach`, `/topics/${id}/track`, `/topics/${id}/map`];
  const edges: Record<string, number> = {};
  for (const route of routes) {
    await page.goto(route);
    await settle(page);
    edges[route] = Math.round((await page.locator('main h1').first().boundingBox())!.x);
  }
  expect(new Set(Object.values(edges)).size, JSON.stringify(edges)).toBe(1);
});

test.describe('dashboard', () => {
  test.beforeEach(async ({ page }) => {
    const id = await seededTopicId(page);
    await selectTopic(page, id);
    await page.goto('/');
    await settle(page);
  });

  test('"Where you stand" names line up and are never cut off', async ({ page }) => {
    const names = page.getByTestId('signal-name');
    await expect(names.first()).toBeVisible();
    const boxes = await names.evaluateAll((els) =>
      els.map((el) => {
        const r = el.getBoundingClientRect();
        return { x: Math.round(r.x), y: r.y, cut: el.scrollWidth > el.clientWidth + 1 };
      })
    );
    // Load-bearing or not, every name starts at the same x.
    expect(new Set(boxes.map((b) => b.x)).size).toBe(1);
    expect(boxes.filter((b) => b.cut)).toEqual([]);
    // The seeded map has both kinds, so the check above means something.
    await expect(page.getByTestId('load-bearing-slot').filter({ hasText: '◆' }).first()).toBeAttached();
    await expect(page.getByTestId('load-bearing-slot').filter({ hasNotText: '◆' }).first()).toBeAttached();

    const row = page.getByTestId('where-you-stand').getByRole('button').first();
    const name = (await row.getByTestId('signal-name').boundingBox())!;
    const marks = (await row.getByTestId('signal-marks').boundingBox())!;
    if (isPhone()) {
      // Below `sm` the signals sit on their own line under the name.
      expect(marks.y).toBeGreaterThanOrEqual(name.y + name.height - 1);
    } else {
      expect(marks.y).toBeLessThan(name.y + name.height);
    }
    await expectNoSideScroll(page);
  });

  test('untested reads as a hollow ring, verified as a diamond, the others as filled dots', async ({ page }) => {
    const dots = page.getByTestId('where-you-stand').getByTestId('verdict-dot');
    const all = await dots.evaluateAll((els) =>
      els.map((el) => ({
        verdict: el.getAttribute('data-verdict'),
        shape: el.getAttribute('data-shape'),
        hollow: el.getAttribute('data-hollow') === 'true',
        bg: getComputedStyle(el).backgroundColor
      }))
    );
    const SHAPE: Record<string, string> = { untested: 'ring', verified: 'diamond' };
    for (const d of all) expect(d.shape, d.verdict!).toBe(SHAPE[d.verdict!] ?? 'dot');
    expect(all.length).toBeGreaterThan(0);
    for (const d of all) expect(d.hollow, d.verdict!).toBe(d.verdict === 'untested');
    expect(all.some((d) => d.verdict === 'untested')).toBe(true);
    for (const d of all.filter((d) => d.hollow)) expect(d.bg).toBe('rgba(0, 0, 0, 0)');
  });

  test('calibration and build progress stack beside the map, and the score history runs full width', async ({ page }) => {
    test.skip(isPhone(), 'one column on a phone');
    const cal = (await page.getByTestId('calibration-card').boundingBox())!;
    const build = (await page.locator('section', { hasText: 'Build progress' }).boundingBox())!;
    const map = (await page.locator('section', { hasText: 'Where you stand' }).boundingBox())!;
    expect(Math.round(build.x)).toBe(Math.round(cal.x));
    expect(build.y).toBeGreaterThan(cal.y + cal.height - 1);
    expect(cal.x).toBeGreaterThan(map.x + map.width);
    // The card wraps its small plot instead of stretching to the map's height.
    expect(cal.height).toBeLessThan(map.height);
    expect(cal.height).toBeLessThan(420);
    // No dead column beside the score chart: it spans the map and the side column.
    const score = (await page.getByTestId('score-card').boundingBox())!;
    expect(Math.round(score.x)).toBe(Math.round(map.x));
    expect(score.x + score.width).toBeGreaterThanOrEqual(cal.x + cal.width - 1);
    expect(score.y).toBeGreaterThan(Math.max(map.y + map.height, build.y + build.height) - 1);
  });

  test('the mean score change reads in points, and the score chart names its x axis', async ({ page }) => {
    const delta = page.getByTestId('stat-delta');
    if (await delta.count()) await expect(delta.locator('[aria-hidden="true"]')).toHaveText(/^[+−±]\d+(\.\d)? pts$/);
    if (await delta.count()) await expect(delta).toHaveAttribute('title', 'change in the mean from the latest probe');
    await expect(page.getByTestId('score-trend-axis')).toHaveText(/probe #/);
  });

  test('activity reads as sentences, with the raw trace a toggle away', async ({ page }) => {
    const feed = page.locator('section', { hasText: 'Recent agent activity' });
    await expect(feed.locator('code')).toHaveCount(0);
    await feed.getByRole('button', { name: 'Raw trace' }).click();
    await expect(feed.locator('code').first()).toBeVisible();
    const found = (await new AxeBuilder({ page }).include('main').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()).violations;
    expect(found.map((v) => v.id)).toEqual([]);
  });
});

test('Constellation draws untested stars as hollow rings and verified ones as diamonds', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  // Every third concept verified (graded high, calibrated), every third untested (no history),
  // the rest as seeded: the map then has all three shapes to check.
  const base = { prompt: 'p', response: 'r', verdict: 'v', gaps: [], delta: null };
  await page.route('**/api/concepts/*/assessments', (r) => {
    const cid = Number(r.request().url().match(/concepts\/(\d+)/)![1]);
    if (cid % 3 === 0)
      return r.fulfill({ json: [{ ...base, id: cid, kind: 'calibration', score: 0.8, confidence_predicted: 0.8, confidence_actual: 0.8, estimate_level: 'high' }] });
    if (cid % 3 === 1) return r.fulfill({ json: [] });
    return r.continue();
  });
  await page.goto(`/topics/${id}/map`);
  await settle(page);
  await expect(page.locator('[data-settled]')).toHaveAttribute('data-settled', 'true', { timeout: 30_000 });
  const stars = await page.getByTestId('constellation-node').evaluateAll((els) =>
    els.map((el) => ({
      shape: el.getAttribute('data-shape'),
      hollow: el.getAttribute('data-hollow') === 'true',
      label: el.closest('[role="button"]')?.getAttribute('aria-label') ?? ''
    }))
  );
  expect(stars.some((s) => s.shape === 'ring')).toBe(true);
  expect(stars.some((s) => s.shape === 'diamond')).toBe(true);
  for (const s of stars) {
    expect(s.hollow, s.label).toBe(/: untested/.test(s.label));
    expect(s.shape, s.label).toBe(/: untested/.test(s.label) ? 'ring' : /: verified/.test(s.label) ? 'diamond' : 'dot');
  }
  // The legend draws the same marks.
  const legend = page.getByTestId('constellation-legend');
  await expect(legend.locator('[data-verdict="untested"]')).toHaveAttribute('data-shape', 'ring');
  await expect(legend.locator('[data-verdict="verified"]')).toHaveAttribute('data-shape', 'diamond');
  await expect(legend.locator('[data-verdict="solid"]')).toHaveAttribute('data-shape', 'dot');
});

test.describe('fleet', () => {
  const voyage = (topic_id: number, topic_title: string, state: string, progress: number) => ({
    topic_id, topic_title, value: 1, state, last_sailed: null, days_since: 1, progress
  });
  const two = [voyage(1, 'Build LLMs from scratch (demo)', 'cruising', 0.6), voyage(2, 'Linear algebra', 'becalmed', 0.2)];
  const three = [...two, voyage(3, 'Probability for machine learning', 'fading', 0.4)];

  test('a small fleet opens on tiles, and the view is a clear two-way control', async ({ page }) => {
    await page.route('**/api/fleet', (r) => r.fulfill({ json: two }));
    await page.goto('/fleet');
    await settle(page);
    const view = page.getByRole('group', { name: 'Fleet view' });
    await expect(view.getByRole('button', { name: 'Tiles' })).toHaveAttribute('aria-pressed', 'true');
    await expect(view.getByRole('button', { name: 'Harbor' })).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('fleet-panorama')).toHaveCount(0);
    await expect(page.getByText('Linear algebra')).toBeVisible();
    await view.getByRole('button', { name: 'Harbor' }).click();
    await expect(page.getByTestId('fleet-panorama')).toBeVisible();
    expect(await page.locator('main').innerText()).not.toMatch(COLOUR_EMOJI);
    await expectNoSideScroll(page);
  });

  test('three voyages open on the harbor, with whole names and line icons', async ({ page }) => {
    await page.route('**/api/fleet', (r) => r.fulfill({ json: three }));
    await page.goto('/fleet');
    await settle(page);
    await expect(page.getByRole('button', { name: 'Harbor' })).toHaveAttribute('aria-pressed', 'true');
    const names = page.getByTestId('fleet-ship-name');
    await expect(names).toHaveCount(3);
    for (const el of await names.all()) {
      const text = await el.innerText();
      expect(text).not.toMatch(/…$/);
      // Wrapped to two lines at most, never cut short.
      expect(await el.evaluate((n) => n.scrollHeight <= n.clientHeight + 1)).toBe(true);
    }
    await expect(names.first()).toHaveText('Build LLMs from scratch (demo)');
    expect(await page.locator('main').innerText()).not.toMatch(COLOUR_EMOJI);
    for (const theme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: theme });
      // The app applies the theme on the media change, then colours ease over 150ms: wait for
      // the theme to land and every transition to finish before axe measures.
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await page.evaluate(
        () =>
          new Promise<void>((done) =>
            requestAnimationFrame(() =>
              requestAnimationFrame(() =>
                Promise.all(document.getAnimations().map((a) => a.finished.catch(() => undefined))).then(() => done())
              )
            )
          )
      );
      const found = (await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()).violations;
      expect(found.map((v) => `${theme}: ${v.id} ${v.nodes.map((n) => `${n.target.join(' ')} ${n.failureSummary ?? ''}`).join(' | ')}`)).toEqual([]);
    }
    await expectNoSideScroll(page);
  });
});

test('track and wayfinder use line icons, not colour emoji', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  for (const sub of ['track', 'wayfinder']) {
    await page.goto(`/topics/${id}/${sub}`);
    await settle(page);
    expect(await page.locator('main').innerText(), sub).not.toMatch(COLOUR_EMOJI);
  }
});
