<script lang="ts">
  import { VERDICT_COLOR, VERDICT_SHAPE, type Verdict } from '$lib/competence';
  import { cn } from '$lib/utils';

  // The one verdict mark used in lists and legends. Shape backs up colour (VERDICT_SHAPE): a
  // filled dot, a hollow ring for "untested", a diamond for "verified", so marks that are
  // close in colour (untested and unverified greys, verified teal and solid green) still read
  // apart. Decorative: the verdict word next to it carries the meaning.
  let { verdict, class: klass = 'size-2' }: { verdict: Verdict; class?: string } = $props();
  const shape = $derived(VERDICT_SHAPE[verdict]);
  const color = $derived(VERDICT_COLOR[verdict]);
</script>

<span
  class={cn(
    'inline-block shrink-0',
    shape === 'ring' && 'rounded-full border-[1.5px] bg-transparent',
    shape === 'dot' && 'rounded-full',
    // A square turned 45°, scaled so its corners reach about the dot's edge.
    shape === 'diamond' && 'rotate-45 scale-[0.85] rounded-[1px]',
    klass
  )}
  style:background={shape === 'ring' ? undefined : color}
  style:border-color={shape === 'ring' ? color : undefined}
  data-testid="verdict-dot"
  data-verdict={verdict}
  data-shape={shape}
  data-hollow={shape === 'ring' ? 'true' : undefined}
  aria-hidden="true"
></span>
