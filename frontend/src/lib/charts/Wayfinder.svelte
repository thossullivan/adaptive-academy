<script lang="ts">
  import { Badge, Markdown } from '$lib/ui';

  type WayPhase = {
    id: number;
    position: number;
    title: string;
    est_hours: string;
    flags: string[];
    done: number;
    total: number;
    status: 'traversed' | 'current' | 'ahead';
    deliverable: { kind: string; text: string } | null;
  };

  let {
    goal = '',
    phases = [],
    nextItem = null,
    reached = false,
    topicId
  }: {
    goal?: string;
    phases?: WayPhase[]; // ascending: Phase 1 first, descending toward the North Star
    nextItem?: { text: string; phaseTitle: string } | null;
    reached?: boolean;
    topicId: number;
  } = $props();

  const starColor = (s: string) =>
    s === 'traversed' ? 'var(--accent)' : s === 'current' ? 'var(--accent-bright)' : 'var(--faint)';

  const SOLID = 'background: linear-gradient(var(--accent), color-mix(in oklab, var(--accent) 35%, transparent))';
  const DOTTED = 'background: repeating-linear-gradient(var(--border-strong) 0 3px, transparent 3px 7px)';
  // A leg of the course is charted (solid) once the phase above it is traversed.
  const leg = (s: string) => (s === 'traversed' ? SOLID : DOTTED);

  // Strip light inline markdown (**bold**, *em*, `code`) for clean single-line display.
  const plain = (t: string) => t.replace(/[*`_]/g, '').trim();
</script>

<div class="relative overflow-hidden rounded-[var(--radius-lg)] border border-border bg-[radial-gradient(120%_90%_at_50%_110%,color-mix(in_oklab,var(--accent)_9%,transparent),transparent_55%)] px-5 py-8 md:px-8">
  <!-- starfield -->
  <svg class="pointer-events-none absolute inset-0 size-full opacity-40" aria-hidden="true">
    {#each Array(60) as _, i}
      <circle cx={`${(i * 61) % 100}%`} cy={`${(i * 37) % 100}%`} r={i % 9 === 0 ? 1.1 : 0.5} fill="var(--faint)" />
    {/each}
  </svg>

  <div class="relative mx-auto max-w-2xl">
    <!-- Cast off (start of the voyage) -->
    <div class="flex gap-4 md:gap-5">
      <div class="relative flex w-10 shrink-0 flex-col items-center">
        <div class="z-10 grid size-10 place-items-center"><span class="size-2.5 rounded-full bg-faint"></span></div>
        <div class="w-px grow" style={phases.length && phases[0].status === 'traversed' ? SOLID : DOTTED}></div>
      </div>
      <div class="flex-1 pb-8 pt-2.5"><span class="eyebrow">cast off · your voyage begins</span></div>
    </div>

    {#if !phases.length && !reached}
      <p class="pb-8 text-center text-sm text-faint">No waypoints charted yet — generate a phased track to plot the voyage.</p>
    {/if}

    <!-- Waypoints, ascending (Phase 1 → Phase N) -->
    {#each phases as p, i (p.id)}
      {@const pctDone = p.total ? Math.round((p.done / p.total) * 100) : 0}
      <div class="relative flex gap-4 md:gap-5">
        <!-- gutter: star + downward course leg -->
        <div class="relative flex w-10 shrink-0 flex-col items-center">
          <div class="relative z-10 grid size-10 place-items-center">
            {#if p.status === 'current'}
              <span class="absolute inline-flex size-9 animate-ping rounded-full opacity-60" style="background: color-mix(in oklab, var(--accent) 40%, transparent)"></span>
            {/if}
            <svg viewBox="0 0 24 24" class={p.status === 'current' ? 'relative size-9' : 'relative size-6'}
                 fill={p.status === 'ahead' ? 'none' : starColor(p.status)}
                 stroke={starColor(p.status)} stroke-width={p.status === 'ahead' ? 1.5 : 0}>
              <path d="M12 2l1.6 7.4L21 11l-7.4 1.6L12 20l-1.6-7.4L3 11l7.4-1.6z" />
            </svg>
            {#if p.status === 'traversed'}
              <svg viewBox="0 0 24 24" class="absolute size-3 text-bg" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12l4 4 10-10" stroke-linecap="round" stroke-linejoin="round" /></svg>
            {/if}
          </div>
          <!-- leg toward the next stop (always present — it continues to the North Star) -->
          <div class="w-px grow" style={leg(p.status)}></div>
        </div>

        <!-- waypoint card -->
        <div class="min-w-0 flex-1 pb-8">
          <div class="rounded-[var(--radius-md)] border p-4 transition-colors {p.status === 'current' ? 'border-[color-mix(in_oklab,var(--accent)_45%,transparent)] bg-accent-wash' : p.status === 'ahead' ? 'border-border bg-surface/60' : 'border-border bg-surface'}">
            <div class="flex flex-col gap-1 md:flex-row md:items-start md:justify-between md:gap-3">
              <div class="min-w-0">
                <div class="flex items-center gap-2">
                  <span class="eyebrow !text-[0.55rem]">Phase {p.position + 1}</span>
                  {#if p.status === 'current'}<Badge tone="accent" dot>you are here</Badge>{/if}
                  {#if p.status === 'traversed'}<Badge tone="success" mono>charted</Badge>{/if}
                </div>
                <!-- The whole title, wrapped: a waypoint's name is the thing you steer by, so never clip it. -->
                <h3 class="mt-1 text-base text-balance break-words {p.status === 'ahead' ? 'text-fg-dim' : 'text-fg'}" data-testid="waypoint-title">{p.title}</h3>
              </div>
              <div class="flex items-baseline gap-2 md:block md:shrink-0 md:text-right">
                <div class="nums text-sm text-muted">{p.done}/{p.total}</div>
                {#if p.est_hours}<div class="eyebrow !text-[0.55rem]">{p.est_hours}</div>{/if}
              </div>
            </div>

            <div class="mt-3 h-1 overflow-hidden rounded-full bg-surface-3">
              <div class="h-full rounded-full transition-all" style:width="{pctDone}%" style:background={p.status === 'ahead' ? 'var(--faint)' : 'var(--accent)'}></div>
            </div>

            {#if p.status === 'current' && nextItem}
              <a href="/topics/{topicId}/tutor" title={plain(nextItem.text)} class="mt-3 flex items-start gap-2 rounded-[var(--radius-sm)] border border-[color-mix(in_oklab,var(--accent)_30%,transparent)] bg-surface-2 px-3 py-2 text-sm transition-colors hover:border-accent">
                <span class="shrink-0 text-accent">↓ steer toward</span>
                <span class="line-clamp-2 min-w-0 flex-1 break-words text-fg-dim">{plain(nextItem.text)}</span>
              </a>
            {/if}

            {#if p.deliverable}
              <div class="mt-3 flex items-start gap-2 text-xs">
                <span class="shrink-0 text-accent-dim">⚓ landfall</span>
                <Markdown text={p.deliverable.text} class="min-w-0 text-muted" />
              </div>
            {/if}

            {#if p.flags.length}
              <div class="mt-2 flex flex-wrap gap-1">
                {#each p.flags as f}<Badge tone="neutral" mono>{f}</Badge>{/each}
              </div>
            {/if}
          </div>
        </div>
      </div>
    {/each}

    <!-- North Star — the destination at journey's end -->
    <div class="flex gap-4 md:gap-5">
      <div class="flex w-10 shrink-0 justify-center">
        <div class="relative grid size-12 place-items-center">
          <div class="absolute inset-0 rounded-full" style="background: radial-gradient(circle, color-mix(in oklab, var(--accent) {reached ? 55 : 38}%, transparent), transparent 70%)"></div>
          <svg viewBox="0 0 24 24" class="relative size-11" fill="var(--accent-bright)">
            <path d="M12 1l1.8 8.2L22 11l-8.2 1.8L12 21l-1.8-8.2L2 11l8.2-1.8z" />
          </svg>
        </div>
      </div>
      <div class="flex-1 pt-1">
        <div class="eyebrow !text-accent">{reached ? "you've arrived" : 'your north star'}</div>
        <p class="mt-1 font-display text-lg leading-snug text-fg">{goal || 'Chart a goal to steer by'}</p>
        {#if reached}
          <p class="mt-1 text-sm text-success">Every waypoint charted — the voyage to mastery is complete. 🜨</p>
        {:else}
          <p class="mt-1 text-xs text-faint">the destination you're steering toward</p>
        {/if}
      </div>
    </div>
  </div>
</div>
