import { expect, test, type Page } from '@playwright/test';

// The Concept Constellation must read as a legible, well-spread graph at any container size:
// every star inside the box and off the walls, labels never clipped, and the legend never
// sitting on top of a star. The e2e seed has 19 concepts (several long names) and 30 edges.

type Box = { x: number; y: number; width: number; height: number };
type NodeGeo = Box & { id: string; r: number };
type Geometry = { canvas: Box; nodes: NodeGeo[]; labels: (Box & { id: string })[]; legend: Box };

// Halo drawn around each star (glow ring); the node's visual footprint includes it.
const HALO = 8;
const EPS = 0.5;

async function topicId(page: Page): Promise<number> {
  const res = await page.request.get('/api/topics');
  expect(res.ok()).toBeTruthy();
  const topics: { id: number }[] = await res.json();
  expect(topics.length).toBeGreaterThan(0);
  return topics[0].id;
}

/** Wait until the simulation has ended for the container's *current* size. */
async function waitSettled(page: Page) {
  await page.waitForFunction(
    () => {
      const root = document.querySelector('[data-testid="constellation"]');
      const canvas = document.querySelector('[data-testid="constellation-canvas"]');
      if (!root || !canvas) return false;
      const r = canvas.getBoundingClientRect();
      return (
        root.getAttribute('data-settled') === 'true' &&
        Math.abs(Number(root.getAttribute('data-layout-w')) - r.width) < 3 &&
        Math.abs(Number(root.getAttribute('data-layout-h')) - r.height) < 3
      );
    },
    null,
    { timeout: 20_000 }
  );
}

async function geometry(page: Page): Promise<Geometry> {
  return page.evaluate(() => {
    const box = (el: Element) => {
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    };
    const canvas = document.querySelector('[data-testid="constellation-canvas"]')!;
    return {
      canvas: box(canvas),
      nodes: [...document.querySelectorAll('[data-testid="constellation-node"]')].map((el) => ({
        ...box(el),
        id: el.getAttribute('data-node-id') ?? '',
        r: Number(el.getAttribute('r'))
      })),
      labels: [...document.querySelectorAll('[data-testid="constellation-label"]')].map((el) => ({
        ...box(el),
        id: el.getAttribute('data-node-id') ?? ''
      })),
      legend: box(document.querySelector('[data-testid="constellation-legend"]')!)
    };
  });
}

function inside(inner: Box, outer: Box): boolean {
  return (
    inner.x >= outer.x - EPS &&
    inner.y >= outer.y - EPS &&
    inner.x + inner.width <= outer.x + outer.width + EPS &&
    inner.y + inner.height <= outer.y + outer.height + EPS
  );
}

function intersects(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function halo(n: NodeGeo): Box {
  return { x: n.x - HALO, y: n.y - HALO, width: n.width + 2 * HALO, height: n.height + 2 * HALO };
}

function assertLayout(g: Geometry) {
  expect(g.nodes).toHaveLength(19);
  const c = g.canvas;
  for (const n of g.nodes) {
    expect(inside(n, c), `node ${n.id} core inside the container`).toBe(true);
    expect(inside(halo(n), c), `node ${n.id} halo inside the container`).toBe(true);
    const cx = n.x + n.width / 2;
    const cy = n.y + n.height / 2;
    const wall = Math.min(cx - c.x, c.x + c.width - cx, cy - c.y, c.y + c.height - cy);
    expect(wall, `node ${n.id} is not hugging a wall`).toBeGreaterThan(n.r + 4);
    expect(intersects(halo(n), g.legend), `legend overlaps node ${n.id}`).toBe(false);
  }
  expect(g.labels.length, 'some labels are shown').toBeGreaterThanOrEqual(3);
  for (const l of g.labels) {
    expect(inside(l, c), `label for node ${l.id} inside the container`).toBe(true);
  }
}

test('constellation lays out inside its box with legible labels', async ({ page }) => {
  const id = await topicId(page);
  await page.goto(`/topics/${id}/map`);
  await waitSettled(page);
  assertLayout(await geometry(page));

  // No rebuild loop: once settled, no further layout runs happen and it stays settled.
  // Sampled without retries so a loop that briefly re-settles cannot pass.
  const root = page.getByTestId('constellation');
  const runs = await root.getAttribute('data-layout-runs');
  for (let i = 0; i < 4; i++) {
    await page.waitForTimeout(500);
    expect(await root.getAttribute('data-layout-runs')).toBe(runs);
    expect(await root.getAttribute('data-settled')).toBe('true');
  }
});

test('a truncated label\'s star carries the full concept name', async ({ page }) => {
  // Labels are pointer-events-none (one can sit over a neighbouring star), so the full name
  // must come from the star: its <title> tooltip and its aria-label.
  // At 1440px no seeded label truncates, so use a narrower desktop where several do.
  if (test.info().project.name === 'desktop') await page.setViewportSize({ width: 1100, height: 760 });
  const id = await topicId(page);
  await page.goto(`/topics/${id}/map`);
  await waitSettled(page);
  const labels = await page.getByTestId('constellation-label').evaluateAll((els) =>
    els.map((el) => {
      const nodeId = el.getAttribute('data-node-id');
      const star = document.querySelector(
        `[data-testid="constellation-node"][data-node-id="${nodeId}"]`
      )?.parentElement;
      return {
        shown: el.textContent ?? '',
        pointerEvents: getComputedStyle(el).pointerEvents,
        title: star?.querySelector(':scope > title')?.textContent ?? null,
        ariaLabel: star?.getAttribute('aria-label') ?? null
      };
    })
  );
  const truncated = labels.filter((l) => l.shown.endsWith('…'));
  expect(truncated.length).toBeGreaterThan(0);
  for (const l of labels) expect(l.pointerEvents, `label "${l.shown}"`).toBe('none');
  for (const l of truncated) {
    const prefix = l.shown.slice(0, -1).trimEnd();
    expect(l.title, `star of "${l.shown}" has a <title>`).not.toBeNull();
    // The full name, not the fitted label text.
    expect(l.title!.endsWith('…')).toBe(false);
    expect(l.title!.length).toBeGreaterThan(prefix.length);
    expect(l.title!.startsWith(prefix)).toBe(true);
    expect(l.ariaLabel).toBe(l.title);
  }
});

test('hovering an edge star shows its label inside the box', async ({ page }) => {
  const id = await topicId(page);
  await page.goto(`/topics/${id}/map`);
  await waitSettled(page);
  const g = await geometry(page);
  // The plain (not load-bearing, so unlabelled until hovered) star closest to a side wall is
  // the label most likely to clip. Only stars on screen: until the shell's rail becomes a
  // drawer, part of the graph can sit past a phone viewport's right edge.
  const vw = page.viewportSize()!.width;
  const c = g.canvas;
  const wallGap = (n: NodeGeo) =>
    Math.min(n.x - c.x, c.x + c.width - (n.x + n.width));
  const plain = g.nodes.filter((n) => n.r < 10 && n.x + n.width < vw - 2);
  expect(plain.length).toBeGreaterThan(0);
  const edge = plain.reduce((a, b) => (wallGap(b) < wallGap(a) ? b : a));
  const label = page.locator(`[data-testid="constellation-label"][data-node-id="${edge.id}"]`);
  await expect(label).toHaveCount(0);
  await page.locator(`[data-testid="constellation-node"][data-node-id="${edge.id}"]`).hover();
  await expect(label).toBeVisible();
  const lb = (await label.boundingBox())!;
  const canvas = (await page.getByTestId('constellation-canvas').boundingBox())!;
  expect(inside(lb, canvas), 'hovered label inside the container').toBe(true);
});

test('constellation re-lays out when the viewport changes', async ({ page }) => {
  const id = await topicId(page);
  await page.goto(`/topics/${id}/map`);
  await waitSettled(page);
  const before = await geometry(page);

  const vp = page.viewportSize()!;
  await page.setViewportSize(
    vp.width > 800 ? { width: 1100, height: 760 } : { width: 640, height: 900 }
  );
  await page.waitForFunction(
    (w) => {
      const c = document.querySelector('[data-testid="constellation-canvas"]');
      return !!c && Math.abs(c.getBoundingClientRect().width - w) > 3;
    },
    before.canvas.width
  );
  await waitSettled(page);
  assertLayout(await geometry(page));
});

test('reduced motion settles off-screen and renders the final layout at once', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const id = await topicId(page);
  await page.goto(`/topics/${id}/map`);
  // No animation to wait out: the first rendered layout is already the settled one.
  await expect(page.getByTestId('constellation')).toHaveAttribute('data-settled', 'true', {
    timeout: 3_000
  });
  await waitSettled(page);
  assertLayout(await geometry(page));
});
