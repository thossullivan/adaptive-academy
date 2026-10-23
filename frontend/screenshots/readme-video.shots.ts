import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { createDemo, replayTutor, reportKeyConfigured, settle } from './demo';

// The README video: `npm run demo-video` records this walk through the demo topic, then
// screenshots/encode-video.sh turns it into docs/images/demo.gif and demo.mp4. Same throwaway
// servers and fakes as the screenshots (see ./demo.ts). Playwright's recording has no mouse
// pointer, so the page draws one.

const SIZE = { width: 1440, height: 900 };
const RAW = fileURLToPath(new URL('../test-results/readme-video/', import.meta.url));

test.use({
  viewport: SIZE,
  video: { mode: 'on', size: SIZE },
  // Motion on, unlike the stills: the graph settling is part of the show.
  reducedMotion: 'no-preference'
});

const POINTER = `
  addEventListener('DOMContentLoaded', () => {
    const dot = document.createElement('div');
    dot.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;width:18px;height:18px;' +
      'margin:-9px 0 0 -9px;border-radius:50%;background:rgba(255,255,255,.85);' +
      'box-shadow:0 0 0 2px rgba(0,0,0,.45);transition:transform .12s;left:-40px;top:-40px';
    document.body.append(dot);
    addEventListener('mousemove', (e) => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', () => { dot.style.transform = 'scale(.7)'; }, true);
    addEventListener('mouseup', () => { dot.style.transform = ''; }, true);
  });
`;

let pointer = { x: SIZE.width / 2, y: SIZE.height / 2 };

/** Glide the pointer to `target`, or just below it when only pointing, so the dot hides no text. */
async function moveTo(page: Page, target: Locator, { below = false } = {}) {
  await target.scrollIntoViewIfNeeded();
  const box = (await target.boundingBox())!;
  const to = { x: box.x + box.width / 2, y: below ? box.y + box.height + 14 : box.y + box.height / 2 };
  await page.mouse.move(pointer.x, pointer.y);
  await page.mouse.move(to.x, to.y, { steps: 25 });
  pointer = to;
}

async function clickSlowly(page: Page, target: Locator) {
  await moveTo(page, target);
  await page.waitForTimeout(250);
  await target.click();
}

const pause = (page: Page, ms: number) => page.waitForTimeout(ms);

// The phone drawer keeps a second, hidden copy of the rail.
const railLink = (page: Page, name: string) =>
  page.locator('aside nav').getByRole('link', { name, exact: true }).filter({ visible: true });

test('README video', async ({ page }) => {
  test.setTimeout(240_000);
  const started = Date.now();
  await page.addInitScript(POINTER);
  await reportKeyConfigured(page);
  const demo = await createDemo(page);

  // 1. The dashboard, then why one concept is only "shaky".
  await page.goto('/');
  await settle(page);
  await expect(page.getByRole('heading', { name: 'Build LLMs from scratch (demo)' })).toBeVisible();
  // Everything before this frame is a blank page; the encoder cuts it.
  const trimSeconds = (Date.now() - started) / 1000;
  await page.mouse.move(pointer.x, pointer.y);
  await pause(page, 2500);
  await clickSlowly(page, page.getByRole('button', { name: /^Why is Causal Self-Attention / }));
  await expect(page.getByText(/^Shaky: /).first()).toBeVisible();
  await pause(page, 3500);

  // 2. Today: what to do next.
  await clickSlowly(page, railLink(page, 'Today'));
  await settle(page);
  await expect(page.getByText('Your next steps on the track:')).toBeVisible();
  await pause(page, 3000);

  // 3. The tutor holds back the answer until there's an attempt.
  const composer = () => page.getByPlaceholder(/Ask the tutor/);
  await replayTutor(page, demo, async (text, attempt) => {
    if (attempt) {
      // Point at the gate before the attempt that opens it.
      await moveTo(page, page.getByText('no attempt yet'), { below: true });
      await pause(page, 1800);
    }
    await clickSlowly(page, composer());
    // About two seconds of typing per message, however long it is. Enter would send, so a
    // line break is Shift+Enter, as a learner types it.
    const delay = Math.min(35, 2000 / text.length);
    for (const [i, line] of text.split('\n').entries()) {
      if (i > 0) await composer().press('Shift+Enter');
      await composer().pressSequentially(line, { delay });
    }
    await pause(page, 400);
    await clickSlowly(page, page.getByRole('button', { name: attempt ? 'Submit attempt' : 'Send' }));
    await pause(page, 2800);
  });
  await moveTo(page, page.getByText('attempt logged'), { below: true });
  await pause(page, 3000);

  // 4. The concept graph, with one concept's prerequisites lit up.
  await clickSlowly(page, railLink(page, 'Constellation'));
  const graph = page.locator('[data-settled]');
  await expect(graph).toHaveAttribute('data-settled', 'true', { timeout: 30_000 });
  await pause(page, 1500);
  await clickSlowly(page, page.locator('g[role="button"][aria-label^="Causal Self-Attention:"]'));
  await expect(page.getByText(/prerequisite ancestors? highlighted/).first()).toBeVisible();
  await pause(page, 4000);

  const video = page.video()!;
  await page.close();
  await video.saveAs(`${RAW}demo.webm`);
  writeFileSync(`${RAW}demo.json`, JSON.stringify({ trimSeconds }));
});
