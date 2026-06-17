<script lang="ts">
  import { page } from '$app/stores';
  import { topics } from '$lib/topics.svelte';
  import TopicSwitcher from './TopicSwitcher.svelte';
  import ThemeToggle from './ThemeToggle.svelte';
  import Icon from './Icon.svelte';

  const tid = $derived(topics.current?.id ?? null);

  type Nav = { label: string; icon: string; href: string; match: (p: string) => boolean };
  type Section = { label: string; items: Nav[] };

  const sections = $derived<Section[]>(
    tid == null
      ? []
      : [
          {
            label: 'Daily',
            items: [
              { label: 'Today', icon: 'today', href: `/topics/${tid}/today`, match: (p) => p.endsWith('/today') },
              { label: 'Wayfinder', icon: 'wayfinder', href: `/topics/${tid}/wayfinder`, match: (p) => p.endsWith('/wayfinder') }
            ]
          },
          {
            label: 'Workspace',
            items: [
              { label: 'Dashboard', icon: 'dashboard', href: '/', match: (p) => p === '/' },
              { label: 'Tutor', icon: 'tutor', href: `/topics/${tid}/tutor`, match: (p) => p.endsWith('/tutor') },
              { label: 'Track', icon: 'track', href: `/topics/${tid}/track`, match: (p) => p.endsWith('/track') },
              { label: 'Assess', icon: 'assess', href: `/topics/${tid}/assess`, match: (p) => p.endsWith('/assess') },
              { label: 'Practice', icon: 'practice', href: `/topics/${tid}/practice`, match: (p) => p.endsWith('/practice') },
              { label: 'Retention', icon: 'retention', href: `/topics/${tid}/retention`, match: (p) => p.endsWith('/retention') },
              { label: 'Sources', icon: 'sources', href: `/topics/${tid}/review`, match: (p) => p.endsWith('/review') }
            ]
          },
          {
            label: 'Reflect',
            items: [
              { label: 'Constellation', icon: 'map', href: `/topics/${tid}/map`, match: (p) => p.endsWith('/map') },
              { label: 'Teach', icon: 'teach', href: `/topics/${tid}/teach`, match: (p) => p.endsWith('/teach') },
              { label: 'Story', icon: 'story', href: `/topics/${tid}/story`, match: (p) => p.endsWith('/story') }
            ]
          }
        ]
  );

  const pathname = $derived($page.url.pathname);
</script>

<aside
  class="sticky top-0 flex h-screen w-[248px] shrink-0 flex-col gap-5 border-r border-border bg-[color-mix(in_oklab,var(--surface)_55%,transparent)] px-3.5 py-5 backdrop-blur-xl"
>
  <!-- Brand -->
  <a href="/" class="flex items-center gap-2.5 px-1.5">
    <span class="relative grid size-8 place-items-center">
      <svg viewBox="0 0 32 32" class="size-8">
        <circle cx="16" cy="16" r="13" fill="none" stroke="var(--border-strong)" stroke-width="1.5" />
        <circle cx="16" cy="16" r="4.5" fill="var(--accent)" />
        <circle cx="16" cy="16" r="9" fill="none" stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="2 4" opacity="0.7" />
      </svg>
    </span>
    <span class="font-display text-[1.05rem] leading-tight text-fg">Adaptive<br /><span class="text-accent">Academy</span></span>
  </a>

  <TopicSwitcher />

  <!-- Nav -->
  <nav class="flex flex-1 flex-col gap-3 overflow-y-auto">
    {#each sections as section (section.label)}
      <div class="flex flex-col gap-0.5">
        <div class="eyebrow mb-1 px-2.5">{section.label}</div>
        {#each section.items as item (item.label)}
          {@const active = item.match(pathname)}
          <a
            href={item.href}
            class="group relative flex h-9 items-center gap-3 rounded-[var(--radius-sm)] px-2.5 text-sm transition-colors"
            class:text-fg={active}
            class:bg-surface-2={active}
            class:text-muted={!active}
          >
            {#if active}
              <span class="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r-full bg-accent"></span>
            {/if}
            <span class={active ? 'text-accent' : 'text-faint transition-colors group-hover:text-fg-dim'}>
              <Icon name={item.icon} />
            </span>
            <span class="transition-colors group-hover:text-fg">{item.label}</span>
          </a>
        {/each}
      </div>
    {/each}
    {#if tid == null}
      <a href="/topics/new" class="flex h-9 items-center gap-3 rounded-[var(--radius-sm)] px-2.5 text-sm text-accent hover:bg-accent-wash">
        <span class="text-base">＋</span> Create your first topic
      </a>
    {/if}
  </nav>

  <!-- Footer -->
  <div class="flex flex-col gap-1 border-t border-border pt-3">
    <ThemeToggle />
    <div class="flex items-center gap-2 px-2.5 pt-1">
      <span class="size-1.5 rounded-full bg-success"></span>
      <span class="eyebrow !text-[0.55rem]">local · private</span>
    </div>
  </div>
</aside>
