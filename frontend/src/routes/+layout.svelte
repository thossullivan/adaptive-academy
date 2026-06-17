<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { theme } from '$lib/theme.svelte';
  import { topics } from '$lib/topics.svelte';
  import Rail from '$lib/shell/Rail.svelte';

  let { children } = $props();
  let ready = $state(false);

  onMount(async () => {
    theme.init();
    try {
      await topics.load();
    } catch (e) {
      console.error('Failed to load topics', e);
    }
    ready = true;
  });
</script>

<div class="flex min-h-screen">
  <Rail />
  <main class="min-w-0 flex-1">
    {#if ready}
      {@render children()}
    {:else}
      <div class="grid h-screen place-items-center">
        <div class="flex flex-col items-center gap-3 text-muted">
          <svg viewBox="0 0 32 32" class="size-8 animate-spin" style="animation-duration:1.6s">
            <circle cx="16" cy="16" r="12" fill="none" stroke="var(--border)" stroke-width="2" />
            <path d="M16 4a12 12 0 0 1 12 12" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
          </svg>
          <span class="eyebrow">calibrating</span>
        </div>
      </div>
    {/if}
  </main>
</div>
