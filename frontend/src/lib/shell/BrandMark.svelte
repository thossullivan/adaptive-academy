<script lang="ts">
  let { class: className = 'size-8' }: { class?: string } = $props();
</script>

<svg viewBox="0 0 32 32" class={className} aria-hidden="true">
  <circle cx="16" cy="16" r="13" fill="none" stroke="var(--border-strong)" stroke-width="1.5" />
  <circle cx="16" cy="16" r="4.5" fill="var(--accent)" />
  <circle cx="16" cy="16" r="9" fill="none" stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="2 4" opacity="0.7" />
</svg>
