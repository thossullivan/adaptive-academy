<script lang="ts">
  import { fly, fade } from 'svelte/transition';
  import { toasts } from '$lib/toast.svelte';
</script>

<div class="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(22rem,calc(100vw-2.5rem))] flex-col gap-2">
  {#each toasts.items as t (t.id)}
    <button
      type="button"
      onclick={() => toasts.dismiss(t.id)}
      in:fly={{ y: 12, duration: 220 }}
      out:fade={{ duration: 160 }}
      class="pointer-events-auto flex items-start gap-2.5 rounded-[var(--radius)] border bg-surface-2/95 px-3.5 py-2.5 text-left text-sm shadow-lg backdrop-blur-xl transition-colors hover:bg-surface-2"
      class:border-success={t.tone === 'success'}
      class:border-danger={t.tone === 'error'}
    >
      <span style:color={t.tone === 'success' ? 'var(--success)' : 'var(--danger)'}>
        {t.tone === 'success' ? '✓' : '!'}
      </span>
      <span class="text-fg-dim">{t.msg}</span>
    </button>
  {/each}
</div>
