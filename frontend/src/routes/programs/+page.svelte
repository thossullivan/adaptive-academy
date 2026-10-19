<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Program } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge } from '$lib/ui';

  let programs = $state<Program[]>([]);
  let loading = $state(true);
  let error = $state('');
  onMount(async () => {
    try {
      programs = await api.listPrograms();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head><title>Programs · Adaptive Academy</title></svelte:head>

<Page
  eyebrow="All topics"
  title="Programs"
  lead="Long-horizon goals: researched milestone maps with verified-depth gates."
>
  {#snippet actions()}
    <Button href="/programs/new">New program</Button>
  {/snippet}
  {#if loading}
    <p class="text-sm text-muted" role="status">Loading…</p>
  {:else if error}
    <p class="text-sm text-danger" role="alert">Couldn’t load programs: {error}</p>
  {:else if programs.length === 0}
    <Card>
      <p class="text-sm text-muted">
        No programs yet. A program owns a substantial goal — e.g. PhD-level CS prep —
        as a sequence of gated milestones, each spawning full topics when you start them.
      </p>
    </Card>
  {:else}
    <div class="flex flex-col gap-3">
      {#each programs as p (p.id)}
        <a href={`/programs/${p.id}`} class="block min-w-0">
          <Card>
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="truncate text-fg">{p.title}</div>
                <div class="mt-1 line-clamp-2 text-sm text-muted">{p.goal_statement}</div>
              </div>
              <div class="shrink-0"><Badge>{p.milestone_count} milestones</Badge></div>
            </div>
          </Card>
        </a>
      {/each}
    </div>
  {/if}
</Page>
