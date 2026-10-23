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
  // With a draft and no attempt logged, Submit attempt is marked out as the step that matters.
  await expect(submit).toHaveAttribute('data-ready', 'true');
  await submit.click();
  await expect(page.getByText('That holds up. Here is the worked solution.')).toBeVisible();
  await expect(page.getByText('attempt logged')).toBeVisible();
  // The attempt bubble carries a chip with what the check made of it.
  await expect(page.getByTestId('attempt-message')).toHaveCount(1);
  await expect(page.getByTestId('attempt-chip')).toHaveText('Attempt · logged');
  await expect(page.getByTestId('attempt-note')).toHaveCount(0);
  expect(sent.map((b) => b.attempt)).toEqual([false, true]);
  // Once the attempt is logged, Submit attempt calms down.
  await input.fill('one more question');
  await expect(submit).toBeEnabled();
  await expect(submit).toHaveAttribute('data-ready', 'false');
});

test('the reply that shows the worked solution is labelled, and messages render as markdown', async ({ page }) => {
  const topic = await seededTopic(page);
  await mockTutor(page, (b) =>
    b.attempt
      ? {
          reply: 'Right. Mask with `-inf` before the softmax:\n```python\nscores = scores.masked_fill(mask == 0, float("-inf"))\n```\n<img src=x onerror="window.__pwned=1">',
          attempt_logged: true,
          attempt_outcome: 'accepted',
          reveals_solution: true
        }
      : { reply: 'What does **each row** of the weights sum to?' }
  );
  await page.goto(`/topics/${topic.id}/tutor`);
  await settle(page);
  const input = page.getByRole('textbox', { name: 'Message the tutor' });
  const log = page.getByRole('log', { name: 'Conversation with the tutor' });

  await input.fill('Why mask before the softmax?');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(log.locator('strong', { hasText: 'each row' })).toBeVisible();
  // An ordinary reply is not marked as the solution.
  await expect(page.getByTestId('worked-solution')).toHaveCount(0);

  await input.fill('Set the masked logits to `-inf` so exp gives zero.');
  await page.getByRole('button', { name: 'Submit attempt' }).click();
  const solution = page.getByTestId('worked-solution');
  await expect(solution).toHaveCount(1);
  await expect(solution).toContainText('Worked solution, unlocked by your attempt');
  // Code renders as code, in both the learner's attempt and the tutor's reply.
  await expect(page.getByTestId('attempt-message').locator('code', { hasText: '-inf' })).toBeVisible();
  await expect(solution.locator('code.md-pre')).toHaveText('scores = scores.masked_fill(mask == 0, float("-inf"))');
  // Model text never becomes HTML.
  await expect(solution.locator('img')).toHaveCount(0);
  await expect(solution).toContainText('<img src=x onerror="window.__pwned=1">');
  expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
});

test('the empty Tutor explains the gate and its starter prompts fill the message box without sending', async ({ page }) => {
  const topic = await seededTopic(page);
  const sends: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes('/api/conversations')) sends.push(req.url());
  });
  const concept = topic.concepts[1];
  await page.goto(`/topics/${topic.id}/tutor?concept=${concept.id}`);
  await settle(page);

  const steps = page.getByRole('list', { name: 'How the tutor works' }).getByRole('listitem');
  await expect(steps).toHaveCount(3);
  await expect(steps.nth(0)).toContainText('Ask');
  await expect(steps.nth(1)).toContainText('Submit attempt');
  await expect(steps.nth(2)).toContainText('worked solution');

  const starters = page.getByRole('group', { name: /Not sure where to start/ }).getByRole('button');
  await expect(starters).toHaveCount(2);
  const first = (await starters.first().textContent())!.trim();
  expect(first).toContain(concept.name);
  await starters.first().click();
  const input = page.getByRole('textbox', { name: 'Message the tutor' });
  await expect(input).toHaveValue(first);
  await expect(input).toBeFocused();
  await page.waitForLoadState('networkidle');
  expect(sends).toHaveLength(0);
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
  await expect(page.getByTestId('attempt-chip')).toHaveText('Attempt · not logged');
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

/**
 * The attempt is checked and stored before the tutor runs; here the tutor call then fails
 * (an overload), and GET /api/conversations/997 returns what the server stored.
 */
async function mockReplyFailureAfterStoredAttempt(page: Page, accepted: boolean) {
  let stored: { content: string } | null = null;
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
    stored = r.request().postDataJSON();
    await r.fulfill({ status: 529, json: { detail: 'The model is overloaded. Try again shortly.' } });
  });
  await page.route('**/api/conversations/997', (r) =>
    r.fulfill({
      json: {
        id: 997,
        concept_id: 1,
        attempt_logged: accepted,
        assistance_level: 'medium',
        challenge_level: 'medium',
        messages: [{ role: 'user', content: stored!.content, is_attempt: true, attempt_accepted: accepted }]
      }
    })
  );
}

for (const accepted of [true, false]) {
  test(`a reply that fails after a ${accepted ? 'logged' : 'rejected'} attempt keeps what was saved`, async ({ page }) => {
    const topic = await seededTopic(page);
    await mockReplyFailureAfterStoredAttempt(page, accepted);
    await page.goto(`/topics/${topic.id}/tutor`);
    await settle(page);

    const input = page.getByRole('textbox', { name: 'Message the tutor' });
    const attempt = 'I divide by sqrt(d_k) because the variance grows with d_k.';
    await input.fill(attempt);
    const reread = page.waitForRequest((r) => r.method() === 'GET' && r.url().endsWith('/api/conversations/997'));
    await page.getByRole('button', { name: 'Submit attempt' }).click();
    await reread;

    await expect(page.getByTestId('toaster')).toContainText(
      accepted
        ? "Your attempt was saved and logged, but the tutor's reply failed (The model is overloaded. Try again shortly.)"
        : "Your attempt was saved but not logged: add your reasoning or a first step and submit again. The tutor's reply also failed (The model is overloaded. Try again shortly.)"
    );
    // The bubble stays (it was stored), the draft is not put back, and the header and note
    // say what the server recorded.
    await expect(page.getByRole('log').getByText(attempt)).toBeVisible();
    await expect(input).toHaveValue('');
    await expect(page.getByText(accepted ? 'attempt logged' : 'no attempt yet')).toBeVisible();
    await expect(page.getByTestId('attempt-note')).toHaveCount(accepted ? 0 : 1);
  });
}

test('a send that fails before anything is stored still takes the bubble back', async ({ page }) => {
  // The keyless e2e API refuses the send before storing anything; the re-read finds no attempt.
  const topic = await seededTopic(page);
  await page.goto(`/topics/${topic.id}/tutor`);
  await settle(page);
  const input = page.getByRole('textbox', { name: 'Message the tutor' });
  await input.fill('my attempt: scale by sqrt(d_k)');
  await page.getByRole('button', { name: 'Submit attempt' }).click();
  await expect(page.getByTestId('toaster')).toContainText(/ANTHROPIC_API_KEY/);
  await expect(page.getByTestId('toaster')).not.toContainText('Your attempt was saved');
  await expect(input).toHaveValue('my attempt: scale by sqrt(d_k)');
  await expect(page.getByText('no attempt yet')).toBeVisible();
});
