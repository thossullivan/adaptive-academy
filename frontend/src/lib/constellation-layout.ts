// Pure layout logic for the Concept Constellation: force parameters derived from the
// container's size and node count, the drawable bounds, and label fitting/placement.
// Kept free of Svelte/DOM so it is unit-testable (and the simulation can run headless).
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationNodeDatum
} from 'd3-force';

export type Size = { width: number; height: number };
export type Rect = { x0: number; y0: number; x1: number; y1: number };

export const MAX_RADIUS = 11;
/** Soft glow ring drawn around each star (radius + GLOW). */
export const GLOW = 8;
/** Minimum gap between anything drawn and the container wall. */
export const EDGE_PAD = 6;
export const LABEL_FONT_SIZE = 11;
/** Gap between a star's edge and its label box. */
export const LABEL_OFFSET = 5;
/** Label box extents around the text baseline (11px sans, generous). */
export const LABEL_ASCENT = 12;
export const LABEL_DESCENT = 4;
export const LABEL_HEIGHT = LABEL_ASCENT + LABEL_DESCENT;
/** Longest label we draw before truncating with an ellipsis (wide containers). */
export const LABEL_MAX_WIDTH = 240;
/** Floor for the width-proportional cap, so mid-size boxes still get readable labels. */
export const LABEL_MIN_WIDTH = 120;

export function nodeRadius(loadBearing: boolean): number {
  return loadBearing ? MAX_RADIUS : 7;
}

/** A container is laid out only once it has a real, measured size. */
export function hasRealSize(size: Size | null | undefined): size is Size {
  return !!size && size.width >= 40 && size.height >= 40;
}

/** True when the container changed enough to warrant a re-layout. */
export function sizeChanged(prev: Size | null, next: Size, threshold = 2): boolean {
  if (!prev) return true;
  return Math.abs(prev.width - next.width) > threshold || Math.abs(prev.height - next.height) > threshold;
}

/**
 * Where star centres may sit. Horizontally: radius + glow + pad (labels flip their anchor
 * at the edges so they need no extra room). Vertically: radius + a full label line, so a
 * star at the top or bottom still has room for its label on the inner side.
 */
export function layoutBounds(size: Size): Rect {
  const mx = MAX_RADIUS + GLOW + EDGE_PAD + 4;
  const my = MAX_RADIUS + LABEL_OFFSET + LABEL_HEIGHT + EDGE_PAD;
  let { x0, x1, y0, y1 } = { x0: mx, x1: size.width - mx, y0: my, y1: size.height - my };
  if (x1 < x0) x0 = x1 = size.width / 2;
  if (y1 < y0) y0 = y1 = size.height / 2;
  return { x0, y0, x1, y1 };
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export type ForceParams = {
  linkDistance: number;
  linkStrength: number;
  charge: number;
  chargeDistanceMax: number;
  gravityX: number;
  gravityY: number;
  collidePad: number;
};

/** Force strengths scaled to the area each node gets, and to the box's aspect ratio. */
export function forceParams(size: Size, count: number): ForceParams {
  const b = layoutBounds(size);
  const uw = Math.max(1, b.x1 - b.x0);
  const uh = Math.max(1, b.y1 - b.y0);
  const cell = Math.sqrt((uw * uh) / Math.max(1, count));
  const base = 0.05;
  // Square-root-ish so the cloud follows the box's shape without flattening into a band.
  const aspect = Math.pow(uw / uh, 0.6);
  return {
    linkDistance: clamp(cell * 0.7, 22, 120),
    linkStrength: 0.35,
    charge: -clamp(cell * cell * 0.035, 18, 700),
    chargeDistanceMax: Math.max(cell * 4, 120),
    // Pull harder along the short axis so the cloud takes the box's shape.
    gravityX: clamp(base / aspect, 0.02, 0.35),
    gravityY: clamp(base * aspect, 0.02, 0.35),
    collidePad: clamp(cell * 0.14, 4, 14)
  };
}

export type LayoutNode = SimulationNodeDatum & { id: number; r: number };
export type LayoutLink = { source: number | LayoutNode; target: number | LayoutNode };

/** Spring nodes back inside the bounds (a soft wall, applied before the hard clamp). */
function forceContain<N extends LayoutNode>(bounds: () => Rect, k = 0.25) {
  let nodes: N[] = [];
  function force() {
    const b = bounds();
    for (const n of nodes) {
      if (n.x! < b.x0) n.vx! += (b.x0 - n.x!) * k;
      else if (n.x! > b.x1) n.vx! += (b.x1 - n.x!) * k;
      if (n.y! < b.y0) n.vy! += (b.y0 - n.y!) * k;
      else if (n.y! > b.y1) n.vy! += (b.y1 - n.y!) * k;
    }
  }
  force.initialize = (ns: N[]) => (nodes = ns);
  return force;
}

function insetRect(r: Rect, frac: number, max: number): Rect {
  const ix = Math.min(max, (r.x1 - r.x0) * frac);
  const iy = Math.min(max, (r.y1 - r.y0) * frac);
  return { x0: r.x0 + ix, x1: r.x1 - ix, y0: r.y0 + iy, y1: r.y1 - iy };
}

/** Safety net only: the forces should already keep nodes in bounds. */
export function clampToBounds(nodes: LayoutNode[], size: Size) {
  const b = layoutBounds(size);
  for (const n of nodes) {
    if (n.x! < b.x0 || n.x! > b.x1) {
      n.x = clamp(n.x!, b.x0, b.x1);
      n.vx = 0;
    }
    if (n.y! < b.y0 || n.y! > b.y1) {
      n.y = clamp(n.y!, b.y0, b.y1);
      n.vy = 0;
    }
  }
}

/** Seed unpositioned nodes on a sunflower spiral filling the box (deterministic). */
function seedPositions(nodes: LayoutNode[], size: Size) {
  const b = layoutBounds(size);
  const cx = (b.x0 + b.x1) / 2;
  const cy = (b.y0 + b.y1) / 2;
  const rx = ((b.x1 - b.x0) / 2) * 0.75;
  const ry = ((b.y1 - b.y0) / 2) * 0.75;
  const golden = Math.PI * (3 - Math.sqrt(5));
  nodes.forEach((n, i) => {
    if (n.x != null && n.y != null && Number.isFinite(n.x) && Number.isFinite(n.y)) return;
    const t = Math.sqrt((i + 0.5) / nodes.length);
    n.x = cx + Math.cos(i * golden) * rx * t;
    n.y = cy + Math.sin(i * golden) * ry * t;
  });
}

/** Point an existing simulation's forces at a (new) container size. */
export function applyForces<N extends LayoutNode>(
  sim: Simulation<N, undefined>,
  links: LayoutLink[],
  size: Size
) {
  const p = forceParams(size, sim.nodes().length);
  const b = layoutBounds(size);
  const cx = (b.x0 + b.x1) / 2;
  const cy = (b.y0 + b.y1) / 2;
  sim
    .force('charge', forceManyBody<N>().strength(p.charge).distanceMax(p.chargeDistanceMax))
    .force(
      'link',
      forceLink<N, any>(links)
        .id((d) => d.id)
        .distance(p.linkDistance)
        .strength(p.linkStrength)
    )
    .force('x', forceX<N>(cx).strength(p.gravityX))
    .force('y', forceY<N>(cy).strength(p.gravityY))
    .force('collide', forceCollide<N>().radius((d) => d.r + p.collidePad))
    // The soft wall sits a little inside the hard bounds, so stars pushed outward come to
    // rest short of the safety clamp rather than lined up against it.
    .force('contain', forceContain<N>(() => insetRect(b, 0.06, 14)));
}

/** A configured, *stopped* simulation; the caller animates it or ticks it to completion. */
export function createLayout<N extends LayoutNode>(
  nodes: N[],
  links: LayoutLink[],
  size: Size
): Simulation<N, undefined> {
  seedPositions(nodes, size);
  const sim = forceSimulation<N>(nodes).stop().alpha(1).alphaDecay(0.03);
  applyForces(sim, links, size);
  return sim;
}

/** Tick a simulation to rest synchronously (reduced motion / tests). */
export function settle<N extends LayoutNode>(sim: Simulation<N, undefined>, size: Size) {
  const nodes = sim.nodes();
  // Same number of ticks d3 would run before firing `end`.
  const n = Math.ceil(Math.log(sim.alphaMin() / sim.alpha()) / Math.log(1 - sim.alphaDecay()));
  for (let i = 0; i < Math.max(0, n); i++) {
    sim.tick();
    clampToBounds(nodes, size);
  }
}

/** Lay out nodes headlessly to their resting positions. */
export function runLayout<N extends LayoutNode>(nodes: N[], links: LayoutLink[], size: Size): N[] {
  const sim = createLayout(nodes, links, size);
  settle(sim, size);
  return nodes;
}

/** Map positions proportionally from one container size to another. */
export function rescalePositions(nodes: { x?: number; y?: number }[], from: Size, to: Size) {
  const sx = to.width / Math.max(1, from.width);
  const sy = to.height / Math.max(1, from.height);
  for (const n of nodes) {
    if (n.x != null) n.x *= sx;
    if (n.y != null) n.y *= sy;
  }
}

// ---- labels -------------------------------------------------------------------------

export type Measure = (text: string) => number;

/** Fit a label into `maxWidth`, truncating with an ellipsis when it does not fit. */
export function fitLabel(
  name: string,
  maxWidth: number,
  measure: Measure
): { text: string; width: number; truncated: boolean } {
  const full = measure(name);
  if (full <= maxWidth) return { text: name, width: full, truncated: false };
  let lo = 0;
  let hi = name.length - 1;
  let best: { text: string; width: number } | null = null;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const text = name.slice(0, mid).trimEnd() + '…';
    const width = measure(text);
    if (width <= maxWidth && mid > 0) {
      best = { text, width };
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return best ? { ...best, truncated: true } : { text: '', width: 0, truncated: true };
}

/** Widest label we allow: ~30% of the box, never wider than the box itself. */
export function labelMaxWidth(size: Size): number {
  const proportional = Math.min(LABEL_MAX_WIDTH, Math.max(LABEL_MIN_WIDTH, size.width * 0.3));
  return Math.max(0, Math.min(proportional, size.width - 2 * EDGE_PAD));
}

export type Anchor = 'start' | 'middle' | 'end';
export type LabelPlacement = { x: number; y: number; anchor: Anchor; box: Rect };

/** Place a label of `width` above/below a star, flipping its anchor near the side walls. */
export function placeLabel(
  node: { x: number; y: number; r: number },
  width: number,
  size: Size,
  side: 'above' | 'below'
): LabelPlacement {
  const half = width / 2;
  const left = EDGE_PAD;
  const right = size.width - EDGE_PAD;
  let anchor: Anchor;
  let x: number;
  let x0: number;
  if (node.x - half >= left && node.x + half <= right) {
    anchor = 'middle';
    x = node.x;
    x0 = x - half;
  } else if (node.x - half < left) {
    anchor = 'start';
    x = clamp(node.x - node.r, left, Math.max(left, right - width));
    x0 = x;
  } else {
    anchor = 'end';
    x = clamp(node.x + node.r, Math.min(right, left + width), right);
    x0 = x - width;
  }
  let top =
    side === 'above'
      ? node.y - node.r - LABEL_OFFSET - LABEL_HEIGHT
      : node.y + node.r + LABEL_OFFSET;
  top = clamp(top, EDGE_PAD, Math.max(EDGE_PAD, size.height - EDGE_PAD - LABEL_HEIGHT));
  return {
    x,
    y: top + LABEL_ASCENT,
    anchor,
    box: { x0, y0: top, x1: x0 + width, y1: top + LABEL_HEIGHT }
  };
}

export type LabelItem = {
  id: number;
  x: number;
  y: number;
  r: number;
  text: string;
  width: number;
  /** Higher places first and so wins collisions. */
  priority: number;
  /** Always shown (hovered / selected), even if it overlaps. */
  pinned?: boolean;
};

export type Circle = { id: number; x: number; y: number; r: number };

const overlaps = (a: Rect, b: Rect, gap = 2) =>
  a.x0 < b.x1 + gap && b.x0 < a.x1 + gap && a.y0 < b.y1 + gap && b.y0 < a.y1 + gap;

const hitsCircle = (a: Rect, c: Circle) => {
  const nx = clamp(c.x, a.x0, a.x1);
  const ny = clamp(c.y, a.y0, a.y1);
  return Math.hypot(c.x - nx, c.y - ny) < c.r + 1;
};

/**
 * Greedy label placement by priority: each label tries above, then below its star, and takes
 * the first spot that clears placed labels (and, preferably, other stars). Labels that find no
 * clear spot are dropped unless pinned — density degrades to "fewer labels", never a pile-up.
 */
export function layoutLabels(items: LabelItem[], others: Circle[], size: Size): Map<number, LabelPlacement> {
  const placed = new Map<number, LabelPlacement>();
  const boxes: Rect[] = [];
  const stars: Circle[] = [...others, ...items.map(({ id, x, y, r }) => ({ id, x, y, r }))];
  const ordered = [...items].sort(
    (a, b) => Number(!!b.pinned) - Number(!!a.pinned) || b.priority - a.priority
  );
  for (const it of ordered) {
    if (!it.text) continue;
    const options = (['above', 'below'] as const).map((side) => placeLabel(it, it.width, size, side));
    const clearOfLabels = options.filter((o) => !boxes.some((b) => overlaps(o.box, b)));
    const clearOfStars = clearOfLabels.filter(
      (o) => !stars.some((s) => s.id !== it.id && hitsCircle(o.box, s))
    );
    const pick = clearOfStars[0] ?? clearOfLabels[0] ?? (it.pinned ? options[0] : undefined);
    if (!pick) continue;
    placed.set(it.id, pick);
    boxes.push(pick.box);
  }
  return placed;
}
