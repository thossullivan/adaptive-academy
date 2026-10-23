import { expect, test, type Locator, type Page } from '@playwright/test';

// First run of a fresh clone: the e2e API runs without ANTHROPIC_API_KEY, so the app must
// say so (and how to fix it) instead of letting LLM-backed actions fail with a bare 500.

const notice = (page: Page) => page.getByTestId('setup-notice');
const topicSubmit = (page: Page) => page.getByRole('button', { name: /Research this topic/ });
const programSubmit = (page: Page) => page.getByRole('button', { name: /Create program/ });

async function fillTopicForm(page: Page) {
  await page.getByPlaceholder('e.g. Build LLMs from scratch').fill('Linear algebra');
  await page.getByPlaceholder("By the end I'll have…").fill('Derive SVD');
}

async function fillProgramForm(page: Page) {
  await page.getByLabel('Title', { exact: true }).fill('Research-ready ML');
}

/** The new first-run blocks must sit within <main> (the content area beside the shell rail),
 *  whatever width the rail leaves at this viewport. */
async function expectInsideMain(page: Page, locators: Locator[]) {
  const main = await page.locator('main').boundingBox();
  expect(main).not.toBeNull();
  for (const loc of locators) {
    const box = await loc.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(main!.x - 1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(main!.x + main!.width + 1);
  }
}

async function mockSetupReady(page: Page) {
  await page.route('**/api/setup', (route) =>
    route.fulfill({
      json: { llm_backend: 'anthropic', llm_ready: true, message: 'Anthropic API key configured.' }
    })
  );
}

test.describe('no API key (real API)', () => {
  test('home explains what is missing and how to fix it', async ({ page }) => {
    await page.goto('/');
    await expect(notice(page)).toBeVisible();
    await expect(notice(page)).toContainText('ANTHROPIC_API_KEY');
    await expect(notice(page)).toContainText('cp .env.example .env');
    await expect(notice(page)).toContainText('AA_LLM_BACKEND=agent_sdk');
    // The populated dashboard still renders beside the notice.
    await expect(
      page.getByRole('heading', { name: 'Build LLMs from Scratch including the math' })
    ).toBeVisible();
  });

  test('/topics/new shows the notice and disables research', async ({ page }) => {
    await page.goto('/topics/new');
    await expect(notice(page)).toBeVisible();
    await fillTopicForm(page);
    await expect(topicSubmit(page)).toBeDisabled();
    await expect(page.getByTestId('submit-blocked')).toBeVisible();
  });

  test('/programs/new shows the notice and disables create', async ({ page }) => {
    await page.goto('/programs/new');
    await expect(notice(page)).toBeVisible();
    await fillProgramForm(page);
    await expect(programSubmit(page)).toBeDisabled();
    await expect(page.getByTestId('submit-blocked')).toBeVisible();
  });
});

test.describe('LLM ready (mocked /api/setup)', () => {
  test('home hides the notice', async ({ page }) => {
    await mockSetupReady(page);
    const setup = page.waitForResponse('**/api/setup');
    await page.goto('/');
    await setup;
    await expect(
      page.getByRole('heading', { name: 'Build LLMs from Scratch including the math' })
    ).toBeVisible();
    await expect(notice(page)).toBeHidden();
  });

  test('/topics/new enables research', async ({ page }) => {
    await mockSetupReady(page);
    const setup = page.waitForResponse('**/api/setup');
    await page.goto('/topics/new');
    await setup;
    await fillTopicForm(page);
    await expect(topicSubmit(page)).toBeEnabled();
    await expect(notice(page)).toBeHidden();
    await expect(page.getByTestId('submit-blocked')).toBeHidden();
    await expect(page.getByText(/runs several model calls/i)).toBeVisible();
  });

  test('/programs/new enables create', async ({ page }) => {
    await mockSetupReady(page);
    const setup = page.waitForResponse('**/api/setup');
    await page.goto('/programs/new');
    await setup;
    await fillProgramForm(page);
    await expect(programSubmit(page)).toBeEnabled();
    await expect(notice(page)).toBeHidden();
    await expect(page.getByTestId('submit-blocked')).toBeHidden();
    await expect(page.getByText(/runs several model calls/i)).toBeVisible();
  });
});

test.describe('empty home (no topics yet)', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/topics', (route) =>
      route.request().method() === 'GET' ? route.fulfill({ json: [] }) : route.fallback()
    );
  });

  test('offers both entry points and the setup notice', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: /Start a program/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Start a topic/ })).toBeVisible();
    await expect(notice(page)).toBeVisible();
  });

  test('puts the demo first, then the entry points, then the setup notice', async ({ page }) => {
    await page.goto('/');
    const demo = page.getByRole('button', { name: /Explore a demo topic/ });
    const program = page.getByRole('link', { name: /Start a program/ });
    await expect(demo).toBeVisible();
    await expect(notice(page)).toBeVisible();
    // A filled (primary) button, not a small text link.
    await expect(demo).toHaveClass(/\bbg-accent\b/);
    const top = async (l: Locator) => (await l.boundingBox())!.y;
    expect(await top(demo)).toBeLessThan(await top(program));
    expect(await top(program)).toBeLessThan(await top(notice(page)));
    // In the first screen at both sizes, not below a tall setup card.
    const box = (await demo.boundingBox())!;
    expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  });

  test('folds the other backends away and keeps the key steps in view', async ({ page }) => {
    await page.goto('/');
    await expect(notice(page).getByText('cp .env.example .env')).toBeVisible();
    const more = notice(page).getByTestId('setup-alternatives');
    await expect(more).not.toHaveAttribute('open', '');
    await expect(more.locator('code', { hasText: 'AA_LLM_BACKEND=agent_sdk' })).toBeHidden();
    await more.getByText('Use a Claude subscription or OpenRouter instead').click();
    await expect(more.locator('code', { hasText: 'AA_LLM_BACKEND=agent_sdk' })).toBeVisible();
  });

  test('"Start a program" goes to /programs/new', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /Start a program/ }).click();
    await expect(page).toHaveURL(/\/programs\/new$/);
  });

  test('"Start a topic" goes to /topics/new', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /Start a topic/ }).click();
    await expect(page).toHaveURL(/\/topics\/new$/);
  });

  test('entry points and notice stay inside the content area', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: /Start a topic/ })).toBeVisible();
    await expectInsideMain(page, [
      notice(page),
      page.getByRole('link', { name: /Start a program/ }),
      page.getByRole('link', { name: /Start a topic/ })
    ]);
  });
});

test('/programs/new carries no personal details in its placeholders', async ({ page }) => {
  await page.goto('/programs/new');
  await expect(programSubmit(page)).toBeVisible();
  const placeholders = await page
    .locator('[placeholder]')
    .evaluateAll((els) => els.map((el) => el.getAttribute('placeholder') ?? ''));
  expect(placeholders.length).toBeGreaterThan(0);
  for (const p of placeholders) expect(p).not.toContain('MS DS');
});

for (const path of ['/topics/new', '/programs/new']) {
  test(`${path} keeps the notice and cost note inside the content area`, async ({ page }) => {
    await page.goto(path);
    await expect(notice(page)).toBeVisible();
    await expectInsideMain(page, [
      notice(page),
      page.getByTestId('submit-blocked'),
      page.getByText(/runs several model calls/i)
    ]);
  });
}
