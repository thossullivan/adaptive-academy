<script lang="ts">
  import type { SetupStatus } from '$lib/types';
  import { llmBlocked } from '$lib/setup';
  import { cn } from '$lib/utils';
  import Badge from './Badge.svelte';
  import Card from './Card.svelte';

  // Presentational: the page owns loading (see $lib/setup.svelte.ts). Renders nothing
  // unless the API positively reports that it cannot make LLM calls.
  let { status, class: klass = '' }: { status: SetupStatus | null; class?: string } = $props();

  // overflow-wrap:anywhere lets a long token (the env var names) break rather than overflow a
  // narrow content column.
  const code = 'rounded-[4px] bg-surface-3 px-1.5 py-0.5 font-mono text-[0.8rem] text-fg [overflow-wrap:anywhere]';
  // Short commands stay on one line so `just api` never splits across a wrap.
  const cmd = cn(code, 'whitespace-nowrap');
</script>

{#if llmBlocked(status)}
  <Card
    pad
    data-testid="setup-notice"
    role="status"
    class={cn(
      'rise border-[color-mix(in_oklab,var(--warn)_35%,var(--border))]',
      'bg-[color-mix(in_oklab,var(--warn)_5%,var(--surface))] text-left',
      klass
    )}
  >
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <Badge tone="warn" dot>Setup needed</Badge>
      <span class="eyebrow min-w-0 [overflow-wrap:anywhere]">LLM backend · {status?.llm_backend ?? 'anthropic'}</span>
    </div>
    <h2 class="mt-3 text-lg text-fg">Add your Anthropic API key to run the agents</h2>
    <p class="mt-1.5 max-w-prose text-sm leading-relaxed text-muted">
      Research, curricula, tutoring and grading all call Claude, and this API has no
      <code class={code}>ANTHROPIC_API_KEY</code> configured. Anything already recorded is still here to browse.
    </p>

    <ol class="mt-4 flex flex-col gap-2.5 text-sm text-fg-dim">
      <li class="flex gap-3">
        <span class="nums mt-0.5 w-4 shrink-0 font-mono text-xs text-faint">1</span>
        <span class="min-w-0">In the repo root: <code class={code}>cp .env.example .env</code></span>
      </li>
      <li class="flex gap-3">
        <span class="nums mt-0.5 w-4 shrink-0 font-mono text-xs text-faint">2</span>
        <span class="min-w-0">Set <code class={code}>ANTHROPIC_API_KEY=sk-ant-…</code> in <code class={cmd}>.env</code></span>
      </li>
      <li class="flex gap-3">
        <span class="nums mt-0.5 w-4 shrink-0 font-mono text-xs text-faint">3</span>
        <span class="min-w-0">
          Restart the API: <code class={cmd}>just api</code>, or <code class={cmd}>just up</code> for the container
        </span>
      </li>
    </ol>

    <p class="mt-4 border-t border-border pt-3 text-xs leading-relaxed text-muted">
      Prefer your Claude subscription? Set <code class={code}>AA_LLM_BACKEND=agent_sdk</code> in
      <code class={cmd}>.env</code> instead — host-only, run with <code class={cmd}>just api</code> rather than the container.
    </p>
  </Card>
{/if}
