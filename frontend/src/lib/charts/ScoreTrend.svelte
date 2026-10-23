<script lang="ts">
  import { Chart, Svg, Axis, Area, Points, Grid } from 'layerchart';

  import { indexTicks } from './ticks';

  let { data = [] }: { data: { i: number; score: number; label: string }[] } = $props();
  // One tick per probe, whole numbers only, thinned so many probes never crowd the axis.
  const xTicks = $derived(indexTicks(data.length, 8));
  const pctOf = (v: number) => Math.round(v * 100);
  const summary = $derived(
    data.length >= 2
      ? `Score trajectory over ${data.length} assessments: first ${pctOf(data[0].score)}%, latest ${pctOf(data[data.length - 1].score)}%, ` +
          `lowest ${pctOf(Math.min(...data.map((d) => d.score)))}%, highest ${pctOf(Math.max(...data.map((d) => d.score)))}%.`
      : ''
  );
  // LayerChart draws each tick label in a nested <svg> and relies on its own `overflow-visible`
  // class, which this app's Tailwind build never sees (node_modules is not scanned). Without
  // it a label left of its tick (the whole 0–100 axis, half the first x label) is clipped.
  const axisClass = '[&_svg]:overflow-visible [&_text]:fill-faint [&_text]:text-[10px]';
</script>

{#if data.length >= 2}
  <figure class="w-full" aria-label={summary} data-testid="score-trend">
    <!-- The drawing is for sighted users; the table below carries the same data. -->
    <div class="h-44 w-full" aria-hidden="true">
      <Chart
        {data}
        x="i"
        y="score"
        yDomain={[0, 1]}
        yNice
        padding={{ top: 10, right: 12, bottom: 22, left: 30 }}
      >
        <Svg>
          <Grid y class="stroke-border/60" />
          <Axis placement="left" ticks={[0, 0.25, 0.5, 0.75, 1]} format={(v: number) => `${pctOf(v)}`} class={axisClass} />
          <Axis placement="bottom" ticks={xTicks} format={(v: number) => `${v + 1}`} class={axisClass} />
          <Area line={{ class: 'fill-none stroke-accent stroke-2' }} class="fill-accent/12" />
          <Points class="fill-accent stroke-bg" r={3} />
        </Svg>
      </Chart>
    </div>
    <!-- The x axis title: the ticks count probes in the order they were taken. -->
    <div class="pl-[30px] pr-3 text-center text-[10px] text-faint" aria-hidden="true" data-testid="score-trend-axis">
      probe #, oldest to newest
    </div>
    <table class="sr-only">
      <caption>Assessment scores, oldest first</caption>
      <thead><tr><th scope="col">Assessment</th><th scope="col">Concept</th><th scope="col">Score</th></tr></thead>
      <tbody>
        {#each data as d, n (n)}
          <tr><td>{n + 1}</td><td>{d.label}</td><td>{pctOf(d.score)}%</td></tr>
        {/each}
      </tbody>
    </table>
  </figure>
{:else if data.length === 1}
  <div class="flex h-44 flex-col items-center justify-center gap-2 text-center">
    <span class="nums font-display text-4xl text-accent">{pctOf(data[0].score)}%</span>
    <span class="eyebrow">one data point · assess again to chart a trend</span>
  </div>
{:else}
  <div class="grid h-44 place-items-center">
    <span class="text-sm text-faint">No assessments yet.</span>
  </div>
{/if}
