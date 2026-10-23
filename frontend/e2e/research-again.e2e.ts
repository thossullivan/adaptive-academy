import { expect, test, type Page } from '@playwright/test';

// A topic whose research failed (a rejected or missing API key) is created but has no
// foundation and no sources. Its Sources page must offer to run research again instead of a
// dead "0 of 0 kept" list with a disabled Save button.

async function topicWithoutResearch(page: Page, label: string): Promise<number> {
  const res = await page.request.post('/api/topics', {
    data: { title: `Research stalled ${label} ${test.info().project.name}`, goal: 'Learn the basics' }
  });
  expect(res.ok()).toBeTruthy();
  return ((await res.json()) as { id: number }).id;
}

test('the Sources page offers Research again and shows why it failed', async ({ page }) => {
  const id = await topicWithoutResearch(page, 'error');
  await page.goto(`/topics/${id}/review`);

  await expect(page.getByText("Research didn't finish for this topic.")).toBeVisible();
  const again = page.getByRole('button', { name: 'Research again' });
  await expect(again).toBeVisible();
  // Nothing to save or quiz on with no sources.
  await expect(page.getByRole('button', { name: 'Save reading list' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Generate quizzes' })).toHaveCount(0);
  await expect(page.getByText(/0 of 0 kept/i)).toHaveCount(0);

  // The e2e API has no key, so research fails; the page must say why, not stay silent.
  await again.click();
  const status = page.getByTestId('research-status');
  await expect(status).toContainText('Something went wrong:');
  await expect(status).toContainText('ANTHROPIC_API_KEY');
  await expect(again).toBeEnabled();
});

test('a successful Research again reloads the page with the reading list', async ({ page }) => {
  const id = await topicWithoutResearch(page, 'ok');
  let researched = false;
  await page.route(`**/api/topics/${id}/research`, async (route) => {
    researched = true;
    await route.fulfill({ json: { foundation: { overview: '', key_concepts: [], prerequisite_map: {} }, sources: [], events: [] } });
  });
  await page.route(`**/api/topics/${id}/foundation`, (route) =>
    researched
      ? route.fulfill({ json: { overview: 'How the pieces fit.', key_concepts: ['Priors'], prerequisite_map: {} } })
      : route.fallback()
  );
  await page.route(`**/api/topics/${id}/sources?status=proposed`, (route) =>
    researched
      ? route.fulfill({
          json: [{ id: 1, title: 'A found source', url: 'https://example.com/a', tier: 1, summary: 'Summary.', why: 'Why.', rank: 0, angle: 'foundational_papers', status: 'proposed' }]
        })
      : route.fallback()
  );

  await page.goto(`/topics/${id}/review`);
  await page.getByRole('button', { name: 'Research again' }).click();

  await expect(page.getByText('A found source')).toBeVisible();
  await expect(page.getByText('How the pieces fit.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save reading list' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Research again' })).toHaveCount(0);
});

const RUNNING = 'Research is still running for this topic. This page updates when it finishes.';
const SOURCE = { id: 1, title: 'A found source', url: 'https://example.com/a', tier: 1, summary: 'Summary.', why: 'Why.', rank: 0, angle: 'foundational_papers', status: 'proposed' };

test('opening Sources while research runs says so, then reloads when it finishes', async ({ page }) => {
  const id = await topicWithoutResearch(page, 'running');
  let running = true;
  await page.route(`**/api/topics/${id}`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), research_running: running } });
  });
  await page.route(`**/api/topics/${id}/sources?status=proposed`, (route) =>
    running ? route.fallback() : route.fulfill({ json: [SOURCE] })
  );

  await page.goto(`/topics/${id}/review`);
  await expect(page.getByTestId('research-running')).toHaveText(RUNNING);
  await expect(page.getByText("Research didn't finish for this topic.")).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Research again' })).toHaveCount(0);
  await expect(page.getByText(/0 of 0 kept/i)).toHaveCount(0);

  // Research finishes: the next check reloads the page with the reading list.
  running = false;
  await expect(page.getByText('A found source')).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId('research-running')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save reading list' })).toBeEnabled();
});

test('Research again refused as already running says so in plain words', async ({ page }) => {
  const id = await topicWithoutResearch(page, 'conflict');
  let refused = false;
  await page.route(`**/api/topics/${id}/research`, (route) => {
    refused = true;
    return route.fulfill({ status: 409, json: { detail: `topic:${id}:research is already running; wait for it to finish` } });
  });
  // The other run is still going when the page checks after the refusal.
  await page.route(`**/api/topics/${id}`, async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), research_running: refused } });
  });

  await page.goto(`/topics/${id}/review`);
  await page.getByRole('button', { name: 'Research again' }).click();
  await expect(page.getByTestId('research-running')).toHaveText(RUNNING);
  await expect(page.getByTestId('research-status')).not.toContainText('Something went wrong');
  await expect(page.getByRole('button', { name: 'Research again' })).toHaveCount(0);
});

test('Research again refused, but the other run finished meanwhile, shows the reading list', async ({ page }) => {
  const id = await topicWithoutResearch(page, 'conflict-done');
  let refused = false;
  await page.route(`**/api/topics/${id}/research`, (route) => {
    refused = true;
    return route.fulfill({ status: 409, json: { detail: `topic:${id}:research is already running; wait for it to finish` } });
  });
  // By the time the page asks, the other run has saved its sources and research_running is
  // false (the real API's answer for this topic), so nothing would update the page later.
  await page.route(`**/api/topics/${id}/sources?status=proposed`, (route) =>
    refused ? route.fulfill({ json: [SOURCE] }) : route.fallback()
  );

  await page.goto(`/topics/${id}/review`);
  await page.getByRole('button', { name: 'Research again' }).click();

  await expect(page.getByText('A found source')).toBeVisible();
  await expect(page.getByTestId('research-status')).toHaveText('');
  await expect(page.getByTestId('research-running')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save reading list' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Research again' })).toHaveCount(0);
});

test('a topic with a foundation but no sources offers Research again, not an empty list', async ({ page }) => {
  const id = await topicWithoutResearch(page, 'foundation');
  await page.route(`**/api/topics/${id}/foundation`, (route) =>
    route.fulfill({ json: { overview: 'How the pieces fit.', key_concepts: ['Priors'], prerequisite_map: {} } })
  );

  await page.goto(`/topics/${id}/review`);
  await expect(page.getByText('How the pieces fit.')).toBeVisible();
  await expect(page.getByText("Research didn't finish for this topic.")).toBeVisible();
  await expect(page.getByRole('button', { name: 'Research again' })).toBeEnabled();
  await expect(page.getByText(/0 of 0 kept/i)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save reading list' })).toHaveCount(0);
});

test('Research again never stays stuck when the reload after it fails', async ({ page }) => {
  const id = await topicWithoutResearch(page, 'reload');
  let researched = false;
  await page.route(`**/api/topics/${id}/research`, async (route) => {
    researched = true;
    await route.fulfill({ json: { foundation: { overview: '', key_concepts: [], prerequisite_map: {} }, sources: [], events: [] } });
  });
  await page.route(`**/api/topics/${id}/sources?status=proposed`, (route) =>
    researched ? route.fulfill({ status: 500, json: { detail: 'boom' } }) : route.fallback()
  );

  await page.goto(`/topics/${id}/review`);
  await page.getByRole('button', { name: 'Research again' }).click();
  await expect(page.getByTestId('research-status')).toContainText("couldn't load the reading list");
  await expect(page.getByRole('button', { name: 'Research again' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Researching…' })).toHaveCount(0);
});
