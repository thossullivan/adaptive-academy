<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    label,
    value,
    unit = '',
    delta = null,
    deltaGood = 'up',
    deltaUnit = 'raw',
    deltaLabel = '',
    hint = '',
    icon
  }: {
    label: string;
    value: string | number;
    unit?: string;
    delta?: number | null;
    deltaGood?: 'up' | 'down';
    /** 'pts': `delta` is in percentage points and reads "+13 pts", in the same unit as a
     *  percent value beside it. 'raw': an arrow and the number to two places. */
    deltaUnit?: 'raw' | 'pts';
    /** What the delta compares (hover text and screen readers), e.g. "latest probe vs the one before". */
    deltaLabel?: string;
    hint?: string;
    icon?: Snippet;
  } = $props();

  // Points to one decimal at most ("+0.6 pts", "+13 pts"): a mean moves by fractions of a point.
  const pts = $derived(delta == null ? '' : String(Math.round(Math.abs(delta) * 10) / 10));
  const deltaText = $derived(
    delta == null ? '' : deltaUnit === 'pts' ? `${delta > 0 ? '+' : delta < 0 ? '−' : '±'}${pts} pts` : Math.abs(delta).toFixed(2)
  );

  const deltaTone = $derived(
    delta == null || delta === 0
      ? 'var(--muted)'
      : (delta > 0) === (deltaGood === 'up')
        ? 'var(--success)'
        : 'var(--danger)'
  );
</script>

<div class="flex flex-col gap-1">
  <div class="flex items-center justify-between">
    <span class="eyebrow">{label}</span>
    {#if icon}<span class="text-faint">{@render icon()}</span>{/if}
  </div>
  <div class="flex items-baseline gap-1.5">
    <span class="nums font-display text-3xl text-fg">{value}</span>
    {#if unit}<span class="text-sm text-muted">{unit}</span>{/if}
    {#if delta != null}
      <span class="nums ml-auto text-xs font-medium" style:color={deltaTone} title={deltaLabel || undefined} data-testid="stat-delta">
        {#if deltaUnit === 'pts'}<span aria-hidden="true">{deltaText}</span><span class="sr-only">{delta > 0 ? 'up' : delta < 0 ? 'down' : 'unchanged,'} {pts} points{deltaLabel ? `, ${deltaLabel}` : ''}</span>{:else}<span aria-hidden="true">{delta > 0 ? '↑' : delta < 0 ? '↓' : '·'}</span><span class="sr-only">{delta > 0 ? 'up ' : delta < 0 ? 'down ' : 'unchanged '}</span>{deltaText}{/if}
      </span>
    {/if}
  </div>
  {#if hint}<span class="text-xs text-faint">{hint}</span>{/if}
</div>
