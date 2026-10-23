<script lang="ts">
  import type { SetupStatus } from '$lib/types';
  import {
    experimentalModels,
    isExperimental,
    keyPlaceholder,
    llmBlocked,
    missingKey,
    providerName,
    setupWarnings,
    showSetupNotice,
    strictnessNote
  } from '$lib/setup';
  import { cn } from '$lib/utils';
  import Badge from './Badge.svelte';
  import Card from './Card.svelte';
  import ExperimentalTag from './ExperimentalTag.svelte';

  // Presentational: the page owns loading (see $lib/setup.svelte.ts). Renders the setup-needed
  // card when the API positively reports that it cannot make LLM calls, a smaller card when a
  // configured model is experimental, the configuration looks mistaken, or grading isn't at
  // the standard level, and nothing otherwise.
  let { status, class: klass = '' }: { status: SetupStatus | null; class?: string } = $props();

  // overflow-wrap:anywhere lets a long token (the env var names) break rather than overflow a
  // narrow content column.
  const code = 'rounded-[4px] bg-surface-3 px-1.5 py-0.5 font-mono text-[0.8rem] text-fg [overflow-wrap:anywhere]';
  // Short commands stay on one line so `just api` never splits across a wrap.
  const cmd = cn(code, 'whitespace-nowrap');
  const warnCard = cn(
    'rise border-[color-mix(in_oklab,var(--warn)_35%,var(--border))]',
    'bg-[color-mix(in_oklab,var(--warn)_5%,var(--surface))] text-left'
  );

  const blocked = $derived(llmBlocked(status));
  const openrouter = $derived(status?.llm_backend === 'openrouter');
  // agent_sdk only reports "not ready" when it can't run here (inside the container).
  const subscription = $derived(status?.llm_backend === 'agent_sdk');
  const provider = $derived(providerName(status));
  const keyVar = $derived(missingKey(status));
  const flagged = $derived(experimentalModels(status));
  const configWarnings = $derived(setupWarnings(status));
  const gradingNote = $derived(strictnessNote(status));
  const models = $derived(Object.entries(status?.models ?? {}));
  // The smaller card's kind: an experimental model, a likely mistake, or only the grading
  // level (a deliberate choice, so an info badge on a plain card rather than a warning).
  const gradingOnly = $derived(!flagged.length && !configWarnings.length);
</script>

{#snippet modelList()}
  <ul class="mt-3 flex flex-col gap-1.5 text-sm" aria-label="Configured models">
    {#each models as [role, model] (role)}
      <li class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span class="eyebrow w-20 shrink-0 text-faint">{role}</span>
        <code class={code}>{model}</code>
        {#if isExperimental(model, status)}<ExperimentalTag />{/if}
      </li>
    {/each}
  </ul>
{/snippet}

{#snippet warningList()}
  {#each configWarnings as warning (warning)}
    <p class="mt-3 max-w-prose text-sm leading-relaxed text-fg-dim [overflow-wrap:anywhere]" data-testid="setup-warning">
      {warning}
    </p>
  {/each}
  {#if gradingNote}
    <p class="mt-3 max-w-prose text-sm leading-relaxed text-fg-dim [overflow-wrap:anywhere]" data-testid="grading-strictness">
      {gradingNote}
    </p>
  {/if}
{/snippet}

{#if showSetupNotice(status)}
  {#if blocked}
    <Card pad data-testid="setup-notice" role="status" class={cn(warnCard, klass)}>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Badge tone="warn" dot>Setup needed</Badge>
        <span class="eyebrow min-w-0 [overflow-wrap:anywhere]">LLM backend · {status?.llm_backend ?? 'anthropic'}</span>
      </div>
      {#if subscription}
        <h2 class="mt-3 text-lg text-fg">The Claude subscription backend can't run here</h2>
        <p class="mt-1.5 max-w-prose text-sm leading-relaxed text-muted [overflow-wrap:anywhere]">{status?.message}</p>
      {:else}
        <h2 class="mt-3 text-lg text-fg">Add your {provider} API key to run the agents</h2>
        <p class="mt-1.5 max-w-prose text-sm leading-relaxed text-muted">
          Research, curricula, tutoring and grading all call the model, and this API has no usable
          <code class={code}>{keyVar}</code> configured. Anything already recorded is still here to browse.
        </p>
        {#if status?.key_hint}
          <p class="mt-2 max-w-prose text-sm leading-relaxed text-fg-dim [overflow-wrap:anywhere]" data-testid="key-hint">
            {status.key_hint}
          </p>
        {/if}

        <ol class="mt-4 flex flex-col gap-2.5 text-sm text-fg-dim">
          <li class="flex gap-3">
            <span class="nums mt-0.5 w-4 shrink-0 font-mono text-xs text-faint">1</span>
            <span class="min-w-0">In the repo root: <code class={code}>cp .env.example .env</code></span>
          </li>
          <li class="flex gap-3">
            <span class="nums mt-0.5 w-4 shrink-0 font-mono text-xs text-faint">2</span>
            <span class="min-w-0">Set <code class={code}>{keyVar}={keyPlaceholder(keyVar)}</code> in <code class={cmd}>.env</code></span>
          </li>
          <li class="flex gap-3">
            <span class="nums mt-0.5 w-4 shrink-0 font-mono text-xs text-faint">3</span>
            <span class="min-w-0">
              Restart the API: <code class={cmd}>just api</code>, or <code class={cmd}>just up</code> for the container
            </span>
          </li>
        </ol>
      {/if}

      {#if flagged.length}
        {@render modelList()}
      {/if}
      {@render warningList()}

      {#if !subscription}
        <!-- Other ways to connect a model: useful, but secondary to the steps above. -->
        <details class="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted" data-testid="setup-alternatives">
          <summary class="cursor-pointer font-medium text-fg-dim hover:text-fg">
            {openrouter ? 'About OpenRouter' : 'Use a Claude subscription or OpenRouter instead'}
          </summary>
          <p class="mt-2">
            {#if openrouter}
              Using OpenRouter (<code class={code}>AA_LLM_BACKEND=openrouter</code>). Each request passes through OpenRouter as
              well as the model's provider, and providers that may train on your prompts are left out. To call Anthropic
              directly, unset it and set <code class={code}>ANTHROPIC_API_KEY</code> instead.
            {:else}
              To use your Claude subscription, set <code class={code}>AA_LLM_BACKEND=agent_sdk</code> in
              <code class={cmd}>.env</code>. It only works on your own machine, so start the API with
              <code class={cmd}>just api</code>, not the container. To use an OpenRouter key, set
              <code class={code}>AA_LLM_BACKEND=openrouter</code> and <code class={code}>OPENROUTER_API_KEY</code>.
            {/if}
          </p>
        </details>
      {/if}
    </Card>
  {:else}
    <Card
      pad
      data-testid={flagged.length ? 'setup-experimental' : gradingOnly ? 'setup-grading' : 'setup-check'}
      role="status"
      class={cn(gradingOnly ? 'rise text-left' : warnCard, klass)}
    >
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <Badge tone={gradingOnly ? 'info' : 'warn'} dot>
          {flagged.length ? 'Experimental model' : gradingOnly ? 'Grading setting' : 'Check your setup'}
        </Badge>
        <span class="eyebrow min-w-0 [overflow-wrap:anywhere]">LLM backend · {status?.llm_backend ?? 'anthropic'}</span>
      </div>
      {#if flagged.length}
        <p class="mt-3 max-w-prose text-sm leading-relaxed text-fg-dim [overflow-wrap:anywhere]">
          {status?.experimental_warning ??
            'A configured model is not a Claude model, so structured answers, web search, and the tutor’s tools may not work as well.'}
        </p>
        {@render modelList()}
      {/if}
      {@render warningList()}
    </Card>
  {/if}
{/if}
