<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { formatWhen, settledSave } from '$lib/notebook';
  import type { Notebook, NotebookConcept } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, NotebookItems, NotesEditor } from '$lib/ui';
  import { cn } from '$lib/utils';

  // The topic's concepts that have notes or work, and one concept's notebook: My notes (to
  // edit) and its attempts, graded explanations, and worked solutions, newest first.
  // ?concept=ID picks the concept (the Tutor's notes panel links here).
  const topicId = Number($page.params.id);
  let concepts = $state<NotebookConcept[] | null>(null);
  let listError = $state('');
  let notebook = $state<Notebook | null>(null);
  let notebookError = $state('');
  let seq = 0;

  const wanted = $derived(Number($page.url.searchParams.get('concept')) || null);
  const selectedId = $derived(wanted ?? concepts?.[0]?.concept_id ?? null);

  onMount(async () => {
    try {
      concepts = (await api.getTopicNotebook(topicId)).concepts;
    } catch (e) {
      listError = e instanceof Error ? e.message : String(e);
      concepts = [];
    }
  });

  $effect(() => {
    const id = selectedId;
    if (id == null) return;
    load(id);
  });

  async function load(id: number) {
    const mine = ++seq;
    notebookError = '';
    try {
      await settledSave(id); // never show text older than a save still on its way
      const nb = await api.getNotebook(id);
      if (mine !== seq) return;
      // Only this topic's concepts: a stale or foreign ?concept= shows nothing.
      notebook = nb.topic_id === topicId ? nb : null;
      if (!notebook) notebookError = 'That concept is not part of this topic.';
    } catch (e) {
      if (mine === seq) {
        notebook = null;
        notebookError = e instanceof Error ? e.message : String(e);
      }
    }
  }

  function counts(c: NotebookConcept): string {
    const bits = [];
    if (c.has_note) bits.push('notes');
    if (c.attempts) bits.push(`${c.attempts} attempt${c.attempts === 1 ? '' : 's'}`);
    if (c.explanations) bits.push(`${c.explanations} explanation${c.explanations === 1 ? '' : 's'}`);
    if (c.solutions) bits.push(`${c.solutions} solution${c.solutions === 1 ? '' : 's'}`);
    return bits.join(' · ');
  }

  function onsaved(note: { concept_id: number; body: string; updated_at: string }) {
    if (!concepts) return;
    const row = concepts.find((c) => c.concept_id === note.concept_id);
    if (row) {
      row.has_note = !!note.body.trim();
    } else if (notebook) {
      concepts = [
        {
          concept_id: note.concept_id,
          name: notebook.concept_name,
          has_note: !!note.body.trim(),
          attempts: notebook.counts.attempts,
          explanations: notebook.counts.explanations,
          solutions: notebook.counts.solutions,
          last_activity_at: note.updated_at
        },
        ...concepts
      ];
    }
  }
</script>

<svelte:head><title>Notebook · Adaptive Academy</title></svelte:head>

<Page
  eyebrow="Library"
  title="Notebook"
  lead="Your notes and your work on each concept in one place, newest first. When a vault is set on the Vault page, each concept's note in Obsidian gets the same notebook."
  width="wide"
>
  {#if concepts === null}
    <p class="text-sm text-muted">Loading…</p>
  {:else if listError}
    <p class="text-sm text-danger" role="alert">Couldn't load the notebook. {listError}</p>
  {:else if !concepts.length && selectedId == null}
    <Card eyebrow="Nothing here yet" title="Start a notebook">
      <p class="text-sm leading-relaxed text-muted">
        Concepts show up here once they have notes or work. Open the
        <a class="text-accent underline underline-offset-2" href="/topics/{topicId}/tutor">Tutor</a>, press Notes to write
        your own, or submit an attempt. Graded explanations from
        <a class="text-accent underline underline-offset-2" href="/topics/{topicId}/assess">Assess</a> and
        <a class="text-accent underline underline-offset-2" href="/topics/{topicId}/teach">Teach</a> appear here too.
      </p>
    </Card>
  {:else}
    <div class="grid min-w-0 gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <nav aria-label="Concepts with notes or work" class="min-w-0">
        {#if concepts.length}
          <ul class="flex flex-col gap-1" data-testid="notebook-concepts">
            {#each concepts as c (c.concept_id)}
              {@const active = c.concept_id === selectedId}
              <li>
                <a
                  href="?concept={c.concept_id}"
                  aria-current={active ? 'page' : undefined}
                  class={cn(
                    'flex flex-col gap-0.5 rounded-[var(--radius-sm)] border px-3 py-2 text-sm transition-colors hover:bg-surface-2',
                    active ? 'border-accent bg-surface-2 text-fg' : 'border-transparent text-fg-dim'
                  )}
                >
                  <span class="[overflow-wrap:anywhere]">{c.name}</span>
                  <span class="text-xs text-muted">{counts(c)}</span>
                </a>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="text-sm text-muted">No other concepts have notes or work yet.</p>
        {/if}
      </nav>

      <section class="flex min-w-0 flex-col gap-5" aria-labelledby="notebook-concept" aria-busy={!notebook && !notebookError}>
        {#if notebook}
          <div>
            <h2 id="notebook-concept" class="text-2xl text-fg [overflow-wrap:anywhere]">{notebook.concept_name}</h2>
            {#if notebook.items.length}
              <p class="mt-1 text-xs text-muted">Latest work {formatWhen(notebook.items[0].created_at)}</p>
            {/if}
          </div>
          <Card>
            {#key notebook.concept_id}
              <NotesEditor
                conceptId={notebook.concept_id}
                conceptName={notebook.concept_name}
                saved={notebook.note?.body ?? ''}
                savedAt={notebook.note?.updated_at ?? null}
                {onsaved}
              />
            {/key}
          </Card>
          <NotebookItems items={notebook.items} {topicId} conceptId={notebook.concept_id} />
        {:else if notebookError}
          <h2 id="notebook-concept" class="sr-only">Notebook</h2>
          <p class="text-sm text-danger" role="alert">{notebookError}</p>
        {:else}
          <h2 id="notebook-concept" class="sr-only">Notebook</h2>
          <p class="text-sm text-muted">Loading…</p>
        {/if}
      </section>
    </div>
  {/if}
</Page>
