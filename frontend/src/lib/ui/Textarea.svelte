<script lang="ts">
  import { cn } from '$lib/utils';

  let {
    value = $bindable(''),
    placeholder = '',
    disabled = false,
    rows = 4,
    class: klass = '',
    ...rest
  }: {
    value?: string;
    placeholder?: string;
    disabled?: boolean;
    rows?: number;
    class?: string;
    [key: string]: unknown;
  } = $props();
</script>

<textarea
  {placeholder}
  {disabled}
  {rows}
  bind:value
  class={cn(
    'w-full resize-y rounded-[var(--radius-sm)] border border-control-border bg-surface-2 px-3 py-2.5 text-sm leading-relaxed text-fg',
    'placeholder:text-faint transition-colors',
    'hover:border-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--ring)]',
    'disabled:cursor-not-allowed disabled:bg-surface-3 disabled:text-faint disabled:hover:border-control-border',
    klass
  )}
  {...rest}
></textarea>
