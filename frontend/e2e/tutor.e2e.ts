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
