import { expect, test, type Page } from '@playwright/test';

// The design pass on the topic pages: each page opens with a plain line about what it is for,
// shows one filled (primary) button for its next step, and never cuts a concept name off
// mid-letter. Checked at 1440px and 390px (the phone project).

const isPhone = () => test.info().project.name === 'phone';

async function seededTopicId(page: Page): Promise<number> {
  const topics = (await (await page.request.get('/api/topics')).json()) as { id: number; is_demo: boolean }[];
  const topic = topics.find((t) => !t.is_demo);
  expect(topic, 'the seeded topic exists').toBeTruthy();
  return topic!.id;
}

async function open(page: Page, path: string) {
  await page.goto(path);
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main h1')).toBeVisible();
}

async function expectNoSideScroll(page: Page) {
  if (!isPhone()) return;
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));
  expect(scrollWidth, page.url()).toBeLessThanOrEqual(innerWidth);
}

// Words the old page intros used that said nothing to a newcomer.
const JARGON = [
  /Learning command center/i,
  /Ledger/,
  /grapple first/i,
  /load-bearing/i,
  /triangulated verdict/i,
  /highest-leverage/i,
  /evidence base/i,
  /verified-depth/i,
  /generation-first/i,
  /CurriculumDirector/,
  /Desirable difficulty/i,
  /the reckoning/i,
  /explicate/i,
  /Becalmed/i,
  /file I\/O/i,
  /Metacognition/i,
  /Observability/i,
  /—/
];

const PAGES = ['today', 'practice', 'assess', 'teach', 'track', 'map', 'retention', 'review', 'story', 'vault'];

for (const name of PAGES) {
  test(`the ${name} page intro is plain and has at most one primary button`, async ({ page }) => {
    const id = await seededTopicId(page);
    await open(page, `/topics/${id}/${name}`);
    const header = page.locator('main header').first();
    const intro = (await header.textContent()) ?? '';
    for (const word of JARGON) expect(intro, `${name}: ${word}`).not.toMatch(word);
    // One filled button: the next step. The rest are outlined.
    const primaries = page.locator('main').locator('a.bg-accent, button.bg-accent').filter({ visible: true });
    expect(await primaries.count(), `${name}: primary buttons`).toBeLessThanOrEqual(1);
    await expectNoSideScroll(page);
  });
}

for (const path of ['/programs', '/programs/new', '/topics/new', '/usage', '/data', '/fleet']) {
  test(`${path} opens with a plain intro`, async ({ page }) => {
    await open(page, path);
    const intro = (await page.locator('main header').first().textContent()) ?? '';
    for (const word of JARGON) expect(intro, `${path}: ${word}`).not.toMatch(word);
  });
}

test('the dashboard says plainly what it shows', async ({ page }) => {
  await open(page, '/');
  const text = (await page.locator('main').textContent()) ?? '';
  for (const word of JARGON.slice(0, -1)) expect(text, `dashboard: ${word}`).not.toMatch(word);
});

test('Today fills only the button of the first step with something to do', async ({ page }) => {
  const id = await seededTopicId(page);
  await open(page, `/topics/${id}/today`);
  await expect(page.getByRole('heading', { name: 'Teach back' })).toBeVisible();
  await expect(page.locator('main').locator('a.bg-accent, button.bg-accent')).toHaveCount(1);
});

test('Today keeps "Warm up" on one line, with its badges wrapping as a group', async ({ page }) => {
  const id = await seededTopicId(page);
  await open(page, `/topics/${id}/today`);
  const heading = page.getByRole('heading', { name: 'Warm up' });
  await expect(heading).toBeVisible();
  const lines = await heading.evaluate((h) => Math.round(h.getBoundingClientRect().height / parseFloat(getComputedStyle(h).lineHeight)));
  expect(lines).toBe(1);
  for (const badge of await page.getByTestId('warmup-heading').locator('span.rounded-full').all()) {
    const shape = await badge.evaluate((b) => ({ h: b.getBoundingClientRect().height, nowrap: getComputedStyle(b).whiteSpace }));
    expect(shape.nowrap).toBe('nowrap');
    expect(shape.h).toBeLessThan(32);
  }
  await expectNoSideScroll(page);
});

for (const name of ['practice', 'assess', 'teach']) {
  test(`the ${name} concept picker shows names whole, or ends them with an ellipsis`, async ({ page }) => {
    const id = await seededTopicId(page);
    await open(page, `/topics/${id}/${name}`);
    const picker = page.getByTestId('concept-picker');
    await expect(picker).toBeVisible();
    const fit = await picker.evaluate((el) => {
      const s = el as HTMLSelectElement;
      const style = getComputedStyle(s);
      const ctx = document.createElement('canvas').getContext('2d')!;
      ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const widest = Math.max(...[...s.options].map((o) => ctx.measureText(o.text).width));
      const room = s.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const box = s.getBoundingClientRect();
      return { widest, room, ellipsis: style.textOverflow, right: box.right, height: box.height };
    });
    expect(fit.ellipsis).toBe('ellipsis');
    expect(fit.right).toBeLessThanOrEqual(page.viewportSize()!.width);
    // On a desktop every seeded concept name fits whole.
    if (!isPhone()) expect(fit.widest).toBeLessThanOrEqual(fit.room + 1);
    await expectNoSideScroll(page);
  });
}

test('Practice, Assess and Teach submit with the same size of button', async ({ page }) => {
  const id = await seededTopicId(page);
  const heights: number[] = [];
  await open(page, `/topics/${id}/assess`);
  heights.push((await page.getByRole('button', { name: 'Submit for assessment' }).boundingBox())!.height);
  await open(page, `/topics/${id}/teach`);
  heights.push((await page.getByRole('button', { name: 'Submit for review' }).boundingBox())!.height);
  await open(page, `/topics/${id}/practice`);
  heights.push((await page.getByRole('button', { name: 'Generate challenge' }).boundingBox())!.height);
  expect(new Set(heights.map(Math.round)).size).toBe(1);
});
