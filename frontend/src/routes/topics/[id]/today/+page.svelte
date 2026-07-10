<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api, conceptLevels } from '$lib/api';
  import type { Concept, Item, WindState, Comeback, ProgramContext } from '$lib/types';
  import { LEVEL_FILL, LEVEL_LABEL, levelColor } from '$lib/utils';
  import { gateBadge } from '$lib/programs';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge, Markdown, ComebackCard } from '$lib/ui';

  const topicId = Number($page.params.id);
  let loading = $state(true);
  let dueCount = $state(0);
  let decayCount = $state(0);
  let nextItems = $state<{ item: Item; phase: string }[]>([]);
  let weakest = $state<Concept | null>(null);
  let weakestLevel = $state('unknown');
  let allDone = $state(false);
  let wind = $state<WindState | null>(null);
  let comeback = $state<Comeback | null>(null);
  let programCtx = $state<ProgramContext | null>(null);

  onMount(async () => {
    let concepts: Concept[] = [];
    try {
      const cur = await api.getCurriculum(topicId);
      concepts = cur.concepts;
      const upcoming: { item: Item; phase: string }[] = [];
      let total = 0;
      for (const p of cur.phases) {
        for (const it of p.items) {
          total++;
          if (it.status !== 'done' && upcoming.length < 3) upcoming.push({ item: it, phase: p.title });
        }
      }
      nextItems = upcoming;
      allDone = total > 0 && upcoming.length === 0;
    } catch {
      nextItems = [];
    }

    try {
      const due = await api.listRetention(topicId, { due: true });
      dueCount = due.cards.length;
    } catch {
      dueCount = 0;
    }
    try {
      decayCount = (await api.listDecay(topicId)).items.length;
    } catch {
      decayCount = 0;
    }
    wind = await api.getWind(topicId).catch(() => null);
    comeback = await api.getComeback(topicId).catch(() => null);
    programCtx = await api.programContext(topicId).catch(() => null);

    // Shakiest load-bearing concept (unmeasured counts as a priority to probe).
    if (concepts.length) {
      const levels = await conceptLevels(concepts.map((c) => c.id));
      const lb = concepts.filter((c) => c.is_load_bearing);
      const pool = lb.length ? lb : concepts;
      pool.sort((a, b) => (LEVEL_FILL[levels[a.id]] ?? 0) - (LEVEL_FILL[levels[b.id]] ?? 0));
      weakest = pool[0] ?? null;
      if (weakest) weakestLevel = levels[weakest.id] ?? 'unknown';
    }
    loading = false;
  });

  const typeGlyph: Record<string, string> = { read: '▢', watch: '▷', build: '◈', write: '✎', do: '◆' };
</script>

<Page eyebrow="Today's session" title="What to do right now" lead="A focused loop assembled from where you actually are — warm up, build, probe, teach back." width="normal">
  {#if programCtx}
    <Card class="mb-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="min-w-0 text-sm">
          <a class="text-accent hover:underline" href={`/programs/${programCtx.program_id}`}>
            {programCtx.program_title}</a>
          <span class="text-muted"> / {programCtx.milestone_title}</span>
        </div>
        <Badge tone={gateBadge(programCtx.gate_status).tone}>{gateBadge(programCtx.gate_status).label}</Badge>
      </div>
      {#if programCtx.unverified.length > 0}
        <p class="mt-2 text-sm text-muted">
          Gate needs cold verification of:
          <span class="text-fg">{programCtx.unverified.slice(0, 3).join(', ')}</span>
          {#if programCtx.unverified.length > 3}&nbsp;+{programCtx.unverified.length - 3} more{/if}
          — run a Decay Check or ship an artifact.
        </p>
      {/if}
      {#if programCtx.revision_suggested}
        <p class="mt-2 text-sm text-muted">
          Leg verified —
          <a class="text-accent hover:underline" href={`/programs/${programCtx.program_id}`}>
            revise the map</a> with what you've learned?
        </p>
      {/if}
    </Card>
  {/if}
  {#if wind && comeback}
    <div class="mb-5"><ComebackCard {wind} {comeback} /></div>
  {/if}
  {#if loading}
    <div class="grid place-items-center py-24"><span class="eyebrow animate-pulse">composing your session…</span></div>
  {:else}
    <div class="flex flex-col gap-3">
      <!-- 1. Warm up -->
      <Card class="rise" pad>
        <div class="flex items-start gap-4">
          <span class="grid size-8 shrink-0 place-items-center rounded-full border border-border-strong font-mono text-sm text-accent">1</span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h2 class="text-lg text-fg">Warm up</h2>
              {#if decayCount}<Badge tone="accent" dot>{decayCount} decay check{decayCount > 1 ? 's' : ''}</Badge>{/if}
              <Badge tone={dueCount ? 'accent' : 'success'} dot>{dueCount ? `${dueCount} card${dueCount > 1 ? 's' : ''} due` : 'cards clear'}</Badge>
            </div>
            <p class="mt-1 text-sm text-muted">
              {#if decayCount}Unassisted recall checks are due — prove it still holds without the tutor.{:else if dueCount}Retrieval practice on cards due today — fast, before you build.{:else}No reviews due. Nice and clear.{/if}
            </p>
          </div>
          {#if dueCount || decayCount}<Button href="/topics/{topicId}/retention">Review →</Button>{/if}
        </div>
      </Card>

      <!-- 2. Build -->
      <Card class="rise" pad>
        <div class="flex items-start gap-4">
          <span class="grid size-8 shrink-0 place-items-center rounded-full border border-border-strong font-mono text-sm text-accent">2</span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h2 class="text-lg text-fg">Build</h2>
              {#if allDone}<Badge tone="success" dot>track complete</Badge>{/if}
            </div>
            {#if nextItems.length}
              <p class="mt-1 text-sm text-muted">Your next steps on the track:</p>
              <ul class="mt-2 flex flex-col gap-1.5">
                {#each nextItems as { item, phase }}
                  <li class="rounded-[var(--radius-sm)] border border-border bg-surface-2 px-3 py-2">
                    <div class="flex items-start gap-2">
                      <span class="mt-0.5 shrink-0 font-mono text-xs text-faint">{typeGlyph[item.type] ?? '·'}</span>
                      <Markdown text={item.text} class="min-w-0 flex-1 text-sm text-fg-dim" />
                    </div>
                    <div class="eyebrow mt-1 pl-5 !text-[0.55rem]">{phase}</div>
                  </li>
                {/each}
              </ul>
            {:else if allDone}
              <p class="mt-1 text-sm text-muted">Every step is done — time to ship and assess.</p>
            {:else}
              <p class="mt-1 text-sm text-muted">No track yet. Generate a curriculum to get build steps.</p>
            {/if}
          </div>
          <Button variant="outline" href="/topics/{topicId}/track">Open track →</Button>
        </div>
      </Card>

      <!-- 3. Probe -->
      <Card class="rise" pad>
        <div class="flex items-start gap-4">
          <span class="grid size-8 shrink-0 place-items-center rounded-full border border-border-strong font-mono text-sm text-accent">3</span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h2 class="text-lg text-fg">Probe</h2>
              {#if weakest}<Badge tone={weakestLevel === 'low' ? 'danger' : weakestLevel === 'unknown' ? 'neutral' : 'accent'} dot>{LEVEL_LABEL[weakestLevel]}</Badge>{/if}
            </div>
            {#if weakest}
              <p class="mt-1 text-sm text-muted">
                Test your shakiest load-bearing concept —
                <span class="font-medium" style:color={levelColor(weakestLevel)}>{weakest.name}</span>. Desirable difficulty: explain it cold.
              </p>
            {:else}
              <p class="mt-1 text-sm text-muted">No concepts to probe yet.</p>
            {/if}
          </div>
          {#if weakest}<Button href="/topics/{topicId}/assess">Assess →</Button>{/if}
        </div>
      </Card>

      <!-- 4. Teach back -->
      <Card class="rise" pad>
        <div class="flex items-start gap-4">
          <span class="grid size-8 shrink-0 place-items-center rounded-full border border-border-strong font-mono text-sm text-accent">4</span>
          <div class="min-w-0 flex-1">
            <h2 class="text-lg text-fg">Teach back</h2>
            <p class="mt-1 text-sm text-muted">
              {weakest ? `Work through ${weakest.name} with the tutor — it won't hand you the answer.` : 'Open the tutor to work a concept Socratically.'}
            </p>
          </div>
          <Button variant="outline" href={weakest ? `/topics/${topicId}/tutor?concept=${weakest.id}` : `/topics/${topicId}/tutor`}>Open tutor →</Button>
        </div>
      </Card>
    </div>
  {/if}
</Page>
