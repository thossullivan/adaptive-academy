<script lang="ts">
  import { onMount } from 'svelte';
  import {
    forceSimulation,
    forceManyBody,
    forceLink,
    forceCenter,
    forceCollide,
    type Simulation
  } from 'd3-force';
  import { levelColor, LEVEL_LABEL } from '$lib/utils';

  type Node = { id: number; name: string; level: string; loadBearing: boolean; hasAnchor: boolean };
  type Edge = { source: number; target: number };

  let {
    nodes = [],
    links = [],
    onselect = (_id: number) => {}
  }: { nodes?: Node[]; links?: Edge[]; onselect?: (id: number) => void } = $props();

  let w = $state(800);
  let h = $state(520);
  let hovered = $state<number | null>(null);
  let sim: Simulation<any, any> | null = null;

  // Mutable simulation nodes; `frame` bumps to push positions into the template each tick.
  type SimNode = Node & { x: number; y: number };
  let simNodes = $state<SimNode[]>([]);
  let simLinks = $state<{ source: any; target: any }[]>([]);

  function radius(n: Node) {
    return n.loadBearing ? 11 : 7;
  }

  function build() {
    if (sim) sim.stop();
    // Seed positions in a ring so the layout opens up nicely.
    const seeded = nodes.map((n, i) => {
      const a = (i / Math.max(1, nodes.length)) * Math.PI * 2;
      return { ...n, x: w / 2 + Math.cos(a) * 120, y: h / 2 + Math.sin(a) * 120 };
    });
    const byId = new Map(seeded.map((n) => [n.id, n]));
    simLinks = links
      .filter((l) => byId.has(l.source) && byId.has(l.target))
      .map((l) => ({ source: byId.get(l.source), target: byId.get(l.target) }));

    sim = forceSimulation(seeded as any)
      .force('charge', forceManyBody().strength(-340))
      .force('link', forceLink(simLinks).distance(96).strength(0.45))
      .force('center', forceCenter(w / 2, h / 2))
      .force('collide', forceCollide().radius((d: any) => radius(d) + 14))
      .alpha(1)
      .alphaDecay(0.028);

    sim.on('tick', () => {
      for (const n of seeded as SimNode[]) {
        n.x = Math.max(20, Math.min(w - 20, n.x));
        n.y = Math.max(20, Math.min(h - 20, n.y));
      }
      simNodes = [...(seeded as SimNode[])];
    });
  }

  onMount(() => {
    build();
    return () => sim?.stop();
  });

  // Rebuild when the data set changes.
  $effect(() => {
    nodes;
    links;
    if (sim) build();
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
</script>

<div class="relative h-[clamp(380px,60vh,640px)] w-full overflow-hidden rounded-[var(--radius-lg)] border border-border bg-[radial-gradient(120%_100%_at_30%_0%,color-mix(in_oklab,var(--info)_7%,transparent),transparent_55%)]" bind:clientWidth={w} bind:clientHeight={h}>
  <!-- faint star field -->
  <svg class="absolute inset-0 size-full" aria-hidden="true">
    {#each Array(40) as _, i}
      <circle cx={(i * 97) % w} cy={(i * 53) % h} r={i % 7 === 0 ? 1.2 : 0.6} fill="var(--faint)" opacity={0.25} />
    {/each}
  </svg>

  <svg class="absolute inset-0 size-full" viewBox="0 0 {w} {h}">
    <!-- edges -->
    {#each simLinks as l}
      {@const s = posById.get(l.source.id)}
      {@const t = posById.get(l.target.id)}
      {#if s && t}
        {@const lit = hovered != null && (l.source.id === hovered || l.target.id === hovered)}
        <line
          x1={s.x}
          y1={s.y}
          x2={t.x}
          y2={t.y}
          stroke={lit ? 'var(--accent)' : 'var(--border-strong)'}
          stroke-width={lit ? 1.5 : 0.8}
          opacity={hovered == null ? 0.55 : lit ? 0.9 : 0.18}
        />
      {/if}
    {/each}

    <!-- nodes -->
    {#each simNodes as n (n.id)}
      {@const r = radius(n)}
      {@const c = levelColor(n.level)}
      {@const dim = hovered != null && !isConnected(n.id)}
      <g
        transform="translate({n.x},{n.y})"
        class="cursor-pointer transition-opacity"
        style:opacity={dim ? 0.3 : 1}
        role="button"
        tabindex="0"
        onmouseenter={() => (hovered = n.id)}
        onmouseleave={() => (hovered = null)}
        onclick={() => onselect(n.id)}
        onkeydown={(e) => e.key === 'Enter' && onselect(n.id)}
      >
        <!-- glow -->
        <circle r={r + 8} fill={c} opacity={hovered === n.id ? 0.28 : 0.14} />
        <circle r={r} fill={c} stroke="var(--bg)" stroke-width="1.5" />
        {#if n.loadBearing}
          <circle r={r + 3.5} fill="none" stroke={c} stroke-width="1" opacity="0.6" />
        {/if}
        {#if n.loadBearing || hovered === n.id}
          <text
            y={-r - 9}
            text-anchor="middle"
            class="pointer-events-none select-none"
            font-size="11"
            fill="var(--fg)"
            style="font-family: var(--font-sans); paint-order: stroke; stroke: var(--bg); stroke-width: 3px;"
          >{n.name}</text>
        {/if}
      </g>
    {/each}
  </svg>

  <!-- legend -->
  <div class="absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-[var(--radius-sm)] border border-border bg-[color-mix(in_oklab,var(--surface)_70%,transparent)] px-3 py-2 backdrop-blur">
    {#each ['high', 'medium', 'low', 'unknown'] as lv}
      <span class="flex items-center gap-1.5 text-[0.7rem] text-muted">
        <span class="size-2 rounded-full" style:background={levelColor(lv)}></span>{LEVEL_LABEL[lv]}
      </span>
    {/each}
    <span class="flex items-center gap-1.5 text-[0.7rem] text-faint">◯ load-bearing</span>
  </div>

  {#if !nodes.length}
    <div class="absolute inset-0 grid place-items-center">
      <span class="text-sm text-faint">No concepts to map yet.</span>
    </div>
  {/if}
</div>
