<script lang="ts">
  import { theme } from '$lib/theme.svelte';
</script>

<button
  onclick={() => theme.toggle()}
  class="group flex h-9 w-full items-center gap-2.5 rounded-[var(--radius-sm)] border border-transparent px-2.5 text-sm text-muted transition-colors hover:border-border hover:bg-surface-2 hover:text-fg"
  aria-label="Toggle theme"
>
  <span class="grid size-5 place-items-center">
    {#if theme.current === 'dark'}
      <!-- moon -->
      <svg viewBox="0 0 16 16" class="size-4" fill="none">
        <path
          d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7Z"
          fill="currentColor"
          opacity="0.85"
        />
      </svg>
    {:else}
      <!-- sun -->
      <svg viewBox="0 0 16 16" class="size-4" fill="none" stroke="currentColor" stroke-width="1.4">
        <circle cx="8" cy="8" r="3" fill="currentColor" stroke="none" />
        <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M13 3l-1 1M4 12l-1 1" stroke-linecap="round" />
      </svg>
    {/if}
  </span>
  <span class="flex-1 text-left">{theme.current === 'dark' ? 'Dark' : 'Light'}</span>
  <span class="eyebrow !text-[0.55rem] opacity-0 transition-opacity group-hover:opacity-100">switch</span>
</button>
