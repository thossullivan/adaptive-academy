<script lang="ts">
  import { levelColor } from '$lib/utils';
  import {
    sigColor,
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

  const gradeColor = $derived(signals.grade === 'unknown' ? 'var(--faint)' : levelColor(signals.grade));
</script>

<div class="flex items-center gap-3 py-1.5">
  <div class="flex min-w-0 flex-1 items-center gap-2">
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
    </div>
    <span class="eyebrow w-[4.5rem] text-right !tracking-[0.12em]" style:color={VERDICT_COLOR[verdict]}>
      {VERDICT_LABEL[verdict]}
    </span>
  </div>
</div>
