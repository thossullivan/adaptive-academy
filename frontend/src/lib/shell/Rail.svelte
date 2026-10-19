<script module lang="ts">
  // The first-run "how a day works" hint. Module-level so the desktop rail and the phone
  // drawer's copy agree; the dismissal is remembered per browser (best effort).
  const HINT_KEY = 'aa.rail.dayHintDismissed';

  function readDismissed(): boolean {
    try {
      return localStorage.getItem(HINT_KEY) === '1';
    } catch {
      return false;
    }
  }

  const dayHint = $state({ dismissed: readDismissed() });

  function dismissDayHint() {
    dayHint.dismissed = true;
    try {
      localStorage.setItem(HINT_KEY, '1');
    } catch {
      /* storage blocked: hidden for this visit only */
    }
  }
</script>

<script lang="ts">
  import { page } from '$app/stores';
  import { topics } from '$lib/topics.svelte';
  import TopicSwitcher from './TopicSwitcher.svelte';
  import ThemeToggle from './ThemeToggle.svelte';
  import Icon from './Icon.svelte';
  import BrandMark from './BrandMark.svelte';
  import { cn } from '$lib/utils';

  // The same rail renders as the static desktop sidebar and inside the phone drawer
  // (see MobileNav); callers adjust only positioning/visibility through `class`. Rows are
  // compact at `md` and up so the whole rail fits a laptop screen, and touch-sized (40px)
  // below it, where only the drawer renders.
  let { class: className = '' }: { class?: string } = $props();

  const tid = $derived(topics.current?.id ?? null);

  type Nav = { label: string; icon: string; href: string; match: (p: string) => boolean };
  /** `pair`: two short links side by side on one row. */
  type Section = { label: string; items: Nav[]; pair?: boolean };

  // Cross-topic views; the only section shown before any topic exists (then on full rows).
  const allTopics = (pair: boolean): Section => ({
    label: 'All topics',
    pair,
    items: [
      { label: 'Fleet', icon: 'fleet', href: '/fleet', match: (p) => p === '/fleet' },
      { label: 'Programs', icon: 'map', href: '/programs', match: (p) => p.startsWith('/programs') }
    ]
  });

  // Where the daily loop starts, and the topic overview: first and slightly larger.
  const primary = $derived<Nav[]>(
    tid == null
      ? []
      : [
          { label: 'Today', icon: 'today', href: `/topics/${tid}/today`, match: (p) => p.endsWith('/today') },
          { label: 'Dashboard', icon: 'dashboard', href: '/', match: (p) => p === '/' }
        ]
  );

  // Grouped by what you are doing: learning, checking where you stand, or reading.
  const sections = $derived<Section[]>(
    tid == null
      ? [allTopics(false)]
      : [
          {
            label: 'Learn',
            items: [
              { label: 'Tutor', icon: 'tutor', href: `/topics/${tid}/tutor`, match: (p) => p.endsWith('/tutor') },
              { label: 'Practice', icon: 'practice', href: `/topics/${tid}/practice`, match: (p) => p.endsWith('/practice') },
              { label: 'Assess', icon: 'assess', href: `/topics/${tid}/assess`, match: (p) => p.endsWith('/assess') },
              { label: 'Teach', icon: 'teach', href: `/topics/${tid}/teach`, match: (p) => p.endsWith('/teach') }
            ]
          },
          {
            label: 'Map & progress',
            items: [
              { label: 'Track', icon: 'track', href: `/topics/${tid}/track`, match: (p) => p.endsWith('/track') },
              { label: 'Wayfinder', icon: 'wayfinder', href: `/topics/${tid}/wayfinder`, match: (p) => p.endsWith('/wayfinder') },
              { label: 'Constellation', icon: 'map', href: `/topics/${tid}/map`, match: (p) => p.endsWith('/map') },
              { label: 'Retention', icon: 'retention', href: `/topics/${tid}/retention`, match: (p) => p.endsWith('/retention') }
            ]
          },
          {
            label: 'Library',
            items: [
              { label: 'Sources', icon: 'sources', href: `/topics/${tid}/review`, match: (p) => p.endsWith('/review') },
              { label: 'Vault', icon: 'vault', href: `/topics/${tid}/vault`, match: (p) => p.endsWith('/vault') },
              { label: 'Story', icon: 'story', href: `/topics/${tid}/story`, match: (p) => p.endsWith('/story') }
            ]
          },
          allTopics(true)
        ]
  );

  // App-level utilities, pinned under the nav.
  const footer: Nav[] = [
    { label: 'Usage', icon: 'usage', href: '/usage', match: (p) => p === '/usage' },
    { label: 'Your data', icon: 'data', href: '/data', match: (p) => p === '/data' }
  ];

  const pathname = $derived($page.url.pathname);
</script>

{#snippet link(item: Nav, size: 'primary' | 'row' | 'pair')}
  {@const active = item.match(pathname)}
  <a
    href={item.href}
    aria-current={active ? 'page' : undefined}
    class={cn(
      'group relative flex h-10 min-w-0 items-center rounded-[var(--radius-sm)] text-sm transition-colors hover:bg-surface-2',
      size === 'primary' && 'gap-3 px-2.5 font-medium md:h-8',
      size === 'row' && 'gap-3 px-2.5 md:h-7',
      size === 'pair' && 'gap-2 px-2.5 md:h-7',
      active ? 'bg-surface-2 text-fg' : size === 'primary' ? 'text-fg-dim' : 'text-muted'
    )}
  >
    {#if active}
      <span class="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r-full bg-accent"></span>
    {/if}
    <span class={cn('shrink-0', active ? 'text-accent' : 'text-faint transition-colors group-hover:text-fg-dim')}>
      <Icon name={item.icon} class="size-[17px]" />
    </span>
    <span class="truncate transition-colors group-hover:text-fg">{item.label}</span>
  </a>
{/snippet}

<aside
  class={cn(
    'sticky top-0 flex h-screen w-[248px] shrink-0 flex-col gap-3 border-r border-border bg-[color-mix(in_oklab,var(--surface)_55%,transparent)] px-3.5 py-4 backdrop-blur-xl md:gap-2.5 md:py-3',
    className
  )}
>
  <!-- Brand -->
  <a href="/" class="flex items-center gap-2.5 px-1.5">
    <span class="relative grid size-7 shrink-0 place-items-center">
      <BrandMark />
    </span>
    <span class="flex min-w-0 flex-col">
      <span class="font-display text-[1.02rem] leading-tight text-fg">Adaptive <span class="text-accent">Academy</span></span>
      <span class="flex items-center gap-1.5">
        <span class="size-1.5 rounded-full bg-success"></span>
        <span class="eyebrow !text-[0.55rem]">local · private</span>
      </span>
    </span>
  </a>

  <TopicSwitcher />

  <!-- Nav -->
  <nav class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto md:gap-2">
    {#if primary.length}
      <div class="flex flex-col gap-px">
        {#each primary as item (item.label)}
          {@render link(item, 'primary')}
        {/each}
        {#if !dayHint.dismissed}
          <div
            class="mt-1 flex items-start gap-2 rounded-[var(--radius-sm)] border border-dashed border-border py-1 pl-2.5 pr-1 text-[0.7rem] leading-snug text-muted"
          >
            <p class="flex-1">
              <span class="text-fg-dim">Start at Today:</span> warm up, build, probe, teach back.
            </p>
            <button
              type="button"
              aria-label="Dismiss hint"
              onclick={dismissDayHint}
              class="grid size-6 shrink-0 place-items-center rounded-[var(--radius-sm)] text-faint transition-colors hover:bg-surface-2 hover:text-fg max-md:size-8"
            >
              <svg viewBox="0 0 20 20" class="size-3" fill="none" aria-hidden="true">
                <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
            </button>
          </div>
        {/if}
      </div>
    {/if}
    {#each sections as section (section.label)}
      <div class="flex flex-col gap-px">
        <div class="eyebrow mb-1 px-2.5 !text-[0.6rem] !leading-none max-md:mt-1">{section.label}</div>
        {#if section.pair}
          <div class="grid grid-cols-2 gap-px">
            {#each section.items as item (item.label)}
              {@render link(item, 'pair')}
            {/each}
          </div>
        {:else}
          {#each section.items as item (item.label)}
            {@render link(item, 'row')}
          {/each}
        {/if}
      </div>
    {/each}
    {#if tid == null}
      <a href="/topics/new" class="flex h-10 items-center gap-3 rounded-[var(--radius-sm)] px-2.5 text-sm text-accent hover:bg-accent-wash md:h-9">
        <span class="text-base">＋</span> Create your first topic
      </a>
    {/if}
  </nav>

  <!-- Footer -->
  <div class="flex flex-col gap-px border-t border-border pt-2">
    <div class="grid grid-cols-2 gap-px">
      {#each footer as item (item.label)}
        {@render link(item, 'pair')}
      {/each}
    </div>
    <ThemeToggle />
  </div>
</aside>
