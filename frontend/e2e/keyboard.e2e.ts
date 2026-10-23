import { expect, test, type Page } from '@playwright/test';
import { withDemoShared } from './demo-lock';

// Keyboard and screen-reader checks axe cannot make: names on icon-only controls, a visible
// focus indicator, focus that moves sensibly (and is trapped only in the phone drawer), text
// alternatives for the charts, live regions for async results, a sane heading outline, and
// reduced motion. Runs at desktop and phone width (the two Playwright projects).

const isPhone = () => test.info().project.name === 'phone';

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
}

/** Whether the focused element paints a focus indicator (outline, ring, or a drawn ring). */
async function focusIndicator(page: Page) {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { tag: 'body', visible: false };
    const s = getComputedStyle(el);
    const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 1;
    const ring = s.boxShadow !== 'none' && s.boxShadow.includes('0px 0px 0px');
    const drawn = !!el.querySelector('[data-testid="constellation-focus-ring"]');
    return { tag: `${el.tagName.toLowerCase()} ${el.getAttribute('aria-label') ?? el.textContent?.trim().slice(0, 30)}`, visible: outline || ring || drawn };
  });
}

test('icon-only controls have accessible names', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  await page.goto(`/topics/${id}/today`);
  await settle(page);
  if (isPhone()) {
    const menu = page.getByRole('button', { name: 'Open navigation' });
    await expect(menu).toBeVisible();
    await menu.click();
    await expect(page.getByRole('button', { name: 'Close navigation' })).toBeVisible();
  }
  const rail = page.locator('aside:visible');
  await expect(rail.getByRole('button', { name: 'Dismiss hint' })).toBeVisible();
  await expect(rail.getByRole('button', { name: /^Topic: Build LLMs from Scratch including the math\. Switch topic$/ })).toBeVisible();
  for (const name of ['System', 'Light', 'Dark']) {
    await expect(rail.getByRole('radiogroup', { name: 'Theme' }).getByRole('radio', { name })).toBeVisible();
  }
  await expect(rail.getByRole('navigation', { name: 'Main' })).toBeVisible();
  // Every button anywhere on the page has a name (axe checks this too; here per state).
  const unnamed = await page.locator('button:visible').evaluateAll((els) =>
    els.filter((b) => !(b.getAttribute('aria-label') || b.textContent?.trim() || b.getAttribute('title'))).map((b) => b.outerHTML.slice(0, 120))
  );
  expect(unnamed).toEqual([]);
});

test('keyboard focus is visible on every stop, and only the phone drawer traps it', async ({ page }) => {
  test.setTimeout(90_000);
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  await page.goto(`/topics/${id}/assess`);
  await settle(page);
  const seen: string[] = [];
  let reachedMain = false;
  for (let i = 0; i < 45; i++) {
    await page.keyboard.press('Tab');
    const f = await focusIndicator(page);
    if (f.tag === 'body') continue;
    expect(f.visible, `focus visible on ${f.tag}`).toBe(true);
    seen.push(f.tag);
    if (await page.evaluate(() => !!document.querySelector('main')?.contains(document.activeElement))) {
      reachedMain = true;
      if (seen.length > 3) break;
    }
  }
  // Tab is not trapped in the rail (or the phone's top bar): it reaches the page itself.
  expect(reachedMain, `tab stops: ${seen.join(' | ')}`).toBe(true);
});

test('the topic switcher opens, closes with Escape and gives focus back', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  await page.goto(`/topics/${id}/today`);
  await settle(page);
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  const rail = page.locator('aside:visible');
  const trigger = rail.getByRole('button', { name: /^Topic: / });
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  const current = rail.getByRole('list', { name: 'Topics' }).locator('[aria-current="true"]');
  await expect(current).toBeFocused();
  await page.keyboard.press('ArrowDown');
  await expect(current).not.toBeFocused();
  await page.keyboard.press('Escape');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await expect(trigger).toBeFocused();
  // On a phone, Escape closed only the list; the drawer is still open.
  if (isPhone()) await expect(page.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'true');
});

test('constellation stars take focus with a visible ring, and Enter or Space selects', async ({ page }) => {
  const id = await seededTopicId(page);
  await page.goto(`/topics/${id}/map`);
  await settle(page);
  await expect(page.getByTestId('constellation')).toHaveAttribute('data-settled', 'true', { timeout: 20_000 });
  const stars = page.getByTestId('constellation').getByRole('button');
  await expect(stars).toHaveCount(19);
  const first = stars.first();
  // Reach the first star from the control before it, as a keyboard user would.
  await first.evaluate((el) => {
    const prev = document.createElement('button');
    prev.textContent = 'before';
    el.closest('[data-testid="constellation"]')!.before(prev);
    prev.focus();
  });
  await page.keyboard.press('Tab');
  await expect(first).toBeFocused();
  await expect(first.getByTestId('constellation-focus-ring')).toHaveCount(1);
  expect((await focusIndicator(page)).visible).toBe(true);
  const name = (await first.getAttribute('aria-label'))!;
  expect(name).toMatch(/: (solid|verified|unverified|shaky|untested)/);
  await page.keyboard.press('Enter');
  await expect(first).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { level: 2, name: name.split(':')[0] })).toBeVisible();
  // Space works too (role=button), on the next star.
  await page.keyboard.press('Tab');
  await page.keyboard.press(' ');
  await expect(stars.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await expect(first).toHaveAttribute('aria-pressed', 'false');
  // The selection is announced.
  await expect(page.locator('[role="status"]').filter({ hasText: /^Selected / })).toHaveCount(1);
});

test('the constellation has a non-visual alternative: every concept as a list', async ({ page }) => {
  const id = await seededTopicId(page);
  await page.goto(`/topics/${id}/map`);
  await settle(page);
  await expect(page.getByRole('group', { name: /Concept graph: 19 concepts, 30 links/ })).toBeAttached();
  const list = page.getByTestId('concept-list');
  await list.getByText('Concepts as a list').click();
  const items = list.getByRole('button');
  await expect(items).toHaveCount(19);
  // Prerequisites in words, read from the graph the page draws ("src requires dst").
  const graph = (await (await page.request.get(`/api/topics/${id}/graph`)).json()) as {
    nodes: { id: number; name: string }[];
    edges: { src: number; dst: number; kind: string }[];
  };
  const byId = new Map(graph.nodes.map((n) => [n.id, n.name]));
  const withPrereq = graph.edges.find((e) => e.kind === 'prerequisite')!;
  const needs = graph.edges.filter((e) => e.kind === 'prerequisite' && e.src === withPrereq.src).map((e) => byId.get(e.dst)!);
  const row = list.getByRole('button', { name: new RegExp(`^${byId.get(withPrereq.src)!.replace(/[()]/g, '\\$&')}`) });
  for (const n of needs) await expect(row).toContainText(n);
  await list.getByRole('button', { name: /^Multi-Head Attention/ }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Multi-Head Attention' })).toBeVisible();
});

test('charts carry a text alternative', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  let served = false;
  await page.route('**/api/concepts/*/assessments', (r) => {
    if (served) return r.fulfill({ json: [] });
    served = true;
    const base = { kind: 'calibration', prompt: 'p', response: 'r', verdict: 'v', gaps: [], delta: null, estimate_level: 'medium' };
    return r.fulfill({
      json: [
        { ...base, id: 3, score: 0.8, confidence_predicted: 0.5, confidence_actual: 0.8 },
        { ...base, id: 2, score: 0.4, confidence_predicted: 0.9, confidence_actual: 0.4 },
        { ...base, id: 1, score: 0.6, confidence_predicted: 0.62, confidence_actual: 0.6 }
      ]
    });
  });
  await page.goto('/');
  await settle(page);
  const trend = page.getByTestId('score-trend');
  await expect(trend).toHaveAttribute('aria-label', /over 3 assessments: first 60%, latest 80%/);
  await expect(trend.getByRole('table')).toBeAttached();
  const cal = page.getByTestId('calibration-plot');
  await expect(cal).toHaveAttribute('aria-label', /3 probes.*1 well calibrated, 1 overconfident, 1 underconfident/);
  await expect(cal.getByRole('row')).toHaveCount(4); // header + 3

  await page.goto(`/topics/${id}/wayfinder`);
  await settle(page);
  await expect(page.getByTestId('wayfinder-summary')).toHaveText(/3 waypoints, \d+ charted\./);
  await expect(page.getByRole('list', { name: 'Waypoints' }).getByRole('listitem')).toHaveCount(3);

  await page.goto('/fleet');
  await settle(page);
  await expect(page.getByTestId('fleet-panorama')).toHaveAttribute('aria-label', /voyage/);
  const ship = page.getByTestId('fleet-panorama').getByRole('link').first();
  await expect(ship).toHaveAttribute('aria-label', /: .+, \d+% toward the North Star$/);
});

test('the demo remove confirm moves focus to Cancel and back', async ({ page }) => {
  await withDemoShared(
    async () => {
      const { topic_id } = (await (await page.request.post('/api/demo')).json()) as { topic_id: number };
      await selectTopic(page, topic_id);
    },
    async () => {
      await page.goto('/');
      await settle(page);
      const remove = page.getByRole('button', { name: 'Remove demo' });
      await remove.focus();
      await page.keyboard.press('Enter');
      const cancel = page.getByRole('button', { name: 'Cancel' });
      await expect(cancel).toBeFocused();
      await expect(page.getByRole('group', { name: 'Remove the demo topic and everything in it?' })).toBeVisible();
      await page.keyboard.press('Enter');
      await expect(page.getByRole('button', { name: 'Remove demo' })).toBeFocused();
      // Escape cancels as well.
      await page.keyboard.press('Enter');
      await expect(cancel).toBeFocused();
      await page.keyboard.press('Escape');
      await expect(page.getByRole('button', { name: 'Remove demo' })).toBeFocused();
    }
  );
});

test('async results are announced through live regions', async ({ page }) => {
  const id = await seededTopicId(page);
  // Toasts: the region exists before any toast, so the first one is read out.
  await page.goto(`/topics/${id}/tutor`);
  await settle(page);
  const toaster = page.getByTestId('toaster');
  await expect(toaster).toHaveAttribute('aria-live', 'polite');
  await expect(toaster).toBeEmpty();
  // The keyless send fails: the error toast lands inside the live region, marked as an error.
  await page.getByRole('textbox', { name: 'Message the tutor' }).fill('hello');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(toaster).toContainText(/Error: .*ANTHROPIC_API_KEY/);

  // Tutor: the transcript is a log, so a reply is read when it lands.
  await page.route('**/api/conversations', (r) =>
    r.request().method() === 'POST'
      ? r.fulfill({ json: { id: 998, concept_id: 1, attempt_logged: false, assistance_level: 'medium', challenge_level: 'medium', messages: [] } })
      : r.fallback()
  );
  await page.route('**/api/conversations/998/messages', (r) =>
    r.fulfill({ json: { reply: 'Try the 2×2 case first.', attempt_logged: false, assistance_level: 'medium', challenge_level: 'medium', events: [], memory: [] } })
  );
  await page.reload();
  await settle(page);
  const log = page.getByRole('log', { name: 'Conversation with the tutor' });
  await expect(log).toBeVisible();
  await page.getByRole('textbox', { name: 'Message the tutor' }).fill('hello');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(log).toContainText('Try the 2×2 case first.');

  // Assess: the grade is announced (the result card itself is not a live region).
  await page.route('**/api/concepts/*/assess', (r) =>
    r.fulfill({ json: { id: 77, kind: 'self_explanation', prompt: 'p', response: 'r', verdict: 'Solid mechanism.', score: 0.81, gaps: [], confidence_predicted: null, confidence_actual: null, delta: null, estimate_level: 'high' } })
  );
  await page.goto(`/topics/${id}/assess`);
  await settle(page);
  const status = page.locator('[role="status"][aria-live="polite"]').filter({ hasText: /^Assessment/ });
  await page.getByRole('button', { name: 'Submit for assessment' }).click();
  await expect(status).toHaveText('Assessment 1: 81 out of 100, high.');
});

const OUTLINE_PAGES = (id: number) => [
  '/',
  '/fleet',
  '/programs',
  '/programs/new',
  '/topics/new',
  '/usage',
  '/data',
  ...['today', 'tutor', 'track', 'practice', 'assess', 'teach', 'retention', 'review', 'notebook', 'story', 'vault', 'wayfinder', 'map'].map(
    (s) => `/topics/${id}/${s}`
  )
];

test('every page has one h1, a matching title, and no skipped heading levels', async ({ page }) => {
  test.setTimeout(120_000);
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  for (const url of OUTLINE_PAGES(id)) {
    await page.goto(url);
    await settle(page);
    const headings = await page.locator('main h1, main h2, main h3, main h4, main h5, main h6').evaluateAll((els) =>
      els
        .filter((h) => h.getClientRects().length > 0 || h.classList.contains('sr-only'))
        .map((h) => ({ level: Number(h.tagName[1]), text: h.textContent!.trim().slice(0, 40) }))
    );
    expect(headings.filter((h) => h.level === 1), `${url}: one h1 in ${JSON.stringify(headings)}`).toHaveLength(1);
    expect(headings[0].level, `${url} starts at h1`).toBe(1);
    for (let i = 1; i < headings.length; i++) {
      expect(headings[i].level - headings[i - 1].level, `${url}: ${headings[i - 1].text} → ${headings[i].text}`).toBeLessThanOrEqual(1);
    }
    await expect(page, url).toHaveTitle(/ · Adaptive Academy$/);
  }
});

test('form fields have labels, and controls have a 3:1 boundary', async ({ page }) => {
  const id = await seededTopicId(page);
  await selectTopic(page, id);
  for (const url of ['/topics/new', '/programs/new', `/topics/${id}/assess`, `/topics/${id}/tutor`, `/topics/${id}/practice`, `/topics/${id}/teach`]) {
    for (const theme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await page.goto(url);
      await settle(page);
      const fields = await page.locator('main').locator('input:visible, select:visible, textarea:visible').evaluateAll((els) =>
        els.map((el) => {
          const lum = (c: string) => {
            const [r, g, b] = c.match(/[\d.]+/g)!.slice(0, 3).map((v) => {
              const s = Number(v) / 255;
              return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
            });
            return 0.2126 * r + 0.7152 * g + 0.0722 * b;
          };
          // The colour around the field: the nearest ancestor with an opaque background.
          let p = el.parentElement;
          let around = 'rgb(255, 255, 255)';
          while (p) {
            const bg = getComputedStyle(p).backgroundColor;
            if (bg && !bg.startsWith('rgba(0, 0, 0, 0)') && !/,\s*0\)$/.test(bg)) {
              around = bg;
              break;
            }
            p = p.parentElement;
          }
          const border = getComputedStyle(el).borderTopColor;
          const [a, b] = [lum(border), lum(around)].sort((x, y) => y - x);
          const labelled =
            !!el.getAttribute('aria-label') ||
            !!el.closest('label') ||
            (!!el.id && !!document.querySelector(`label[for="${el.id}"]`)) ||
            !!el.getAttribute('aria-labelledby');
          return { field: el.outerHTML.slice(0, 90), labelled, contrast: (a + 0.05) / (b + 0.05), type: (el as HTMLInputElement).type };
        })
      );
      expect(fields.length, url).toBeGreaterThan(0);
      for (const f of fields) {
        expect(f.labelled, `${url}: ${f.field} has a label`).toBe(true);
        if (f.type !== 'range') expect(f.contrast, `${url} (${theme}): ${f.field} boundary`).toBeGreaterThanOrEqual(3);
      }
    }
  }
});

test('the theme picker is touch-sized in the phone drawer', async ({ page }) => {
  test.skip(!isPhone(), 'phone-only layout');
  await page.goto('/');
  await settle(page);
  await page.getByRole('button', { name: 'Open navigation' }).click();
  for (const name of ['System', 'Light', 'Dark']) {
    const box = (await page.locator('#mobile-nav-drawer').getByRole('radio', { name }).boundingBox())!;
    expect(box.height, `${name} is at least 40px tall`).toBeGreaterThanOrEqual(40);
  }
  const close = (await page.getByRole('button', { name: 'Close navigation' }).boundingBox())!;
  expect(close.height).toBeGreaterThanOrEqual(40);
});

test('reduced motion stills the decorative loops', async ({ page }) => {
  const id = await seededTopicId(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`/topics/${id}/wayfinder`);
  await settle(page);
  const ping = page.locator('.animate-ping').first();
  await expect(ping).toBeAttached();
  expect(await ping.evaluate((el) => getComputedStyle(el).animationName)).toBe('none');
  // And without the preference, the "you are here" ping does animate.
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  expect(await ping.evaluate((el) => getComputedStyle(el).animationName)).not.toBe('none');
});
