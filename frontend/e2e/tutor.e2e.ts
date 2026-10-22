import { expect, test, type Page, type Request } from '@playwright/test';

// Opening the Tutor must not save an empty conversation: the conversation row is created on
// the first Send, not on mount or on a concept switch. The e2e API runs keyless, so the send
// itself fails with the ANTHROPIC_API_KEY message after the conversation is created.

type Topic = { id: number; title: string; concepts: { id: number; name: string }[] };

async function seededTopic(page: Page): Promise<Topic> {
  const res = await page.request.get('/api/topics');
  expect(res.ok()).toBeTruthy();
  const topics = (await res.json()) as Topic[];
  const topic = topics.find((t) => t.title === 'Build LLMs from Scratch including the math');
  expect(topic).toBeTruthy();
  return topic!;
}

/** Record every POST /api/conversations (the create call, not .../messages). */
function spyConversationCreates(page: Page): Request[] {
  const creates: Request[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname === '/api/conversations') creates.push(req);
  });
  return creates;
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
}

test('visiting the tutor and switching concepts saves no conversation', async ({ page }) => {
  const topic = await seededTopic(page);
  const creates = spyConversationCreates(page);

  await page.goto(`/topics/${topic.id}/tutor`);
  await settle(page);
  // The header still shows the session's levels (seeded estimates are "medium") and gate.
  await expect(page.getByText('assistance · medium')).toBeVisible();
  await expect(page.getByText('challenge · medium')).toBeVisible();
  await expect(page.getByText('no attempt yet')).toBeVisible();
  await expect(page.getByPlaceholder(/Ask the tutor/)).toBeEnabled();

  const select = page.getByRole('combobox');
  for (const c of topic.concepts.slice(1, 3)) {
    const preview = page.waitForResponse((r) => r.url().includes('/api/conversations/preview'));
    await select.selectOption(String(c.id));
    await preview;
    await expect(page.getByRole('heading', { name: c.name })).toBeVisible();
  }
  await page.waitForLoadState('networkidle');
  expect(creates).toHaveLength(0);
});

test('the first Send creates exactly one conversation and a retry reuses it', async ({ page }) => {
  const topic = await seededTopic(page);
  const creates = spyConversationCreates(page);
  const sends: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/conversations\/\d+\/messages$/.test(new URL(req.url()).pathname))
      sends.push(new URL(req.url()).pathname);
  });

  const concept = topic.concepts[1];
  await page.goto(`/topics/${topic.id}/tutor?concept=${concept.id}`);
  await settle(page);
  expect(creates).toHaveLength(0);

  const input = page.getByPlaceholder(/Ask the tutor/);
  const draft = 'Why does the gradient flow backwards?';
  await input.fill(draft);
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText(/ANTHROPIC_API_KEY/).first()).toBeVisible();
  await expect(input).toHaveValue(draft);
  expect(creates).toHaveLength(1);
  expect(creates[0].postDataJSON()).toEqual({ topic_id: topic.id, concept_id: concept.id });
  expect(sends).toHaveLength(1);

  // Retrying the failed send reuses the session created a moment ago.
  await page.getByRole('button', { name: 'Send' }).click();
  await expect.poll(() => sends.length).toBe(2);
  await page.waitForLoadState('networkidle');
  expect(creates).toHaveLength(1);
  expect(new Set(sends).size).toBe(1);
  await expect(page.getByText('no attempt yet')).toBeVisible();
});

// ── The Attempt button ──────────────────────────────────────────────────────────────────────
// The e2e API runs keyless, so these serve the conversation and each reply from the test. The
// API's own checks (engine/attempt.py) are covered by tests/test_attempt_button.py.

type SendBody = { content: string; attempt: boolean };

/** Serve the conversation and answer each send with `reply(body)`; returns the bodies sent. */
async function mockTutor(page: Page, reply: (body: SendBody) => Record<string, unknown>): Promise<SendBody[]> {
  const sent: SendBody[] = [];
  await page.route('**/api/conversations', (r) =>
    r.request().method() === 'POST'
      ? r.fulfill({
          json: {
            id: 997,
            concept_id: r.request().postDataJSON().concept_id,
            attempt_logged: false,
            assistance_level: 'medium',
            challenge_level: 'medium',
            messages: []
          }
        })
      : r.fallback()
  );
  await page.route('**/api/conversations/997/messages', async (r) => {
    const body = r.request().postDataJSON() as SendBody;
    sent.push(body);
    await r.fulfill({
      json: {
        reply: 'What made you pick that?',
        attempt_logged: false,
        attempt_outcome: null,
        assistance_level: 'medium',
        challenge_level: 'medium',
        events: [],
        memory: [],
        ...reply(body)
      }
    });
  });
  return sent;
}

test('Submit attempt sends the message as an attempt and the header turns to attempt logged', async ({ page }) => {
  const topic = await seededTopic(page);
  const sent = await mockTutor(page, (b) =>
    b.attempt
      ? { reply: 'That holds up. Here is the worked solution.', attempt_logged: true, attempt_outcome: 'accepted' }
      : {}
  );
  await page.goto(`/topics/${topic.id}/tutor`);
  await settle(page);

  const input = page.getByRole('textbox', { name: 'Message the tutor' });
  const submit = page.getByRole('button', { name: 'Submit attempt' });
  const sendButton = page.getByRole('button', { name: 'Send' });
  // Both actions wait for a message.
  await expect(submit).toBeDisabled();
  await expect(sendButton).toBeDisabled();

  await input.fill('Why scale the scores at all?');
  await sendButton.click();
  await expect(page.getByText('What made you pick that?')).toBeVisible();
  await expect(page.getByText('no attempt yet')).toBeVisible();

  await input.fill('I divide by sqrt(d_k) because the variance of the dot product grows with d_k.');
  await submit.click();
  await expect(page.getByText('That holds up. Here is the worked solution.')).toBeVisible();
  await expect(page.getByText('attempt logged')).toBeVisible();
  await expect(page.getByText('your attempt', { exact: true })).toBeVisible();
  await expect(page.getByTestId('attempt-note')).toHaveCount(0);
  expect(sent.map((b) => b.attempt)).toEqual([false, true]);
});

test('an attempt that is not logged gets a kind note and the gate stays shut', async ({ page }) => {
  const topic = await seededTopic(page);
  await mockTutor(page, () => ({
    reply: 'Tell me how you got there: what would your first step be?',
    attempt_outcome: 'rejected'
  }));
  await page.goto(`/topics/${topic.id}/tutor`);
  await settle(page);

  await page.getByRole('textbox', { name: 'Message the tutor' }).fill('is it 42?');
  await page.getByRole('button', { name: 'Submit attempt' }).click();
  await expect(page.getByText('what would your first step be?')).toBeVisible();
  await expect(page.getByTestId('attempt-note')).toHaveText(
    'Not logged as an attempt yet. Add your reasoning or a first step, then submit again.'
  );
  await expect(page.getByText('no attempt yet')).toBeVisible();
});

test('keyboard: Enter sends, Ctrl+Enter submits an attempt, Shift+Enter adds a line', async ({ page }) => {
  const topic = await seededTopic(page);
  const sent = await mockTutor(page, (b) => (b.attempt ? { attempt_logged: true, attempt_outcome: 'accepted' } : {}));
  await page.goto(`/topics/${topic.id}/tutor`);
  await settle(page);

  const input = page.getByRole('textbox', { name: 'Message the tutor' });
  await expect(page.getByRole('button', { name: 'Submit attempt' })).toHaveAttribute(
    'aria-keyshortcuts',
    'Control+Enter Meta+Enter'
  );
  await input.focus();
  await page.keyboard.type('a question');
  await page.keyboard.press('Shift+Enter');
  await page.keyboard.type('on two lines');
  await expect(input).toHaveValue('a question\non two lines');
  await page.keyboard.press('Enter');
  await expect.poll(() => sent.length).toBe(1);
  await expect(input).toBeEnabled();

  await input.focus();
  await page.keyboard.type('my attempt: divide by sqrt(d_k), the dot products grow with d_k');
  await page.keyboard.press('Control+Enter');
  await expect.poll(() => sent.length).toBe(2);
  expect(sent).toEqual([
    { content: 'a question\non two lines', attempt: false },
    { content: 'my attempt: divide by sqrt(d_k), the dot products grow with d_k', attempt: true }
  ]);
  await expect(page.getByText('attempt logged')).toBeVisible();
});
