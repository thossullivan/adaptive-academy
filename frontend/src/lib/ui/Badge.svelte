<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  let {
    tone = 'neutral',
    mono = false,
    dot = false,
    class: klass = '',
    children
  }: {
    tone?: 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info';
    mono?: boolean;
    dot?: boolean;
    class?: string;
    children: Snippet;
  } = $props();

  const tones = {
    neutral: 'text-muted border-border bg-surface-2',
    accent: 'text-accent border-[color-mix(in_oklab,var(--accent)_35%,transparent)] bg-accent-wash',
    success: 'text-success border-[color-mix(in_oklab,var(--success)_35%,transparent)] bg-[color-mix(in_oklab,var(--success)_10%,transparent)]',
    warn: 'text-warn border-[color-mix(in_oklab,var(--warn)_35%,transparent)] bg-[color-mix(in_oklab,var(--warn)_10%,transparent)]',
    danger: 'text-danger border-[color-mix(in_oklab,var(--danger)_35%,transparent)] bg-[color-mix(in_oklab,var(--danger)_10%,transparent)]',
    info: 'text-info border-[color-mix(in_oklab,var(--info)_35%,transparent)] bg-[color-mix(in_oklab,var(--info)_10%,transparent)]'
  };

  const dotColor = {
    neutral: 'var(--muted)',
    accent: 'var(--accent)',
    success: 'var(--success)',
    warn: 'var(--warn)',
    danger: 'var(--danger)',
    info: 'var(--info)'
  };
</script>

<span
  class={cn(
    'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
    mono && 'font-mono text-[0.7rem] tracking-tight',
    tones[tone],
    klass
  )}
>
  {#if dot}
    <span class="size-1.5 rounded-full" style:background={dotColor[tone]}></span>
  {/if}
  {@render children()}
</span>
