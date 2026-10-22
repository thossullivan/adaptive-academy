import { expect, type Page } from '@playwright/test';

// Shared by the README screenshots (readme.shots.ts) and the README video (readme-video.shots.ts).
//
// What is not the API's own answer, and why:
// - GET /api/setup reports a configured key. These runs have no ANTHROPIC_API_KEY (no run may
//   spend tokens), so without this every page would carry the "Setup needed" card. The images
//   show the app as a user with a key sees it.
// - On the Tutor page, the demo's existing causal-self-attention conversation (read from
//   GET /api/conversations/{id}) is replayed through the composer: each of its user messages is
//   typed and sent, POST /api/conversations is answered with that conversation, and each
//   POST .../messages with its next tutor reply. The messages, attempt flag and levels are the
//   API's own; only the endpoints that deliver them differ, because the page always opens a
//   fresh session and has no view of past conversations.

type TopicOut = { id: number; is_demo: boolean; concepts: { id: number; name: string }[] };
type ConversationOut = {
  id: number;
  concept_id: number;
  attempt_logged: boolean;
  assistance_level: string;
  challenge_level: string;
  messages: { role: string; content: string; is_attempt: boolean }[];
};

export type Demo = { id: number; causal: { id: number; name: string } };

export async function reportKeyConfigured(page: Page) {
  await page.route('**/api/setup', async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({
      json: { ...body, llm_ready: true, message: 'Anthropic API key configured.', warnings: [] }
    });
  });
}

/** Add the demo topic through the real POST /api/demo. */
export async function createDemo(page: Page): Promise<Demo> {
  const created = await page.request.post('/api/demo');
  expect(created.ok()).toBe(true);
  const topics = (await (await page.request.get('/api/topics')).json()) as TopicOut[];
  const demo = topics.find((t) => t.is_demo)!;
  expect(demo, 'the demo topic exists').toBeTruthy();
  const causal = demo.concepts.find((c) => c.name === 'Causal Self-Attention')!;
  return { id: demo.id, causal };
}

export async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.getByText('calibrating')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
  // No blinking caret or scrollbars in the images.
  await page.addStyleTag({
    content: '*{caret-color:transparent!important} ::-webkit-scrollbar{display:none}'
  });
}

/**
 * Open the Tutor on the demo's causal-self-attention conversation and replay it.
 * `send` types and sends one learner message (with Submit attempt when `attempt`); the
 * default fills it in one step.
 */
export async function replayTutor(
  page: Page,
  demo: Demo,
  send: (text: string, attempt: boolean) => Promise<void> = async (text, attempt) => {
    await page.getByPlaceholder(/Ask the tutor/).fill(text);
    await page.getByRole('button', { name: attempt ? 'Submit attempt' : 'Send' }).click();
  }
) {
  let conversation: ConversationOut | null = null;
  for (let cid = 1; cid <= 20 && !conversation; cid++) {
    const res = await page.request.get(`/api/conversations/${cid}`);
    if (!res.ok()) continue;
    const c = (await res.json()) as ConversationOut;
    if (c.concept_id === demo.causal.id && c.messages.length) conversation = c;
  }
  expect(conversation, 'the demo has a causal-self-attention tutor conversation').toBeTruthy();
  const convo = conversation!;
  const replies = convo.messages.filter((m) => m.role === 'tutor');
  // The demo's learner submitted one message as an attempt (is_attempt, see demo.py), so the
  // header reads "no attempt yet" until the reply to that message, as it did live.
  const learner = convo.messages.filter((m) => m.role === 'user');
  const attemptAfter = (i: number) => convo.attempt_logged && learner.slice(0, i + 1).some((m) => m.is_attempt);
  await page.route('**/api/conversations', (route) =>
    route.request().method() === 'POST' ? route.fulfill({ json: { ...convo, messages: [] } }) : route.fallback()
  );
  let replied = 0;
  await page.route(`**/api/conversations/${convo.id}/messages`, (route) => {
    const i = replied++;
    return route.fulfill({
      json: {
        reply: replies[i].content,
        attempt_logged: attemptAfter(i),
        attempt_outcome: learner[i].is_attempt ? 'accepted' : null,
        assistance_level: convo.assistance_level,
        challenge_level: convo.challenge_level,
        events: [],
        memory: []
      }
    });
  });
  await page.goto(`/topics/${demo.id}/tutor?concept=${demo.causal.id}`);
  await settle(page);
  const composer = page.getByPlaceholder(/Ask the tutor/);
  for (const m of learner) {
    const sent = replied;
    await send(m.content, m.is_attempt);
    await expect.poll(() => replied).toBe(sent + 1);
    await expect(composer).toBeEnabled();
  }
  await expect(page.getByText('attempt logged')).toBeVisible();
  await page.unroute('**/api/conversations');
  await page.unroute(`**/api/conversations/${convo.id}/messages`);
}
