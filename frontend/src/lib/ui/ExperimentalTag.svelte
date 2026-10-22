<script lang="ts">
  import Badge from './Badge.svelte';

  // The "Experimental" mark for a model that is not a Claude model (the API's model catalog
  // decides). A text label, so it never relies on colour alone.
  let { class: klass = '' }: { class?: string } = $props();
</script>

<span data-testid="experimental-label" class="inline-flex shrink-0" title="Not a Claude model: allowed through OpenRouter, but not verified with this app's tools">
  <Badge tone="warn" class={klass}>Experimental</Badge>
</span>
