<script lang="ts">
  import { untrack } from 'svelte';
  import type { Simulation } from 'd3-force';
  import { VERDICT_COLOR, VERDICT_LABEL, type Verdict } from '$lib/competence';
  import type { GraphLink } from '$lib/types';
  import {
    LABEL_FONT_SIZE,
    applyForces,
    clampToBounds,
    createLayout,
    fitLabel,
    hasRealSize,
    labelMaxWidth,
    layoutLabels,
    nodeRadius,
    rescalePositions,
    settle,
    sizeChanged,
    type LabelItem,
    type LayoutNode,
    type Measure,
    type Size
  } from '$lib/constellation-layout';

  type Node = { id: number; name: string; verdict: Verdict; loadBearing: boolean; hasAnchor: boolean };

  let {
    nodes = [],
    links = [],
    selected = null,
    highlighted = [],
    onselect = (_id: number) => {}
  }: {
    nodes?: Node[];
    links?: GraphLink[];
    selected?: number | null;
    highlighted?: number[];
    onselect?: (id: number) => void;
  } = $props();

  type SimNode = Node & LayoutNode & { x: number; y: number };
  type SimLink = { source: SimNode; target: SimNode; kind: GraphLink['kind']; weight: number };

  let rootEl: HTMLDivElement | undefined = $state();
  let canvasEl: HTMLDivElement | undefined = $state();
  /** The drawing area's measured size (follows the container live). */
  let size = $state<Size>({ width: 0, height: 0 });
  /** The size the current layout was computed for — the SVG's coordinate space. */
  let layoutSize = $state<Size | null>(null);
  let settled = $state(false);
  // Counts simulation runs; exposed so tests can prove a settled graph does not re-layout.
  let layoutRuns = $state(0);
  let hovered = $state<number | null>(null);

  let sim: Simulation<SimNode, undefined> | null = null;
  let live: SimNode[] = [];
  let liveLinks: SimLink[] = [];
  // Render snapshots: fresh objects each frame so keyed blocks see the new positions.
  let simNodes = $state.raw<SimNode[]>([]);
  let simLinks = $state.raw<SimLink[]>([]);

  const LEGEND: Verdict[] = ['solid', 'verified', 'unverified', 'shaky', 'untested'];
  const RESIZE_DEBOUNCE_MS = 150;

  function reducedMotion(): boolean {
    return typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function publish() {
    simNodes = live.map((n) => ({ ...n }));
  }

  /** Run (or re-run) the simulation for container size `s`, animated unless reduced motion. */
  function run(s: Size) {
    const current = sim;
    if (!current) return;
    settled = false;
    layoutRuns += 1;
    layoutSize = { ...s };
    if (reducedMotion()) {
      // Settle off-screen and render only the final state.
      current.on('tick', null).on('end', null).stop();
      settle(current, s);
      publish();
      settled = true;
      return;
    }
    current
      .on('tick', () => {
        clampToBounds(live, s);
        publish();
      })
      .on('end', () => {
        if (sim === current) settled = true;
      })
      .restart();
  }

  function build() {
    sim?.stop();
    sim = null;
    live = [];
    liveLinks = [];
    simNodes = [];
    simLinks = [];
    settled = false;
    // Lay out only once the container has a real size; the ResizeObserver calls back here.
    if (!hasRealSize(size)) return;
    if (!nodes.length) {
      layoutSize = { ...size };
      settled = true;
      return;
    }
    live = nodes.map((n) => ({ ...n, r: nodeRadius(n.loadBearing) }) as SimNode);
    const byId = new Map(live.map((n) => [n.id, n]));
    liveLinks = links
      .filter((l) => byId.has(l.source) && byId.has(l.target))
      .map((l) => ({
        source: byId.get(l.source)!,
        target: byId.get(l.target)!,
        kind: l.kind,
        weight: l.weight
      }));
    simLinks = liveLinks;
    sim = createLayout(live, liveLinks, size);
    run({ ...size });
  }

  /** Container resized: carry the layout over proportionally and let it re-settle. */
  function relayout() {
    if (!hasRealSize(size)) return;
    if (!sim || !layoutSize) return build();
    if (!sizeChanged(layoutSize, size)) return;
    const s = { ...size };
    sim.stop();
    rescalePositions(live, layoutSize, s);
    applyForces(sim, liveLinks, s);
    sim.alpha(0.5);
    run(s);
  }

  // Rebuild ONLY when the data set changes. `build()` reads the measured size via untrack so
  // it never becomes an effect dependency — size changes go through the debounced
  // ResizeObserver path below instead (re-running this on every measure was a captive page).
  $effect(() => {
    nodes;
    links;
    untrack(() => build());
    return () => sim?.stop();
  });

  // Measure the drawing area. The canvas is sized by CSS alone (the SVGs are absolutely
  // positioned and the legend sits outside it), so nothing we render can feed back into it.
  $effect(() => {
    const el = canvasEl;
    if (!el || typeof ResizeObserver === 'undefined') return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ro = new ResizeObserver((entries) => {
      const r = entries[entries.length - 1].contentRect;
      size = { width: r.width, height: r.height };
      clearTimeout(timer);
      // First real measurement: lay out immediately. Later changes: debounced.
      if (!sim && !layoutSize) build();
      else timer = setTimeout(relayout, RESIZE_DEBOUNCE_MS);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      clearTimeout(timer);
    };
  });

  // Text metrics for label fitting; re-measured once web fonts have loaded.
  let fontsLoaded = $state(0);
  $effect(() => {
    if (typeof document === 'undefined' || !document.fonts) return;
    let alive = true;
    document.fonts.ready.then(() => alive && fontsLoaded++);
    return () => (alive = false);
  });

  const measure = $derived.by<Measure>(() => {
    fontsLoaded;
    const el = rootEl;
    const ctx = el && typeof document !== 'undefined' ? document.createElement('canvas').getContext('2d') : null;
    if (!el || !ctx) return (t) => t.length * 6.8;
    const style = getComputedStyle(el);
    const family = style.getPropertyValue('--font-sans').trim() || style.fontFamily;
    ctx.font = `${LABEL_FONT_SIZE}px ${family}`;
    // Small safety factor: SVG text and canvas metrics can differ by a pixel or two.
    return (t) => ctx.measureText(t).width * 1.04 + 1;
  });

  const fitted = $derived.by(() => {
    const s = layoutSize;
    if (!s) return new Map<number, ReturnType<typeof fitLabel>>();
    const max = labelMaxWidth(s);
    return new Map(nodes.map((n) => [n.id, fitLabel(n.name, max, measure)]));
  });

  const degree = $derived.by(() => {
    const d = new Map<number, number>();
    for (const l of links) {
      d.set(l.source, (d.get(l.source) ?? 0) + 1);
      d.set(l.target, (d.get(l.target) ?? 0) + 1);
    }
    return d;
  });

  function isConnected(id: number): boolean {
    if (hovered == null) return false;
    if (id === hovered) return true;
    return links.some(
      (l) =>
        (l.source === hovered && l.target === id) || (l.target === hovered && l.source === id)
    );
  }

  const posById = $derived(new Map(simNodes.map((n) => [n.id, n])));
  const highlightedSet = $derived(new Set(highlighted));
  const selectedSet = $derived(new Set(selected == null ? highlighted : [selected, ...highlighted]));

  // Labels: load-bearing stars by default, plus whatever is hovered, selected or highlighted
  // (every star when the graph is small). Placed greedily by priority so dense graphs drop
  // the least important labels instead of piling them up.
  const labels = $derived.by(() => {
    const s = layoutSize;
    if (!s || !simNodes.length) return [];
    const showAll = simNodes.length <= 12;
    const items: LabelItem[] = [];
    for (const n of simNodes) {
      const fit = fitted.get(n.id);
      if (!fit || !fit.text) continue;
      const pinned = n.id === hovered || n.id === selected;
      const lit = highlightedSet.has(n.id);
      if (!(pinned || lit || n.loadBearing || showAll)) continue;
      items.push({
        id: n.id,
        x: n.x,
        y: n.y,
        r: n.r,
        text: fit.text,
        width: fit.width,
        pinned,
        priority: (n.id === hovered ? 1000 : 0) + (lit ? 50 : 0) + (n.loadBearing ? 10 : 0) + (degree.get(n.id) ?? 0) * 0.1
      });
    }
    const placed = layoutLabels(items, simNodes.map(({ id, x, y, r }) => ({ id, x, y, r })), s);
    return items
      .filter((it) => placed.has(it.id))
      .map((it) => ({ ...it, place: placed.get(it.id)! }));
  });

  function dimmed(id: number): boolean {
    return selected != null ? id !== selected && !highlightedSet.has(id) : hovered != null && !isConnected(id);
  }

  const vb = $derived(layoutSize ?? { width: Math.max(1, size.width), height: Math.max(1, size.height) });
</script>

<div
  bind:this={rootEl}
  data-testid="constellation"
  data-settled={settled ? 'true' : 'false'}
  data-layout-w={layoutSize?.width ?? 0}
  data-layout-h={layoutSize?.height ?? 0}
  data-layout-runs={layoutRuns}
  class="relative flex h-[clamp(380px,60vh,640px)] w-full flex-col overflow-hidden rounded-[var(--radius-lg)] border border-border bg-[radial-gradient(120%_100%_at_30%_0%,color-mix(in_oklab,var(--info)_7%,transparent),transparent_55%)]"
>
  <div bind:this={canvasEl} data-testid="constellation-canvas" class="relative min-h-0 w-full flex-1">
    <!-- faint star field -->
    <svg class="absolute inset-0 size-full" aria-hidden="true">
      {#each Array(40) as _, i}
        <circle cx={(i * 97) % Math.max(1, size.width)} cy={(i * 53) % Math.max(1, size.height)} r={i % 7 === 0 ? 1.2 : 0.6} fill="var(--faint)" opacity={0.25} />
      {/each}
    </svg>

    <svg class="absolute inset-0 size-full" viewBox="0 0 {vb.width} {vb.height}">
      <!-- edges -->
      {#each simLinks as l}
        {@const s = posById.get(l.source.id)}
        {@const t = posById.get(l.target.id)}
        {#if s && t}
          {@const lit = selected != null
            ? selectedSet.has(l.source.id) && selectedSet.has(l.target.id)
            : hovered != null && (l.source.id === hovered || l.target.id === hovered)}
          <line
            x1={s.x}
            y1={s.y}
            x2={t.x}
            y2={t.y}
            stroke={lit ? 'var(--accent)' : l.kind === 'related' ? 'var(--info)' : 'var(--border-strong)'}
            stroke-width={lit ? 1.5 : 0.8}
            stroke-dasharray={l.kind === 'related' ? '5 4' : l.kind === 'alias' ? '2 4' : undefined}
            opacity={selected == null && hovered == null ? 0.55 : lit ? 0.9 : 0.18}
          />
        {/if}
      {/each}

      <!-- nodes -->
      {#each simNodes as n (n.id)}
        {@const r = n.r}
        {@const c = VERDICT_COLOR[n.verdict]}
        <g
          transform="translate({n.x},{n.y})"
          class="cursor-pointer transition-opacity"
          style:opacity={dimmed(n.id) ? 0.3 : 1}
          role="button"
          tabindex="0"
          aria-label={n.name}
          onmouseenter={() => (hovered = n.id)}
          onmouseleave={() => (hovered = null)}
          onclick={() => onselect(n.id)}
          onkeydown={(e) => e.key === 'Enter' && onselect(n.id)}
        >
          <title>{n.name}</title>
          <!-- glow (decorative: never steals the pointer from a neighbouring star) -->
          <circle r={r + 8} fill={c} opacity={hovered === n.id ? 0.28 : 0.14} pointer-events="none" />
          <!-- hit target: r + 4 stays clear of neighbours (collision keeps stars r + 4 apart) -->
          <circle r={r + 4} fill="transparent" />
          <circle data-testid="constellation-node" data-node-id={n.id} {r} fill={c} stroke="var(--bg)" stroke-width="1.5" />
          {#if n.id === selected || highlightedSet.has(n.id)}
            <circle r={r + 6} fill="none" stroke="var(--accent)" stroke-width={n.id === selected ? 2 : 1.25} opacity="0.9" pointer-events="none" />
          {/if}
          {#if n.loadBearing}
            <circle r={r + 3.5} fill="none" stroke={c} stroke-width="1" opacity="0.6" pointer-events="none" />
          {/if}
        </g>
      {/each}

      <!-- labels: their own layer, above every star, placed to stay inside the box. They never
           take the pointer (a label can sit over a neighbouring star), so a truncated name's full
           text comes from its star's <title> and aria-label. -->
      {#each labels as l (l.id)}
        <text
          data-testid="constellation-label"
          data-node-id={l.id}
          x={l.place.x}
          y={l.place.y}
          text-anchor={l.place.anchor}
          class="pointer-events-none select-none transition-opacity"
          style:opacity={dimmed(l.id) ? 0.3 : 1}
          font-size={LABEL_FONT_SIZE}
          fill="var(--fg)"
          style="font-family: var(--font-sans); paint-order: stroke; stroke: var(--bg); stroke-width: 3px;"
        >{l.text}</text>
      {/each}
    </svg>

    {#if !nodes.length}
      <div class="absolute inset-0 grid place-items-center">
        <span class="text-sm text-faint">No concepts to map yet.</span>
      </div>
    {/if}
  </div>

  <!-- legend: below the drawing area, so it can never sit on a star -->
  <div class="shrink-0 px-3 pb-3 pt-1">
    <div data-testid="constellation-legend" class="inline-flex flex-wrap gap-x-3 gap-y-1 rounded-[var(--radius-sm)] border border-border bg-[color-mix(in_oklab,var(--surface)_70%,transparent)] px-3 py-2 backdrop-blur">
      {#each LEGEND as v}
        <span class="flex items-center gap-1.5 text-[0.7rem] text-muted">
          <span class="size-2 rounded-full" style:background={VERDICT_COLOR[v]}></span>{VERDICT_LABEL[v]}
        </span>
      {/each}
      <span class="flex items-center gap-1.5 text-[0.7rem] text-faint">◯ load-bearing</span>
    </div>
  </div>
</div>
