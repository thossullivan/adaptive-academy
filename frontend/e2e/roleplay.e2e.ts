import { expect, test, type Page } from '@playwright/test';

// The roleplay endpoints are routed to canned responses: what's under test is how the page
// treats a turn the server did not record (`recorded: false`), not the persona model.

const SID = 9001;
const SESSION = {
  session_id: SID,
  program_id: 1,
  status: 'active',
  brief_public: { persona: 'Skeptical staff engineer', situation: 'Design review' },
  turns: [
    { role: 'user', content: 'Opening move' },
    { role: 'persona', content: 'Go on.' }
  ],
  outcome: null,
  scorecard: null
};
const NOTICE = 'The examiner had no reply to that one. Try rephrasing your answer.';

async function routeSession(page: Page, turn: (body: string) => object | null) {
  await page.route(`**/api/roleplay/${SID}`, (route) => route.fulfill({ json: SESSION }));
  await page.route(`**/api/roleplay/${SID}/turns`, (route) => {
    const reply = turn(route.request().postData() ?? '');
    return reply
      ? route.fulfill({ json: reply })
      : route.fulfill({ status: 429, json: { detail: 'Daily spending limit reached.' } });
  });
}

test('an unrecorded turn is withdrawn and shown as a system notice, not a persona line', async ({ page }) => {
  await routeSession(page, () => ({ reply: NOTICE, status: 'active', recorded: false }));
  await page.goto(`/roleplay/${SID}`);
  await expect(page.getByText('Go on.')).toBeVisible();

  const box = page.getByPlaceholder('Respond to the examiner…');
  await box.fill('My risky answer');
  await page.getByRole('button', { name: 'Send' }).click();

  const notice = page.getByTestId('roleplay-notice');
  await expect(notice).toContainText(NOTICE);
  // Not a persona bubble, and the learner's line is gone from the transcript (as on reload)…
  await expect(page.locator('.eyebrow', { hasText: /^persona$/ })).toHaveCount(1);
  await expect(page.getByText('My risky answer', { exact: true })).toHaveCount(0);
  // …but kept in the input to rephrase.
  await expect(box).toHaveValue('My risky answer');
});

test('a recorded turn shows the persona reply and clears the notice', async ({ page }) => {
  let calls = 0;
  await routeSession(page, () =>
    ++calls === 1
      ? { reply: NOTICE, status: 'active', recorded: false }
      : { reply: 'Why that trade-off?', status: 'active', recorded: true }
  );
  await page.goto(`/roleplay/${SID}`);
  const box = page.getByPlaceholder('Respond to the examiner…');
  await box.fill('First try');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByTestId('roleplay-notice')).toBeVisible();

  await box.fill('Second try');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('Why that trade-off?')).toBeVisible();
  await expect(page.getByText('Second try', { exact: true })).toBeVisible();
  await expect(page.getByTestId('roleplay-notice')).toHaveCount(0);
  await expect(box).toHaveValue('');
});

test('a failed turn is withdrawn too and the text is kept', async ({ page }) => {
  await routeSession(page, () => null);
  await page.goto(`/roleplay/${SID}`);
  const box = page.getByPlaceholder('Respond to the examiner…');
  await box.fill('Over budget answer');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('Daily spending limit reached.')).toBeVisible();
  await expect(page.getByText('Over budget answer', { exact: true })).toHaveCount(0);
  await expect(box).toHaveValue('Over budget answer');
});
