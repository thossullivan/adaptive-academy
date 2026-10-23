import { expect, test, type Page } from '@playwright/test';
import { withDemoLock } from './demo-lock';

// One click from an empty home to a realistic demo topic, with no API key (the e2e API runs
// keyless), and one click to remove it again. The demo is created through the real API in the
// shared e2e db, so the spec removes it at the end and leaves the db as it found it.

const DEMO_TITLE = 'Build LLMs from scratch (demo)';
const isPhone = () => test.info().project.name === 'phone';

// The desktop and phone projects (and the a11y spec) share one db and one demo topic: the
// cross-process demo lock keeps one spec from removing the demo under another.

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.getByText('calibrating')).toHaveCount(0);
}

async function expectNoSideScroll(page: Page) {
  if (!isPhone()) return;
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth
  }));
  expect(scrollWidth, page.url()).toBeLessThanOrEqual(innerWidth);
}

async function demoTopic(page: Page): Promise<{ id: number; concepts: { id: number; name: string }[] }> {
  const topics = (await (await page.request.get('/api/topics')).json()) as {
    id: number;
    is_demo: boolean;
    concepts: { id: number; name: string }[];
  }[];
  const demo = topics.find((t) => t.is_demo);
  expect(demo, 'the demo topic exists').toBeTruthy();
  return demo!;
}

test('a keyless user explores the demo topic in one click and removes it', async ({ page }) => {
  test.setTimeout(180_000);
  await withDemoLock(async () => {
    // Start clean even if an earlier run died before removing its demo.
    await page.request.delete('/api/demo');

    // The e2e db is pre-seeded, so pretend this is a fresh install for the first load only.
    await page.route('**/api/topics', (route) =>
      route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.fallback()
    );
    await page.goto('/');
    const explore = page.getByRole('button', { name: /Explore a demo topic/ });
    await expect(explore).toBeVisible();
    await expect(page.getByText(/no API key/i)).toBeVisible();
    await expect(page.getByRole('link', { name: /Start a topic/ })).toBeVisible();
    await expectNoSideScroll(page);
    await page.unroute('**/api/topics');

    // Browsing the demo (not a program topic) must not log a single failed request; the
    // keyless tutor send at the end is the one expected error, so stop collecting before it.
    const failed: string[] = [];
    let collecting = true;
    page.on('response', (r) => {
      if (collecting && r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
    });

    await explore.click();
    await expect(page.getByRole('heading', { name: DEMO_TITLE })).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId('page-demo-badge')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Remove demo' })).toBeVisible();
    // The dashboard reads as real use: stats, a knowledge map, and an activity trace.
    await expect(page.getByText('No curriculum yet')).toHaveCount(0);
    await expect(page.getByText('Causal Self-Attention').first()).toBeVisible();
    await expect(page.getByText('No activity yet.')).toHaveCount(0);
    await expectNoSideScroll(page);

    // The topic switcher marks the demo too (inside the drawer on a phone).
    if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
    await expect(page.getByTestId('switcher-demo-badge').filter({ visible: true })).toBeVisible();
    if (isPhone()) await page.keyboard.press('Escape');

    const demo = await demoTopic(page);

    await page.goto(`/topics/${demo.id}/today`);
    await settle(page);
    await expect(page.getByText('Your next steps on the track:')).toBeVisible();
    await expect(page.getByText(/decay check/).first()).toBeVisible();
    await expect(page.getByText('No track yet', { exact: false })).toHaveCount(0);
    await expectNoSideScroll(page);

    await page.goto(`/topics/${demo.id}/track`);
    await settle(page);
    await expect(page.getByText('Phase 1 — Autograd from first principles')).toBeVisible();
    await expect(page.getByText('Phase 4 — Train a tiny GPT')).toBeVisible();
    // Side notes name their kind in words ("Math refresher"), never as raw `math_refresh`.
    const kinds = page.getByTestId('sidebar-kind');
    expect(await kinds.count()).toBeGreaterThan(0);
    for (const kind of await kinds.allTextContents()) expect(kind).toMatch(/^[A-Z][a-z]+( [a-z]+)*$/);
    await expectNoSideScroll(page);

    await page.goto(`/topics/${demo.id}/map`);
    await settle(page);
    await expect(page.getByText(`${demo.concepts.length} concepts`)).toBeVisible();
    await expect(page.getByText('No concepts to map')).toHaveCount(0);
    await expect(page.getByText(/\d+ concept links/)).toBeVisible();
    await expectNoSideScroll(page);

    await page.goto(`/topics/${demo.id}/retention`);
    await settle(page);
    await expect(page.getByText(/Decay checks · \d+/)).toBeVisible();
    await expect(page.getByText(/Due now · \d+/)).toBeVisible();
    await expect(page.getByText('No cards yet', { exact: false })).toHaveCount(0);
    // Prompts are rendered as markdown: "*why*" shows in italics, not with its asterisks.
    const prompt = page.locator('[id^="decay-prompt-"]').first();
    await expect(prompt.locator('em', { hasText: 'why' })).toBeVisible();
    await expect(page.locator('main').getByText('*why*')).toHaveCount(0);
    await expectNoSideScroll(page);

    await page.goto(`/topics/${demo.id}/story`);
    await settle(page);
    await expect(page.getByText('The numbers behind the story')).toBeVisible();
    await expect(page.getByTestId('story-facts')).toContainText('Assessments');
    // Only graded concepts count as solid; the six the demo never probed are untested (their
    // stored estimate is a prior, not a grade).
    await expect(page.getByTestId('story-facts')).toContainText('6 untested');
    // One way to compose the story, not one in the header and another in the card.
    await expect(page.getByRole('button', { name: 'Compose my story' })).toHaveCount(1);
    await expectNoSideScroll(page);

    collecting = false;
    expect(failed, 'failed requests while browsing the demo').toEqual([]);

    // A new tutor session starts with the reveal gate closed; sending without a key says how to
    // fix it and keeps the draft.
    const causal = demo.concepts.find((c) => c.name === 'Causal Self-Attention')!;
    await page.goto(`/topics/${demo.id}/tutor?concept=${causal.id}`);
    await settle(page);
    await expect(page.getByText('no attempt yet')).toBeVisible();
    const draft = 'Why −∞ and not a large negative number?';
    await page.getByPlaceholder(/Ask the tutor/).fill(draft);
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText(/ANTHROPIC_API_KEY/).first()).toBeVisible();
    await expect(page.getByPlaceholder(/Ask the tutor/)).toHaveValue(draft);
    await expectNoSideScroll(page);

    // Remove it from its dashboard, with a confirm step.
    await page.goto('/');
    await settle(page);
    await expect(page.getByRole('heading', { name: DEMO_TITLE })).toBeVisible();
    await page.getByRole('button', { name: 'Remove demo' }).click();
    await expect(page.getByText(/Remove the demo topic and everything in it\?/)).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('heading', { name: DEMO_TITLE })).toBeVisible();
    await page.getByRole('button', { name: 'Remove demo' }).click();
    await page.getByRole('button', { name: 'Yes, remove it' }).click();
    await expect(page.getByRole('heading', { name: DEMO_TITLE })).toHaveCount(0);
    await expect(page).toHaveURL(/\/$/);

    const left = (await (await page.request.get('/api/topics')).json()) as { is_demo: boolean }[];
    expect(left.some((t) => t.is_demo)).toBe(false);
  });
});
