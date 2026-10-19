import { fileURLToPath } from 'node:url';
import { expect, test, type Locator, type Page } from '@playwright/test';

// README screenshots: `npm run screenshots` (playwright.screenshots.config.ts). Not part of
// `npm run test:e2e`. Writes docs/images/*.png from the demo topic, created through the real
// POST /api/demo on a fresh throwaway db.
//
// What is not the API's own answer, and why:
// - GET /api/setup reports a configured key. The screenshot API runs without
//   ANTHROPIC_API_KEY (no run may spend tokens), so without this every page would carry the
//   "Setup needed" card. The screenshots show the app as a user with a key sees it.
// - On the Tutor page, the demo's existing causal-self-attention conversation (read from
//   GET /api/conversations/{id}) is replayed through the composer: each of its user messages is
//   typed and sent, POST /api/conversations is answered with that conversation, and each
//   POST .../messages with its next tutor reply. The messages, attempt flag and levels are the
//   API's own; only the endpoints that deliver them differ, because the page always opens a
//   fresh session and has no view of past conversations.
// - The Usage page reads rows from screenshots/seed_screenshots.py (see the note there).

const OUT = fileURLToPath(new URL('../../docs/images/', import.meta.url));
const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

type TopicOut = { id: number; is_demo: boolean; concepts: { id: number; name: string }[] };
type ConversationOut = {
  id: number;
  concept_id: number;
  attempt_logged: boolean;
  assistance_level: string;
  challenge_level: string;
  messages: { role: string; content: string }[];
};

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.getByText('calibrating')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
  // No blinking caret or scrollbars in the images.
  await page.addStyleTag({
    content: '*{caret-color:transparent!important} ::-webkit-scrollbar{display:none}'
  });
}

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
  await page.route('**/api/setup', async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({
      json: { ...body, llm_ready: true, message: 'Anthropic API key configured.', warnings: [] }
    });
  });

  const created = await page.request.post('/api/demo');
  expect(created.ok()).toBe(true);
  const topics = (await (await page.request.get('/api/topics')).json()) as TopicOut[];
  const demo = topics.find((t) => t.is_demo)!;
  expect(demo, 'the demo topic exists').toBeTruthy();
  const id = demo.id;
  const causal = demo.concepts.find((c) => c.name === 'Causal Self-Attention')!;

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
  await expect(page.getByText(/^Shaky — /).first()).toBeVisible();
  const map = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Where you stand' }) });
  await shoot(map, 'competence');

  // 3. Today: the daily loop.
  await page.goto(`/topics/${id}/today`);
  await settle(page);
  await expect(page.getByText('Your next steps on the track:')).toBeVisible();
  await shoot(page, 'today');

  // 4. Tutor: the demo's conversation in which the reveal came only after a logged attempt.
  let conversation: ConversationOut | null = null;
  for (let cid = 1; cid <= 20 && !conversation; cid++) {
    const res = await page.request.get(`/api/conversations/${cid}`);
    if (!res.ok()) continue;
    const c = (await res.json()) as ConversationOut;
    if (c.concept_id === causal.id && c.messages.length) conversation = c;
  }
  expect(conversation, 'the demo has a causal-self-attention tutor conversation').toBeTruthy();
  const convo = conversation!;
  const turns = convo.messages;
  const replies = turns.filter((m) => m.role === 'tutor');
  await page.route('**/api/conversations', (route) =>
    route.request().method() === 'POST' ? route.fulfill({ json: { ...convo, messages: [] } }) : route.fallback()
  );
  let replied = 0;
  await page.route(`**/api/conversations/${convo.id}/messages`, (route) => {
    const reply = replies[replied++];
    return route.fulfill({
      json: {
        reply: reply.content,
        attempt_logged: convo.attempt_logged,
        assistance_level: convo.assistance_level,
        challenge_level: convo.challenge_level,
        events: [],
        memory: []
      }
    });
  });
  await page.goto(`/topics/${id}/tutor?concept=${causal.id}`);
  await settle(page);
  const composer = page.getByPlaceholder(/Ask the tutor/);
  for (const m of turns.filter((t) => t.role === 'user')) {
    const sent = replied;
    await composer.fill(m.content);
    await page.getByRole('button', { name: 'Send' }).click();
    await expect.poll(() => replied).toBe(sent + 1);
    await expect(composer).toBeEnabled();
  }
  await expect(page.getByText('attempt logged')).toBeVisible();
  await page.evaluate(() => document.querySelectorAll('.overflow-y-auto').forEach((el) => el.scrollTo(0, 0)));
  await shoot(page, 'tutor');
  await page.unroute('**/api/conversations');
  await page.unroute(`**/api/conversations/${convo.id}/messages`);

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
