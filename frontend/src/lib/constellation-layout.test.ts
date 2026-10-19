import { describe, expect, it } from 'vitest';
import {
  EDGE_PAD,
  LABEL_MAX_WIDTH,
  LABEL_MIN_WIDTH,
  MAX_RADIUS,
  fitLabel,
  forceParams,
  hasRealSize,
  labelMaxWidth,
  layoutBounds,
  layoutLabels,
  placeLabel,
  rescalePositions,
  sizeChanged,
  runLayout,
  type LabelItem,
  type LayoutNode
} from './constellation-layout';

// Fake text metrics: every glyph is 6px wide.
const measure = (t: string) => t.length * 6;

// The e2e seed graph: 19 concepts, 30 prerequisite edges, 10 load-bearing.
const LOAD_BEARING = [0, 2, 3, 5, 7, 8, 9, 10, 13];
const EDGES: [number, number][] = [
  [1, 0], [2, 0], [2, 1], [4, 3], [3, 5], [5, 6], [5, 7], [0, 7],
  [5, 8], [8, 9], [9, 10], [8, 10], [10, 13], [11, 13], [12, 13], [6, 13],
  [7, 13], [5, 14], [13, 14], [0, 15], [15, 16], [13, 16], [16, 17], [13, 17],
  [9, 18], [13, 18], [2, 8], [7, 9], [12, 11], [15, 13]
];
const seedNodes = (): LayoutNode[] =>
  Array.from({ length: 19 }, (_, i) => ({ id: i, r: LOAD_BEARING.includes(i) ? 11 : 7 }));
const seedLinks = () => EDGES.map(([s, t]) => ({ source: s, target: t }));

describe('container size', () => {
  it('treats an unmeasured or collapsed container as not ready', () => {
    expect(hasRealSize({ width: 0, height: 0 })).toBe(false);
    expect(hasRealSize({ width: 775, height: 0 })).toBe(false);
    expect(hasRealSize({ width: 775, height: 540 })).toBe(true);
  });

  it('only counts meaningful size changes', () => {
    expect(sizeChanged({ width: 775, height: 540 }, { width: 775.4, height: 540 })).toBe(false);
    expect(sizeChanged({ width: 775, height: 540 }, { width: 760, height: 540 })).toBe(true);
    expect(sizeChanged(null, { width: 775, height: 540 })).toBe(true);
  });
});

describe('layout bounds', () => {
  it('insets by at least node radius plus a label allowance', () => {
    const b = layoutBounds({ width: 775, height: 540 });
    expect(b.x0).toBeGreaterThanOrEqual(MAX_RADIUS + 8);
    expect(b.y0).toBeGreaterThanOrEqual(MAX_RADIUS + 20);
    expect(b.x1).toBe(775 - b.x0);
    expect(b.y1).toBe(540 - b.y0);
  });

  it('collapses to the centre line rather than inverting in a tiny box', () => {
    const b = layoutBounds({ width: 30, height: 30 });
    expect(b.x0).toBeLessThanOrEqual(b.x1);
    expect(b.y0).toBeLessThanOrEqual(b.y1);
  });
});

describe('force parameters', () => {
  it('scale with available area per node', () => {
    const big = forceParams({ width: 775, height: 540 }, 19);
    const small = forceParams({ width: 160, height: 500 }, 19);
    expect(big.linkDistance).toBeGreaterThan(small.linkDistance);
    expect(Math.abs(big.charge)).toBeGreaterThan(Math.abs(small.charge));
    expect(big.charge).toBeLessThan(0);
  });

  it('pull harder along the short axis', () => {
    const wide = forceParams({ width: 900, height: 400 }, 19);
    expect(wide.gravityY).toBeGreaterThan(wide.gravityX);
    const tall = forceParams({ width: 160, height: 500 }, 19);
    expect(tall.gravityX).toBeGreaterThan(tall.gravityY);
  });

  it('spread fewer nodes further apart', () => {
    const few = forceParams({ width: 775, height: 540 }, 4);
    const many = forceParams({ width: 775, height: 540 }, 40);
    expect(few.linkDistance).toBeGreaterThanOrEqual(many.linkDistance);
  });
});

describe('simulated layout of the 19-concept seed graph', () => {
  for (const size of [
    { width: 775, height: 540 },
    { width: 1080, height: 520 },
    { width: 165, height: 380 },
    { width: 340, height: 420 }
  ]) {
    it(`stays inside, off the walls, and spread out at ${size.width}x${size.height}`, () => {
      const nodes = seedNodes();
      runLayout(nodes, seedLinks(), size);
      const b = layoutBounds(size);
      const xs = nodes.map((n) => n.x!);
      const ys = nodes.map((n) => n.y!);
      for (const n of nodes) {
        expect(n.x!).toBeGreaterThanOrEqual(b.x0);
        expect(n.x!).toBeLessThanOrEqual(b.x1);
        expect(n.y!).toBeGreaterThanOrEqual(b.y0);
        expect(n.y!).toBeLessThanOrEqual(b.y1);
      }
      // Forces, not the safety clamp, keep nodes in: few nodes sit pinned on the bounds.
      const pinned = nodes.filter(
        (n) =>
          n.x! - b.x0 < 1 || b.x1 - n.x! < 1 || n.y! - b.y0 < 1 || b.y1 - n.y! < 1
      ).length;
      expect(pinned).toBeLessThanOrEqual(1);
      // ...and the constellation actually uses the box instead of clumping in the middle.
      expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan((b.x1 - b.x0) * 0.65);
      expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan((b.y1 - b.y0) * 0.65);
      // No two stars overlap.
      for (let i = 0; i < nodes.length; i++)
        for (let j = i + 1; j < nodes.length; j++) {
          const d = Math.hypot(nodes[i].x! - nodes[j].x!, nodes[i].y! - nodes[j].y!);
          expect(d).toBeGreaterThan(nodes[i].r + nodes[j].r);
        }
    });
  }
});

describe('rescalePositions', () => {
  it('maps positions proportionally into the new box', () => {
    const nodes = [{ x: 100, y: 50 }, { x: 700, y: 500 }];
    rescalePositions(nodes, { width: 800, height: 540 }, { width: 400, height: 540 });
    expect(nodes[0].x).toBeCloseTo(50);
    expect(nodes[1].x).toBeCloseTo(350);
    expect(nodes[1].y).toBeCloseTo(500);
  });
});

describe('fitLabel', () => {
  it('keeps short names intact', () => {
    expect(fitLabel('LoRA', 100, measure)).toEqual({ text: 'LoRA', width: 24, truncated: false });
  });

  it('truncates long names with an ellipsis within the width', () => {
    const name = 'Positional Encodings (sinusoidal and RoPE)';
    const fit = fitLabel(name, 120, measure);
    expect(fit.truncated).toBe(true);
    expect(fit.text.endsWith('…')).toBe(true);
    expect(fit.width).toBeLessThanOrEqual(120);
    expect(name.startsWith(fit.text.slice(0, -1).trimEnd())).toBe(true);
  });

  it('gives up cleanly when nothing fits', () => {
    expect(fitLabel('Anything', 2, measure)).toEqual({ text: '', width: 0, truncated: true });
  });
});

describe('labelMaxWidth', () => {
  it('scales with the box but never exceeds it', () => {
    expect(labelMaxWidth({ width: 775, height: 540 })).toBeGreaterThanOrEqual(220);
    expect(labelMaxWidth({ width: 2000, height: 540 })).toBe(LABEL_MAX_WIDTH);
    expect(labelMaxWidth({ width: 400, height: 300 })).toBe(LABEL_MIN_WIDTH);
    expect(labelMaxWidth({ width: 100, height: 300 })).toBe(100 - 2 * EDGE_PAD);
  });
});

describe('placeLabel', () => {
  const size = { width: 400, height: 300 };

  it('centres the label above a node with room', () => {
    const p = placeLabel({ x: 200, y: 150, r: 7 }, 80, size, 'above');
    expect(p.anchor).toBe('middle');
    expect(p.x).toBe(200);
    expect(p.box.y1).toBeLessThan(150 - 7);
  });

  it('flips to start-anchored near the left edge', () => {
    const p = placeLabel({ x: 30, y: 150, r: 7 }, 120, size, 'above');
    expect(p.anchor).toBe('start');
    expect(p.box.x0).toBeGreaterThanOrEqual(EDGE_PAD);
  });

  it('flips to end-anchored near the right edge', () => {
    const p = placeLabel({ x: 380, y: 150, r: 7 }, 120, size, 'above');
    expect(p.anchor).toBe('end');
    expect(p.box.x1).toBeLessThanOrEqual(400 - EDGE_PAD);
  });

  it('places below the node when asked', () => {
    const p = placeLabel({ x: 200, y: 40, r: 11 }, 60, size, 'below');
    expect(p.box.y0).toBeGreaterThan(40 + 11);
  });
});

describe('layoutLabels', () => {
  const size = { width: 400, height: 300 };
  const item = (id: number, x: number, y: number, priority: number, pinned = false): LabelItem => ({
    id,
    x,
    y,
    r: 7,
    text: 'Some concept',
    width: 72,
    priority,
    pinned
  });

  it('keeps every placed label inside the container', () => {
    const placed = layoutLabels(
      [item(1, 20, 20, 1), item(2, 390, 290, 1), item(3, 200, 150, 1)],
      [],
      size
    );
    expect(placed.size).toBe(3);
    for (const p of placed.values()) {
      expect(p.box.x0).toBeGreaterThanOrEqual(EDGE_PAD);
      expect(p.box.y0).toBeGreaterThanOrEqual(EDGE_PAD);
      expect(p.box.x1).toBeLessThanOrEqual(size.width - EDGE_PAD);
      expect(p.box.y1).toBeLessThanOrEqual(size.height - EDGE_PAD);
    }
  });

  it('drops a lower-priority label that would collide, but never a pinned one', () => {
    const placed = layoutLabels(
      [item(1, 200, 150, 1), item(2, 205, 150, 5), item(3, 202, 150, 0, true)],
      [],
      size
    );
    expect(placed.has(3)).toBe(true);
    expect(placed.size).toBeLessThan(3);
  });

  it('tries below before giving up', () => {
    const placed = layoutLabels([item(1, 200, 150, 2), item(2, 200, 160, 1)], [], size);
    expect(placed.size).toBe(2);
  });

  it('avoids covering other stars when it can', () => {
    // A star sits right where the "above" label would go; the label moves below instead.
    const placed = layoutLabels([item(1, 200, 150, 1)], [{ id: 9, x: 200, y: 128, r: 7 }], size);
    expect(placed.get(1)!.box.y0).toBeGreaterThan(150);
  });
});
