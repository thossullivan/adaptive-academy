<script lang="ts">
  import { Chart, Svg, Axis, Area, Spline, Points, Grid } from 'layerchart';

  let { data = [] }: { data: { i: number; score: number; label: string }[] } = $props();
</script>

{#if data.length >= 2}
  <div class="h-44 w-full">
    <Chart
      {data}
      x="i"
      y="score"
      yDomain={[0, 1]}
      yNice
      padding={{ top: 10, right: 10, bottom: 22, left: 30 }}
    >
      <Svg>
        <Grid y class="stroke-border/60" />
        <Axis
          placement="left"
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          format={(v: number) => `${Math.round(v * 100)}`}
          class="text-faint [&_text]:fill-faint [&_text]:text-[10px]"
        />
        <Axis placement="bottom" ticks={data.length} format={(v: number) => `${v + 1}`} class="[&_text]:fill-faint [&_text]:text-[10px]" />
        <Area line={{ class: 'stroke-accent stroke-2' }} class="fill-accent/12" />
        <Points class="fill-accent stroke-bg" r={3} />
      </Svg>
    </Chart>
  </div>
{:else if data.length === 1}
  <div class="flex h-44 flex-col items-center justify-center gap-2 text-center">
    <span class="nums font-display text-4xl text-accent">{Math.round(data[0].score * 100)}%</span>
    <span class="eyebrow">one data point · assess again to chart a trend</span>
  </div>
{:else}
  <div class="grid h-44 place-items-center">
    <span class="text-sm text-faint">No assessments yet.</span>
  </div>
{/if}
