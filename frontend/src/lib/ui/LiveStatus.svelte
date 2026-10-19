<script lang="ts">
  // A visually hidden polite live region: screen readers announce `message` whenever it
  // changes, without moving focus. Keep it mounted (an empty message says nothing) so the
  // region exists before the first announcement; a region inserted together with its text is
  // often not read. Use it for async results that matter (a grade, a reply), not for chatter.
  let { message = '' }: { message?: string } = $props();
</script>

<div class="sr-only" role="status" aria-live="polite" aria-atomic="true">{message}</div>
