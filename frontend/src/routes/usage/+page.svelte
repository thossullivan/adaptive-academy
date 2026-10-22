<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { QualityReport, UsageReport, UsageTotals } from '$lib/types';
  import {
    budgetFraction,
    cacheShareLabel,
    callDestination,
    costLabel,
    featureLabel,
    formatTokens,
    formatUsd,
    totalTokens
  } from '$lib/usage';
  import { setup } from '$lib/setup.svelte';
  import Page from '$lib/shell/Page.svelte';
  import { Card, ExperimentalTag, QualityScorecard, Stat } from '$lib/ui';

  let report = $state<UsageReport | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(true);
  let quality = $state<QualityReport | null>(null);
  let qualityError = $state<string | null>(null);
  const warnings = $derived(setup.status?.warnings ?? []);

  onMount(async () => {
    setup.refresh(); // limit warnings (GET /api/setup); a failure just shows none
    // The scorecard loads beside the report; if it fails, only its own section says so.
    api.getUsageQuality().then(
      (q) => (quality = q),
      (e) => (qualityError = e instanceof Error ? e.message : String(e))
    );
    try {
      report = await api.getUsage();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  });

  const windows = $derived(
    report
      ? ([
          ['Today', report.totals.today],
          ['Last 7 days', report.totals.last_7_days],
          ['Last 30 days', report.totals.last_30_days],
          ['All time', report.totals.all_time]
        ] as [string, UsageTotals][])
      : []
  );

  const fraction = $derived(report ? budgetFraction(report.budget) : null);
  const subscription = $derived(report?.backend === 'agent_sdk');
  const openrouter = $derived(report?.backend === 'openrouter');

  // Bars in a breakdown are relative to its most expensive row.
  function share(rows: UsageTotals[], row: UsageTotals): number {
    const top = Math.max(...rows.map((r) => r.cost_usd), 0);
    return top > 0 ? row.cost_usd / top : 0;
  }

  function hint(t: UsageTotals): string {
    const parts = [`${t.calls} call${t.calls === 1 ? '' : 's'}`, `${formatTokens(totalTokens(t))} tokens`];
    if (t.web_search_requests) parts.push(`${t.web_search_requests} searches`);
    if (t.unpriced_calls) parts.push(`${t.unpriced_calls} price unknown`);
    return parts.join(' · ');
  }
</script>

<svelte:head><title>Usage · Adaptive Academy</title></svelte:head>

<Page
  eyebrow="Ledger"
  title="Usage & cost"
  lead="Every model call the agents make, counted on this machine: tokens, web searches, and what they cost."
>
  {#if loading}
    <p class="py-10 text-center text-sm text-faint" role="status">Tallying the ledger…</p>
  {:else if error || !report}
    <p class="py-10 text-center text-sm text-danger" role="alert">Couldn't load usage: {error ?? 'no data'}</p>
  {:else}
    <div class="flex flex-col gap-5" data-testid="usage-report">
      {#if subscription}
        <p class="rounded-[var(--radius)] border border-border bg-surface-2 px-4 py-3 text-sm text-fg-dim">
          Calls run on your <span class="text-fg">Claude subscription</span> (Agent SDK backend).
          Dollar figures are the SDK's list-price estimate, not a charge to an API key.
        </p>
      {:else if openrouter}
        <p class="rounded-[var(--radius)] border border-border bg-surface-2 px-4 py-3 text-sm text-fg-dim" data-testid="usage-openrouter">
          Calls run through <span class="text-fg">OpenRouter</span>. Dollar figures are what OpenRouter reported
          charging for each call, fees included, and they count toward the daily limit.
        </p>
      {/if}

      <!-- Spend by window -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {#each windows as [label, t] (label)}
          <Card pad class="min-w-0">
            <Stat {label} value={costLabel(t)} hint={hint(t)} />
          </Card>
        {/each}
      </div>

      <!-- Daily limit -->
      <Card eyebrow="API key" title="Daily spending limit" accent={report.budget.exceeded || warnings.length > 0}>
        {#each warnings as warning (warning)}
          <p
            class="mb-3 rounded-[var(--radius-sm)] border border-[color-mix(in_oklab,var(--warn)_35%,var(--border))] bg-[color-mix(in_oklab,var(--warn)_6%,var(--surface))] px-3 py-2 text-sm leading-relaxed text-fg-dim [overflow-wrap:anywhere]"
            role="status"
            data-testid="budget-warning"
          >
            {warning}
          </p>
        {/each}
        {#if report.budget.limit_usd == null}
          <p class="text-sm text-muted">
            No limit set. Today's API-key spend so far:
            <span class="nums text-fg">{formatUsd(report.budget.spent_today_usd)}</span>.
          </p>
          <p class="mt-2 text-sm text-muted">
            To cap it, set <code class="font-mono text-fg-dim">AA_DAILY_BUDGET_USD=5</code> (any
            dollar amount) in <code class="font-mono text-fg-dim">.env</code> and restart the API.
          </p>
        {:else}
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <span class="nums font-display text-2xl text-fg" data-testid="budget-spent">
              {formatUsd(report.budget.spent_today_usd)}
              <span class="text-sm text-muted">of {formatUsd(report.budget.limit_usd)} today</span>
            </span>
            {#if report.budget.exceeded}
              <span class="eyebrow" style:color="var(--danger)">Limit reached</span>
            {:else}
              <span class="eyebrow text-faint">{formatUsd(report.budget.remaining_usd ?? 0)} left</span>
            {/if}
          </div>
          <div class="mt-3 h-1.5 overflow-hidden rounded-full bg-border" aria-hidden="true">
            <div
              class="h-full rounded-full"
              style:width={`${Math.round((fraction ?? 0) * 100)}%`}
              style:background={report.budget.exceeded ? 'var(--danger)' : 'var(--accent)'}
            ></div>
          </div>
          <p class="mt-3 text-xs leading-relaxed text-faint">
            {#if report.budget.exceeded}
              New API-key calls are refused until tomorrow (server's local day). Raise or unset
              <code class="font-mono">AA_DAILY_BUDGET_USD</code> in <code class="font-mono">.env</code>
              and restart the API to continue now.
            {:else}
              Checked before each API-key call; one call can run past the limit. Subscription
              (Agent SDK) calls are never blocked.
            {/if}
          </p>
        {/if}
      </Card>

      <!-- Breakdowns (last 30 days) -->
      <div class="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card eyebrow="Last 30 days" title="By feature">
          {#if !report.by_feature.length}
            <p class="text-sm text-faint">No model calls yet.</p>
          {:else}
            <ul class="flex flex-col gap-3" data-testid="usage-by-feature">
              {#each report.by_feature as row (row.feature ?? '—')}
                {@const cached = cacheShareLabel(row.cache_read_share)}
                <li class="min-w-0">
                  <!-- The label is never cut short: when it and the figures don't fit on one
                       line, the figures wrap below it. -->
                  <div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
                    <span class="flex-1 text-fg-dim" data-testid="feature-label">{featureLabel(row.feature)}</span>
                    <span class="ml-auto flex shrink-0 items-baseline gap-3">
                      <span class="eyebrow hidden text-faint sm:inline">{formatTokens(totalTokens(row))} tok</span>
                      {#if cached}
                        <span
                          class="eyebrow hidden text-faint sm:inline"
                          title="Share of input tokens read from the prompt cache"
                          data-testid="cache-share">{cached}</span
                        >
                      {/if}
                      <span class="eyebrow text-faint">{row.calls}×</span>
                      <span class="nums w-24 text-right text-fg">{costLabel(row)}</span>
                    </span>
                  </div>
                  <div class="mt-1 h-1 overflow-hidden rounded-full bg-border" aria-hidden="true">
                    <div class="h-full rounded-full bg-accent" style:width={`${Math.round(share(report.by_feature, row) * 100)}%`}></div>
                  </div>
                </li>
              {/each}
            </ul>
          {/if}
        </Card>

        <Card eyebrow="Last 30 days" title="By model">
          {#if !report.by_model.length}
            <p class="text-sm text-faint">No model calls yet.</p>
          {:else}
            <ul class="flex flex-col gap-3" data-testid="usage-by-model">
              {#each report.by_model as row (row.model)}
                <li class="min-w-0">
                  <div class="flex items-baseline gap-3 text-sm">
                    <span class="flex min-w-0 flex-1 items-center gap-2">
                      <span class="min-w-0 truncate font-mono text-xs text-fg-dim" title={row.model}>{row.model}</span>
                      {#if row.experimental}<ExperimentalTag />{/if}
                    </span>
                    <span class="eyebrow hidden text-faint sm:inline">{formatTokens(totalTokens(row))} tok</span>
                    <span class="eyebrow text-faint">{row.calls}×</span>
                    <span class="nums w-24 text-right text-fg">{costLabel(row)}</span>
                  </div>
                  <div class="mt-1 h-1 overflow-hidden rounded-full bg-border" aria-hidden="true">
                    <div class="h-full rounded-full bg-accent" style:width={`${Math.round(share(report.by_model, row) * 100)}%`}></div>
                  </div>
                </li>
              {/each}
            </ul>
          {/if}
        </Card>
      </div>

      <QualityScorecard report={quality} error={qualityError} />

      <p class="text-xs leading-relaxed text-faint" data-testid="usage-footnote">
        {#if openrouter}
          Dollar figures are the cost OpenRouter reported for each call, fees included. For a call
          where it reported none, the price comes from
        {:else}
          Prices come from
        {/if}
        <a class="underline decoration-border hover:text-fg" href={report.pricing_source} target="_blank" rel="noreferrer">Anthropic's pricing page<span class="sr-only"> (opens in a new tab)</span></a>,
        read {report.pricing_as_of}, for {report.priced_models.join(', ')}. Other models record
        tokens with "price unknown". These records stay in your local database.
        {callDestination(report.backend)}
        {#if report.by_model.some((m) => m.experimental)}Models marked Experimental are not Claude models.{/if}
      </p>
    </div>
  {/if}
</Page>
