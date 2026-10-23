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
