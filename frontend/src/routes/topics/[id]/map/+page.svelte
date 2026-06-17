<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api, conceptLevels } from '$lib/api';
  import type { Concept, Foundation } from '$lib/types';
  import { LEVEL_LABEL, levelColor } from '$lib/utils';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge } from '$lib/ui';
  import Constellation from '$lib/charts/Constellation.svelte';

  const topicId = Number($page.params.id);
  let loading = $state(true);
  let concepts = $state<Concept[]>([]);
  let levels = $state<Record<number, string>>({});
  let nodes = $state<{ id: number; name: string; level: string; loadBearing: boolean; hasAnchor: boolean }[]>([]);
  let links = $state<{ source: number; target: number }[]>([]);
  let edgeCount = $state(0);

  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

  onMount(async () => {
    let foundation: Foundation | null = null;
    try {
      const cur = await api.getCurriculum(topicId);
      concepts = cur.concepts;
    } catch {
      concepts = [];
    }
    try {
      foundation = await api.getFoundation(topicId);
    } catch {
      foundation = null;
    }
    levels = await conceptLevels(concepts.map((c) => c.id));

    nodes = concepts.map((c) => ({
      id: c.id,
      name: c.name,
      level: levels[c.id] ?? 'unknown',
      loadBearing: c.is_load_bearing,
      hasAnchor: !!c.has_anchor
    }));

    // Build prerequisite edges from the foundation's concept map, matching names leniently.
    const byNorm = new Map(concepts.map((c) => [norm(c.name), c.id]));
    const out: { source: number; target: number }[] = [];
    if (foundation?.prerequisite_map) {
      for (const [name, prereqs] of Object.entries(foundation.prerequisite_map)) {
        const targetId = byNorm.get(norm(name));
        if (targetId == null || !Array.isArray(prereqs)) continue;
        for (const pre of prereqs as string[]) {
          const sourceId = byNorm.get(norm(String(pre)));
          if (sourceId != null && sourceId !== targetId) out.push({ source: sourceId, target: targetId });
        }
      }
    }
    links = out;
    edgeCount = out.length;
    loading = false;
  });

  let selected = $state<number | null>(null);
  const selectedConcept = $derived(concepts.find((c) => c.id === selected) ?? null);

  function openTutor(id: number) {
    goto(`/topics/${topicId}/tutor?concept=${id}`);
  }

  const counts = $derived({
    high: nodes.filter((n) => n.level === 'high').length,
    medium: nodes.filter((n) => n.level === 'medium').length,
    low: nodes.filter((n) => n.level === 'low').length,
    unknown: nodes.filter((n) => n.level === 'unknown').length
  });
</script>

<Page eyebrow="Concept constellation" title="The shape of what you're learning" lead="Each star is a concept — sized by how load-bearing it is, lit by how well you know it. Lines are prerequisites." width="wide">
  {#if loading}
    <div class="grid place-items-center py-24"><span class="eyebrow animate-pulse">mapping the sky…</span></div>
  {:else if !nodes.length}
    <Card accent pad class="text-center">
      <div class="py-10">
        <h2 class="text-xl text-fg">No concepts to map</h2>
        <p class="mx-auto mt-2 max-w-sm text-sm text-muted">Generate a curriculum to populate your constellation.</p>
        <div class="mt-6"><Button href="/topics/{topicId}/review">Go to Sources →</Button></div>
      </div>
    </Card>
  {:else}
    <div class="grid gap-4 lg:grid-cols-[1fr_280px]">
      <div class="rise">
        <Constellation {nodes} {links} onselect={(id) => (selected = id)} />
      </div>

      <div class="flex flex-col gap-4">
        <Card pad eyebrow="Survey" title="{nodes.length} concepts">
          <div class="flex flex-col gap-2">
            {#each [['high', counts.high], ['medium', counts.medium], ['low', counts.low], ['unknown', counts.unknown]] as [lv, n]}
              <div class="flex items-center gap-2 text-sm">
                <span class="size-2.5 rounded-full" style:background={levelColor(lv as string)}></span>
                <span class="flex-1 text-fg-dim">{LEVEL_LABEL[lv as string]}</span>
                <span class="nums text-muted">{n}</span>
              </div>
            {/each}
            <div class="mt-1 border-t border-border pt-2 text-xs text-faint">{edgeCount} prerequisite links</div>
          </div>
        </Card>

        {#if selectedConcept}
          <Card accent pad class="rise">
            <span class="eyebrow">selected</span>
            <h3 class="mt-1 text-lg text-fg">{selectedConcept.name}</h3>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <Badge tone={levels[selectedConcept.id] === 'high' ? 'success' : levels[selectedConcept.id] === 'low' ? 'danger' : 'accent'} dot>
                {LEVEL_LABEL[levels[selectedConcept.id] ?? 'unknown']}
              </Badge>
              {#if selectedConcept.is_load_bearing}<Badge tone="accent" mono>load-bearing</Badge>{/if}
              {#if selectedConcept.has_anchor}<Badge tone="info" mono>has quiz</Badge>{/if}
            </div>
            <div class="mt-4 flex flex-col gap-2">
              <Button size="sm" onclick={() => openTutor(selectedConcept.id)}>Tutor on this →</Button>
              <Button size="sm" variant="outline" href="/topics/{topicId}/assess">Assess it</Button>
            </div>
          </Card>
        {:else}
          <Card pad class="text-center"><p class="py-6 text-sm text-faint">Click a star to focus a concept.</p></Card>
        {/if}
      </div>
    </div>
  {/if}
</Page>
