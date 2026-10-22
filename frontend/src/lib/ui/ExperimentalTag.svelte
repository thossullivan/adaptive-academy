<script lang="ts">
  import Badge from './Badge.svelte';

  // The "Experimental" mark for a model that is not a Claude model (the API's model catalog
  // decides). A text label, so it never relies on colour alone; the explanation is in the
  // accessible name too (sr-only), not only in a hover tooltip.
  let { class: klass = '' }: { class?: string } = $props();
  const why = "Not a Claude model: allowed through OpenRouter, but not verified with this app's tools";
</script>

<span data-testid="experimental-label" class="inline-flex shrink-0" title={why}>
  <Badge tone="warn" class={klass}>Experimental</Badge><span class="sr-only">: {why}</span>
</span>
