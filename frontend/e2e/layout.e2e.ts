import { expect, test, type Page } from '@playwright/test';

// The shared page frame (shell/Page.svelte): every page's content starts at the same left
// edge, whatever its own width, so moving between pages never makes the content jump sideways.
// At 1440px the heading of every main page sits at one x; at 390px no page scrolls sideways.
// The Tutor page is left out on purpose: it is a full-height chat, not a framed page.

const isPhone = () => test.info().project.name === 'phone';

const APP_PAGES = ['/', '/fleet', '/programs', '/programs/new', '/topics/new', '/usage', '/data'];
const TOPIC_PAGES = [
  'today',
  'practice',
  'assess',
  'teach',
  'track',
  'wayfinder',
  'map',
  'retention',
  'review',
  'notebook',
  'vault',
  'story'
];

async function seededTopicId(page: Page): Promise<number> {
  const topics = (await (await page.request.get('/api/topics')).json()) as { id: number; title: string }[];
  return topics.find((t) => t.title === 'Build LLMs from Scratch including the math')!.id;
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}

async function routes(page: Page): Promise<string[]> {
  const id = await seededTopicId(page);
  await page.addInitScript((id) => localStorage.setItem('aa-current-topic', String(id)), id);
  return [...APP_PAGES, ...TOPIC_PAGES.map((s) => `/topics/${id}/${s}`)];
}

test('every main page puts its heading at the same left edge at 1440px', async ({ page }) => {
  test.skip(isPhone(), 'desktop width only');
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const edges: Record<string, number> = {};
  for (const route of await routes(page)) {
    await page.goto(route);
    await settle(page);
    const h1 = page.locator('main h1').first();
    await expect(h1, route).toBeVisible();
    edges[route] = Math.round((await h1.boundingBox())!.x);
  }
  const xs = new Set(Object.values(edges));
  expect(xs.size, JSON.stringify(edges, null, 1)).toBe(1);
  // And that edge is the frame's: the rail's width plus the frame's padding, not drifting.
  const frame = await page.locator('[data-page-frame]').first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    return r.x + parseFloat(getComputedStyle(el).paddingLeft);
  });
  expect([...xs][0]).toBe(Math.round(frame));
});

test('no main page scrolls sideways at 390px', async ({ page }) => {
  test.skip(!isPhone(), 'phone width only');
  test.setTimeout(120_000);
  const width = page.viewportSize()!.width;
  const overflowing: string[] = [];
  for (const route of await routes(page)) {
    await page.goto(route);
    await settle(page);
    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth
    }));
    if (scrollWidth > innerWidth || scrollWidth > width) overflowing.push(`${route}: ${scrollWidth}`);
  }
  expect(overflowing).toEqual([]);
});
