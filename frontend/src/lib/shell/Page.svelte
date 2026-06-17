<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  let {
    eyebrow = '',
    title = '',
    lead = '',
    width = 'normal',
    actions,
    children
  }: {
    eyebrow?: string;
    title?: string;
    lead?: string;
    width?: 'normal' | 'wide' | 'narrow';
    actions?: Snippet;
    children: Snippet;
  } = $props();

  const max = $derived({ narrow: 'max-w-2xl', normal: 'max-w-4xl', wide: 'max-w-6xl' }[width]);
</script>

<div class={cn('mx-auto w-full px-6 py-8 md:px-10 md:py-10', max)}>
  {#if eyebrow || title || actions}
    <header class="mb-7 flex flex-wrap items-end justify-between gap-4 rise">
      <div class="min-w-0">
        {#if eyebrow}<div class="eyebrow mb-2">{eyebrow}</div>{/if}
        {#if title}<h1 class="text-3xl text-fg md:text-[2.1rem]">{title}</h1>{/if}
        {#if lead}<p class="mt-2 max-w-prose text-sm leading-relaxed text-muted">{lead}</p>{/if}
      </div>
      {#if actions}<div class="flex shrink-0 items-center gap-2">{@render actions()}</div>{/if}
    </header>
  {/if}
  {@render children()}
</div>
