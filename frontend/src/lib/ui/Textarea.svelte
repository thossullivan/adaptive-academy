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
    'w-full resize-y rounded-[var(--radius-sm)] border border-border bg-surface-2 px-3 py-2.5 text-sm leading-relaxed text-fg',
    'placeholder:text-faint transition-colors',
    'hover:border-border-strong focus:border-accent focus:outline-none',
    'disabled:opacity-50',
    klass
  )}
  {...rest}
></textarea>
