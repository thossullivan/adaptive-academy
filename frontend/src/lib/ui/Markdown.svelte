<script lang="ts">
  import { inlineMd, blockMd } from '$lib/md';
  import { cn } from '$lib/utils';

  let {
    text = '',
    block = false,
    class: klass = ''
  }: { text?: string; block?: boolean; class?: string } = $props();

  const html = $derived(block ? blockMd(text) : inlineMd(text));
</script>

<span class={cn('md', klass)}>{@html html}</span>
