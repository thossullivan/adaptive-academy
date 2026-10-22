<script lang="ts">
  import type { QualityCalls, QualityReport, UsageWindowKey } from '$lib/types';
  import {
    featureLabel,
    formatUnitCost,
    formatUsd,
    perCallLabel,
    perGradeLabel,
    problemsLabel,
    shareLabel
  } from '$lib/usage';
  import Badge from './Badge.svelte';
  import Card from './Card.svelte';
  import ExperimentalTag from './ExperimentalTag.svelte';

  // The quality scorecard on the Usage page (GET /api/usage/quality; every number is
  // defined in the API's engine/scorecard.py). A failure to load it leaves the rest of the
  // page as it was.
  let { report, error = null }: { report: QualityReport | null; error?: string | null } = $props();

  const WINDOWS: [UsageWindowKey, string][] = [
    ['today', 'Today'],
    ['last_7_days', 'Last 7 days'],
    ['last_30_days', 'Last 30 days'],
    ['all_time', 'All time']
  ];
  let selected = $state<UsageWindowKey>('last_30_days');
  const w = $derived(report ? report.windows[selected] : null);
  const gradingNames = $derived(report ? report.grading_features.map(featureLabel).join(', ') : '');
  const windowName = $derived(WINDOWS.find(([key]) => key === selected)?.[1] ?? '');

  type Row = QualityCalls & { name: string; experimental: boolean; mono: boolean };
  const tables = $derived<{ id: string; title: string; head: string; rows: Row[] }[]>(
    w
      ? [
          {
            id: 'quality-by-feature',
            title: 'Calls by feature',
            head: 'Feature',
            rows: w.by_feature.map((r) => ({ ...r, name: featureLabel(r.feature), experimental: false, mono: false }))
          },
          {
            id: 'quality-by-model',
            title: 'Calls by model',
            head: 'Model',
            rows: w.by_model.map((r) => ({ ...r, name: r.model, experimental: !!r.experimental, mono: true }))
          }
        ]
      : []
  );

  function plural(n: number, one: string, many = `${one}s`): string {
    return `${n} ${n === 1 ? one : many}`;
  }

  function problemTone(row: QualityCalls): string {
    return row.refusals + row.empty_replies + row.cut_offs + row.invalid_outputs > 0 ? 'text-fg' : 'text-faint';
  }
</script>

<section class="flex flex-col gap-4" aria-labelledby="quality-title" data-testid="usage-quality">
  <div class="flex flex-wrap items-end justify-between gap-3">
    <div class="min-w-0">
      <div class="eyebrow">Quality</div>
      <h2 id="quality-title" class="mt-1 text-lg text-fg">Is each model doing its job?</h2>
      <p class="mt-1 max-w-prose text-sm text-muted">
        How the model calls went, what one grade costs, and how often the checks on grades and
        tutor replies had to step in.
      </p>
    </div>
    <div
      role="group"
      aria-label="Scorecard time window"
      class="flex flex-wrap gap-1 rounded-[var(--radius-md)] border border-border bg-surface-2 p-1"
    >
      {#each WINDOWS as [key, label] (key)}
        <button
          type="button"
          aria-pressed={selected === key}
          class="rounded-[var(--radius-sm)] px-2.5 py-1.5 text-xs font-medium transition-colors {selected === key
            ? 'bg-surface text-fg shadow-[var(--shadow)] ring-1 ring-control-border'
            : 'text-muted hover:text-fg'}"
          onclick={() => (selected = key)}>{label}</button
        >
      {/each}
    </div>
  </div>

  {#if error}
    <p class="text-sm text-danger" role="alert">Couldn't load the scorecard: {error}</p>
  {:else if !w}
    <p class="text-sm text-faint" role="status">Loading the scorecard</p>
  {:else}
    <div class="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <!-- Cost per graded assessment -->
      <Card eyebrow="Grading" title="Cost per grade" class="min-w-0" data-testid="quality-cost-per-grade">
        {#if w.grading.cost_per_assessment_usd != null}
          <p class="nums font-display text-3xl text-fg">{formatUnitCost(w.grading.cost_per_assessment_usd)}</p>
          <p class="mt-1 text-xs text-faint">
            {formatUsd(w.grading.cost_usd)} over {plural(w.grading.calls, 'call')} for
            {plural(w.grading.graded_assessments, 'grade')}.
          </p>
          {#if w.grading.unpriced_calls > 0}
            <p class="mt-1 text-xs text-faint" data-testid="quality-unpriced-note">
              Leaves out {plural(w.grading.unpriced_calls, 'grading call')} with no known price.
            </p>
          {/if}
        {:else}
          <p class="text-sm text-faint" data-testid="quality-no-data">
            No data yet.
            {#if w.grading.graded_assessments === 0}No assessments were written in this window.
            {:else if w.grading.calls === 0}No grading calls were recorded in this window.
            {:else}The grading model's price is unknown.{/if}
          </p>
        {/if}
        <p class="mt-3 text-xs leading-relaxed text-muted">
          Everything spent on the features that grade your answers ({gradingNames}), divided by
          the grades they wrote. An artifact review counts once, however many concepts it covers.
          The demo topic is left out.
        </p>
      </Card>

      <!-- Grading health -->
      <Card eyebrow="Grading" title="Grade checks" class="min-w-0" data-testid="quality-grading">
        {#if w.grading.first_attempts === 0 && w.grading.rejected === 0}
          <p class="text-sm text-faint">No grades checked in this window yet.</p>
        {:else}
          <dl class="flex flex-col gap-3 text-sm">
            <div>
              <dt class="text-muted">Regenerations per grade</dt>
              <dd>
                <span class="nums text-xl text-fg">{perGradeLabel(w.grading.regenerations_per_grade) ?? '0.00'}</span>
                <span class="block text-xs text-faint">
                  {w.grading.regenerations} of {plural(w.grading.first_attempts, 'grade')} failed a check and
                  were asked once more.
                </span>
              </dd>
            </div>
            <div>
              <dt class="text-muted">Rejected grades</dt>
              <dd>
                <span class="nums text-xl text-fg">{w.grading.rejected}</span>
                <span class="block text-xs text-faint">
                  {w.grading.rejected_failed_checks} failed the checks twice{#if w.grading.rejected_share != null}{` (${shareLabel(w.grading.rejected_share)} of grades)`}{/if},
                  {w.grading.rejected_stopped} stopped early (refused or cut off). Nothing was recorded for them.
                </span>
              </dd>
            </div>
            <div>
              <dt class="text-muted">Most failed checks</dt>
              <dd class="mt-1">
                {#if w.grading.top_failed_rules.length}
                  <ul class="flex flex-wrap gap-1.5" aria-label="Most failed checks">
                    {#each w.grading.top_failed_rules as rule (rule.rule_id)}
                      <li><Badge mono>{rule.rule_id} · {rule.count}</Badge></li>
                    {/each}
                  </ul>
                {:else}
                  <span class="text-xs text-faint">None failed.</span>
                {/if}
              </dd>
            </div>
          </dl>
        {/if}
        <p class="mt-3 text-xs leading-relaxed text-muted">
          Each grade is checked against named rules before it is saved. A failed check asks the
          model once more; a second failure saves nothing.
        </p>
      </Card>

      <!-- Tutor solution guard -->
      <Card eyebrow="Tutor" title="Solution guard" class="min-w-0" data-testid="quality-guard">
        {#if w.guard.checks === 0}
          <p class="text-sm text-faint">No tutor replies checked in this window yet.</p>
        {:else}
          <dl class="flex flex-col gap-3 text-sm">
            <div>
              <dt class="text-muted">Held back</dt>
              <dd>
                <span class="nums text-xl text-fg">{shareLabel(w.guard.blocked_share)}</span>
                <span class="block text-xs text-faint">{w.guard.blocked} of {plural(w.guard.checks, 'reply', 'replies')} gave the answer away.</span>
              </dd>
            </div>
            <div>
              <dt class="text-muted">Fallback questions</dt>
              <dd>
                <span class="nums text-xl text-fg">{w.guard.fallbacks}</span>
                <span class="block text-xs text-faint">The rewrite gave it away too, so the tutor asked a question instead.</span>
              </dd>
            </div>
            <div>
              <dt class="text-muted">Screen only</dt>
              <dd>
                <span class="nums text-xl text-fg">{shareLabel(w.guard.unavailable_share)}</span>
                <span class="block text-xs text-faint">{plural(w.guard.unavailable, 'check')} where the model check failed and the keyword screen decided alone.</span>
              </dd>
            </div>
          </dl>
        {/if}
        <p class="mt-3 text-xs leading-relaxed text-muted">
          Tutor replies written before your first attempt are checked for the answer, and held back
          if they give it away.
        </p>
      </Card>
    </div>

    <!-- Calls by feature and by model -->
    {#each tables as table (table.id)}
      <Card eyebrow="Quality" title={table.title} class="min-w-0">
        {#if !table.rows.length}
          <p class="text-sm text-faint">No model calls in this window yet.</p>
        {:else}
          <table class="w-full table-fixed text-sm" data-testid={table.id}>
            <caption class="sr-only">{table.title}, {windowName}</caption>
            <colgroup>
              <col class="w-[34%]" />
              <col class="w-[14%]" />
              <col class="w-[20%]" />
              <col class="w-[32%]" />
            </colgroup>
            <thead>
              <tr class="eyebrow text-left text-faint">
                <th scope="col" class="pb-2 font-normal">{table.head}</th>
                <th scope="col" class="pb-2 text-right font-normal">Calls</th>
                <th scope="col" class="pb-2 text-right font-normal">Per call</th>
                <th scope="col" class="pb-2 pl-3 font-normal">Problems</th>
              </tr>
            </thead>
            <tbody>
              {#each table.rows as row (row.name)}
                <tr class="border-t border-border align-top">
                  <th scope="row" class="py-2 pr-2 text-left font-normal">
                    <span class="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span class="min-w-0 text-fg-dim [overflow-wrap:anywhere] {row.mono ? 'font-mono text-xs' : ''}">{row.name}</span>
                      {#if row.experimental}<ExperimentalTag />{/if}
                    </span>
                  </th>
                  <td class="nums py-2 text-right text-fg-dim">{row.calls}</td>
                  <td class="nums py-2 text-right text-fg">{perCallLabel(row)}</td>
                  <td class="py-2 pl-3 text-xs leading-relaxed {problemTone(row)}">{problemsLabel(row)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </Card>
    {/each}

    <p class="text-xs leading-relaxed text-faint">
      Per call is the spend over the calls that had a price. Problems counts calls the model
      refused, answered with nothing, stopped because the answer ran too long, or answered in the
      wrong format for a step that needs structured output (counted even when the one retry fixed
      it). A grade in the wrong format is counted under Grade checks above, not under Problems.
      Problems are recorded for calls made with an API key from this version on; older calls
      and Claude subscription calls show "not recorded".
    </p>
  {/if}
</section>
