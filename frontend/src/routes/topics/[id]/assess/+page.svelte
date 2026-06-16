<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Curriculum, Assessment } from '$lib/types';

  const topicId = Number($page.params.id);
  let cur = $state<Curriculum | null>(null);
  let conceptId = $state<number | null>(null);
  let kind = $state('self_explanation');
  let response = $state('');
  let confidence = $state(70);
  let result = $state<Assessment | null>(null);
  let busy = $state(false);

  onMount(async () => {
    try { cur = await api.getCurriculum(topicId); } catch { cur = null; }
    if (cur?.concepts.length) conceptId = cur.concepts[0].id;
  });

  let remediating = $state(false);
  let remediatedCount = $state<number | null>(null);
  async function remediate() {
    if (conceptId == null) return;
    remediating = true;
    try {
      const r = await api.remediate(conceptId);
      remediatedCount = r.items.length;
    } finally { remediating = false; }
  }

  async function run() {
    if (conceptId == null) return;
    busy = true;
    try {
      result = await api.assess(conceptId, {
        kind, response,
        confidence_predicted: kind === 'calibration' ? confidence / 100 : null
      });
    } finally { busy = false; }
  }
</script>

<main class="mx-auto max-w-3xl p-6 flex flex-col gap-4">
  <h1 class="text-xl font-semibold">Assess understanding</h1>
  {#if cur}
    <label class="flex flex-col gap-1 text-sm">Concept
      <select class="border rounded p-2" bind:value={conceptId}>
        {#each cur.concepts as c}<option value={c.id}>{c.name}</option>{/each}
      </select>
    </label>
    <label class="flex flex-col gap-1 text-sm">Probe
      <select class="border rounded p-2" bind:value={kind}>
        <option value="self_explanation">Self-explanation</option>
        <option value="calibration">Calibration</option>
        <option value="artifact_review">Artifact review</option>
      </select>
    </label>
    {#if kind === 'calibration'}
      <label class="flex flex-col gap-1 text-sm">Your confidence: {confidence}%
        <input type="range" min="0" max="100" bind:value={confidence} />
      </label>
    {/if}
    <textarea class="border rounded p-2 min-h-32" bind:value={response}
              placeholder="Explain in your own words…"></textarea>
    <button class="bg-black text-white rounded px-4 py-2 disabled:opacity-50 self-start"
            onclick={run} disabled={busy || conceptId == null}>
      {busy ? 'Grading…' : 'Submit for assessment'}
    </button>

    {#if result}
      <section class="border rounded p-4 flex flex-col gap-2">
        <div class="text-sm">Score: <b>{result.score.toFixed(2)}</b> · estimate now
          <b>{result.estimate_level}</b>
          {#if result.delta != null}· Δ {result.delta > 0 ? '+' : ''}{result.delta.toFixed(2)}{/if}
        </div>
        {#if result.confidence_predicted != null}
          <div class="text-sm text-amber-700">Calibration: predicted
            {(result.confidence_predicted * 100).toFixed(0)}% vs actual
            {((result.confidence_actual ?? 0) * 100).toFixed(0)}%</div>
        {/if}
        <p class="text-sm">{result.verdict}</p>
        {#if result.gaps.length}
          <ul class="list-disc ml-5 text-sm text-gray-700">
            {#each result.gaps as g}<li>{g}</li>{/each}
          </ul>
          <button class="border rounded px-3 py-1 text-sm self-start disabled:opacity-50"
                  onclick={remediate} disabled={remediating}>
            {remediating ? 'Remediating…' : 'Remediate these gaps'}
          </button>
          {#if remediatedCount != null}
            <p class="text-xs text-gray-600">
              {remediatedCount > 0
                ? `Injected ${remediatedCount} item(s) — see the track.`
                : 'Already covered by an open remediation item.'}
              <a class="underline" href="/topics/{topicId}/track">Open track →</a>
            </p>
          {/if}
        {/if}
        <a class="text-sm underline" href="/topics/{topicId}/retention">Review retention →</a>
      </section>
    {/if}
  {:else}
    <p class="text-sm text-gray-500">No curriculum yet — generate one first.</p>
  {/if}
</main>
