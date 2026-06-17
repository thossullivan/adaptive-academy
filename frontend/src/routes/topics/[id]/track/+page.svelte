<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { canShip } from '$lib/ship';
  import type { Curriculum, ShipResult } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Markdown, Input, Textarea } from '$lib/ui';

  const topicId = Number($page.params.id);
  let cur = $state<Curriculum | null>(null);
  let loading = $state(true);
  const cycle: Record<string, string> = { todo: 'doing', doing: 'done', done: 'todo' };

  // Ship-it (per deliverable) state.
  let shipOpen = $state<Record<number, boolean>>({});
  let shipUrl = $state<Record<number, string>>({});
  let shipContent = $state<Record<number, string>>({});
  let shipResult = $state<Record<number, ShipResult>>({});
  let shipping = $state<number | null>(null);

  async function ship(d: { id: number }) {
    const content = shipContent[d.id] ?? '';
    const url = shipUrl[d.id] ?? '';
    if (!canShip(url, content) || shipping === d.id) return;
    shipping = d.id;
    try {
      const r = await api.shipDeliverable(d.id, url, content);
      shipResult[d.id] = r;
      // Persist the shipped state on the curriculum so the badge sticks.
      if (cur) {
        for (const p of cur.phases) {
          if (p.deliverable?.id === d.id) {
            p.deliverable.review_verdict = r.verdict;
            p.deliverable.artifact_url = shipUrl[d.id] ?? p.deliverable.artifact_url;
          }
        }
      }
    } finally {
      shipping = null;
    }
  }

  const statusTone: Record<string, 'neutral' | 'accent' | 'success'> = {
    todo: 'neutral',
    doing: 'accent',
    done: 'success'
  };
  const typeGlyph: Record<string, string> = { read: '▢', watch: '▷', build: '◈', write: '✎', do: '◆' };

  onMount(async () => {
    try {
      cur = await api.getCurriculum(topicId);
    } catch {
      cur = null;
    }
    loading = false;
  });

  async function toggle(itemId: number, status: string) {
    const next = cycle[status] ?? 'todo';
    const updated = await api.updateItem(itemId, { status: next });
    if (!cur) return;
    for (const p of cur.phases) for (const it of p.items) if (it.id === itemId) it.status = updated.status;
  }

  async function exportMd() {
    const md = await api.exportCurriculumMd(topicId);
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `track-${topicId}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function phaseProgress(items: { status: string }[]) {
    const done = items.filter((i) => i.status === 'done').length;
    return items.length ? Math.round((done / items.length) * 100) : 0;
  }
</script>

<Page eyebrow="Phased track" title={cur?.track.title ?? 'Track'} lead={cur?.track.overview ?? ''} width="normal">
  {#snippet actions()}
    <Button variant="outline" href="/topics/{topicId}/assess">Assess</Button>
    <Button variant="ghost" onclick={exportMd}>Export .md</Button>
  {/snippet}

  {#if loading}
    <div class="grid place-items-center py-24"><span class="eyebrow animate-pulse">loading track…</span></div>
  {:else if !cur}
    <Card accent class="text-center" pad>
      <div class="py-10">
        <h2 class="text-xl text-fg">No curriculum yet</h2>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">Generate one from your reviewed sources.</p>
        <div class="mt-6"><Button href="/topics/{topicId}/review">Go to Sources →</Button></div>
      </div>
    </Card>
  {:else}
    <div class="flex flex-col gap-4">
      {#each cur.phases as p, idx (p.id)}
        <Card class="rise" pad>
          <div class="mb-4 flex items-start justify-between gap-4">
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span class="grid size-7 shrink-0 place-items-center rounded-full border border-border-strong font-mono text-xs text-accent">{idx + 1}</span>
                <h2 class="truncate text-lg text-fg">{p.title}</h2>
              </div>
              <div class="mt-1.5 flex flex-wrap items-center gap-1.5 pl-9">
                {#if p.est_hours}<span class="eyebrow">{p.est_hours}</span>{/if}
                {#each p.flags as f}<Badge tone="neutral" mono>{f}</Badge>{/each}
              </div>
            </div>
            <div class="shrink-0 text-right">
              <div class="nums font-display text-2xl text-fg">{phaseProgress(p.items)}%</div>
              <div class="eyebrow !text-[0.55rem]">{p.items.filter((i) => i.status === 'done').length}/{p.items.length}</div>
            </div>
          </div>

          <ul class="flex flex-col">
            {#each p.items as it (it.id)}
              <li
                class="group flex items-center gap-3 rounded-[var(--radius-sm)] px-2 py-2 transition-colors hover:bg-surface-2 {it.is_remediation ? 'border-l-2 border-warn pl-3' : ''}"
              >
                <button
                  onclick={() => toggle(it.id, it.status)}
                  class="grid size-5 shrink-0 place-items-center rounded-[var(--radius-xs)] border transition-colors"
                  style:border-color={it.status === 'done' ? 'var(--success)' : 'var(--border-strong)'}
                  style:background={it.status === 'done' ? 'var(--success)' : it.status === 'doing' ? 'var(--accent-wash)' : 'transparent'}
                  title="status: {it.status} (click to advance)"
                  aria-label="toggle status"
                >
                  {#if it.status === 'done'}
                    <svg viewBox="0 0 16 16" class="size-3.5 text-bg" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 8l3.5 3.5L13 5" stroke-linecap="round" stroke-linejoin="round" /></svg>
                  {:else if it.status === 'doing'}
                    <span class="size-2 rounded-full bg-accent"></span>
                  {/if}
                </button>
                <span class="shrink-0 font-mono text-xs text-faint" title={it.type}>{typeGlyph[it.type] ?? '·'}</span>
                <Markdown text={it.text} class="min-w-0 flex-1 text-sm {it.status === 'done' ? 'text-faint line-through' : 'text-fg-dim'}" />
                {#if it.is_remediation}<Badge tone="warn" mono>remediation</Badge>{/if}
              </li>
            {/each}
          </ul>

          {#if p.deliverable}
            {@const d = p.deliverable}
            <div class="mt-3 rounded-[var(--radius-md)] border border-[color-mix(in_oklab,var(--accent)_30%,transparent)] bg-accent-wash p-3.5">
              <div class="flex items-center gap-2">
                <span class="text-accent">🎯</span>
                <span class="eyebrow !text-accent">Ship · {p.deliverable.kind}</span>
              </div>
              <p class="mt-1.5 text-sm text-fg"><Markdown text={p.deliverable.text} /></p>
              {#if p.deliverable.acceptance_criteria.length}
                <ul class="mt-2 flex flex-col gap-1">
                  {#each p.deliverable.acceptance_criteria as c}
                    <li class="flex items-start gap-2 text-xs text-muted"><span class="shrink-0 text-accent-dim">▸</span><Markdown text={c} /></li>
                  {/each}
                </ul>
              {/if}

              <!-- Ship it -->
              <div class="mt-3 border-t border-[color-mix(in_oklab,var(--accent)_20%,transparent)] pt-3">
                {#if d.review_verdict && !shipOpen[d.id]}
                  <div class="flex flex-wrap items-center gap-2 text-xs">
                    <Badge tone="success" dot>⚒ shipped</Badge>
                    {#if d.artifact_url}<a href={d.artifact_url} target="_blank" rel="noreferrer" class="text-accent underline">artifact ↗</a>{/if}
                    <span class="text-muted">{d.review_verdict}</span>
                    <button class="eyebrow ml-auto transition-colors hover:text-fg-dim" onclick={() => (shipOpen[d.id] = true)}>re-ship</button>
                  </div>
                {:else if !shipOpen[d.id]}
                  <Button variant="outline" size="sm" onclick={() => (shipOpen[d.id] = true)}>⚒ Ship it for review</Button>
                {:else}
                  <div class="flex flex-col gap-2">
                    <Input bind:value={shipUrl[d.id]} placeholder="Artifact URL (repo / blog / notebook)" />
                    <p class="text-xs text-fg-dim">
                      Supported hosts (GitHub, GitLab, arXiv, HuggingFace, Kaggle, Medium, Substack…) are
                      fetched automatically — paste below only to add context or if the URL isn't public.
                    </p>
                    <Textarea bind:value={shipContent[d.id]} rows={6} placeholder="Optionally paste the artifact — key code, the writeup, the ablation table. Graded against the acceptance criteria above." />
                    <div class="flex items-center gap-2">
                      <Button size="sm" onclick={() => ship(d)} disabled={shipping === d.id || !canShip(shipUrl[d.id] ?? '', shipContent[d.id] ?? '')}>
                        {shipping === d.id ? 'Reviewing…' : 'Ship & review'}
                      </Button>
                      <button class="eyebrow transition-colors hover:text-fg-dim" onclick={() => (shipOpen[d.id] = false)}>cancel</button>
                    </div>
                  </div>
                {/if}

                {#if shipResult[d.id]}
                  {@const r = shipResult[d.id]}
                  <div class="mt-2 rounded-[var(--radius-sm)] border border-border bg-surface p-3 text-sm">
                    <div class="flex items-center gap-2">
                      <Badge tone={r.score >= 0.7 ? 'success' : r.score >= 0.45 ? 'accent' : 'danger'} dot>{Math.round(r.score * 100)}%</Badge>
                      <span class="text-fg-dim">{r.verdict}</span>
                    </div>
                    {#if r.gaps.length}
                      <ul class="mt-2 flex flex-col gap-1">
                        {#each r.gaps as g}<li class="flex items-start gap-2 text-xs text-muted"><span class="text-warn">▸</span>{g}</li>{/each}
                      </ul>
                    {/if}
                    {#if r.concepts.length}<p class="mt-2 text-xs text-faint">Counts toward: {r.concepts.join(' · ')}</p>{/if}
                  </div>
                {/if}
              </div>
            </div>
          {/if}
        </Card>
      {/each}

      {#if cur.sidebars.length}
        <div class="grid gap-3 md:grid-cols-2">
          {#each cur.sidebars as s (s.id)}
            <Card pad class="border-l-2 border-info">
              <div class="flex items-center gap-2">
                <span class="eyebrow !text-info">{s.kind}</span>
              </div>
              <h3 class="mt-1 text-base text-fg">{s.title}</h3>
              <p class="mt-1.5 text-sm leading-relaxed text-muted"><Markdown text={s.body} block /></p>
            </Card>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</Page>
