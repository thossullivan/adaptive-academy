<script lang="ts">
  import { fly, fade } from 'svelte/transition';
  import { toasts } from '$lib/toast.svelte';
  import { prefersReducedMotion } from 'svelte/motion';
</script>

<!-- One polite live region, always mounted, so each toast is read out as it arrives (a region
     inserted together with its text is often missed). Errors say so in words, not just "!". -->
<div
  class="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(22rem,calc(100vw-2.5rem))] flex-col gap-2"
  role="status"
  aria-live="polite"
  aria-label="Notifications"
  data-testid="toaster"
>
  {#each toasts.items as t (t.id)}
    <button
      type="button"
      onclick={() => toasts.dismiss(t.id)}
      title="Dismiss"
      in:fly={{ y: prefersReducedMotion.current ? 0 : 12, duration: prefersReducedMotion.current ? 0 : 220 }}
      out:fade={{ duration: prefersReducedMotion.current ? 0 : 160 }}
      class="pointer-events-auto flex items-start gap-2.5 rounded-[var(--radius)] border bg-surface-2/95 px-3.5 py-2.5 text-left text-sm shadow-lg backdrop-blur-xl transition-colors hover:bg-surface-2"
      class:border-success={t.tone === 'success'}
      class:border-danger={t.tone === 'error'}
    >
      <span style:color={t.tone === 'success' ? 'var(--success)' : 'var(--danger)'} aria-hidden="true">
        {t.tone === 'success' ? '✓' : '!'}
      </span>
      <span class="text-fg-dim"><span class="sr-only">{t.tone === 'error' ? 'Error: ' : ''}</span>{t.msg}</span>
    </button>
  {/each}
</div>
