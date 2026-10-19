<script lang="ts">
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { theme } from '$lib/theme.svelte';
  import { topics } from '$lib/topics.svelte';
  import Rail from '$lib/shell/Rail.svelte';
  import MobileNav from '$lib/shell/MobileNav.svelte';
  import Toaster from '$lib/ui/Toaster.svelte';

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

<!-- Phone: top bar + drawer stacked over the page. md+: the static rail beside it. -->
<div class="flex min-h-screen flex-col md:flex-row">
  <MobileNav />
  <Rail class="hidden md:flex" />
  <main class="min-w-0 flex-1">
    {#if ready}
      <!-- Re-key on the topic id so switching topics on the SAME route (e.g.
           /topics/1/wayfinder → /topics/2/wayfinder) remounts the page and reloads
           its data, instead of showing stale data until a manual refresh. -->
      {#key $page.params.id}
        {@render children()}
      {/key}
    {:else}
      <div class="grid h-[calc(100dvh-3.5rem)] place-items-center md:h-screen">
        <div class="flex flex-col items-center gap-3 text-muted" role="status">
          <svg viewBox="0 0 32 32" class="size-8 animate-spin" style="animation-duration:1.6s" aria-hidden="true">
            <circle cx="16" cy="16" r="12" fill="none" stroke="var(--border)" stroke-width="2" />
            <path d="M16 4a12 12 0 0 1 12 12" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
          </svg>
          <span class="eyebrow">calibrating</span>
        </div>
      </div>
    {/if}
  </main>
</div>

<Toaster />
