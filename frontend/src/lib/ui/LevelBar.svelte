<script lang="ts">
  import { LEVEL_FILL, LEVEL_LABEL, levelColor } from '$lib/utils';

  let {
    name,
    level = 'unknown',
    loadBearing = false,
    hasAnchor = false
  }: {
    name: string;
    level?: string;
    loadBearing?: boolean;
    hasAnchor?: boolean;
  } = $props();

  const fill = $derived(LEVEL_FILL[level] ?? 0.12);
  const color = $derived(levelColor(level));
  const segments = 5;
  const lit = $derived(Math.round(fill * segments));
</script>

<div class="flex items-center gap-3 py-1.5">
  <div class="flex min-w-0 flex-1 items-center gap-2">
    {#if loadBearing}
      <span class="text-accent" title="Key concept">◆</span>
    {/if}
    <span class="truncate text-sm text-fg-dim">{name}</span>
    {#if hasAnchor}
      <span class="eyebrow !text-[0.55rem] text-faint" title="Has a source-grounded quiz anchor">⌗</span>
    {/if}
  </div>
  <div class="flex shrink-0 items-center gap-2">
    <div class="flex gap-0.5">
      {#each Array(segments) as _, i}
        <span
          class="h-3.5 w-1.5 rounded-[2px] transition-colors"
          style:background={i < lit ? color : 'var(--surface-3)'}
        ></span>
      {/each}
    </div>
    <span class="eyebrow w-20 text-right !tracking-[0.12em]" style:color>{LEVEL_LABEL[level] ?? level}</span>
  </div>
</div>
