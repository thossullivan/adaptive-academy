<script lang="ts">
  // Predicted (x) vs actual (y) confidence. The diagonal is perfect calibration:
  // above it = underconfident, below it = overconfident.
  let { data = [] }: { data: { predicted: number; actual: number; label: string }[] } = $props();

  const P = 10; // inner padding within 0..100 viewBox
  const sx = (v: number) => P + v * (100 - 2 * P);
  const sy = (v: number) => 100 - P - v * (100 - 2 * P);

  function dotColor(d: { predicted: number; actual: number }) {
    const gap = Math.abs(d.predicted - d.actual);
    if (gap <= 0.1) return 'var(--success)';
    return d.predicted > d.actual ? 'var(--danger)' : 'var(--info)';
  }

  function verdict(d: { predicted: number; actual: number }) {
    const gap = Math.abs(d.predicted - d.actual);
    if (gap <= 0.1) return 'well calibrated';
    return d.predicted > d.actual ? 'overconfident' : 'underconfident';
  }

  const counts = $derived({
    over: data.filter((d) => verdict(d) === 'overconfident').length,
    under: data.filter((d) => verdict(d) === 'underconfident').length,
    well: data.filter((d) => verdict(d) === 'well calibrated').length
  });
  const summary = $derived(
    `Calibration plot of ${data.length} probe${data.length === 1 ? '' : 's'}, predicted against actual score: ` +
      `${counts.well} well calibrated, ${counts.over} overconfident, ${counts.under} underconfident.`
  );
</script>

{#if data.length}
  <figure class="flex items-center gap-4" aria-label={summary} data-testid="calibration-plot">
    <!-- The drawing is for sighted users; the table below carries the same data. -->
    <svg viewBox="0 0 100 100" class="aspect-square h-44 w-44 shrink-0" aria-hidden="true">
      <!-- zones -->
      <polygon points="{P},{P} {100 - P},{P} {100 - P},{100 - P}" fill="var(--info)" opacity="0.06" />
      <polygon points="{P},{P} {P},{100 - P} {100 - P},{100 - P}" fill="var(--danger)" opacity="0.06" />
      <!-- frame -->
      <rect x={P} y={P} width={100 - 2 * P} height={100 - 2 * P} fill="none" stroke="var(--border)" stroke-width="0.5" />
      <!-- diagonal -->
      <line x1={P} y1={100 - P} x2={100 - P} y2={P} stroke="var(--border-strong)" stroke-width="0.6" stroke-dasharray="2 2" />
      <!-- points -->
      {#each data as d}
        <circle cx={sx(d.predicted)} cy={sy(d.actual)} r="2.4" fill={dotColor(d)} stroke="var(--bg)" stroke-width="0.6">
          <title>{d.label}: predicted {Math.round(d.predicted * 100)}% · actual {Math.round(d.actual * 100)}%</title>
        </circle>
      {/each}
    </svg>
    <div class="flex flex-col gap-2 text-xs" aria-hidden="true">
      <div class="flex items-center gap-2"><span class="size-2 rounded-full" style:background="var(--info)"></span><span class="text-muted">Underconfident</span></div>
      <div class="flex items-center gap-2"><span class="size-2 rounded-full" style:background="var(--success)"></span><span class="text-muted">Well-calibrated</span></div>
      <div class="flex items-center gap-2"><span class="size-2 rounded-full" style:background="var(--danger)"></span><span class="text-muted">Overconfident</span></div>
      <div class="eyebrow mt-1 !text-[0.55rem]">predicted → actual</div>
    </div>
    <table class="sr-only">
      <caption>Calibration probes: predicted against actual score</caption>
      <thead><tr><th scope="col">Concept</th><th scope="col">Predicted</th><th scope="col">Actual</th><th scope="col">Reading</th></tr></thead>
      <tbody>
        {#each data as d, n (n)}
          <tr><td>{d.label}</td><td>{Math.round(d.predicted * 100)}%</td><td>{Math.round(d.actual * 100)}%</td><td>{verdict(d)}</td></tr>
        {/each}
      </tbody>
    </table>
  </figure>
{:else}
  <div class="grid h-44 place-items-center">
    <span class="text-sm text-faint">Run a calibration probe to plot this.</span>
  </div>
{/if}
