<script lang="ts">
  import { inlineMd, blockMd, preMd } from '$lib/md';
  import { cn } from '$lib/utils';

  // `block`: line breaks as <br>. `pre`: line breaks and indentation kept as typed
  // (white-space: pre-wrap), for tutor replies. Both render ``` fenced code.
  let {
    text = '',
    block = false,
    pre = false,
    class: klass = ''
  }: { text?: string; block?: boolean; pre?: boolean; class?: string } = $props();

  const html = $derived(pre ? preMd(text) : block ? blockMd(text) : inlineMd(text));
</script>

<span class={cn('md', pre && 'whitespace-pre-wrap', klass)}>{@html html}</span>
