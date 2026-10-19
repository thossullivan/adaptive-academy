<script lang="ts">
  import { cn } from '$lib/utils';

  let {
    value = $bindable(''),
    placeholder = '',
    disabled = false,
    type = 'text',
    class: klass = '',
    ...rest
  }: {
    value?: string;
    placeholder?: string;
    disabled?: boolean;
    type?: string;
    class?: string;
    [key: string]: unknown;
  } = $props();
</script>

<input
  {type}
  {placeholder}
  {disabled}
  bind:value
  class={cn(
    'h-10 w-full rounded-[var(--radius-sm)] border border-control-border bg-surface-2 px-3 text-sm text-fg',
    'placeholder:text-faint transition-colors',
    'hover:border-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--ring)]',
    'disabled:opacity-50',
    klass
  )}
  {...rest}
/>
