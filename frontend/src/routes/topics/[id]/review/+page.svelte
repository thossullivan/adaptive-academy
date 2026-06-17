<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { SourceDoc, Foundation, EventOut } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge } from '$lib/ui';
  import EventFeed from '$lib/shell/EventFeed.svelte';

  const topicId = Number($page.params.id);
  let foundation = $state<Foundation | null>(null);
  let sources = $state<SourceDoc[]>([]);
  let events = $state<EventOut[]>([]);
  let keep = $state<Record<number, boolean>>({});
  let busy = $state(false);
  let saved = $state(false);
  let generating = $state(false);
  let generatingAnchors = $state(false);
  let anchorCount = $state<number | null>(null);

  onMount(async () => {
    try {
      foundation = await api.getFoundation(topicId);
    } catch {
      foundation = null;
    }
    sources = await api.listSources(topicId, 'proposed');
    for (const s of sources) keep[s.id] = true;
    events = await api.listEvents(topicId);
  });

  const keptCount = $derived(sources.filter((s) => keep[s.id]).length);

  async function save() {
    busy = true;
    const accepted = sources.filter((s) => keep[s.id]).map((s) => s.id);
    const pruned = sources.filter((s) => !keep[s.id]).map((s) => s.id);
    try {
      await api.reviewSources(topicId, accepted, pruned);
      saved = true;
    } finally {
      busy = false;
    }
  }

  async function generate() {
    generating = true;
    try {
      await api.generateCurriculum(topicId);
      await goto(`/topics/${topicId}/track`);
    } finally {
      generating = false;
    }
  }

  async function generateAnchors() {
    generatingAnchors = true;
    try {
      const r = await api.generateAnchors(topicId);
      anchorCount = r.anchors.length;
    } finally {
      generatingAnchors = false;
    }
  }
</script>

<Page eyebrow="Researcher" title="Review reading list" lead="Curate the foundation before the CurriculumDirector builds your track. Keep what earns its place." width="normal">
  {#snippet actions()}
    <Button variant="outline" onclick={generateAnchors} disabled={generatingAnchors}>
      {generatingAnchors ? 'Generating…' : 'Generate quizzes'}
    </Button>
  {/snippet}

  <div class="flex flex-col gap-4">
    {#if foundation}
      <Card accent pad class="rise" eyebrow="Foundation" title="The lay of the land">
        <p class="text-sm leading-relaxed text-fg-dim">{foundation.overview}</p>
        {#if foundation.key_concepts.length}
          <div class="mt-3 flex flex-wrap gap-1.5">
            {#each foundation.key_concepts as c}<Badge tone="neutral">{c}</Badge>{/each}
          </div>
        {/if}
      </Card>
    {/if}

    {#if anchorCount != null}
      <p class="text-sm text-success">Generated {anchorCount} source-grounded quiz anchor(s).</p>
    {/if}

    <div class="flex items-center justify-between">
      <span class="eyebrow">{keptCount} of {sources.length} kept</span>
      {#if saved}<Badge tone="success" dot>saved</Badge>{/if}
    </div>

    <ul class="flex flex-col gap-2.5">
      {#each sources as s (s.id)}
        <li>
          <Card pad class="rise transition-opacity {keep[s.id] ? '' : 'opacity-45'}">
            <div class="flex items-start gap-3">
              <button
                onclick={() => (keep[s.id] = !keep[s.id])}
                class="mt-0.5 grid size-5 shrink-0 place-items-center rounded-[var(--radius-xs)] border transition-colors"
                style:border-color={keep[s.id] ? 'var(--accent)' : 'var(--border-strong)'}
                style:background={keep[s.id] ? 'var(--accent)' : 'transparent'}
                aria-label={keep[s.id] ? 'drop source' : 'keep source'}
              >
                {#if keep[s.id]}
                  <svg viewBox="0 0 16 16" class="size-3.5 text-accent-fg" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 8l3.5 3.5L13 5" stroke-linecap="round" stroke-linejoin="round" /></svg>
                {/if}
              </button>
              <div class="min-w-0 flex-1">
                <a href={s.url} target="_blank" rel="noreferrer" class="font-medium text-fg underline decoration-border underline-offset-2 transition-colors hover:decoration-accent">{s.title}</a>
                <div class="mt-1 flex flex-wrap items-center gap-1.5">
                  <Badge mono tone={s.tier === 1 ? 'accent' : 'neutral'}>tier {s.tier}</Badge>
                  <span class="eyebrow !text-[0.55rem]">{s.angle}</span>
                </div>
                {#if s.summary}<p class="mt-2 text-sm text-fg-dim">{s.summary}</p>{/if}
                {#if s.why}<p class="mt-1 text-sm text-muted"><span class="text-faint">Why:</span> {s.why}</p>{/if}
              </div>
            </div>
          </Card>
        </li>
      {/each}
    </ul>

    <div class="flex flex-wrap items-center gap-2">
      <Button onclick={save} disabled={busy || !sources.length}>{busy ? 'Saving…' : 'Save reading list'}</Button>
      {#if saved}
        <Button onclick={generate} disabled={generating}>{generating ? 'Generating curriculum…' : 'Generate curriculum →'}</Button>
      {/if}
    </div>

    {#if events.length}
      <Card pad eyebrow="Observability" title="What the agents did">
        <EventFeed {events} limit={20} />
      </Card>
    {/if}
  </div>
</Page>
