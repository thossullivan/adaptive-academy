import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Deleting a topic from the foot of its dashboard, behind a confirm step. Each test makes its
// own throwaway topics through the real API (titles unique per project and run), so the
// desktop and phone projects never delete each other's, and removes whatever is left.

const isPhone = () => test.info().project.name === 'phone';

async function makeTopic(request: APIRequestContext, label: string): Promise<{ id: number; title: string }> {
  const title = `Delete me ${label} ${test.info().project.name} ${Date.now()}`;
  const res = await request.post('/api/topics', { data: { title, goal: 'a throwaway e2e topic' } });
  expect(res.ok()).toBeTruthy();
  const { id } = (await res.json()) as { id: number };
  return { id, title };
}

async function selectTopic(page: Page, id: number) {
  await page.addInitScript((id) => localStorage.setItem('aa-current-topic', String(id)), id);
}

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
}

async function topicTitles(page: Page): Promise<string[]> {
  return ((await (await page.request.get('/api/topics')).json()) as { title: string }[]).map((t) => t.title);
}

test('a topic is deleted from its dashboard after a confirm, and Cancel keeps it', async ({ page }) => {
  const doomed = await makeTopic(page.request, 'doomed');
  try {
    await selectTopic(page, doomed.id);
    await page.goto('/');
    await settle(page);
    await expect(page.getByRole('heading', { level: 1, name: doomed.title })).toBeVisible();

    // The confirm says what goes, what stays, and where the backup is.
    await page.getByRole('button', { name: 'Delete topic' }).click();
    const group = page.getByRole('group', { name: `Delete ${doomed.title}?` });
    await expect(group).toBeVisible();
    await expect(group).toContainText('Notes already written to your Obsidian vault stay there.');
    await expect(group).toContainText("This can't be undone.");
    await expect(group.getByRole('link', { name: 'Your data' })).toHaveAttribute('href', '/data');

    // Cancel keeps it.
    await group.getByRole('button', { name: 'Cancel' }).click();
    await expect(group).toHaveCount(0);
    await expect(page.getByRole('heading', { level: 1, name: doomed.title })).toBeVisible();
    expect(await topicTitles(page)).toContain(doomed.title);

    // Confirm deletes it and lands on the next topic's dashboard, heading focused.
    await page.getByRole('button', { name: 'Delete topic' }).click();
    await page.getByRole('button', { name: 'Yes, delete it' }).click();
    await expect(page.getByRole('heading', { level: 1, name: doomed.title })).toHaveCount(0);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('main h1')).toBeFocused();
    await expect(page.getByRole('button', { name: 'Delete topic' })).toBeVisible(); // closed again
    expect(await topicTitles(page)).not.toContain(doomed.title);

    // The topic switcher no longer offers it.
    if (isPhone()) {
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await expect(page.locator('#mobile-nav-drawer')).toBeVisible();
    }
    const rail = page.locator('aside:visible');
    await rail.getByRole('button', { name: /^Topic: / }).click();
    const list = rail.getByRole('list', { name: 'Topics' });
    await expect(list).toBeVisible();
    await expect(list.getByText(doomed.title)).toHaveCount(0);
  } finally {
    await page.request.delete(`/api/topics/${doomed.id}`);
  }
});

test('the delete confirm moves focus to Cancel and back, and Escape cancels', async ({ page }) => {
  const topic = await makeTopic(page.request, 'keyboard');
  try {
    await selectTopic(page, topic.id);
    await page.goto('/');
    await settle(page);
    const del = page.getByRole('button', { name: 'Delete topic' });
    await del.focus();
    await page.keyboard.press('Enter');
    const cancel = page.getByRole('button', { name: 'Cancel' });
    await expect(cancel).toBeFocused();
    await expect(page.getByRole('group', { name: `Delete ${topic.title}?` })).toBeVisible();
    await page.keyboard.press('Enter');
    await expect(del).toBeFocused();
    // Escape cancels as well.
    await page.keyboard.press('Enter');
    await expect(cancel).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(del).toBeFocused();
    expect(await topicTitles(page)).toContain(topic.title);
  } finally {
    await page.request.delete(`/api/topics/${topic.id}`);
  }
});

test("deleting a topic clears its concepts' note drafts, and keeps other drafts", async ({ page }) => {
  // Concept ids come back after a delete, so a draft left behind would restore into a new
  // topic's concept. The topic is mocked to own concept 987001; 987002 belongs elsewhere.
  const doomed = await makeTopic(page.request, 'drafts');
  try {
    await page.route(`**/api/topics/${doomed.id}`, async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const res = await route.fetch();
      await route.fulfill({
        response: res,
        json: { ...(await res.json()), concepts: [{ id: 987001, name: 'Gone', is_load_bearing: false }] }
      });
    });
    await selectTopic(page, doomed.id);
    await page.goto('/');
    await settle(page);
    await page.evaluate(() => {
      sessionStorage.setItem('aa.note-draft.987001', JSON.stringify({ v: 1, body: 'old draft', base: null }));
      sessionStorage.setItem('aa.note-draft.987002', 'keep me');
    });

    await page.getByRole('button', { name: 'Delete topic' }).click();
    await page.getByRole('button', { name: 'Yes, delete it' }).click();
    await expect(page.getByRole('heading', { level: 1, name: doomed.title })).toHaveCount(0);

    const drafts = await page.evaluate(() => ({
      gone: sessionStorage.getItem('aa.note-draft.987001'),
      kept: sessionStorage.getItem('aa.note-draft.987002')
    }));
    expect(drafts).toEqual({ gone: null, kept: 'keep me' });
  } finally {
    await page.request.delete(`/api/topics/${doomed.id}`);
  }
});

test('axe: the dashboard mid delete-confirm', async ({ page }) => {
  test.setTimeout(120_000);
  const topic = await makeTopic(page.request, 'axe');
  try {
    await selectTopic(page, topic.id);
    const found: unknown[] = [];
    for (const theme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme: theme });
      await page.goto('/');
      await settle(page);
      await page.getByRole('button', { name: 'Delete topic' }).click();
      await expect(page.getByRole('button', { name: 'Yes, delete it' })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze();
      found.push(...results.violations.map((v) => ({ theme, rule: v.id, targets: v.nodes.map((n) => n.target) })));
    }
    expect(found, JSON.stringify(found, null, 2)).toEqual([]);
  } finally {
    await page.request.delete(`/api/topics/${topic.id}`);
  }
});
