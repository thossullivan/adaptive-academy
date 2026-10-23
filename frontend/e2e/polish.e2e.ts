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

test('a topic with no track is sent to the Sources page to build one, not told it is charted', async ({ page }) => {
  // The API's answer for a topic with no track and no concepts (engine/momentum.py).
  const id = await seededTopicId(page);
  await page.route('**/api/topics/*/wind', (r) =>
    r.fulfill({
      json: { topic_id: id, topic_title: 't', value: 0, state: 'unsailed', last_sailed: null, days_since: null, progress: 0 }
    })
  );
  await page.route('**/api/topics/*/comeback', (r) =>
    r.fulfill({
      json: {
        move: { kind: 'build_track', label: 'Build your track from the reading list on the Sources page', href: `/topics/${id}/review`, minutes: 5 }
      }
    })
  );
  await page.goto(`/topics/${id}/today`);
  await settle(page);
  await expect(page.getByText('Your voyage is charted.')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: "Your voyage isn't charted yet." })).toBeVisible();
  await expect(page.getByText('Build your track from the reading list on the Sources page')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Set sail' })).toHaveCount(0);
  const go = page.getByRole('link', { name: 'Go to Sources' });
  await expect(go).toHaveAttribute('href', `/topics/${id}/review`);
  await go.click();
  await expect(page).toHaveURL(new RegExp(`/topics/${id}/review$`));
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

test('track phase titles are shown in full, never clipped', async ({ page }) => {
  const id = await seededTopicId(page);
  await page.goto(`/topics/${id}/track`);
  await settle(page);
  const long = 'Phase 2 — Tokenization, Embeddings, and the Embedding Table in Detail';
  await expect(page.getByRole('heading', { level: 2, name: long, exact: true })).toBeVisible();
  const titles = page.getByTestId('phase-title');
  await expect(titles).toHaveCount(3);
  for (const el of await titles.all()) {
    const clip = await el.evaluate((n) => ({
      x: n.scrollWidth - n.clientWidth,
      y: n.scrollHeight - n.clientHeight,
      ellipsis: getComputedStyle(n).textOverflow
    }));
    expect(clip.x).toBeLessThanOrEqual(1);
    expect(clip.y).toBeLessThanOrEqual(1);
    expect(clip.ellipsis).not.toBe('ellipsis');
  }
  await expectNoSideScroll(page);
});

test('the topic switcher shows the current title in full, or names it in full', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  await page.goto(`/topics/${id}/today`);
  await settle(page);
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  const rail = page.locator('aside:visible');
  const title = rail.getByTestId('switcher-title');
  const full = 'Build LLMs from Scratch including the math';
  await expect(title).toHaveText(full);
  // It wraps instead of cutting off after one line: nothing scrolls sideways, and at least two
  // lines of it show (it used to be a single truncated line).
  const shape = await title.evaluate((n) => ({
    x: n.scrollWidth - n.clientWidth,
    lines: Math.round(n.clientHeight / parseFloat(getComputedStyle(n).lineHeight)),
    nowrap: getComputedStyle(n).whiteSpace === 'nowrap'
  }));
  expect(shape.x).toBeLessThanOrEqual(1);
  expect(shape.nowrap).toBe(false);
  expect(shape.lines).toBe(2);
  // Whatever the clamp hides is still the button's accessible name and hover title.
  await expect(rail.getByRole('button', { name: `Topic: ${full}. Switch topic`, exact: true })).toHaveAttribute('title', full);
  // A much longer title is clamped to two lines, and is named in full the same way.
  const huge = `${full}, then fine-tune it with LoRA and serve it behind a KV cache on a laptop GPU`;
  await page.route('**/api/topics', async (r) => {
    if (r.request().method() !== 'GET') return r.fallback();
    const res = await r.fetch();
    const topics = (await res.json()) as { id: number; title: string }[];
    return r.fulfill({ json: topics.map((t) => (t.id === id ? { ...t, title: huge } : t)) });
  });
  await page.reload();
  await settle(page);
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  const trigger = page.locator('aside:visible').getByRole('button', { name: `Topic: ${huge}. Switch topic`, exact: true });
  await expect(trigger).toBeVisible();
  await expect(trigger).toHaveAttribute('title', huge);
  expect(await page.locator('aside:visible').getByTestId('switcher-title').evaluate((n) => getComputedStyle(n).webkitLineClamp)).toBe('2');
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

for (const theme of ['light', 'dark'] as const) {
  test(`the score trajectory's axis labels are all drawn and none is clipped (${theme})`, async ({ page }) => {
    test.setTimeout(90_000);
    const id = await seededTopicId(page);
    await selectTopic(page, id);
    await page.emulateMedia({ colorScheme: theme });
    let n = 0;
    let served = false;
    // n probes on the first concept the dashboard asks about, none on the rest.
    await page.route('**/api/concepts/*/assessments', (r) => {
      if (served) return r.fulfill({ json: [] });
      served = true;
      const base = { kind: 'recall', prompt: 'p', response: 'r', verdict: 'v', gaps: [], confidence_predicted: null, confidence_actual: null, delta: null, estimate_level: 'medium' };
      return r.fulfill({ json: Array.from({ length: n }, (_, k) => ({ ...base, id: n - k, score: ((n - k) * 37 % 100) / 100 })) });
    });
    for (const count of [1, 2, 5, 22]) {
      n = count;
      served = false;
      await page.goto('/');
      await settle(page);
      const card = page.locator('section', { hasText: 'Score trajectory' });
      if (count === 1) {
        await expect(card.getByText('one data point')).toBeVisible();
        continue;
      }
      const chart = card.getByTestId('score-trend');
      await expect(chart.locator('svg circle')).toHaveCount(count);
      const cardBox = (await card.boundingBox())!;
      // Every tick label paints inside the card: nothing hidden by a clipping <svg>.
      const labels = await chart.locator('svg text').evaluateAll((els) =>
        els.map((el) => {
          const r = el.getBoundingClientRect();
          // The nearest <svg> clips its children unless it is overflow:visible.
          const clip = el.closest('svg')!;
          const c = clip.getBoundingClientRect();
          const visible = getComputedStyle(clip).overflow === 'visible';
          const inClip = r.left >= c.left - 0.5 && r.right <= c.right + 0.5 && r.top >= c.top - 0.5 && r.bottom <= c.bottom + 0.5;
          return { text: el.textContent!.trim(), left: r.left, right: r.right, width: r.width, unclipped: visible || inClip };
        })
      );
      const texts = labels.map((l) => l.text);
      for (const y of ['0', '25', '50', '75', '100']) expect(texts, `${count} points: left axis`).toContain(y);
      expect(texts, `${count} points: first probe`).toContain('1');
      expect(texts, `${count} points: last probe`).toContain(String(count));
      for (const l of labels) {
        expect(l.unclipped, `${count} points: "${l.text}" is not clipped`).toBe(true);
        expect(l.width, `"${l.text}" has width`).toBeGreaterThan(0);
        expect(l.left, `${count} points: "${l.text}" inside the card`).toBeGreaterThanOrEqual(cardBox.x);
        expect(l.right, `${count} points: "${l.text}" inside the card`).toBeLessThanOrEqual(cardBox.x + cardBox.width);
      }
      // The same data, for screen readers.
      await expect(chart.locator('table tbody tr')).toHaveCount(count);
      await expect(chart).toHaveAttribute('aria-label', new RegExp(`over ${count} assessments`));
    }
  });
}

test('an empty fleet offers a way in and hides the collapse control', async ({ page }) => {
  await page.route('**/api/fleet', (r) => r.fulfill({ json: [] }));
  await page.goto('/fleet');
  await settle(page);
  await expect(page.getByTestId('fleet-empty')).toBeVisible();
  await expect(page.getByRole('group', { name: 'Fleet view' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Start a topic/ })).toHaveAttribute('href', '/topics/new');
  await expect(page.getByRole('button', { name: /Explore a demo topic/ })).toBeVisible();
  await expectNoSideScroll(page);
});

test('the fleet keeps its view control when there are voyages', async ({ page }) => {
  await page.goto('/fleet');
  await settle(page);
  const view = page.getByRole('group', { name: 'Fleet view' });
  await expect(view.getByRole('button', { name: 'Harbor' })).toBeVisible();
  await expect(view.getByRole('button', { name: 'Tiles' })).toBeVisible();
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
  // The dashboard reads in plain sentences, repeats folded with a count and the latest time.
  const rows = feed.locator('li');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toHaveText(/Exported 12 notes to your vault/);
  await expect(rows.nth(0)).not.toContainText('vault:export');
  await expect(rows.nth(0).getByTestId('event-count')).toHaveText('×4');
  await expect(rows.nth(0)).toContainText('5m ago'); // the latest of the run
  await expect(rows.nth(1)).toHaveText(/Research finished: 8 sources/);
  await expect(rows.nth(1).getByTestId('event-count')).toHaveCount(0);
  // The raw trace is one toggle away, folded the same way.
  const toggle = feed.getByRole('button', { name: 'Raw trace' });
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText('vault:export');
  await expect(rows.nth(0).getByTestId('event-count')).toHaveText('×4');
  await expect(rows.nth(1)).toContainText('research:done');
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
