<script lang="ts">
  import { clamp } from '$lib/utils';

  let {
    value = 0,
    size = 64,
    stroke = 6,
    color = 'var(--accent)',
    track = 'var(--surface-3)',
    label = '',
    sublabel = ''
  }: {
    value?: number;
    size?: number;
    stroke?: number;
    color?: string;
    track?: string;
    label?: string;
    sublabel?: string;
  } = $props();

  const r = $derived((size - stroke) / 2);
  const circ = $derived(2 * Math.PI * r);
  const offset = $derived(circ * (1 - clamp(value)));
</script>

<div class="relative inline-grid place-items-center" style:width="{size}px" style:height="{size}px">
  <svg width={size} height={size} class="-rotate-90">
    <circle cx={size / 2} cy={size / 2} {r} fill="none" stroke={track} stroke-width={stroke} />
    <circle
      cx={size / 2}
      cy={size / 2}
      {r}
      fill="none"
      stroke={color}
      stroke-width={stroke}
      stroke-linecap="round"
      stroke-dasharray={circ}
      stroke-dashoffset={offset}
      style="transition: stroke-dashoffset 0.7s cubic-bezier(0.22,1,0.36,1)"
    />
  </svg>
  <div class="absolute text-center leading-none">
    {#if label}<div class="nums text-sm font-semibold text-fg">{label}</div>{/if}
    {#if sublabel}<div class="eyebrow mt-0.5 !text-[0.55rem]">{sublabel}</div>{/if}
  </div>
</div>
