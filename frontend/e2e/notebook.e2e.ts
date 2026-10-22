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
  const toggle = page.getByRole('button', { name: 'Notes', exact: true });
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await toggle.click();
  await expect(page.getByRole('button', { name: 'Hide notes' })).toHaveAttribute('aria-expanded', 'true');

  const panel = page.locator('#tutor-notes');
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
  await expect(explanations.getByRole('link', { name: 'Retention' })).toHaveAttribute('href', `/topics/${topic.id}/retention`);
  await expect(explanations.getByRole('link', { name: 'Assess' })).toHaveAttribute('href', `/topics/${topic.id}/assess`);

  // Picking another concept in the list shows its notebook.
  await list.getByRole('link', { name: /Scaled Dot-Product Attention/ }).click();
  await expect(page.getByRole('heading', { level: 2, name: 'Scaled Dot-Product Attention' })).toBeVisible();
  await expect(page.getByTestId('notebook-explanations')).toContainText('Self-explanation, 80 of 100');
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
