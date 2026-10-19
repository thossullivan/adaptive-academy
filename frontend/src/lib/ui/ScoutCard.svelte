<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { TopicSuggestion } from '$lib/types';
  import { evidenceLabel, groupSuggestionsByKind } from '$lib/api';
  import Badge from './Badge.svelte';
  import Button from './Button.svelte';
  import Card from './Card.svelte';

  let {
    suggestions,
    title,
    busy = false,
    error = '',
    note = '',
    emptyText = '',
    targetLabel = '',
    showScore = false,
    class: className = '',
    onaccept,
    ondismiss,
    controls,
    header
  }: {
    suggestions: TopicSuggestion[];
    title: string;
    busy?: boolean;
    error?: string;
    note?: string;
    emptyText?: string;
    /** Where an accepted stub lands (e.g. the current milestone title). */
    targetLabel?: string;
    showScore?: boolean;
    class?: string;
    onaccept: (id: number) => void;
    ondismiss: (id: number) => void;
    /** Extra per-suggestion controls (e.g. a milestone picker). */
    controls?: Snippet<[TopicSuggestion]>;
    header?: Snippet;
  } = $props();

  const groups = $derived(groupSuggestionsByKind(suggestions));
</script>

<Card accent class={className} eyebrow="Evidence-backed topics" {title} {header}>
  {#if note}<p class="mb-3 text-xs text-muted">{note}</p>{/if}
  {#if groups.length === 0}
    {#if emptyText}<p class="text-sm text-muted">{emptyText}</p>{/if}
  {:else}
    <div class="grid gap-5">
      {#each groups as group (group.kind)}
        <div>
          <Badge mono tone="neutral">{group.kind.replaceAll('_', ' ')}</Badge>
          <ul class="mt-2 grid gap-3">
            {#each group.suggestions as suggestion (suggestion.id)}
              <li
                class="grid gap-3 border-t border-border/50 pt-3 text-sm lg:grid-cols-[minmax(0,1fr)_auto]"
              >
                <div class="min-w-0">
                  <div class="flex flex-wrap items-baseline gap-2">
                    <p class="font-medium text-fg">{suggestion.title}</p>
                    {#if showScore}
                      <span class="nums text-xs text-faint">{Math.round(suggestion.score * 100)}%</span>
                    {/if}
                  </div>
                  <p class="mt-1 text-muted">{suggestion.rationale}</p>
                  <details class="mt-2 text-xs text-faint">
                    <summary class="cursor-pointer">Evidence ({suggestion.evidence.length})</summary>
                    <ul class="mt-1 grid gap-1 pl-3">
                      {#each suggestion.evidence as evidence}
                        <li>{evidenceLabel(evidence)}</li>
                      {/each}
                    </ul>
                  </details>
                </div>
                <div class="grid content-start gap-2">
                  {#if controls}{@render controls(suggestion)}{/if}
                  {#if targetLabel}<p class="text-xs text-faint">Accept → {targetLabel}</p>{/if}
                  <div class="flex gap-2">
                    <Button size="sm" onclick={() => onaccept(suggestion.id)} disabled={busy}>Accept</Button>
                    <Button size="sm" variant="ghost" onclick={() => ondismiss(suggestion.id)} disabled={busy}
                      >Dismiss</Button
                    >
                  </div>
                </div>
              </li>
            {/each}
          </ul>
        </div>
      {/each}
    </div>
  {/if}
  {#if error}<p class="mt-3 text-sm text-danger" role="alert">{error}</p>{/if}
</Card>
