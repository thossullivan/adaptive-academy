import { expect, test, type Page } from '@playwright/test';

// Concept notebooks: the Notes panel on the Tutor page (edit and save My notes, with a
// saved/unsaved state, from the keyboard too) and the Notebook page under Library, which
// lists the topic's concepts with notes or work and shows each one's notebook. The desktop
// and phone projects share one database, so each edits its own concept.

type Topic = { id: number; title: string; concepts: { id: number; name: string }[] };

const isPhone = () => test.info().project.name === 'phone';

async function seededTopic(page: Page): Promise<Topic> {
  const res = await page.request.get('/api/topics');
  expect(res.ok()).toBeTruthy();
  const topics = (await res.json()) as Topic[];
  const topic = topics.find((t) => t.title === 'Build LLMs from Scratch including the math');
  expect(topic).toBeTruthy();
  await page.addInitScript((id) => localStorage.setItem('aa-current-topic', String(id)), topic!.id);
  return topic!;
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
}

test('write and save notes from the Tutor, then find them in the Notebook', async ({ page }) => {
  const topic = await seededTopic(page);
  const name = isPhone() ? 'LoRA' : 'KV Cache';
  const concept = topic.concepts.find((c) => c.name === name)!;
  const words = `Cache keys and values once per token (${test.info().project.name}).`;

  await page.goto(`/topics/${topic.id}/tutor?concept=${concept.id}`);
  await settle(page);
  // A toggle button: pressed while the panel is open, and an outline (never the primary fill).
  const toggle = page.getByRole('button', { name: 'Notes', exact: true });
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(toggle).toHaveAttribute('aria-controls', 'tutor-notes');
  await expect(toggle).not.toHaveClass(/bg-accent(\s|$)/);

  const panel = page.locator('#tutor-notes');
  await expect(page.getByRole('complementary', { name: `Notes on ${name}` })).toBeVisible();
  // One title: the editor's label, no second heading over it.
  await expect(panel.getByRole('heading')).toHaveCount(0);
  const box = panel.getByRole('textbox', { name: `My notes on ${name}` });
  const status = panel.getByTestId('note-status');
  await expect(box).toBeVisible();
  await expect(status).toHaveText('No notes yet');
  if (isPhone()) {
    // On a phone the panel takes the conversation's place while it is open.
    await expect(page.getByRole('log', { name: 'Conversation with the tutor' })).toBeHidden();
  }

  // Keyboard only: type, then Ctrl+S saves.
  await box.focus();
  await page.keyboard.type(words);
  await expect(status).toHaveText('Unsaved changes');
  await page.keyboard.press('Control+s');
  await expect(status).toContainText('Saved');
  await expect(panel.getByRole('button', { name: 'Save notes' })).toBeDisabled();

  // The Save button works too.
  await box.fill(`${words}\nCheck the cache size for long contexts.`);
  await expect(status).toHaveText('Unsaved changes');
  await panel.getByRole('button', { name: 'Save notes' }).click();
  await expect(status).toContainText('Saved');

  // Saved on the server: a reload shows it.
  await page.reload();
  await settle(page);
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  await expect(page.locator('#tutor-notes').getByRole('textbox', { name: `My notes on ${name}` })).toHaveValue(
    `${words}\nCheck the cache size for long contexts.`
  );

  // The panel links to this concept's notebook.
  await page.locator('#tutor-notes').getByRole('link', { name: `Open the notebook for ${name}` }).click();
  await expect(page).toHaveURL(new RegExp(`/topics/${topic.id}/notebook\\?concept=${concept.id}$`));
  await settle(page);
  await expect(page.getByRole('heading', { level: 1, name: 'Notebook' })).toBeVisible();
  await expect(page.getByRole('heading', { level: 2, name })).toBeVisible();
  const list = page.getByRole('navigation', { name: 'Concepts with notes or work' });
  await expect(list.getByRole('link', { name: new RegExp(name) })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('textbox', { name: `My notes on ${name}` })).toHaveValue(
    `${words}\nCheck the cache size for long contexts.`
  );
  await expect(page.getByTestId('notebook-attempts')).toContainText('No attempts yet.');
});

test('the Notebook lists graded explanations with score, gaps, and where they were made', async ({ page }) => {
  const topic = await seededTopic(page);
  const backprop = topic.concepts.find((c) => c.name === 'Backpropagation and Autograd')!;

  await page.goto(`/topics/${topic.id}/notebook?concept=${backprop.id}`);
  await settle(page);
  const list = page.getByRole('navigation', { name: 'Concepts with notes or work' });
  await expect(list.getByRole('link', { name: /Backpropagation and Autograd/ })).toBeVisible();
  await expect(list.getByRole('link', { name: /Scaled Dot-Product Attention/ })).toBeVisible();
  // A concept with nothing written or done is not listed.
  await expect(list.getByRole('link', { name: /Weight Tying/ })).toHaveCount(0);

  const explanations = page.getByTestId('notebook-explanations');
  await expect(explanations.getByRole('heading', { name: /My explanations · 2/ })).toBeVisible();
  await expect(explanations).toContainText('Decay check, 60 of 100');
  await expect(explanations).toContainText('Self-explanation, 35 of 100');
  // Each score in its level's colour, as on the dashboard: 60 is medium, 35 is low.
  const scores = explanations.getByTestId('item-score');
  await expect(scores.filter({ hasText: '60 of 100' })).toHaveAttribute('style', /var\(--accent\)/);
  await expect(scores.filter({ hasText: '35 of 100' })).toHaveAttribute('style', /var\(--danger\)/);
  await expect(explanations.getByRole('link', { name: 'Retention' })).toHaveAttribute('href', `/topics/${topic.id}/retention`);
  await expect(explanations.getByRole('link', { name: 'Assess' })).toHaveAttribute('href', `/topics/${topic.id}/assess`);

  // Picking another concept in the list shows its notebook.
  await list.getByRole('link', { name: /Scaled Dot-Product Attention/ }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Scaled Dot-Product Attention' })).toBeVisible();
  await expect(page.getByTestId('notebook-explanations')).toContainText('Self-explanation, 80 of 100');
});

test('without ?concept= the Notebook opens on the most recently active concept with notes', async ({ page }) => {
  const topic = await seededTopic(page);
  const [newest, withNotes] = topic.concepts;
  await page.route('**/api/topics/*/notebook', (r) =>
    r.fulfill({
      json: {
        topic_id: topic.id,
        concepts: [
          // The newest has work but no notes; the one to open on has notes.
          { concept_id: newest.id, name: newest.name, has_note: false, attempts: 0, explanations: 2, solutions: 0, last_activity_at: '2026-10-22T09:00:00' },
          { concept_id: withNotes.id, name: withNotes.name, has_note: true, attempts: 0, explanations: 0, solutions: 0, last_activity_at: '2026-10-20T09:00:00' }
        ]
      }
    })
  );
  await page.goto(`/topics/${topic.id}/notebook`);
  await settle(page);
  await expect(page.getByRole('heading', { level: 2, name: withNotes.name })).toBeVisible();
  const list = page.getByRole('navigation', { name: 'Concepts with notes or work' });
  await expect(list.getByRole('link', { name: withNotes.name })).toHaveAttribute('aria-current', 'page');
});

test('the rail links to the Notebook under Library', async ({ page }) => {
  const topic = await seededTopic(page);
  await page.goto(`/topics/${topic.id}/today`);
  await settle(page);
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  const library = page.locator('aside:visible').getByRole('group', { name: 'Library' });
  await library.getByRole('link', { name: 'Notebook' }).click();
  await expect(page).toHaveURL(new RegExp(`/topics/${topic.id}/notebook$`));
  await expect(page.getByRole('heading', { level: 1, name: 'Notebook' })).toBeVisible();
});

// --- drafts are never lost ------------------------------------------------------------------

/** The concept's saved note body, straight from the API. */
async function savedBody(page: Page, conceptId: number): Promise<string> {
  const res = await page.request.get(`/api/concepts/${conceptId}/notebook`);
  expect(res.ok()).toBeTruthy();
  return ((await res.json()) as { note: { body: string } | null }).note?.body ?? '';
}

async function openNotes(page: Page, topicId: number, conceptId: number, name: string) {
  await page.goto(`/topics/${topicId}/tutor?concept=${conceptId}`);
  await settle(page);
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  const box = page.locator('#tutor-notes').getByRole('textbox', { name: `My notes on ${name}` });
  await expect(box).toBeVisible();
  return box;
}

test('a draft whose save failed is kept in the tab and restored after a reload', async ({ page }) => {
  const topic = await seededTopic(page);
  const name = isPhone() ? 'Feed-Forward Sublayer (FFN)' : 'AdamW and Learning-Rate Schedules';
  const concept = topic.concepts.find((c) => c.name === name)!;
  page.on('dialog', (d) => d.accept()); // the reload asks first: there are unsaved changes

  const box = await openNotes(page, topic.id, concept.id, name);
  await page.route(`**/api/concepts/${concept.id}/note`, (r) => r.fulfill({ status: 503, json: { detail: 'The server is busy.' } }));
  await box.fill('Warmup then cosine decay.');
  await page.keyboard.press('Control+s');
  const status = page.getByTestId('note-status');
  await expect(status).toHaveText(/Not saved: The server is busy/);

  await page.reload();
  await settle(page);
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  await expect(page.locator('#tutor-notes').getByRole('textbox', { name: `My notes on ${name}` })).toHaveValue('Warmup then cosine decay.');
  await expect(status).toContainText('Unsaved changes');
  await expect(page.getByTestId('note-restored')).toBeVisible();

  await page.unroute(`**/api/concepts/${concept.id}/note`);
  await page.locator('#tutor-notes').getByRole('button', { name: 'Save notes' }).click();
  await expect(status).toContainText('Saved');
  expect(await savedBody(page, concept.id)).toBe('Warmup then cosine decay.');
});

test('edits typed while a save runs are saved right after it', async ({ page }) => {
  const topic = await seededTopic(page);
  const name = isPhone() ? 'Multi-Head Attention' : 'Residual Connections and LayerNorm';
  const concept = topic.concepts.find((c) => c.name === name)!;
  const box = await openNotes(page, topic.id, concept.id, name);
  const bodies: string[] = [];
  await page.route(`**/api/concepts/${concept.id}/note`, async (r) => {
    bodies.push(JSON.parse(r.request().postData() ?? '{}').body);
    await new Promise((res) => setTimeout(res, 400));
    await r.fallback();
  });

  await box.fill('first');
  await page.keyboard.press('Control+s');
  await box.press('End');
  await page.keyboard.type(' and second');
  await page.keyboard.press('Control+s');
  await expect(page.getByTestId('note-status')).toContainText('Saved');
  await expect.poll(() => savedBody(page, concept.id)).toBe('first and second');
  expect(bodies).toEqual(['first', 'first and second']);
});

test('switching away and straight back shows the text just saved, not an older copy', async ({ page }) => {
  const topic = await seededTopic(page);
  const name = isPhone() ? 'Language Modeling Objective' : 'Token Embeddings';
  const concept = topic.concepts.find((c) => c.name === name)!;
  const other = topic.concepts.find((c) => c.name === 'Computational Graphs')!;
  const box = await openNotes(page, topic.id, concept.id, name);
  await page.route(`**/api/concepts/${concept.id}/note`, async (r) => {
    await new Promise((res) => setTimeout(res, 800));
    await r.fallback();
  });

  await box.fill('Saved on the way out.');
  const select = page.getByRole('combobox', { name: 'Concept' });
  await select.selectOption(String(other.id)); // the draft is saved as the editor goes
  await expect(page.locator('#tutor-notes').getByRole('textbox', { name: 'My notes on Computational Graphs' })).toBeVisible();
  await select.selectOption(String(concept.id));

  const back = page.locator('#tutor-notes').getByRole('textbox', { name: `My notes on ${name}` });
  await expect(back).toHaveValue('Saved on the way out.');
  await expect(page.getByTestId('note-status')).toContainText('Saved');
  expect(await savedBody(page, concept.id)).toBe('Saved on the way out.');
});

test('a draft over the limit cannot be saved, and leaving the page asks first', async ({ page }) => {
  const topic = await seededTopic(page);
  const name = 'Byte Pair Encoding';
  const concept = topic.concepts.find((c) => c.name === name)!;
  const box = await openNotes(page, topic.id, concept.id, name);
  await box.fill('x'.repeat(50001));
  await expect(page.getByTestId('note-status')).toContainText('Too long to save: 50,001 of 50,000 characters');
  await expect(page.locator('#tutor-notes').getByRole('button', { name: 'Save notes' })).toBeDisabled();

  const asked: string[] = [];
  page.once('dialog', (d) => {
    asked.push(d.message());
    d.dismiss();
  });
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.locator('aside:visible').getByRole('link', { name: 'Today', exact: true }).click();
  await expect.poll(() => asked.length).toBe(1);
  expect(asked[0]).toMatch(/over the 50,000 character limit/);
  await expect(page).toHaveURL(new RegExp(`/topics/${topic.id}/tutor`));
  expect(await savedBody(page, concept.id)).toBe('');
});

test('a quick switch away and back, before the other notebook loads, shows the text just saved', async ({ page }) => {
  // The panel used to remount from the copy it showed before the switch, which predates the
  // save made on the way out; editing it then overwrote the newer text.
  const topic = await seededTopic(page);
  const name = isPhone() ? 'Supervised Fine-Tuning' : 'Chain Rule for Vector Functions';
  const concept = topic.concepts.find((c) => c.name === name)!;
  const other = topic.concepts.find((c) => c.name === (isPhone() ? 'Transformer Architecture (GPT-style)' : 'Tokenization and Vocabulary Construction'))!;
  const box = await openNotes(page, topic.id, concept.id, name);
  await page.route(`**/api/concepts/${other.id}/notebook`, async (r) => {
    await new Promise((res) => setTimeout(res, 2000));
    await r.fallback();
  });

  await box.fill('Newest words, saved on the way out.');
  const select = page.getByRole('combobox', { name: 'Concept' });
  const saved = page.waitForResponse((r) => r.url().endsWith(`/api/concepts/${concept.id}/note`) && r.request().method() === 'PUT');
  await select.selectOption(String(other.id));
  await saved;
  await select.selectOption(String(concept.id)); // back before the other notebook arrives

  const back = page.locator('#tutor-notes').getByRole('textbox', { name: `My notes on ${name}` });
  await expect(back).toHaveValue('Newest words, saved on the way out.');
  await expect(page.getByTestId('note-status')).toContainText('Saved');
  expect(await savedBody(page, concept.id)).toBe('Newest words, saved on the way out.');
});

/** Leave the Tutor for Today through the rail (an in-app navigation, so the editor unmounts). */
async function leaveForToday(page: Page) {
  if (isPhone()) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.locator('aside:visible').getByRole('link', { name: 'Today', exact: true }).click();
  await expect(page).toHaveURL(/\/today$/);
  await settle(page);
}

test('a kept draft never silently overwrites a note saved after it', async ({ page }) => {
  const topic = await seededTopic(page);
  const name = isPhone() ? 'Scaled Dot-Product Attention' : 'Positional Encodings (sinusoidal and RoPE)';
  const concept = topic.concepts.find((c) => c.name === name)!;
  page.on('dialog', (d) => d.accept()); // a reload with unsaved changes asks first
  const puts: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'PUT' && req.url().endsWith(`/api/concepts/${concept.id}/note`)) puts.push(req.postDataJSON().body);
  });
  /** Another tab saves the note while this tab holds a draft. */
  const saveElsewhere = async (body: string) => {
    const res = await page.request.put(`/api/concepts/${concept.id}/note`, { data: { body, vault_path: '' } });
    expect(res.ok()).toBeTruthy();
  };

  let box = await openNotes(page, topic.id, concept.id, name);
  await box.fill('Draft from this tab.');
  await saveElsewhere('Saved in another tab.');
  await page.reload();
  await settle(page);
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  const panel = page.locator('#tutor-notes');
  box = panel.getByRole('textbox', { name: `My notes on ${name}` });

  // The draft comes back, with a choice, and is described to screen readers.
  const notice = panel.getByTestId('note-conflict');
  await expect(notice).toBeVisible();
  await expect(notice).toContainText('your saved notes changed after it');
  await expect(box).toHaveValue('Draft from this tab.');
  await expect(box).toHaveAttribute('aria-describedby', /-conflict /);
  await expect(panel.getByRole('button', { name: 'Keep my draft' })).toBeVisible();

  // Leaving without choosing saves nothing: the newer note stays.
  await leaveForToday(page);
  expect(puts).toEqual([]);
  expect(await savedBody(page, concept.id)).toBe('Saved in another tab.');

  // Back again, it asks again; Use the saved note (from the keyboard) drops the draft.
  box = await openNotes(page, topic.id, concept.id, name);
  await expect(box).toHaveValue('Draft from this tab.');
  await panel.getByRole('button', { name: 'Use the saved note' }).focus();
  await page.keyboard.press('Enter');
  await expect(box).toHaveValue('Saved in another tab.');
  await expect(box).toBeFocused();
  await expect(notice).toHaveCount(0);
  expect(await page.evaluate((id) => sessionStorage.getItem(`aa.note-draft.${id}`), concept.id)).toBeNull();

  // Keep my draft: chosen, so it is saved on the way out.
  await box.fill('A second draft.');
  await saveElsewhere('Newer again.');
  await page.reload();
  await settle(page);
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  await expect(box).toHaveValue('A second draft.');
  await panel.getByRole('button', { name: 'Keep my draft' }).click();
  await expect(notice).toHaveCount(0);
  await leaveForToday(page);
  await expect.poll(() => savedBody(page, concept.id)).toBe('A second draft.');
  expect(puts).toEqual(['A second draft.']);
});

test('a restored draft is not saved on the way out until it is edited, and Discard draft drops it', async ({ page }) => {
  const topic = await seededTopic(page);
  const name = isPhone() ? 'Causal (Masked) Self-Attention' : 'Transformer Architecture (GPT-style)';
  const concept = topic.concepts.find((c) => c.name === name)!;
  page.on('dialog', (d) => d.accept());

  let box = await openNotes(page, topic.id, concept.id, name);
  await box.fill('Half a thought.');
  await page.reload();
  await settle(page);
  await page.getByRole('button', { name: 'Notes', exact: true }).click();
  const panel = page.locator('#tutor-notes');
  box = panel.getByRole('textbox', { name: `My notes on ${name}` });
  // Written on the note saved now: restored quietly, no question.
  await expect(box).toHaveValue('Half a thought.');
  await expect(page.getByTestId('note-restored')).toBeVisible();
  await expect(panel.getByTestId('note-conflict')).toHaveCount(0);

  await leaveForToday(page);
  expect(await savedBody(page, concept.id)).toBe('');

  box = await openNotes(page, topic.id, concept.id, name);
  await expect(box).toHaveValue('Half a thought.');
  await panel.getByRole('button', { name: 'Discard draft' }).click();
  await expect(box).toHaveValue('');
  await expect(page.getByTestId('note-status')).toHaveText('No notes yet');
  await expect(panel.getByRole('button', { name: 'Discard draft' })).toHaveCount(0);
  expect(await page.evaluate((id) => sessionStorage.getItem(`aa.note-draft.${id}`), concept.id)).toBeNull();
});

test('clearing the vault folder stops notebooks syncing to it', async ({ page }) => {
  const topic = await seededTopic(page);
  await page.addInitScript(() => localStorage.setItem('aa_vault_path', '/no/such/vault'));
  const syncs: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'PUT' && new URL(req.url()).pathname === '/api/vault/sync') {
      syncs.push(JSON.parse(req.postData() ?? '{}').vault_path);
    }
  });
  await page.goto(`/topics/${topic.id}/vault`);
  await settle(page);
  const field = page.getByRole('textbox', { name: 'Vault folder path' });
  await expect(field).toHaveValue('/no/such/vault');
  await field.fill('');
  await field.blur();
  await expect.poll(() => syncs.includes('')).toBe(true);
  expect(await page.evaluate(() => localStorage.getItem('aa_vault_path'))).toBeNull();
});

test('the vault set by AA_OBSIDIAN_VAULT_PATH shows its sync state, and clearing the field never claims it stopped', async ({ page }) => {
  const topic = await seededTopic(page);
  const envSync = {
    path: '/vault',
    source: 'env',
    last_synced_at: null,
    last_error: "Couldn't update c-2.md: its notebook section was edited in Obsidian",
    last_error_at: '2026-10-22T09:00:00',
    problems: 1,
    pending: 0
  };
  await page.route('**/api/vault/status**', (r) =>
    r.fulfill({ json: { configured: true, path: '/vault', exists: true, is_dir: true, note_count: 3, sync: envSync } })
  );
  await page.route('**/api/vault/sync', (r) => r.fulfill({ json: envSync }));

  await page.goto(`/topics/${topic.id}/vault`);
  await settle(page);
  const sync = page.getByTestId('vault-sync');
  await expect(sync).toContainText('Notes sync to /vault (set by AA_OBSIDIAN_VAULT_PATH). To stop, leave it empty in .env and restart.');
  await expect(sync).toContainText("Couldn't update c-2.md");

  // A folder saved in this browser, then cleared: the env vault is still where notes go.
  await page.evaluate(() => localStorage.setItem('aa_vault_path', '/somewhere'));
  await page.reload();
  await settle(page);
  const field = page.getByRole('textbox', { name: 'Vault folder path' });
  await expect(field).toHaveValue('/somewhere');
  await field.fill('');
  await field.blur();
  await expect(page.getByRole('status').filter({ hasText: 'set by AA_OBSIDIAN_VAULT_PATH' }).first()).toBeAttached();
  await expect(page.getByText('no longer sync')).toHaveCount(0);
});
