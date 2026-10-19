<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { PaperProbe } from '$lib/types';
  import { unanswered } from '$lib/paper-probe';
  import { Badge, Button, Card } from '$lib/ui';

  const pid = Number($page.params.pid);
  let probe = $state<PaperProbe | null>(null);
  let answers = $state<Record<number, string>>({});
  let loading = $state(true);
  let error = $state('');
  let submitting = $state(false);

  onMount(async () => {
    try {
      probe = await api.getPaperProbe(pid);
      for (const a of probe.answers ?? []) answers[a.question_index] = a.content;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  });

  async function submit() {
    if (!probe || submitting) return;
    submitting = true;
    error = '';
    try {
      for (const q of probe.questions) {
        await api.answerPaperProbe(pid, q.index, answers[q.index] ?? '');
      }
      probe = await api.submitPaperProbe(pid);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      submitting = false;
    }
  }
</script>

<svelte:head><title>Paper probe · Adaptive Academy</title></svelte:head>

<div class="mx-auto max-w-3xl px-6 py-8 md:px-10">
  {#if loading}
    <p class="text-sm text-muted">Loading…</p>
  {:else if error && !probe}
    <p class="text-sm text-danger" role="alert">Couldn’t load probe: {error}</p>
  {:else if probe}
    <header class="mb-6 flex flex-wrap items-start gap-3">
      <div class="min-w-0 flex-1">
        <div class="eyebrow mb-1">Paper probe</div>
        <h1 class="text-lg text-fg">{probe.paper.title}</h1>
        {#if probe.paper.url}
          <a class="text-xs text-accent hover:underline" href={probe.paper.url} target="_blank"
            rel="noreferrer">{probe.paper.url}</a>
        {/if}
      </div>
      <Badge tone={probe.status === 'graded' ? 'success' : 'info'} dot>{probe.status}</Badge>
    </header>

    {#if probe.status !== 'graded'}
      <div class="flex flex-col gap-5">
        {#each probe.questions as q (q.index)}
          <Card>
            <div class="eyebrow mb-1.5 text-accent">{q.axis}</div>
            <p class="mb-2 text-sm leading-relaxed text-fg">{q.prompt}</p>
            <textarea
              bind:value={answers[q.index]}
              rows="4"
              placeholder="Your answer — generate your own critique before submitting…"
              class="w-full resize-y rounded-[var(--radius-md)] border border-control-border bg-surface-2 px-3.5 py-3 text-sm leading-relaxed text-fg placeholder:text-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--ring)]"
            ></textarea>
          </Card>
        {/each}
        <div class="flex items-center gap-3">
          <Button size="lg" onclick={submit} disabled={submitting}>
            {submitting ? 'Grading…' : 'Submit for grading'}
          </Button>
          {#if unanswered(probe.questions, answers) > 0}
            <span class="text-xs text-muted">{unanswered(probe.questions, answers)} unanswered</span>
          {/if}
        </div>
        {#if error}<p class="text-sm text-danger" role="alert">{error}</p>{/if}
      </div>
    {:else}
      <Card>
        <div class="eyebrow mb-2">Outcome</div>
        {#if probe.outcome}
          <p class="text-sm font-medium text-fg">{probe.outcome.result}</p>
          <p class="mt-1 text-sm leading-relaxed text-muted">{probe.outcome.summary}</p>
        {/if}
        {#if probe.scorecard?.length}
          <div class="mt-4 overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="text-left text-xs text-muted">
                  <th class="py-1 pr-4 font-normal">Concept</th>
                  <th class="py-1 pr-4 font-normal">Score</th>
                  <th class="py-1 pr-4 font-normal">Verdict</th>
                  <th class="py-1 font-normal">Gaps</th>
                </tr>
              </thead>
              <tbody>
                {#each probe.scorecard as row (row.concept_id)}
                  <tr class="border-t border-border/50">
                    <td class="py-1.5 pr-4 text-fg">{row.concept}</td>
                    <td class="py-1.5 pr-4">{Math.round(row.score * 100)}%</td>
                    <td class="py-1.5 pr-4 text-muted">{row.verdict}</td>
                    <td class="py-1.5 text-muted">{row.gaps.join(', ') || '—'}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
        <div class="mt-4">
          <a class="text-sm text-accent hover:underline" href={`/programs/${probe.program_id}`}
            >← Back to program</a>
        </div>
      </Card>
    {/if}
  {/if}
</div>
