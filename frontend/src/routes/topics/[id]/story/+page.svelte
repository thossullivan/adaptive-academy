<script lang="ts">
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import type { Story } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Markdown } from '$lib/ui';

  const topicId = Number($page.params.id);
  let story = $state<Story | null>(null);
  let busy = $state(false);
  let error = $state('');

  async function compose() {
    busy = true;
    error = '';
    try {
      story = await api.makeStory(topicId);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  const facts = $derived(story?.facts ?? null);
</script>

<Page eyebrow="Progress story" title="Your build-in-public chapter" lead="A generation-first narrative of how far you've come — grounded in your real numbers, honest about the gaps." width="normal">
  {#snippet actions()}
    <Button onclick={compose} disabled={busy}>{busy ? 'Composing…' : story ? 'Recompose' : 'Compose my story'}</Button>
  {/snippet}

  {#if error}
    <Card pad class="border-l-2 border-danger"><p class="text-sm text-danger">Couldn't compose the story: {error}</p></Card>
  {/if}

  {#if busy && !story}
    <div class="grid place-items-center py-24">
      <div class="flex flex-col items-center gap-3 text-muted">
        <svg viewBox="0 0 32 32" class="size-7 animate-spin" style="animation-duration:1.4s">
          <circle cx="16" cy="16" r="12" fill="none" stroke="var(--border)" stroke-width="2" />
          <path d="M16 4a12 12 0 0 1 12 12" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
        </svg>
        <span class="eyebrow">reading your trajectory…</span>
      </div>
    </div>
  {:else if story}
    <article class="flex flex-col gap-6 rise">
      <Card accent pad>
        <span class="eyebrow text-accent">✶ this chapter</span>
        <h2 class="mt-2 font-display text-3xl leading-tight text-fg">{story.headline}</h2>
        <div class="mt-5 flex flex-col gap-4">
          {#each story.narrative as para}
            <p class="text-[0.95rem] leading-relaxed text-fg-dim"><Markdown text={para} block /></p>
          {/each}
        </div>
      </Card>

      {#if story.highlights.length}
        <div class="grid gap-2.5 sm:grid-cols-2">
          {#each story.highlights as h}
            <div class="flex items-start gap-2.5 rounded-[var(--radius-md)] border border-border bg-surface-2 p-3">
              <span class="mt-0.5 text-accent">→</span>
              <Markdown text={h} class="text-sm text-fg-dim" />
            </div>
          {/each}
        </div>
      {/if}

      {#if facts}
        <Card pad eyebrow="Grounded in" title="The numbers behind the story">
          <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {#each [
              { l: 'Progress', v: `${facts.progress_pct}%`, h: `${facts.items_done}/${facts.items_total} steps` },
              { l: 'Assessments', v: facts.assessments_count, h: facts.mean_score == null ? 'no mean yet' : `mean ${Math.round(facts.mean_score * 100)}%` },
              { l: 'Days active', v: facts.span_days, h: `${facts.phases_completed}/${facts.phases_total} phases` },
              { l: 'Solid concepts', v: facts.concepts_solid.length, h: `${facts.load_bearing_shaky.length} shaky load-bearing` }
            ] as s}
              <div>
                <div class="eyebrow">{s.l}</div>
                <div class="nums mt-1 font-display text-2xl text-fg">{s.v}</div>
                <div class="text-xs text-faint">{s.h}</div>
              </div>
            {/each}
          </div>
          {#if facts.calibration_note}
            <div class="mt-4 border-t border-border pt-3">
              <Badge tone={facts.calibration_note.includes('well') ? 'success' : 'warn'} dot>calibration: {facts.calibration_note}</Badge>
            </div>
          {/if}
        </Card>
      {/if}
    </article>
  {:else}
    <Card accent pad class="text-center">
      <div class="py-12">
        <div class="mx-auto mb-4 grid size-14 place-items-center rounded-full border border-border bg-surface text-2xl text-accent">✶</div>
        <h2 class="text-xl text-fg">Compose your progress story</h2>
        <p class="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
          An agent reads your assessments, deltas, shipped artifacts, and calibration, then writes the build-in-public
          chapter of where you are — wins and shaky spots both.
        </p>
        <div class="mt-6"><Button onclick={compose} size="lg" disabled={busy}>{busy ? 'Composing…' : 'Compose my story'}</Button></div>
      </div>
    </Card>
  {/if}
</Page>
