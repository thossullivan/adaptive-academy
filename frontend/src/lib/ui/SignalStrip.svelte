<script lang="ts">
  import { levelColor } from '$lib/utils';
  import {
    sigColor,
    roleColor,
    verdictRationale,
    VERDICT_COLOR,
    VERDICT_LABEL,
    type ConceptSignals,
    type Verdict
  } from '$lib/competence';

  let {
    name,
    signals,
    verdict,
    loadBearing = false,
    hasAnchor = false
  }: {
    name: string;
    signals: ConceptSignals;
    verdict: Verdict;
    loadBearing?: boolean;
    hasAnchor?: boolean;
  } = $props();

  let open = $state(false);
  const gradeColor = $derived(signals.grade === 'unknown' ? 'var(--faint)' : levelColor(signals.grade));
  const why = $derived(verdictRationale(signals));
</script>

<div class="border-b border-border/60 last:border-0">
  <button
    type="button"
    class="flex w-full items-center gap-3 py-1.5 text-left transition-colors hover:bg-bg-soft/40"
    aria-expanded={open}
    aria-label="Why is {name} {VERDICT_LABEL[verdict]}?"
    onclick={() => (open = !open)}
  >
    <div class="flex min-w-0 flex-1 items-center gap-2">
      <span class="text-faint transition-transform" class:rotate-90={open} aria-hidden="true">›</span>
      {#if loadBearing}<span class="text-accent" title="Load-bearing concept">◆</span>{/if}
      <span class="truncate text-sm text-fg-dim">{name}</span>
      {#if hasAnchor}<span class="eyebrow !text-[0.55rem] text-faint" title="Has a source-grounded quiz">⌗</span>{/if}
    </div>
    <div class="flex shrink-0 items-center gap-2.5">
      <div class="flex items-center gap-1.5 text-sm">
        <span title="Mechanism grade: {signals.grade}" style:color={gradeColor}>◆</span>
        <span title="Held cold on delayed recall ({signals.decay})" style:color={sigColor(signals.decay)}>↺</span>
        <span title="Self-assessment calibrated ({signals.calibration})" style:color={sigColor(signals.calibration)}>◷</span>
        <span title="Taught to an audience ({signals.taught})" style:color={sigColor(signals.taught)}>◳</span>
        <span title="Shipped an artifact that meets its criteria ({signals.shipped})" style:color={sigColor(signals.shipped)}>⚒</span>
      </div>
      <span class="eyebrow w-[4.5rem] text-right !tracking-[0.12em]" style:color={VERDICT_COLOR[verdict]}>
        {VERDICT_LABEL[verdict]}
      </span>
    </div>
  </button>

  {#if open}
    <div class="mb-2 ml-4 border-l border-border/60 pl-4 pb-1">
      <p class="mb-2 text-xs text-fg-dim">{why.headline}</p>
      <ul class="flex flex-col gap-1">
        {#each why.signals as d (d.key)}
          <li class="flex items-baseline gap-2 text-xs">
            <span class="w-3 shrink-0 text-center" style:color={roleColor(d.role)}>{d.glyph}</span>
            <span class="w-20 shrink-0 text-faint">{d.label}</span>
            <span class="text-fg-dim">{d.note}</span>
          </li>
        {/each}
      </ul>
      {#if why.nextStep}
        <p class="mt-2 text-xs" style:color="var(--accent)">→ {why.nextStep}</p>
      {/if}
    </div>
  {/if}
</div>
