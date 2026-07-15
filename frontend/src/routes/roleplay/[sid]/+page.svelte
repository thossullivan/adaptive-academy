<script lang="ts">
  import { page } from '$app/stores';
  import { onMount, tick } from 'svelte';
  import { api } from '$lib/api';
  import { gateBadge } from '$lib/programs';
  import type { RoleplaySession, RoleplayTurnRow } from '$lib/types';
  import { Badge, Button, Card } from '$lib/ui';

  const sid = Number($page.params.sid);
  let session = $state<RoleplaySession | null>(null);
  let turns = $state<RoleplayTurnRow[]>([]);
  let loading = $state(true);
  let error = $state('');
  let input = $state('');
  let busy = $state(false);
  let ending = $state(false);
  let scroller: HTMLDivElement | null = null;

  onMount(async () => {
    try {
      session = await api.getRoleplay(sid);
      turns = session.turns ?? [];
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  });

  async function send() {
    if (!session || !input.trim() || busy || session.status === 'graded') return;
    const content = input;
    input = '';
    turns = [...turns, { role: 'user', content }];
    busy = true;
    error = '';
    await tick();
    scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    try {
      const r = await api.sendRoleplayTurn(sid, content);
      turns = [...turns, { role: 'persona', content: r.reply }];
      session = { ...session, status: r.status };
      await tick();
      scroller?.scrollTo({ top: scroller.scrollHeight, behavior: 'smooth' });
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function endAndScore() {
    if (!session || ending) return;
    ending = true;
    error = '';
    try {
      session = await api.endRoleplay(sid);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      ending = false;
    }
  }
</script>

<svelte:head><title>Spar · Adaptive Academy</title></svelte:head>

<div class="flex h-screen flex-col">
  <!-- Header -->
  <header class="flex flex-wrap items-center gap-3 border-b border-border px-6 py-4 md:px-10">
    <div class="min-w-0 flex-1">
      <div class="eyebrow mb-1">Roleplay examiner</div>
      {#if session?.brief_public?.persona}
        <h1 class="text-lg text-fg">{session.brief_public.persona}</h1>
      {/if}
      {#if session?.brief_public?.situation}
        <p class="mt-1 max-w-2xl text-sm leading-relaxed text-muted">{session.brief_public.situation}</p>
      {/if}
    </div>
    {#if session}
      <Badge tone={session.status === 'graded' ? 'success' : 'info'} dot>{session.status}</Badge>
    {/if}
  </header>

  <!-- Messages -->
  <div bind:this={scroller} class="flex-1 overflow-y-auto px-6 py-6 md:px-10">
    <div class="mx-auto flex max-w-3xl flex-col gap-4">
      {#if loading}
        <p class="text-sm text-muted">Loading…</p>
      {:else if error && !session}
        <p class="text-sm text-danger">Couldn’t load session: {error}</p>
      {:else if !turns.length}
        <div class="mt-12 text-center">
          <h2 class="text-2xl text-fg">The examiner is waiting</h2>
          <p class="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
            Open with your first move — the persona above will stay in character and probe your understanding.
          </p>
        </div>
      {/if}
      {#each turns as t, i (i)}
        <div class="flex {t.role === 'user' ? 'justify-end' : 'justify-start'}">
          <div
            class="max-w-[80%] whitespace-pre-wrap rounded-[var(--radius-lg)] px-4 py-3 text-sm leading-relaxed {t.role ===
            'user'
              ? 'rounded-br-sm bg-surface-3 text-fg'
              : 'rounded-bl-sm border border-border bg-surface text-fg-dim'}"
          >
            {#if t.role === 'persona'}<div class="eyebrow mb-1.5 !text-[0.55rem] text-accent">persona</div>{/if}
            {t.content}
          </div>
        </div>
      {/each}
      {#if busy}
        <div class="flex justify-start">
          <div class="flex items-center gap-1.5 rounded-[var(--radius-lg)] rounded-bl-sm border border-border bg-surface px-4 py-3">
            {#each [0, 1, 2] as d}
              <span class="size-1.5 animate-bounce rounded-full bg-accent" style:animation-delay="{d * 0.15}s"></span>
            {/each}
          </div>
        </div>
      {/if}

      {#if session?.status === 'graded'}
        <Card class="mt-4">
          <div class="eyebrow mb-2">Outcome</div>
          {#if session.outcome}
            <p class="text-sm font-medium text-fg">{session.outcome.result}</p>
            <p class="mt-1 text-sm leading-relaxed text-muted">{session.outcome.summary}</p>
          {/if}
          {#if session.scorecard?.length}
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
                  {#each session.scorecard as row (row.concept_id)}
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
            <a class="text-sm text-accent hover:underline" href={`/programs/${session.program_id}`}
              >← Back to program</a
            >
          </div>
        </Card>
      {/if}
    </div>
  </div>

  <!-- Composer -->
  {#if session && session.status !== 'graded'}
    <div class="border-t border-border bg-[color-mix(in_oklab,var(--surface)_40%,transparent)] px-6 py-4 backdrop-blur md:px-10">
      <form
        class="mx-auto flex max-w-3xl items-end gap-2"
        onsubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <textarea
          bind:value={input}
          rows="1"
          placeholder="Respond to the examiner…"
          disabled={busy || session.status === 'ended'}
          onkeydown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          class="max-h-40 min-h-[2.75rem] flex-1 resize-none rounded-[var(--radius-md)] border border-border bg-surface-2 px-3.5 py-3 text-sm leading-relaxed text-fg placeholder:text-faint transition-colors hover:border-border-strong focus:border-accent focus:outline-none disabled:opacity-50"
        ></textarea>
        <Button
          type="submit"
          size="lg"
          disabled={busy || session.status === 'ended' || !input.trim()}>Send</Button
        >
        {#if session.status === 'active' || session.status === 'ended'}
          <Button type="button" variant="outline" size="lg" onclick={endAndScore} disabled={ending}
            >{ending ? 'Scoring…' : 'End & score me'}</Button
          >
        {/if}
      </form>
      {#if error}<p class="mx-auto mt-2 max-w-3xl text-sm text-danger">{error}</p>{/if}
    </div>
  {/if}
</div>
