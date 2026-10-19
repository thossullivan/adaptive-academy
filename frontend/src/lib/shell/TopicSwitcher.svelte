<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { topics } from '$lib/topics.svelte';
  import Badge from '$lib/ui/Badge.svelte';

  let open = $state(false);

  function close() {
    open = false;
  }

  /** If we're on a topic-scoped page, keep the same sub-page when switching topics. */
  function subpage(): string {
    const m = $page.url.pathname.match(/^\/topics\/\d+(\/[a-z]+)?/);
    return m?.[1] ?? '';
  }

  async function pick(id: number) {
    topics.select(id);
    close();
    const sub = subpage();
    if (sub || $page.url.pathname.startsWith('/topics/')) {
      await goto(`/topics/${id}${sub}`);
    }
  }

  function clickOutside(node: HTMLElement) {
    function onDoc(e: MouseEvent) {
      if (!node.contains(e.target as Node)) close();
    }
    document.addEventListener('click', onDoc, true);
    return { destroy: () => document.removeEventListener('click', onDoc, true) };
  }
</script>

<div class="relative" use:clickOutside>
  <button
    onclick={() => (open = !open)}
    class="group flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border border-border bg-surface-2 p-2.5 text-left transition-colors hover:border-border-strong"
  >
    <span
      class="grid size-9 shrink-0 place-items-center rounded-[var(--radius-sm)] bg-accent-wash font-display text-lg text-accent"
    >
      {topics.current?.title?.[0]?.toUpperCase() ?? '·'}
    </span>
    <span class="min-w-0 flex-1">
      <span class="flex items-center gap-1.5">
        <span class="eyebrow !text-[0.55rem]">Topic</span>
        {#if topics.current?.is_demo}
          <span data-testid="switcher-demo-badge"><Badge tone="info" class="!px-1.5 !py-0 !text-[0.6rem]">Demo</Badge></span>
        {/if}
      </span>
      <span class="block truncate text-sm font-medium text-fg">{topics.current?.title ?? 'No topic yet'}</span>
    </span>
    <svg class="size-3.5 shrink-0 text-muted transition-transform" class:rotate-180={open} viewBox="0 0 16 16" fill="none">
      <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>

  {#if open}
    <div
      class="absolute left-0 right-0 top-full z-50 mt-1.5 overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface shadow-[var(--shadow)]"
    >
      <ul class="max-h-72 overflow-y-auto p-1">
        {#each topics.list as t (t.id)}
          <li>
            <button
              onclick={() => pick(t.id)}
              class="flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-2 text-left text-sm transition-colors hover:bg-surface-2"
              class:text-fg={t.id === topics.currentId}
              class:text-muted={t.id !== topics.currentId}
            >
              <span class="size-1.5 shrink-0 rounded-full" style:background={t.id === topics.currentId ? 'var(--accent)' : 'transparent'}></span>
              <span class="truncate">{t.title}</span>
              {#if t.is_demo}<Badge tone="info" class="shrink-0 !px-1.5 !py-0 !text-[0.6rem]">Demo</Badge>{/if}
              <span class="eyebrow ml-auto shrink-0 !text-[0.55rem]">{t.concepts.length}c</span>
            </button>
          </li>
        {/each}
      </ul>
      <a
        href="/topics/new"
        onclick={close}
        class="flex items-center gap-2 border-t border-border px-3 py-2.5 text-sm text-accent transition-colors hover:bg-accent-wash"
      >
        <span class="text-base leading-none">＋</span> New topic
      </a>
    </div>
  {/if}
</div>
