<script lang="ts">
  import { tick } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { topics } from '$lib/topics.svelte';
  import Badge from '$lib/ui/Badge.svelte';

  let open = $state(false);
  let trigger: HTMLButtonElement | null = $state(null);
  let list: HTMLUListElement | null = $state(null);
  let popup: HTMLDivElement | null = $state(null);
  // The desktop rail and the phone drawer each render a switcher: ids must not collide.
  const uid = $props.id();
  const listId = `topic-switcher-${uid}`;

  function close({ restoreFocus = false } = {}) {
    open = false;
    if (restoreFocus) trigger?.focus();
  }

  async function toggle() {
    open = !open;
    if (open) {
      // Keyboard users land on the current topic, ready to arrow or tab through the list.
      await tick();
      (list?.querySelector<HTMLElement>('[aria-current="true"]') ?? list?.querySelector<HTMLElement>('button'))?.focus();
    }
  }

  /** If we're on a topic-scoped page, keep the same sub-page when switching topics. */
  function subpage(): string {
    const m = $page.url.pathname.match(/^\/topics\/\d+(\/[a-z]+)?/);
    return m?.[1] ?? '';
  }

  async function pick(id: number) {
    topics.select(id);
    close({ restoreFocus: true });
    const sub = subpage();
    if (sub || $page.url.pathname.startsWith('/topics/')) {
      await goto(`/topics/${id}${sub}`);
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'Escape') {
      // Close just the list; the phone drawer around it stays open.
      e.preventDefault();
      e.stopPropagation();
      close({ restoreFocus: true });
      return;
    }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const items = Array.from(popup?.querySelectorAll<HTMLElement>('button, a[href]') ?? []);
      if (!items.length) return;
      e.preventDefault();
      const i = items.indexOf(document.activeElement as HTMLElement);
      const step = e.key === 'ArrowDown' ? 1 : -1;
      items[(i + step + items.length) % items.length].focus();
    }
  }

  function clickOutside(node: HTMLElement) {
    function onDoc(e: MouseEvent) {
      if (!node.contains(e.target as Node)) close();
    }
    // Tabbing out of the open list closes it too.
    function onFocusOut(e: FocusEvent) {
      if (open && e.relatedTarget && !node.contains(e.relatedTarget as Node)) close();
    }
    document.addEventListener('click', onDoc, true);
    node.addEventListener('focusout', onFocusOut);
    return {
      destroy: () => {
        document.removeEventListener('click', onDoc, true);
        node.removeEventListener('focusout', onFocusOut);
      }
    };
  }

  const title = $derived(topics.current?.title ?? 'No topic yet');
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="relative" use:clickOutside onkeydown={onKeydown}>
  <button
    bind:this={trigger}
    type="button"
    onclick={toggle}
    aria-expanded={open}
    aria-controls={listId}
    aria-label="Topic: {title}{topics.current?.is_demo ? ' (demo)' : ''}. Switch topic"
    title={title}
    class="group flex w-full items-center gap-2.5 rounded-[var(--radius-md)] border border-border bg-surface-2 p-2 text-left transition-colors hover:border-border-strong md:py-1.5"
  >
    <span
      class="grid size-8 shrink-0 place-items-center rounded-[var(--radius-sm)] bg-accent-wash font-display text-lg text-accent"
      aria-hidden="true"
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
      <!-- Two lines, then an ellipsis; the whole title is the button's name and hover title. -->
      <span class="line-clamp-2 break-words text-sm font-medium leading-snug text-fg md:text-[0.8125rem] md:leading-tight" data-testid="switcher-title">{title}</span>
    </span>
    <svg class="size-3.5 shrink-0 text-muted transition-transform" class:rotate-180={open} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>

  {#if open}
    <div
      bind:this={popup}
      class="absolute left-0 right-0 top-full z-50 mt-1.5 overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface shadow-[var(--shadow)]"
    >
      <ul bind:this={list} id={listId} aria-label="Topics" class="max-h-72 overflow-y-auto p-1">
        {#each topics.list as t (t.id)}
          <li>
            <button
              type="button"
              onclick={() => pick(t.id)}
              aria-current={t.id === topics.currentId ? 'true' : undefined}
              title={t.title}
              class="flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-2 text-left text-sm transition-colors hover:bg-surface-2"
              class:text-fg={t.id === topics.currentId}
              class:text-muted={t.id !== topics.currentId}
            >
              <span class="size-1.5 shrink-0 rounded-full" style:background={t.id === topics.currentId ? 'var(--accent)' : 'transparent'} aria-hidden="true"></span>
              <span class="line-clamp-2 min-w-0 break-words">{t.title}</span>
              {#if t.is_demo}<Badge tone="info" class="shrink-0 !px-1.5 !py-0 !text-[0.6rem]">Demo</Badge>{/if}
              <span class="eyebrow ml-auto shrink-0 !text-[0.55rem]"><span aria-hidden="true">{t.concepts.length}c</span><span class="sr-only">, {t.concepts.length} concepts</span></span>
            </button>
          </li>
        {/each}
      </ul>
      <a
        href="/topics/new"
        onclick={() => close()}
        class="flex items-center gap-2 border-t border-border px-3 py-2.5 text-sm text-accent transition-colors hover:bg-accent-wash"
      >
        <span class="text-base leading-none" aria-hidden="true">＋</span> New topic
      </a>
    </div>
  {/if}
</div>
