<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { toasts } from '$lib/toast.svelte';
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
  let error = $state('');
  let anchorCount = $state<number | null>(null);

  onMount(async () => {
    try {
      foundation = await api.getFoundation(topicId);
    } catch {
      foundation = null;
    }
    // Show proposed sources; once they've been saved (accepted), show those instead so the
    // curated list persists on a revisit — otherwise the page reads an empty "0 of 0 kept".
    sources = await api.listSources(topicId, 'proposed');
    if (!sources.length) {
      sources = await api.listSources(topicId, 'accepted');
      saved = sources.length > 0;
    }
    for (const s of sources) keep[s.id] = true;
    events = await api.listEvents(topicId);
  });

  const keptCount = $derived(sources.filter((s) => keep[s.id]).length);

  async function save() {
    busy = true;
    error = '';
    const accepted = sources.filter((s) => keep[s.id]).map((s) => s.id);
    const pruned = sources.filter((s) => !keep[s.id]).map((s) => s.id);
    try {
      await api.reviewSources(topicId, accepted, pruned);
      saved = true;
    } catch (e) {
      error = `Couldn't save the reading list: ${e}`;
    } finally {
      busy = false;
    }
  }

  async function generate() {
    generating = true;
    error = '';
    try {
      await api.generateCurriculum(topicId);
      toasts.show('Your track is ready.');
      await goto(`/topics/${topicId}/track`);
    } catch (e) {
      error = `Couldn't build the track: ${e}. Your reading list is saved, so it's safe to try again.`;
    } finally {
      generating = false;
    }
  }

  async function generateAnchors() {
    generatingAnchors = true;
    error = '';
    try {
      const r = await api.generateAnchors(topicId);
      anchorCount = r.anchors.length;
    } catch (e) {
      error = `Couldn't make the quizzes: ${e}`;
    } finally {
      generatingAnchors = false;
    }
  }
</script>

<svelte:head><title>Sources · Adaptive Academy</title></svelte:head>

<Page eyebrow="Sources" title="Your reading list" lead="The sources research found for this topic. Keep the ones worth your time, save the list, then build your track from it." width="normal">
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

    <p class="text-sm text-success empty:hidden" role="status">
      {#if anchorCount != null}Made {anchorCount} quiz question{anchorCount === 1 ? '' : 's'} from your sources.{/if}
    </p>

    <div class="flex items-center justify-between">
      <span class="eyebrow">{keptCount} of {sources.length} kept</span>
      <span role="status">{#if saved}<Badge tone="success" dot>saved</Badge>{/if}</span>
    </div>

    <ul class="flex flex-col gap-2.5">
      {#each sources as s (s.id)}
        <li>
          <!-- A dropped source stays readable (a translucent card failed text contrast): a
               dashed, unfilled card and a struck-through title mark it instead. -->
          <Card pad class="rise transition-colors {keep[s.id] ? '' : 'border-dashed !bg-transparent !shadow-none'}">
            <div class="flex items-start gap-3">
              <button
                type="button"
                role="checkbox"
                aria-checked={!!keep[s.id]}
                onclick={() => (keep[s.id] = !keep[s.id])}
                class="mt-0.5 grid size-5 shrink-0 place-items-center rounded-[var(--radius-xs)] border transition-colors"
                style:border-color={keep[s.id] ? 'var(--accent)' : 'var(--control-border)'}
                style:background={keep[s.id] ? 'var(--accent)' : 'transparent'}
                aria-label="Keep {s.title}"
              >
                {#if keep[s.id]}
                  <svg viewBox="0 0 16 16" class="size-3.5 text-accent-fg" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M3 8l3.5 3.5L13 5" stroke-linecap="round" stroke-linejoin="round" /></svg>
                {/if}
              </button>
              <div class="min-w-0 flex-1">
                <a href={s.url} target="_blank" rel="noreferrer" class="font-medium text-fg underline decoration-border underline-offset-2 transition-colors hover:decoration-accent {keep[s.id] ? '' : 'line-through'}">{s.title}<span class="sr-only"> (opens in a new tab)</span></a>
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
      <!-- One filled button: Save until the list is saved, then the next step, building the track. -->
      <Button variant={saved ? 'outline' : 'primary'} onclick={save} disabled={busy || !sources.length}>{busy ? 'Saving…' : 'Save reading list'}</Button>
      {#if saved}
        <Button onclick={generate} disabled={generating}>{generating ? 'Building your track…' : 'Build my track →'}</Button>
        {#if generating}
          <span class="text-xs text-faint" role="status">Planning the whole track. This can take a couple of minutes.</span>
        {/if}
      {/if}
    </div>

    {#if error}
      <p class="rounded-[var(--radius-sm)] border border-danger/40 bg-danger/10 px-3 py-2 text-sm" style:color="var(--danger)" role="alert">{error}</p>
    {/if}

    {#if events.length}
      <Card pad eyebrow="Agent log" title="What the agents did">
        <EventFeed {events} limit={20} />
      </Card>
    {/if}
  </div>
</Page>
