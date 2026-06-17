<script lang="ts">
  import type { Snippet } from 'svelte';
  import { cn } from '$lib/utils';

  let {
    variant = 'primary',
    size = 'md',
    href = undefined,
    type = 'button',
    disabled = false,
    class: klass = '',
    onclick = undefined,
    children,
    ...rest
  }: {
    variant?: 'primary' | 'outline' | 'ghost' | 'danger';
    size?: 'sm' | 'md' | 'lg';
    href?: string;
    type?: 'button' | 'submit';
    disabled?: boolean;
    class?: string;
    onclick?: (e: MouseEvent) => void;
    children: Snippet;
    [key: string]: unknown;
  } = $props();

  const base =
    'inline-flex items-center justify-center gap-2 rounded-[var(--radius-sm)] font-medium ' +
    'transition-[background,color,border,transform,box-shadow] duration-150 active:translate-y-px ' +
    'disabled:pointer-events-none disabled:opacity-45 select-none whitespace-nowrap';

  const variants = {
    primary:
      'bg-accent text-accent-fg hover:bg-accent-bright shadow-[0_1px_0_rgba(255,255,255,0.12)_inset,0_6px_16px_-8px_var(--accent)]',
    outline: 'border border-border-strong bg-surface-2 text-fg-dim hover:text-fg hover:border-faint',
    ghost: 'text-muted hover:text-fg hover:bg-surface-2',
    danger: 'border border-[color-mix(in_oklab,var(--danger)_45%,transparent)] text-danger hover:bg-[color-mix(in_oklab,var(--danger)_12%,transparent)]'
  };

  const sizes = {
    sm: 'h-8 px-3 text-xs',
    md: 'h-10 px-4 text-sm',
    lg: 'h-12 px-6 text-base'
  };

  const cls = $derived(cn(base, variants[variant], sizes[size], klass));
</script>

{#if href}
  <a {href} class={cls} {...rest}>{@render children()}</a>
{:else}
  <button {type} {disabled} {onclick} class={cls} {...rest}>{@render children()}</button>
{/if}
