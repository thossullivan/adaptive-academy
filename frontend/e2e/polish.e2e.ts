import { expect, test, type Page } from '@playwright/test';

// UI polish regressions: clipped text that could not be read, fractional axis ticks, a
// bare empty state, repeated trace rows, an artifact verdict that read "—", and 404 noise.
// Every view is checked at both 1440px and 390px (the phone project).

const isPhone = () => test.info().project.name === 'phone';

async function seededTopicId(page: Page): Promise<number> {
  const topics = (await (await page.request.get('/api/topics')).json()) as { id: number }[];
  expect(topics.length).toBeGreaterThan(0);
  return topics[0].id;
}

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

async function selectTopic(page: Page, id: number) {
  await page.addInitScript((id) => localStorage.setItem('aa-current-topic', String(id)), id);
}

const LONG_MOVE =
  "Derive the evidence lower bound by hand from Jensen's inequality, then implement a " +
  'reparameterised Gaussian VAE on MNIST and verify the gradient estimator against finite ' +
  'differences before scaling to the full dataset.';

test('the comeback move is clipped on a word boundary and can be read in full', async ({ page }) => {
  const id = await seededTopicId(page);
  await page.route('**/api/topics/*/wind', (r) =>
    r.fulfill({
      json: { topic_id: id, topic_title: 't', value: 0, state: 'unsailed', last_sailed: null, days_since: null, progress: 0 }
    })
  );
  await page.route('**/api/topics/*/comeback', (r) =>
    r.fulfill({ json: { move: { kind: 'build', label: LONG_MOVE, href: `/topics/${id}/track`, minutes: 25 } } })
  );
  await page.goto(`/topics/${id}/today`);
  await settle(page);

  const move = page.locator('p', { hasText: 'Derive the evidence lower bound' }).first();
  await expect(move).toHaveAttribute('title', LONG_MOVE);
  const clipped = (await move.innerText()).replace(/\s*Show all$/, '').trim();
  expect(clipped.endsWith('…')).toBe(true);
  expect(LONG_MOVE.startsWith(clipped.slice(0, -1))).toBe(true);
  expect(LONG_MOVE[clipped.length - 1]).toBe(' '); // cut between words, never mid-word

  const toggle = page.getByRole('button', { name: 'Show all' });
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await toggle.click();
  await expect(page.getByText('before scaling to the full dataset.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Show less' })).toHaveAttribute('aria-expanded', 'true');
  await expectNoSideScroll(page);
});

test('wayfinder phase titles are shown in full, never clipped', async ({ page }) => {
  const id = await seededTopicId(page);
  await page.goto(`/topics/${id}/wayfinder`);
  await settle(page);
  const long = 'Phase 2 — Tokenization, Embeddings, and the Embedding Table in Detail';
  await expect(page.getByRole('heading', { name: long, exact: true })).toBeVisible();
  const titles = page.getByTestId('waypoint-title');
  await expect(titles).toHaveCount(3);
  for (const el of await titles.all()) {
    const clippedBy = await el.evaluate((n) => ({
      overflow: n.scrollWidth - n.clientWidth,
      ellipsis: getComputedStyle(n).textOverflow
    }));
    expect(clippedBy.overflow).toBeLessThanOrEqual(1);
    expect(clippedBy.ellipsis).not.toBe('ellipsis');
  }
  // The next-step link keeps its whole text as its accessible name and hover title.
  const steer = page.getByRole('link', { name: /steer toward/ });
  await expect(steer).toHaveAttribute('title', /Clone micrograd .* XOR dataset\./);
  await expectNoSideScroll(page);
});

test('the score trajectory axis only shows whole-number probe ticks', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  // Two probes on the first concept, none elsewhere: d3's "nice" ticks for n=2 were 1, 1.5, 2.
  let served = false;
  await page.route('**/api/concepts/*/assessments', (r) => {
    const base = { prompt: 'p', response: 'r', verdict: 'v', gaps: [], confidence_predicted: null, confidence_actual: null, delta: null, estimate_level: 'medium' };
    if (served) return r.fulfill({ json: [] });
    served = true;
    return r.fulfill({
      json: [
        { ...base, id: 2, kind: 'recall', score: 0.6 },
        { ...base, id: 1, kind: 'self_explanation', score: 0.35 }
      ]
    });
  });
  await page.goto('/');
  await settle(page);
  const card = page.locator('section', { hasText: 'Score trajectory' });
  await expect(card.locator('svg circle').first()).toBeVisible();
  const labels = (await card.locator('svg text').allTextContents()).map((t) => t.trim()).filter(Boolean);
  expect(labels).toContain('1');
  expect(labels).toContain('2');
  expect(labels.filter((t) => !/^\d+$/.test(t)), 'non-integer tick labels').toEqual([]);
});

test('an empty fleet offers a way in and hides the collapse control', async ({ page }) => {
  await page.route('**/api/fleet', (r) => r.fulfill({ json: [] }));
  await page.goto('/fleet');
  await settle(page);
  await expect(page.getByTestId('fleet-empty')).toBeVisible();
  await expect(page.getByRole('button', { name: /Collapse to tiles|Show harbor/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Start a topic/ })).toHaveAttribute('href', '/topics/new');
  await expect(page.getByRole('button', { name: /Explore a demo topic/ })).toBeVisible();
  await expectNoSideScroll(page);
});

test('the fleet keeps its collapse control when there are voyages', async ({ page }) => {
  await page.goto('/fleet');
  await settle(page);
  await expect(page.getByRole('button', { name: 'Collapse to tiles' })).toBeVisible();
});

test('repeated agent events collapse into one row with a count', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  const at = (m: number) => new Date(Date.now() - m * 60_000).toISOString().replace('Z', '');
  await page.route('**/api/topics/*/events', (r) =>
    r.fulfill({
      json: [
        { kind: 'research:done', detail: '8 sources', created_at: at(50) },
        { kind: 'vault:export', detail: '12 notes', created_at: at(40) },
        { kind: 'vault:export', detail: '12 notes', created_at: at(30) },
        { kind: 'vault:export', detail: '12 notes', created_at: at(20) },
        { kind: 'vault:export', detail: '12 notes', created_at: at(5) }
      ]
    })
  );
  await page.goto('/');
  await settle(page);
  const feed = page.locator('section', { hasText: 'Recent agent activity' });
  const rows = feed.locator('li');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('vault:export');
  await expect(rows.nth(0).getByTestId('event-count')).toHaveText('×4');
  await expect(rows.nth(0)).toContainText('5m ago'); // the latest of the run
  await expect(rows.nth(1)).toContainText('research:done');
  await expect(rows.nth(1).getByTestId('event-count')).toHaveCount(0);
  await expectNoSideScroll(page);
});

test('an artifact review shows what it did to the shipped signal, not a "—" grade', async ({ page }) => {
  const id = await seededTopicId(page);
  const result = (score: number) => ({
    id: 99, kind: 'artifact_review', prompt: 'p', response: 'r',
    verdict: 'The notebook trains end to end.', score, gaps: [],
    confidence_predicted: null, confidence_actual: null, delta: null, estimate_level: null
  });
  let score = 0.72;
  await page.route('**/api/concepts/*/assess', (r) => r.fulfill({ json: result(score) }));
  await page.goto(`/topics/${id}/assess`);
  await settle(page);
  await page.getByRole('combobox').nth(1).selectOption('artifact_review');
  await page.getByRole('button', { name: 'Submit for assessment' }).click();
  await expect(page.getByTestId('artifact-outcome')).toHaveText('shipped ✓');
  await expect(page.getByText(/Artifact reviews corroborate rather than grade/)).toBeVisible();
  await expect(page.getByText('72', { exact: true })).toBeVisible();

  score = 0.3;
  await page.getByRole('button', { name: 'Submit for assessment' }).click();
  await expect(page.getByTestId('artifact-outcome')).toHaveText('shipped ✗');
  await expectNoSideScroll(page);
});

test('a standalone topic loads its pages without any failed API request', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  const failed: string[] = [];
  page.on('response', (r) => {
    if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
  });
  for (const route of ['/', `/topics/${id}/today`, `/topics/${id}/track`, `/topics/${id}/wayfinder`]) {
    await page.goto(route);
    await settle(page);
  }
  expect(failed).toEqual([]);
});
