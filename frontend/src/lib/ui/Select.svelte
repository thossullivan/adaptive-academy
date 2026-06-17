<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  let {
    value = $bindable<string | number | null>(''),
    disabled = false,
    class: klass = '',
    children,
    ...rest
  }: {
    value?: string | number | null;
    disabled?: boolean;
    class?: string;
    children: Snippet;
    [key: string]: unknown;
  } = $props();
</script>

<div class={cn('relative', klass)}>
  <select
    bind:value
    {disabled}
    {...rest}
    class={cn(
      'h-10 w-full appearance-none rounded-[var(--radius-sm)] border border-border bg-surface-2 pl-3 pr-9 text-sm text-fg',
      'transition-colors hover:border-border-strong focus:border-accent focus:outline-none',
      'disabled:opacity-50'
    )}
  >
    {@render children()}
  </select>
  <svg
    class="pointer-events-none absolute right-3 top-1/2 size-3.5 -translate-y-1/2 text-muted"
    viewBox="0 0 16 16"
    fill="none"
  >
    <path d="M4 6l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
</div>
