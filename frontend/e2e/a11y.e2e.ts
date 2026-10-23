import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { withDemoLock, withDemoShared } from './demo-lock';
import {
  agentSdkInContainer,
  mistypedBackend,
  mockOpenRouterUsage,
  mockSetup,
  openrouterExperimental,
  openrouterMissingKey
} from './openrouter-mocks';

// Automated accessibility audit: axe-core's WCAG 2.0/2.1 A + AA rules on every page, in both
// themes, at desktop and phone width (the two Playwright projects). Topic pages run against
// the one-click demo topic so they have real content to check. The demo is shared with
// demo.e2e.ts (which removes it), so each test holds a shared demo lock while it reads pages.

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];
const THEMES = ['light', 'dark'] as const;

const APP_PAGES = ['/', '/fleet', '/programs', '/programs/new', '/topics/new', '/usage', '/data'];
const TOPIC_PAGES = [
  'today',
  'tutor',
  'track',
  'practice',
  'assess',
  'teach',
  'retention',
  'review',
  'notebook',
  'story',
  'vault',
  'wayfinder',
  'map'
];

async function settle(page: Page) {
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.getByText('calibrating')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
  // Let entrance animations finish: axe measures contrast on what is painted, and a panel
  // fading in is briefly translucent.
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined))
    )
  );
}

type Found = { page: string; theme: string; rule: string; impact: string; help: string; targets: string[] };

async function audit(page: Page, label: string, theme: string): Promise<Found[]> {
  const results = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  return results.violations.map((v) => ({
    page: label,
    theme,
    rule: v.id,
    impact: v.impact ?? '',
    help: v.help,
    targets: v.nodes.map((n) => `${n.target.join(' ')}${n.failureSummary ? ` :: ${n.failureSummary.split('\n').slice(1).join(' ').trim()}` : ''}`)
  }));
}

/** Make the demo topic exist and be the selected topic; returns its id. */
async function useDemo(page: Page): Promise<number> {
  const res = await page.request.post('/api/demo');
  expect(res.ok()).toBeTruthy();
  const { topic_id } = (await res.json()) as { topic_id: number };
  await page.addInitScript((id) => localStorage.setItem('aa-current-topic', String(id)), topic_id);
  return topic_id;
}

async function auditRoute(page: Page, route: (demoId: number) => string) {
  test.setTimeout(240_000);
  const found = await withDemoShared(() => useDemo(page), async (id) => {
    const url = route(id);
    const all: Found[] = [];
    for (const theme of THEMES) {
      await page.emulateMedia({ colorScheme: theme });
      await page.goto(url);
      await settle(page);
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      all.push(...(await audit(page, url, theme)));
    }
    return all;
  });
  expect(found, JSON.stringify(found, null, 2)).toEqual([]);
}

test.afterAll(async ({ playwright }, info) => {
  // Leave the shared db without a demo, as the other specs found it.
  const request = await playwright.request.newContext({ baseURL: info.project.use.baseURL });
  await withDemoLock(async () => {
    await request.delete('/api/demo');
  });
  await request.dispose();
});

for (const path of APP_PAGES) {
  test(`axe: ${path}`, async ({ page }) => {
    await auditRoute(page, () => path);
  });
}

for (const sub of TOPIC_PAGES) {
  test(`axe: /topics/{demo}/${sub}`, async ({ page }) => {
    await auditRoute(page, (id) => `/topics/${id}/${sub}`);
  });
}

// ── Interactive states a plain page load never shows ────────────────────────────────────────

const isPhone = () => test.info().project.name === 'phone';

/** Audit `url` in both themes after `prepare` puts the page in the state under test. */
async function auditState(page: Page, url: (demoId: number) => string, prepare: () => Promise<void>) {
  test.setTimeout(240_000);
  const found = await withDemoShared(() => useDemo(page), async (id) => {
    const all: Found[] = [];
    for (const theme of THEMES) {
      await page.emulateMedia({ colorScheme: theme });
      await page.goto(url(id));
      await settle(page);
      await prepare();
      await settle(page);
      all.push(...(await audit(page, `${url(id)} (${test.info().title})`, theme)));
    }
    return all;
  });
  expect(found, JSON.stringify(found, null, 2)).toEqual([]);
}

test('axe: the first-run welcome', async ({ page }) => {
  await page.route('**/api/topics', (r) => (r.request().method() === 'GET' ? r.fulfill({ json: [] }) : r.fallback()));
  await auditState(page, () => '/', async () => {
    await expect(page.getByRole('button', { name: /Explore a demo topic/ })).toBeVisible();
  });
});

test('axe: the open navigation (the drawer on a phone) and topic list', async ({ page }) => {
  await auditState(page, (id) => `/topics/${id}/today`, async () => {
    if (isPhone()) {
      await page.getByRole('button', { name: 'Open navigation' }).click();
      await expect(page.locator('#mobile-nav-drawer')).toBeVisible();
    }
    const rail = page.locator('aside:visible');
    await rail.getByRole('button', { name: /^Topic: / }).click();
    await expect(rail.getByRole('list', { name: 'Topics' })).toBeVisible();
  });
});

test('axe: the dashboard mid-confirm, with a concept rationale open', async ({ page }) => {
  await auditState(page, () => '/', async () => {
    await page.getByRole('button', { name: 'Remove demo' }).click();
    await expect(page.getByRole('button', { name: 'Yes, remove it' })).toBeVisible();
    await page.getByRole('button', { name: /^Why is / }).first().click();
  });
});

test('axe: the constellation with a star selected and the list open', async ({ page }) => {
  await auditState(page, (id) => `/topics/${id}/map`, async () => {
    await page.getByText('Concepts as a list').click();
    await page.getByTestId('concept-list').getByRole('button').first().click();
    await expect(page.getByText('selected', { exact: true })).toBeVisible();
  });
});

test('axe: a tutor reply with the agent trace open', async ({ page }) => {
  await mockTutor(page);
  await auditState(page, (id) => `/topics/${id}/tutor`, async () => {
    await page.getByRole('textbox', { name: 'Message the tutor' }).fill('Why mask with −∞?');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText('What happens to the softmax')).toBeVisible();
    await page.getByRole('button', { name: /what the agent did/ }).click();
  });
});

test('axe: a submitted attempt that was not logged, with its note', async ({ page }) => {
  await mockTutor(page, { attempt_logged: false, attempt_outcome: 'rejected' });
  await auditState(page, (id) => `/topics/${id}/tutor`, async () => {
    await page.getByRole('textbox', { name: 'Message the tutor' }).fill('is it 42?');
    await page.getByRole('button', { name: 'Submit attempt' }).click();
    await expect(page.getByTestId('attempt-note')).toBeVisible();
    await expect(page.getByTestId('attempt-chip')).toHaveText('Attempt · not logged');
  });
});

test('axe: a logged attempt and the worked solution it unlocked, with code', async ({ page }) => {
  await mockTutor(page, {
    reply: 'Mask with `-inf` first:\n```python\nscores = scores.masked_fill(mask == 0, float("-inf"))\n```\nThen take the softmax.',
    attempt_logged: true,
    attempt_outcome: 'accepted',
    reveals_solution: true
  });
  await auditState(page, (id) => `/topics/${id}/tutor`, async () => {
    const input = page.getByRole('textbox', { name: 'Message the tutor' });
    await input.fill('Set the masked logits to `-inf` before the softmax.');
    await expect(page.getByRole('button', { name: 'Submit attempt' })).toHaveAttribute('data-ready', 'true');
    await page.getByRole('button', { name: 'Submit attempt' }).click();
    await expect(page.getByTestId('worked-solution')).toBeVisible();
    await expect(page.getByTestId('attempt-chip')).toHaveText('Attempt · logged');
    // A draft after the attempt is logged: the calmer Submit attempt is audited too.
    await input.fill('And during generation?');
  });
});

test('axe: a kept draft that conflicts with a newer saved note', async ({ page }) => {
  page.on('dialog', (dialog) => dialog.accept());
  await auditState(page, (id) => `/topics/${id}/tutor`, async () => {
    // A draft of unknown age (kept as plain text) always asks which to keep.
    const conceptId = Number(await page.getByRole('combobox', { name: 'Concept' }).inputValue());
    await page.evaluate((id) => sessionStorage.setItem(`aa.note-draft.${id}`, 'An older draft from this tab.'), conceptId);
    await page.getByRole('button', { name: 'Notes', exact: true }).click();
    await expect(page.getByTestId('note-conflict')).toBeVisible();
  });
});

test('axe: the tutor with the notes panel open and a draft unsaved', async ({ page }) => {
  // The unsaved draft makes the browser ask before the next theme's page load: leave anyway.
  page.on('dialog', (dialog) => dialog.accept());
  await auditState(page, (id) => `/topics/${id}/tutor`, async () => {
    await page.getByRole('button', { name: 'Notes', exact: true }).click();
    const box = page.locator('#tutor-notes').getByRole('textbox', { name: /^My notes on / });
    await expect(box).toBeVisible();
    await box.fill('An unsaved draft for the audit.');
    // The second theme finds the draft kept in this tab: the status also says it was restored.
    await expect(page.getByTestId('note-status')).toContainText('Unsaved changes');
  });
});

test('axe: the notebook for a concept with notes, attempts, and a worked solution', async ({ page }) => {
  await auditState(page, (id) => `/topics/${id}/notebook`, async () => {
    const list = page.getByRole('navigation', { name: 'Concepts with notes or work' });
    await list.getByRole('link', { name: /Causal Self-Attention/ }).click();
    await expect(page.getByTestId('notebook-solutions')).toContainText('Worked solution');
    await expect(page.getByRole('textbox', { name: 'My notes on Causal Self-Attention' })).not.toHaveValue('');
  });
});

test('axe: the OpenRouter missing-key card', async ({ page }) => {
  await mockSetup(page, openrouterMissingKey);
  await auditState(page, () => '/topics/new', async () => {
    await expect(page.getByTestId('setup-notice')).toBeVisible();
  });
});

test('axe: the experimental-model card on the dashboard', async ({ page }) => {
  await mockSetup(page, openrouterExperimental);
  await auditState(page, () => '/', async () => {
    await expect(page.getByTestId('setup-experimental')).toBeVisible();
  });
});

test('axe: the container agent_sdk card and the setup-warning card', async ({ page }) => {
  await mockSetup(page, agentSdkInContainer);
  await auditState(page, () => '/topics/new', async () => {
    await expect(page.getByTestId('setup-notice')).toBeVisible();
  });
  await page.unroute('**/api/setup');
  await mockSetup(page, mistypedBackend);
  await auditState(page, () => '/', async () => {
    await expect(page.getByTestId('setup-check')).toBeVisible();
  });
});

test('axe: the usage page with an experimental model row', async ({ page }) => {
  await mockOpenRouterUsage(page);
  await auditState(page, () => '/usage', async () => {
    await expect(page.getByTestId('experimental-label')).toBeVisible();
    // The quality scorecard, with its tables and window buttons, is audited too.
    await expect(page.getByTestId('quality-by-model')).toBeVisible();
  });
});

/** A keyless tutor that answers: the conversation and one reply, served by the test. */
async function mockTutor(page: Page, reply: Record<string, unknown> = {}) {
  await page.route('**/api/conversations', (r) =>
    r.request().method() === 'POST'
      ? r.fulfill({
          json: { id: 999, concept_id: 1, attempt_logged: false, assistance_level: 'medium', challenge_level: 'medium', messages: [] }
        })
      : r.fallback()
  );
  await page.route('**/api/conversations/999/messages', async (r) => {
    await new Promise((res) => setTimeout(res, 300));
    await r.fulfill({
      json: {
        reply: 'What happens to the softmax if a logit is −∞?',
        attempt_logged: true,
        assistance_level: 'medium',
        challenge_level: 'high',
        events: [{ kind: 'tool:reveal_solution', detail: 'blocked', created_at: new Date().toISOString().replace('Z', ''), count: 1 }],
        memory: [],
        ...reply
      }
    });
  });
}
